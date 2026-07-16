"""tuner/segment.py — state-segmented telemetry analysis.

Splits a recorded lap into driving phases (straight / corner-entry / apex /
exit) and computes per-phase grip + balance evidence plus whole-lap driver
technique timers.

Why this exists: a flat lap-mean of slip (what the original analyzer does)
divides a real corner-exit problem across thousands of near-zero straight-line
frames, so the signal vanishes. Slip means different things on-throttle
(wheelspin / diff) vs under braking (lockup / bias) vs mid-corner (balance).
Segmenting first, then measuring, is how motorsport data engineers read data.

Output is EVIDENCE for the AI/MCP reasoning layer, not hardcoded pass/fail
verdicts — no validated FH6 numeric thresholds exist, so the cutoffs below are
sim-community starting points the AI is told to treat as approximate.
"""
from __future__ import annotations

import numpy as np

from telemetry.parser import tire_temp_to_celsius

G = 9.81  # m/s^2

# Definitional constants (NOT tuning cutoffs, so NOT data-derived):
#   SLIDE=1.0 is the MEANING of the normalized combined-slip channel — |v|>=1 is
#   grip loss by the FH6 spec, not a threshold to calibrate.
#   MIN_PHASE_FRAMES is a data-sufficiency floor (need N samples for a stable mean).
# The frame-state classifiers (moving / cornering / on-throttle / braking / coasting)
# are NOT constants — they are derived per session from the data by _otsu (below).
SLIDE = 1.0
MIN_PHASE_FRAMES = 50


def _otsu(x: np.ndarray) -> float:
    """Data-derived threshold separating a signal's two modes — Otsu's method: the
    cut that maximizes between-class variance of a 256-bin histogram.

    Replaces hardcoded state cutoffs (cornering g, on-throttle %, braking %): a
    steering/throttle/lateral-g trace is bimodal (off-cluster near zero, on-cluster
    high), and this finds the valley between them from THIS session's own data, so
    the split adapts to the car, controller, and track instead of a fixed guess.
    """
    x = x[np.isfinite(x)]
    if x.size == 0:
        return 0.0
    lo, hi = float(x.min()), float(x.max())
    if hi <= lo:
        return lo
    hist, edges = np.histogram(x, bins=256, range=(lo, hi))
    hist = hist.astype(float)
    centers = (edges[:-1] + edges[1:]) / 2.0
    w = np.cumsum(hist)                 # cumulative weight below each edge
    cw = np.cumsum(hist * centers)      # cumulative weighted mean numerator
    total, total_cw = w[-1], cw[-1]
    wf = total - w                      # weight above
    with np.errstate(invalid="ignore", divide="ignore"):
        mb = cw / w                     # mean of the below class
        mf = (total_cw - cw) / wf       # mean of the above class
        var_between = w * wf * (mb - mf) ** 2
    var_between[~np.isfinite(var_between)] = -1.0
    return float(centers[int(np.argmax(var_between))])


def _col(frames: list[dict], key: str) -> np.ndarray:
    return np.array([f[key] for f in frames], dtype=float)


def _sample_rate_hz(frames: list[dict]) -> float:
    """Estimate the telemetry sample rate from timestamps (Forza ~60 Hz)."""
    ts = _col(frames, "timestamp_ms")
    dt = np.diff(ts)
    dt = dt[(dt > 0) & (dt < 1000)]  # drop lap-boundary resets / freezes
    if dt.size == 0:
        return 60.0
    return float(1000.0 / np.median(dt))


def _reversal_count(x: np.ndarray, deadband: float) -> int:
    """Count zig-zag direction reversals whose swing exceeds ``deadband``.

    The basis for steering-wheel-reversal-rate (sawing the wheel) and throttle
    stab metrics. The first move only establishes the initial direction and is
    not counted as a reversal.
    """
    count = 0
    direction = 0  # +1 rising, -1 falling, 0 unset
    pivot = float(x[0])
    for v in x:
        v = float(v)
        if direction >= 0:
            if v > pivot:
                pivot = v
            elif v < pivot - deadband:
                if direction == 1:
                    count += 1
                direction = -1
                pivot = v
                continue
        if direction <= 0:
            if v < pivot:
                pivot = v
            elif v > pivot + deadband:
                if direction == -1:
                    count += 1
                direction = 1
                pivot = v
    return count


def _gearing_stats(
    rpm: np.ndarray, maxrpm: np.ndarray, gear: np.ndarray,
    speed_mph: np.ndarray, throttle: np.ndarray,
) -> dict:
    """Gearing health that the upshift-RPM heuristic misses.

    The mean-upshift-RPM metric only samples the instant of a shift, so it is
    blind to an over-tall TOP gear (never revved out -> no upshift to see) and
    to time spent below the power band. These signals catch "gearing too long":
    a top gear that never reaches redline, and on-throttle RPM sitting low.
    """
    redline = float(np.median(maxrpm[maxrpm > 0])) if (maxrpm > 0).any() else 0.0
    on = throttle > 0.5
    real = (gear >= 1) & (gear <= 10)
    out: dict = {"redline_rpm": round(redline), "top_gear_used": int(gear[real].max()) if real.any() else 0}
    if redline and real.any():
        tg = real & (gear == out["top_gear_used"])
        # top gear never near redline at speed = top gear too long
        out["top_gear_max_rpm_pct"] = round(float(rpm[tg].max() / redline), 3) if tg.any() else None
    if redline and on.any():
        # high = lugging below the power band (gearing too long / spacing too wide)
        out["on_throttle_below_powerband_pct"] = round(float(np.mean(rpm[on] < 0.70 * redline)), 3)
        out["mean_on_throttle_rpm_pct"] = round(float(rpm[on].mean() / redline), 3)
    if redline and speed_mph.size:
        i = int(np.argmax(speed_mph))
        out["rpm_pct_at_max_speed"] = round(float(rpm[i] / redline), 3)
        out["max_speed_mph"] = round(float(speed_mph[i]), 1)
    return out


def _damper_histogram(travel_m: dict[str, np.ndarray], moving: np.ndarray, rate: float) -> dict:
    """Per-corner damper shaft-velocity from SuspensionTravelMeters (real mm/s).

    Differentiates the ABSOLUTE (meters) travel to calibrated mm/s — the normalized
    0-1 channel can't give velocity. The diagnostic is per-CORNER compression/rebound
    SYMMETRY through the band the chassis actually works in, taken as the session's
    OWN inter-quartile |velocity| range (data-derived, not a fixed mm/s cutoff), plus
    the velocity distribution (percentiles). ~0.5 = even; per-corner asymmetry flags a
    bump/rebound imbalance on that corner; a high p90 vs p50 = spiky/curb-heavy input.
    """
    out: dict = {"note": "mm/s from the meters channel; comp/reb ~0.5 = even through the car's own IQR velocity band; per-corner asymmetry is the signal"}
    mv = moving[:-1]
    for w, tm in travel_m.items():
        v = (np.diff(tm) * rate * 1000.0)[mv]  # m/frame -> mm/s
        if v.size < MIN_PHASE_FRAMES:
            out[w] = None
            continue
        av = np.abs(v)
        p25, p50, p90 = (float(x) for x in np.percentile(av, (25, 50, 90)))
        band = (av >= p25) & (av <= np.percentile(av, 75))  # the car's own typical-motion range
        comp = int(np.count_nonzero((v > 0) & band))
        reb = int(np.count_nonzero((v < 0) & band))
        out[w] = {
            "comp_reb_balance_iqr": round(comp / max(comp + reb, 1), 3),
            "abs_mm_s_p50": round(p50, 1),
            "abs_mm_s_p90": round(p90, 1),
        }
    return out


def _response_lag(steer: np.ndarray, yaw_rate: np.ndarray, rate: float, max_lag_frames: int = 25) -> dict:
    """Steer->yaw response lag (cross-correlation) — the sharp-vs-heavy signal.

    Low lag = crisp turn-in; high lag = lazy/heavy (yaw builds slowly after the
    steering input — the response-rate complaint, distinct from understeer).
    Approximate: |steer| vs |yaw rate| over the whole run, best-correlation lag.
    """
    s, y = np.abs(steer), np.abs(yaw_rate)
    s, y = s - s.mean(), y - y.mean()
    best_lag, best_corr = 0, -2.0
    for lag in range(max_lag_frames + 1):
        a = s[: s.size - lag] if lag else s
        b = y[lag:] if lag else y
        if a.size < 200:
            break
        denom = a.std() * b.std()
        c = float(np.mean(a * b) / denom) if denom > 0 else 0.0
        if c > best_corr:
            best_corr, best_lag = c, lag
    return {
        "steer_to_yaw_lag_ms": round(best_lag / rate * 1000),
        "peak_corr": round(best_corr, 3),
        "note": "yaw lag behind steering; higher ms = lazier/heavier turn-in, lower = sharper",
    }


def _per_corner(speed: np.ndarray, lat_g: np.ndarray, front_sa: np.ndarray,
                rear_sa: np.ndarray, moving: np.ndarray, rate: float,
                corner_lat: float, top_n: int = 5) -> dict | None:
    """Per-individual-corner balance (not just the per-phase lap aggregate).

    Splits the lap into discrete corners (contiguous |latG| > ``corner_lat`` runs, the
    session's own data-derived cornering onset) and reports the worst by
    understeer/oversteer so a SPECIFIC corner can be targeted.
    """
    corner = moving & (np.abs(lat_g) > corner_lat)
    idx = np.where(corner)[0]
    if idx.size < 50:
        return None
    gap = min_len = int(0.3 * rate)
    runs, start, prev = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        if i - prev > gap:
            runs.append((start, prev))
            start = int(i)
        prev = int(i)
    runs.append((start, prev))
    corners = []
    for a, b in runs:
        if b - a < min_len:
            continue
        sl = slice(a, b + 1)
        corners.append({
            "apex_mph": round(float(speed[sl].min()) * 2.237),
            "balance": round(float(front_sa[sl].mean() - rear_sa[sl].mean()), 2),
            "seconds": round((b - a) / rate, 1),
        })
    if not corners:
        return None
    return {
        "corners_detected": len(corners),
        "worst_by_balance": sorted(corners, key=lambda c: -abs(c["balance"]))[:top_n],
        "note": "+balance = understeer, - = oversteer, per individual corner; apex_mph = min speed in it",
    }


def _phase_stats(
    mask: np.ndarray,
    *,
    front_sa: np.ndarray,
    rear_sa: np.ndarray,
    front_cs: np.ndarray,
    rear_cs: np.ndarray,
    front_sr: np.ndarray,
    rear_sr: np.ndarray,
    lat_g: np.ndarray,
    comb_g: np.ndarray,
    g_peak: float,
) -> dict | None:
    """Aggregate grip/balance evidence over the frames selected by ``mask``."""
    n = int(mask.sum())
    if n < MIN_PHASE_FRAMES:
        return None
    fa, ra = float(front_sa[mask].mean()), float(rear_sa[mask].mean())
    return {
        "frames": n,
        "front_slip_angle": round(fa, 4),
        "rear_slip_angle": round(ra, 4),
        # >0 = front sliding more (understeer); <0 = rear sliding more (oversteer)
        "balance_front_minus_rear": round(fa - ra, 4),
        "front_combined_slip": round(float(front_cs[mask].mean()), 4),
        "rear_combined_slip": round(float(rear_cs[mask].mean()), 4),
        # signed slip ratio: + = drive/wheelspin, - = braking lockup
        "front_slip_ratio_signed": round(float(front_sr[mask].mean()), 4),
        "rear_slip_ratio_signed": round(float(rear_sr[mask].mean()), 4),
        "mean_abs_lat_g": round(float(np.abs(lat_g[mask]).mean()), 3),
        "traction_use": round(float(comb_g[mask].mean() / g_peak), 3) if g_peak else None,
    }


def _banded(
    mask: np.ndarray,
    *,
    key: np.ndarray,
    key_name: str,
    front_sa: np.ndarray,
    rear_sa: np.ndarray,
    front_cs: np.ndarray,
    rear_cs: np.ndarray,
    lat_g: np.ndarray,
) -> dict:
    """Balance + grip split into DATA-DERIVED thirds of the session's own ``key``
    distribution (corner speed / lateral load / tyre temperature) within ``mask``.

    Grip/balance are load-, speed- and temperature-dependent, so a per-phase mean
    blends states that exist at no real instant. The band EDGES are the terciles of
    THIS lap's own distribution — no fixed cutoffs — so the split adapts to the
    actual track and car; conditioning on the axis a lever acts through
    (aero→speed, load-sensitivity→lateral g, grip→temperature) makes it attributable.
    """
    k = key[mask]
    if k.size < 3 * MIN_PHASE_FRAMES:
        return {"note": f"too few frames to band by {key_name}"}
    lo_e, hi_e = (float(x) for x in np.percentile(k, (100.0 / 3, 200.0 / 3)))
    out: dict = {
        "band_edges": [round(lo_e, 2), round(hi_e, 2)],
        "note": f"thirds of this session's {key_name} (data-derived edges, not fixed cutoffs)",
    }
    for lo, hi, name in ((-np.inf, lo_e, "low"), (lo_e, hi_e, "mid"), (hi_e, np.inf, "high")):
        band = mask & (key >= lo) & (key < hi)
        n = int(band.sum())
        if n < MIN_PHASE_FRAMES:
            out[name] = {"frames": n}
            continue
        fa, ra = float(front_sa[band].mean()), float(rear_sa[band].mean())
        out[name] = {
            "frames": n,
            f"mean_{key_name}": round(float(key[band].mean()), 2),
            # >0 = understeer (front sliding more), <0 = oversteer
            "balance_front_minus_rear": round(fa - ra, 4),
            "front_combined_slip": round(float(front_cs[band].mean()), 4),
            "rear_combined_slip": round(float(rear_cs[band].mean()), 4),
            "mean_abs_lat_g": round(float(np.abs(lat_g[band]).mean()), 3),
        }
    return out


def _extended_blocks(
    frames: list[dict], *, moving: np.ndarray, lat_g: np.ndarray, long_g: np.ndarray,
    throttle: np.ndarray, brake: np.ndarray, speed: np.ndarray, rpm: np.ndarray,
    maxrpm: np.ndarray, gear: np.ndarray, lat_thr: float, thr_thr: float,
) -> dict:
    """Consume every remaining telemetry channel into a useful signal.

    Each block below exists to turn a parsed-but-idle field into evidence the
    AI tuning/coaching layer can act on: chassis attitude (roll/pitch/rates),
    body sideslip, airtime, wheel-speed cross-checks, raw suspension travel,
    surface/weather context, the power/torque curve, clutch/handbrake use,
    lap timing, the AI reference line, and track geometry.
    """
    wheels = ("fl", "fr", "rl", "rr")
    cornering = moving & (np.abs(lat_g) > lat_thr)   # session-derived cornering cut
    on_thr = throttle > thr_thr                      # session-derived on-throttle cut
    # WOT = near the session's OWN max throttle; "fast" = upper-speed frames by the
    # moving-speed distribution — both data-relative, no absolute cutoff.
    tmax = float(np.nanmax(throttle)) if throttle.size else 1.0
    wot = (throttle > 0.9 * tmax) & moving
    fast = moving & (speed > float(np.percentile(speed[moving], 40))) if int(moving.sum()) else moving

    # --- Chassis attitude: roll/pitch and their rates, heading ---
    pitch, roll, yaw = _col(frames, "pitch"), _col(frames, "roll"), _col(frames, "yaw")
    pitch_rate, roll_rate = _col(frames, "angular_velocity_x"), _col(frames, "angular_velocity_z")
    roll_per_g = None
    if int(cornering.sum()) > 200:
        roll_per_g = float(np.polyfit(np.abs(lat_g[cornering]), np.degrees(np.abs(roll[cornering])), 1)[0])
    braking_m, accel_m = moving & (long_g < -0.3), moving & (long_g > 0.3)
    # Cumulative heading change with a per-frame deadband so sensor jitter on
    # straights doesn't inflate the total (only real turning crosses 0.15 deg/frame).
    heading_change = None
    if int(moving.sum()) > 1:
        hd = np.abs(np.diff(np.unwrap(yaw[moving])))
        heading_change = round(float(np.sum(hd[hd > np.radians(0.15)]) * 180 / np.pi), 0)
    attitude = {
        "body_roll_deg_per_g": round(roll_per_g, 3) if roll_per_g is not None else None,
        "max_body_roll_deg": round(float(np.degrees(np.percentile(np.abs(roll[moving]), 99.5))), 1) if moving.any() else None,
        "mean_brake_dive_deg": round(float(np.degrees(pitch[braking_m].mean())), 2) if int(braking_m.sum()) > 50 else None,
        "mean_accel_squat_deg": round(float(np.degrees(pitch[accel_m].mean())), 2) if int(accel_m.sum()) > 50 else None,
        "max_pitch_rate_rad_s": round(float(np.percentile(np.abs(pitch_rate[moving]), 99.5)), 2) if moving.any() else None,
        "max_roll_rate_rad_s": round(float(np.percentile(np.abs(roll_rate[moving]), 99.5)), 2) if moving.any() else None,
        "total_heading_change_deg": heading_change,
    }

    # --- Body sideslip (car-local velocity): true chassis slide, not tire slip ---
    vx, vy, vz = _col(frames, "velocity_x"), _col(frames, "velocity_y"), _col(frames, "velocity_z")
    beta = np.degrees(np.arctan2(vx, np.maximum(np.abs(vz), 0.1)))
    body_slip = {
        "mean_abs_slip_deg_cornering": round(float(np.abs(beta[cornering]).mean()), 2) if int(cornering.sum()) > 50 else None,
        "max_abs_slip_deg": round(float(np.percentile(np.abs(beta[moving]), 99.5)), 1) if moving.any() else None,
        "big_slide_pct": round(float(np.mean(np.abs(beta[moving]) > 15)), 3) if moving.any() else None,
        # ~1.0 confirms velocity is car-local (vz == forward speed); sanity gauge
        "velocity_z_vs_speed_ratio": round(float(np.median((np.abs(vz[fast]) / np.maximum(speed[fast], 0.1)))), 3) if fast.any() else None,
    }
    vert_g = _col(frames, "acceleration_y") / G  # vertical load: bumps, crests, landings
    airborne = {
        "max_vertical_velocity_ms": round(float(np.percentile(np.abs(vy[moving]), 99.5)), 2) if moving.any() else None,
        "airtime_pct": round(float(np.mean(np.abs(vy[moving]) > 2.0)), 4) if moving.any() else None,
        "max_vertical_g": round(float(np.percentile(np.abs(vert_g[moving]), 99.5)), 2) if moving.any() else None,
    }

    # --- Wheel rotation speeds: corroborate spin/lockup and diff behaviour ---
    wr = {w: _col(frames, f"wheel_rotation_speed_{w}") for w in wheels}
    front_w = (np.abs(wr["fl"]) + np.abs(wr["fr"])) / 2
    rear_w = (np.abs(wr["rl"]) + np.abs(wr["rr"])) / 2
    spin = on_thr & fast
    brake_hard = fast & (brake > 0.3)
    rf_ratio = rear_w / np.maximum(front_w, 1e-3)
    fr_ratio = front_w / np.maximum(rear_w, 1e-3)
    # No-drive coast frames give the tyre-diameter baseline so cross-axle ratios
    # mean wheelspin/lockup, not just "rear tyres are bigger". None if unavailable.
    coast = moving & (throttle < 0.05) & (brake < 0.05) & fast
    base_rf = float(np.mean(rf_ratio[coast])) if int(coast.sum()) > 50 else None
    base_fr = float(np.mean(fr_ratio[coast])) if int(coast.sum()) > 50 else None
    wheel_speeds = {
        # >1.0 = rear spinning faster than the coast baseline (wheelspin)
        "rear_wheelspin_index_on_throttle": round(float(np.mean(rf_ratio[spin]) / base_rf), 3) if (spin.any() and base_rf) else None,
        # <1.0 = front rotating slower than baseline under braking (locking up)
        "front_lockup_index_braking": round(float(np.mean(fr_ratio[brake_hard]) / base_fr), 3) if (brake_hard.any() and base_fr) else None,
        "rear_lr_wheelspeed_diff_on_throttle": round(float(np.mean(np.abs(wr["rl"] - wr["rr"])[spin])), 2) if spin.any() else None,
        "front_lr_wheelspeed_diff_on_throttle": round(float(np.mean(np.abs(wr["fl"] - wr["fr"])[spin])), 2) if spin.any() else None,
        "tyre_baseline_available": bool(base_rf is not None),
    }

    # --- Raw suspension travel (metres): bottoming the normalized value hides ---
    st = {w: _col(frames, f"suspension_travel_{w}") for w in wheels}
    front_t, rear_t = (st["fl"] + st["fr"]) / 2, (st["rl"] + st["rr"]) / 2

    def _range(a: np.ndarray) -> list | None:
        return [round(float(np.percentile(a[moving], 1)), 3), round(float(np.percentile(a[moving], 99.5)), 3)] if moving.any() else None

    def _bottom(a: np.ndarray) -> float | None:
        mx = float(np.percentile(a[moving], 99.5)) if moving.any() else 0.0
        return round(float(np.mean(a[moving] > 0.97 * mx)), 4) if mx > 0 else None

    raw_suspension = {
        "front_travel_range_m": _range(front_t),
        "rear_travel_range_m": _range(rear_t),
        "front_bottoming_pct_raw": _bottom(front_t),
        "rear_bottoming_pct_raw": _bottom(rear_t),
    }

    # --- Surface / weather context (gates how to trust grip findings) ---
    on_rumble = np.logical_or.reduce([_col(frames, f"wheel_on_rumble_{w}") > 0 for w in wheels])
    in_puddle = np.logical_or.reduce([_col(frames, f"wheel_in_puddle_{w}") > 0 for w in wheels])
    surf = np.mean(np.array([_col(frames, f"surface_rumble_{w}") for w in wheels]), axis=0)
    surface_context = {
        "curb_usage_pct": round(float(np.mean(on_rumble[moving])), 3) if moving.any() else None,
        "wet_pct": round(float(np.mean(in_puddle[moving])), 3) if moving.any() else None,
        "mean_surface_roughness": round(float(np.mean(surf[moving])), 3) if moving.any() else None,
        "max_surface_roughness": round(float(np.percentile(surf[moving], 99.5)), 3) if moving.any() else None,
    }

    # --- Powertrain: the power/torque curve sets the gearing target ---
    power, torque, boost = _col(frames, "power"), _col(frames, "torque"), _col(frames, "boost")
    idle = float(np.median(_col(frames, "engine_idle_rpm")))
    redline = float(np.median(maxrpm[maxrpm > 0])) if (maxrpm > 0).any() else 0.0
    peak_power_rpm = peak_torque_rpm = None
    if int(wot.sum()) > 200 and redline > idle:
        bins = np.linspace(idle, redline, 25)
        idx = np.digitize(rpm[wot], bins)
        mp = [power[wot][idx == k].mean() if int((idx == k).sum()) > 5 else -1 for k in range(1, len(bins))]
        mt = [torque[wot][idx == k].mean() if int((idx == k).sum()) > 5 else -1 for k in range(1, len(bins))]
        if max(mp) > 0:  # guard: all-sparse bins -> argmax 0 -> bogus idle "peak"
            bp = int(np.argmax(mp))
            peak_power_rpm = round(float((bins[bp] + bins[bp + 1]) / 2))
        if max(mt) > 0:
            bt = int(np.argmax(mt))
            peak_torque_rpm = round(float((bins[bt] + bins[bt + 1]) / 2))
    powertrain = {
        "idle_rpm": round(idle),
        # 99.5th pct on moving WOT — raw max() reads ~850hp from standstill/collision spikes
        "peak_power_hp": round(float(np.percentile(power[wot], 99.5)) / 745.7) if wot.any() else None,
        "peak_power_rpm": peak_power_rpm,
        "peak_torque_rpm": peak_torque_rpm,
        "max_boost": round(float(boost[moving].max()), 2) if moving.any() else None,
        "mean_boost_on_throttle": round(float(boost[wot].mean()), 2) if wot.any() else None,
    }

    # --- Tyre temperature balance: load distribution + alignment from the 4 temps ---
    tt = {w: _col(frames, f"tire_temp_{w}") for w in wheels}  # Fahrenheit on the wire
    if moving.any():
        m_c = {w: tire_temp_to_celsius(float(tt[w][moving].mean())) for w in wheels}
        front_c, rear_c = (m_c["fl"] + m_c["fr"]) / 2, (m_c["rl"] + m_c["rr"]) / 2
        left_c, right_c = (m_c["fl"] + m_c["rl"]) / 2, (m_c["fr"] + m_c["rr"]) / 2
        hottest = max(m_c, key=m_c.get)
        tire_temps = {
            "front_mean_c": round(front_c, 1),
            "rear_mean_c": round(rear_c, 1),
            # >0 = front runs hotter (front axle working harder / forward bias)
            "front_minus_rear_c": round(front_c - rear_c, 1),
            # >0 = left side hotter (net cornering-load / setup bias; track-dependent)
            "left_minus_right_c": round(left_c - right_c, 1),
            "hottest_corner": hottest,
            # FH6 temp/grip coupling is unverified: project memory refutes
            # "temp zone = peak grip" and finds no validated optimal window.
            # These temps read axle/side WORK and bias, not grip. Tune
            # camber/pressure by grip (peak latG, |slip| under 1 hold), not by
            # chasing a temp window.
            "grip_from_temp": "unverified in FH6 - read temps as work/bias, tune by grip not temp",
        }
    else:
        tire_temps = None

    # --- Extra driver inputs: clutch and handbrake ---
    clutch, hbrake = _col(frames, "clutch"), _col(frames, "hand_brake")
    driver_inputs = {
        "clutch_usage_pct": round(float(np.mean((clutch > 20) & moving)), 4) if moving.any() else None,
        "handbrake_pct": round(float(np.mean((hbrake > 20) & moving)), 4) if moving.any() else None,
    }

    # --- Lap / race timing ---
    best, last = _col(frames, "best_lap"), _col(frames, "last_lap")
    cur, rtime = _col(frames, "current_lap"), _col(frames, "current_race_time")
    lap_no, pos = _col(frames, "lap_number"), _col(frames, "race_position")
    timing = {
        "best_lap_s": round(float(np.min(best[best > 0])), 3) if (best > 0).any() else None,
        "last_lap_s": round(float(last[last > 0].max()), 3) if (last > 0).any() else None,
        "laps_seen": [int(np.min(lap_no)), int(np.max(lap_no))] if lap_no.size else None,
        "race_time_span_s": round(float(rtime.max() - rtime.min()), 1) if rtime.size else None,
        "race_position": int(np.median(pos)) if pos.size else None,
        "current_lap_max_s": round(float(cur.max()), 1) if cur.size else None,
    }

    # --- AI reference line: braking-point and line coaching ---
    ndl, abd = _col(frames, "norm_driving_line"), _col(frames, "norm_ai_brake_diff")
    reference_line = {
        "mean_abs_driving_line_offset": round(float(np.mean(np.abs(ndl[moving]))), 1) if moving.any() else None,
        "ai_brake_diff_mean": round(float(np.mean(abd[moving])), 1) if moving.any() else None,
        "note": "norm_ai_brake_diff > 0 ~ braking later/lighter than the game's reference line; < 0 ~ earlier/harder",
    }

    # --- Track geometry: route length and elevation ---
    px, py, pz = _col(frames, "position_x"), _col(frames, "position_y"), _col(frames, "position_z")
    dist = _col(frames, "distance_traveled")
    ts = _col(frames, "timestamp_ms")
    dt = np.clip(np.diff(ts) / 1000.0, 0.0, 1.0)
    driven_m = float(np.sum((speed[:-1] * dt)[moving[:-1]])) if ts.size > 1 else None
    track = {
        # integrated from speed (reliable); the raw distance_traveled counter resets per checkpoint
        "distance_driven_m": round(driven_m) if driven_m is not None else None,
        "ingame_distance_counter_range_m": round(float(dist.max() - dist.min())) if dist.size else None,
        "elevation_range_m": round(float(py[moving].max() - py[moving].min()), 1) if moving.any() else None,
        "net_displacement_m": round(float(np.hypot(px[-1] - px[0], pz[-1] - pz[0]))) if px.size else None,
    }

    return {
        "chassis_attitude": attitude,
        "body_slip": body_slip,
        "airborne": airborne,
        "wheel_speeds": wheel_speeds,
        "raw_suspension": raw_suspension,
        "surface_context": surface_context,
        "powertrain": powertrain,
        "tire_temps": tire_temps,
        "driver_inputs": driver_inputs,
        "timing": timing,
        "reference_line": reference_line,
        "track": track,
    }


def segment_session(frames: list[dict]) -> dict:
    """Per-phase grip/balance evidence + whole-lap driver technique timers.

    Returns a payload describing the car's behaviour split by driving state,
    designed to be read by the AI tuning/coaching layer. Returns
    ``{"error": ...}`` when there are too few moving frames to segment.
    """
    if len(frames) < 100:
        return {"error": f"Not enough data ({len(frames)} frames; need >100)."}

    throttle = _col(frames, "accel") / 255.0
    brake = _col(frames, "brake") / 255.0
    steer = _col(frames, "steer") / 127.0
    speed = _col(frames, "speed")  # m/s
    lat_g = _col(frames, "acceleration_x") / G
    long_g = _col(frames, "acceleration_z") / G
    comb_g = np.hypot(lat_g, long_g)

    # Per-axle, per-frame magnitudes (slip angle / combined slip) and signed
    # slip ratio (sign distinguishes wheelspin from lockup).
    def axle_abs(prefix: str, fl: str, fr: str) -> np.ndarray:
        return (np.abs(_col(frames, f"{prefix}_{fl}")) + np.abs(_col(frames, f"{prefix}_{fr}"))) / 2

    def axle_signed(prefix: str, fl: str, fr: str) -> np.ndarray:
        return (_col(frames, f"{prefix}_{fl}") + _col(frames, f"{prefix}_{fr}")) / 2

    front_sa = axle_abs("tire_slip_angle", "fl", "fr")
    rear_sa = axle_abs("tire_slip_angle", "rl", "rr")
    front_cs = axle_abs("tire_combined_slip", "fl", "fr")
    rear_cs = axle_abs("tire_combined_slip", "rl", "rr")
    front_sr = axle_signed("tire_slip_ratio", "fl", "fr")
    rear_sr = axle_signed("tire_slip_ratio", "rl", "rr")

    rpm = _col(frames, "current_engine_rpm")
    maxrpm = _col(frames, "engine_max_rpm")
    gear = _col(frames, "gear")
    yaw_rate = _col(frames, "angular_velocity_y")

    race_on = _col(frames, "is_race_on")
    # Frame-state classifiers, DERIVED per session (no fixed cutoffs). The game's own
    # is_race_on flag gates active driving — the most data-driven "moving" signal there
    # is (Otsu on SPEED is wrong: a track's speed trace is bimodal slow-corner/fast-
    # straight, not stopped/moving, so it would discard the slow corners). Otsu then
    # splits the |lat_g|/pedal traces at the valley between their off- and on-clusters.
    # Collisions are excluded from the lateral-g cut so non-physical spikes can't drag it.
    moving = race_on > 0
    if int(moving.sum()) < 100:
        return {"error": "Car barely moved; nothing to segment."}

    lat_abs = np.abs(lat_g)
    absteer = np.abs(steer)
    # Cornering onset = lateral-g clearly above the car's OWN straight-line noise:
    # take the least-steered third of moving frames as "straight" and set the cut at the
    # top (90th pct) of THEIR |lat_g|. Data-derived, and it stays low enough to keep
    # gentle corners and turn-in — where light-load rotation lives — unlike an Otsu
    # class-valley, which a straight-dominated histogram pushes mid-corner (throwing the
    # light cornering, and its findings, away).
    steer_cut = float(np.percentile(absteer[moving], 33.0))
    straight_lat = lat_abs[moving & (absteer <= steer_cut)]
    corner_lat = float(np.percentile(straight_lat, 90.0)) if straight_lat.size \
        else float(np.percentile(lat_abs[moving], 25.0))
    thr_thr = _otsu(throttle[moving])                    # on-throttle vs off (pedals ARE bimodal)
    brk_thr = _otsu(brake[moving])                       # braking vs not
    # A LOADED gate (Otsu of |lat_g|, collisions excluded) only for load-normalized
    # chassis metrics in _extended_blocks, where dividing by tiny lat_g would blow up.
    load_gate = _otsu(lat_abs[moving & (lat_abs < 4.0)])
    cornering = moving & (lat_abs > corner_lat)
    braking = brake > brk_thr
    on_throttle = throttle > thr_thr

    # Mutually-exclusive cornering phases (entry takes priority over exit/apex).
    entry = cornering & braking                      # trail-brake / turn-in
    exit_ = cornering & on_throttle & ~braking        # power-down on exit
    apex = cornering & ~braking & ~on_throttle        # mid-corner, off pedals
    straight = moving & ~cornering

    # Collisions/resets on open-road drives spike acceleration to non-physical
    # values; exclude them (|g| < 4) so the grip envelope reflects real cornering.
    clean = moving & (np.abs(lat_g) < 4.0) & (np.abs(long_g) < 4.0)
    if int(clean.sum()) < 100:
        clean = moving
    g_peak = float(np.percentile(comb_g[clean], 99))

    def stats(mask: np.ndarray) -> dict | None:
        return _phase_stats(
            mask, front_sa=front_sa, rear_sa=rear_sa, front_cs=front_cs,
            rear_cs=rear_cs, front_sr=front_sr, rear_sr=rear_sr, lat_g=lat_g,
            comb_g=comb_g, g_peak=g_peak,
        )

    n_move = int(moving.sum())
    rate = _sample_rate_hz(frames)
    dur_min = n_move / rate / 60.0

    coasting = moving & (throttle < thr_thr) & (brake < brk_thr)
    n_brake = int((braking & moving).sum())
    n_exit = int(exit_.sum())

    # Driver-technique timers (whole-lap).
    driver = {
        "trail_brake_pct": round(int(entry.sum()) / n_brake, 3) if n_brake else None,
        "coasting_pct": round(int(coasting.sum()) / n_move, 3),
        "exit_wheelspin_pct": round(int((exit_ & (rear_cs > SLIDE)).sum()) / n_exit, 3) if n_exit else None,
        "braking_lockup_pct": round(int((braking & moving & (front_sr < -0.5)).sum()) / n_brake, 3) if n_brake else None,
        "steering_reversals_per_min": round(_reversal_count(steer, 0.05) / dur_min, 1) if dur_min else None,
        "throttle_stabs_per_min": round(_reversal_count(throttle, 0.15) / dur_min, 1) if dur_min else None,
    }

    # Collision / clean-lap detection from the FH Horizon gap fields (CarGroup +
    # smashable scenery). Absent in recordings made before gap parsing was added.
    if "smashable_vel_diff" in frames[0]:
        svd = _col(frames, "smashable_vel_diff")
        mass = _col(frames, "smashable_mass")
        cg = _col(frames, "car_group").astype(int)
        hit = svd > 0.5
        rising = int(np.count_nonzero(np.diff(hit.astype(int)) > 0))  # new-impact edges
        impacts = {
            "car_group": int(np.bincount(cg[cg >= 0]).argmax()) if (cg >= 0).any() else None,
            "impact_events": rising,
            "impacts_per_10min": round(float(rising / (dur_min / 10)), 1) if dur_min else None,
            "heaviest_impact_kg": round(float(mass[hit].max())) if hit.any() else 0,
        }
    else:
        impacts = {"note": "recorded before Horizon-gap parsing; CarGroup/Smashable not captured"}

    extended = _extended_blocks(
        frames, moving=moving, lat_g=lat_g, long_g=long_g, throttle=throttle,
        brake=brake, speed=speed, rpm=rpm, maxrpm=maxrpm, gear=gear,
        lat_thr=load_gate, thr_thr=thr_thr,
    )
    return {
        "sample_rate_hz": round(rate, 1),
        "moving_minutes": round(dur_min, 2),
        "race_on_pct": round(float(np.mean(race_on > 0)), 3),
        "derived_thresholds": {
            "moving": "is_race_on (game flag)",
            "cornering_lat_g": round(corner_lat, 3),
            "on_throttle_frac": round(thr_thr, 3),
            "braking_frac": round(brk_thr, 3),
            "load_gate_lat_g": round(load_gate, 3),
            "note": "derived per session from the data (cornering = above straight-line noise; pedals = Otsu), not fixed cutoffs",
        },
        "phase_time_pct": {
            "straight": round(int(straight.sum()) / n_move, 3),
            "corner_entry": round(int(entry.sum()) / n_move, 3),
            "corner_apex": round(int(apex.sum()) / n_move, 3),
            "corner_exit": round(int(exit_.sum()) / n_move, 3),
        },
        "traction_circle": {
            "peak_combined_g": round(g_peak, 2),
            "max_lat_g": round(float(np.percentile(np.abs(lat_g[clean]), 99.5)), 2),
            "max_accel_g": round(float(np.percentile(long_g[clean], 99.5)), 2),
            "max_braking_g": round(float(np.percentile(long_g[clean], 0.5)), 2),
            "collision_frames_excluded": int(moving.sum() - clean.sum()),
        },
        "by_phase": {
            "corner_entry": stats(entry),
            "corner_apex": stats(apex),
            "corner_exit": stats(exit_),
            "straight": stats(straight),
        },
        "gearing": _gearing_stats(rpm, maxrpm, gear, speed * 2.237, throttle),
        "driver": driver,
        "impacts": impacts,
        "damper_histogram": _damper_histogram(
            {w: _col(frames, f"suspension_travel_{w}") for w in ("fl", "fr", "rl", "rr")},
            moving, rate,
        ),
        "response": _response_lag(steer, yaw_rate, rate),
        "worst_corners": _per_corner(speed, lat_g, front_sa, rear_sa, moving, rate, corner_lat),
        # Balance/grip split by operating point (speed / lateral load / tyre temp)
        # so speed-, load- and temperature-dependent levers are judged on the axis
        # they actually act through, not a blended per-phase mean.
        "apex_by_speed_band": _banded(
            apex, key=speed * 2.237, key_name="mph",
            front_sa=front_sa, rear_sa=rear_sa, front_cs=front_cs, rear_cs=rear_cs, lat_g=lat_g,
        ),
        "cornering_by_speed_band": _banded(
            cornering, key=speed * 2.237, key_name="mph",
            front_sa=front_sa, rear_sa=rear_sa, front_cs=front_cs, rear_cs=rear_cs, lat_g=lat_g,
        ),
        "cornering_by_load_band": _banded(
            cornering, key=np.abs(lat_g), key_name="latg",
            front_sa=front_sa, rear_sa=rear_sa, front_cs=front_cs, rear_cs=rear_cs, lat_g=lat_g,
        ),
        "cornering_by_temp_band": _banded(
            cornering,
            key=((_col(frames, "tire_temp_fl") + _col(frames, "tire_temp_fr")) / 2 - 32) * 5 / 9,
            key_name="tempc",
            front_sa=front_sa, rear_sa=rear_sa, front_cs=front_cs, rear_cs=rear_cs, lat_g=lat_g,
        ),
        **extended,
    }
