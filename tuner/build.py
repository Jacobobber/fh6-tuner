from pathlib import Path

import numpy as np

from tuner.analyzer import _load_session, _arr, _shift_rpm_ratio, DRIVETRAIN_NAMES
from tuner.segment import segment_session

# Domain guidance for the LLM that turns build signals into UPGRADE advice. The
# build layer sets the PI ceiling, so it comes FIRST in build->tune->driver. The
# verified "PI meta" is directional (community-sourced); refuted lore is fenced
# off so the model doesn't assert it. See memory: fh6-build-meta.
BUILD_GUIDANCE = """You are a Forza Horizon build engineer reading summarized \
telemetry plus car context, recommending UPGRADES (the build layer) to make the \
car faster. Pace stacks in priority order: BUILD (part upgrades) sets the \
Performance Index (PI) ceiling, TUNING (sliders) optimizes within it and is \
PI-neutral, the DRIVER extracts it. Recommend in that order — fix the build \
first, then tuning, then driving.

PI mechanics:
- PI is a lap-time-simulation composite of five factors (Speed, Handling, \
Acceleration, Launch, Braking) — non-linear, NOT an average of the bars. Only \
part upgrades change PI; slider tunes don't (but part selections in the tune \
menu — transmission tier, tire compound — do). A fast build BALANCES power, \
grip, and braking, not just power. Treat the in-game install-screen PI delta as \
the real cost of any part.

PI meta (directional, cross-corroborated across community guides — treat numbers \
as priors, not Turn10 specs):
- Weight reduction is among the most PI-efficient upgrades (improves \
acceleration, braking, AND cornering at once) — max it within budget \
(diminishing on very light <~800kg cars).
- Engine power: exhaust is the most PI-efficient; intake/ignition/fuel/pistons \
are cheap follow-ups; DISPLACEMENT is the LEAST PI-efficient (large PI per unit \
torque) — add it last.
- Race/Rally springs+dampers and race anti-roll bars cost little PI (~1-5) and \
unlock the tuning sliders — install by default (less critical at B class and \
below).
- Tires: compound scales with class — roughly street/sport ~700 PI, semi-slick \
~800, race slick at S1/S2; rally/off-road/drift builds need their MATCHING \
compound (slicks lose traction off-road). Tire WIDTH adds grip (bigger contact \
patch). In FH6, FRONT tire width is one of the cleanest PI gains — 1-2 notches \
often beat a full compound-class jump. (This reversed from FH5; this tool \
targets FH6.)
- Drivetrain: RWD is lighter, more PI-efficient, and can be "powerbuilt" (high \
power on weaker tires) — claims the fastest single laps. AWD wins S1(900)/S2 \
road racing via corner-exit grip but adds weight, tends to understeer, and an \
AWD swap costs ~30-80+ PI — not worth it in D/C class.

Telemetry -> which modification (NO verified numeric thresholds exist — reason \
directionally and hedge; limiting_factor_hint is a heuristic, not a verdict):
- SYMMETRIC driven-axle wheelspin (traction.wheelspin_pct high, \
driven_axle_lr_slip_diff low) = not enough tire for the power → BUILD wider / \
stickier tires, or AWD to split torque. L/R-ASYMMETRIC driven slip (one wheel \
spinning) = open diff → TUNE acceleration diff lock first (BUILD a race diff if \
one isn't fitted).
- gearing.mean_upshift_rpm_fraction near max with low wheelspin and lacking \
acceleration/top speed = POWER-limited → BUILD more power (engine, then \
aspiration) and/or lengthen gearing; bouncing off the limiter on the straight → \
taller final drive.
- grip front-vs-rear balance + peak_lateral_g: understeer (front > rear) → TUNE \
balance first, then BUILD front grip (front tire width in FH6, forward weight \
reduction, front aero); oversteer (rear > front) → TUNE, then rear grip/aero. A \
low peak lateral-G ceiling overall = grip-limited → BUILD compound/width.

state_segmented sharpens the power-vs-grip-limited call (the core build question):
- by_phase.corner_apex.traction_use near 1.0 = the tire is at the grip CEILING \
mid-corner → grip-limited → BUILD compound/width/weight; well below 1.0 with an \
understeer balance = a distribution/TUNE problem, not a ceiling. traction_circle.\
peak_combined_g is the actual grip ceiling reached.
- powertrain.peak_power_rpm / peak_torque_rpm vs gearing.on_throttle_below_powerband_pct \
and rpm_pct_at_max_speed: if you live below the power band or never reach redline \
in top gear, that's GEARING (tune) before power. If gearing is right and you still \
lack straight-line speed = POWER-limited → BUILD engine/aspiration.
- body_slip.big_slide_pct high with a low grip ceiling = not enough tire (BUILD); \
wheel_speeds.rear_wheelspin_index_on_throttle > 1 (when tyre_baseline_available) \
corroborates traction-limited power delivery.

Do NOT assert these (unverified / refuted): a specific forced-induction ranking \
(which of turbo / twin-turbo / supercharger / centrifugal is "best" or "laggy"); \
a fixed engine-upgrade order beyond "exhaust efficient, displacement \
inefficient"; or that power-to-weight is the single decisive metric. For \
aspiration or exact parts, recommend trying it and reading the install-screen PI \
delta.

Tailor to the goal (race / drag / top speed / rally / drift) and the PI cap or \
open/X target. Be specific and directional, justify each recommendation from the \
data, and never invent telemetry that isn't present."""

_DRIVEN = {0: ("fl", "fr"), 1: ("rl", "rr"), 2: ("fl", "fr", "rl", "rr")}


def _limiting_factor(wheelspin_pct: float, lr_diff: float, upshift_frac: float | None,
                     front_sa: float, rear_sa: float, peak_lat_g: float) -> dict:
    """Heuristic, labeled directional hint — NOT a verdict (no verified thresholds)."""
    if wheelspin_pct > 15.0 and lr_diff < 0.15:
        return {"factor": "traction (symmetric)",
                "detail": "Driven axle overwhelmed under power → BUILD: wider/stickier tires, or AWD to split torque."}
    if wheelspin_pct > 15.0:
        return {"factor": "traction (one-wheel)",
                "detail": "Asymmetric driven-wheel spin → TUNE accel diff lock first (BUILD a race diff if none)."}
    if upshift_frac is not None and upshift_frac >= 0.97:
        return {"factor": "power",
                "detail": "Tires hooked up and revving near the limiter → BUILD more power / lengthen gearing; check top speed on the straight."}
    if front_sa - rear_sa > 0.05:
        return {"factor": "front grip (understeer)",
                "detail": "Front loses grip first → TUNE balance, then BUILD front grip (FH6 front tire width, forward weight reduction, front aero)."}
    if rear_sa - front_sa > 0.05:
        return {"factor": "rear grip (oversteer)",
                "detail": "Rear loses grip first → TUNE balance, then BUILD rear grip/aero."}
    return {"factor": "balanced",
            "detail": "No single limit dominates → refine via tuning and driving; raise the PI ceiling with weight reduction + efficient power."}


def compute_build_signals(session_dir: Path) -> dict:
    """Reduce a session to upgrade-diagnostic signals + car context for an LLM.

    Returns DATA (no verdicts beyond a labeled directional hint). Raises
    FileNotFoundError if the session has no laps; returns {"error": ...} if too
    few frames.
    """
    frames, info = _load_session(session_dir)
    if len(frames) < 100:
        return {"error": f"Not enough data ({len(frames)} frames; need >100)."}

    dt_id = info.get("drivetrain_type", -1)
    driven = _DRIVEN.get(dt_id, ("fl", "fr", "rl", "rr"))

    accel = _arr(frames, "accel")  # throttle 0-255
    on_throttle = accel > 200
    rpm = _arr(frames, "current_engine_rpm")
    max_rpm = _arr(frames, "engine_max_rpm")
    rpm_frac = np.divide(rpm, max_rpm, out=np.zeros_like(rpm), where=max_rpm > 0)
    speed_mph = _arr(frames, "speed") * 2.237
    power_w = _arr(frames, "power")
    # Robust peak power: raw max() reads ~850hp from standstill/collision spikes.
    _wot = on_throttle & (speed_mph > 6.7)
    peak_power_hp = round(float(np.percentile(power_w[_wot], 99.5)) / 745.7) if bool(_wot.any()) else round(float(np.max(power_w)) / 745.7)
    torque = _arr(frames, "torque")
    latg = np.abs(_arr(frames, "acceleration_x") / 9.81)
    comb = {c: _arr(frames, f"tire_combined_slip_{c}") for c in ("fl", "fr", "rl", "rr")}

    driven_slip = np.maximum.reduce([comb[c] for c in driven])
    n_on = int(np.sum(on_throttle))
    wheelspin_pct = round(100 * float(np.mean(driven_slip[on_throttle] > 1.0)), 1) if n_on else 0.0
    lr = ("rl", "rr") if dt_id in (1, 2) else ("fl", "fr")
    lr_diff = float(np.mean(np.abs(comb[lr[0]] - comb[lr[1]])))

    sa_f = np.concatenate([_arr(frames, "tire_slip_angle_fl"), _arr(frames, "tire_slip_angle_fr")])
    sa_r = np.concatenate([_arr(frames, "tire_slip_angle_rl"), _arr(frames, "tire_slip_angle_rr")])
    front_sa, rear_sa = float(np.mean(np.abs(sa_f))), float(np.mean(np.abs(sa_r)))
    front_cs = float(np.mean(np.concatenate([comb["fl"], comb["fr"]])))
    rear_cs = float(np.mean(np.concatenate([comb["rl"], comb["rr"]])))
    peak_lat_g = round(float(np.percentile(latg, 95)), 2)
    upshift_frac = _shift_rpm_ratio(frames)

    return {
        "car": {
            "performance_index": info.get("car_performance_index", "unknown"),
            "car_class": info.get("car_class", "unknown"),
            "drivetrain": DRIVETRAIN_NAMES.get(dt_id, "unknown"),
            "num_cylinders": info.get("num_cylinders", "unknown"),
        },
        "power": {
            "max_power_hp": peak_power_hp,
            "max_torque_nm": round(float(np.max(torque)), 0),
            "max_engine_rpm": round(float(np.max(max_rpm)), 0),
            "mean_upshift_rpm_fraction": round(upshift_frac, 3) if upshift_frac is not None else None,
            "time_at_limiter_pct": round(100 * float(np.mean(rpm_frac > 0.98)), 1),
        },
        "speed_mph": {"top": round(float(np.max(speed_mph)), 1), "mean": round(float(np.mean(speed_mph)), 1)},
        "traction": {
            "driven_axle": "/".join(driven),
            "full_throttle_pct": round(100 * float(np.mean(accel > 250)), 1),
            "wheelspin_pct": wheelspin_pct,
            "driven_axle_lr_slip_diff": round(lr_diff, 4),
        },
        "grip": {
            "peak_lateral_g": peak_lat_g,
            "front_combined_slip_mean": round(front_cs, 4),
            "rear_combined_slip_mean": round(rear_cs, 4),
            "slip_angle_front_mean_abs": round(front_sa, 4),
            "slip_angle_rear_mean_abs": round(rear_sa, 4),
        },
        "limiting_factor_hint": _limiting_factor(wheelspin_pct, lr_diff, upshift_frac, front_sa, rear_sa, peak_lat_g),
        "state_segmented": segment_session(frames),
    }
