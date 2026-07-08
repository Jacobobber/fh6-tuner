import json
from pathlib import Path

import numpy as np

from tuner.analyzer import _load_session, _arr, DRIVETRAIN_NAMES
from tuner.segment import segment_session
from laps.comparator import compute_comparison

# Domain guidance for the LLM that turns these stats into driver coaching. Kept
# with the data shape, mirroring tuner.summary.TUNING_GUIDANCE. The numbers here
# are DATA: the model reasons over them, it does not get pre-baked verdicts.
COACHING_GUIDANCE = """You are a driving coach reading summarized telemetry from \
a real driven session. Turn these aggregates into concrete, prioritized driver \
feedback about technique -- braking, throttle, lines, car control, consistency \
-- separate from car setup. Be specific and reference the numbers.

How to read the stats:
- inputs.full_throttle_pct / braking_pct / coasting_pct describe commitment. \
Very high full-throttle with little braking is open-road/straight-line driving; \
lots of coasting suggests hesitancy or lifting too early.
- inputs.brake_throttle_overlap_pct: time both pedals are applied. A little is \
trail-braking; a lot (esp. in RWD) unsettles the car -- coach cleaner pedal \
transitions.
- inputs.trail_brake_pct: braking while steering (braking carried into the \
corner). Some is good rotation; too much with front grip-loss means overdriving \
entry.
- grip.front_grip_loss_pct / rear_grip_loss_pct: fraction of time that axle's \
combined slip exceeds 1.0 (sliding). High front = washing out / too much entry \
speed or steering for available grip; high rear = power-down or lift-off \
oversteer. This is partly driver (entry speed, inputs) and partly car (balance) \
-- say which.
- grip.wheelspin_or_lock_pct: traction lost under power or braking (modulate \
throttle/brake, or it's a setup/diff issue).
- grip.slip_angle_front/rear_mean_abs: cornering balance the driver is working \
the tires at; front >> rear pairs with understeer feel.
- g_force.sustained_* are robust percentiles (real cornering/braking capability \
being used). peak_g_likely_impact and impact_events_over_4g are COLLISIONS / \
curb or terrain strikes, NOT cornering -- each one scrubs speed and upsets the \
car; coach cleaner lines, do not read them as grip.
- consistency (only present with >=2 completed laps): lap_time_spread_s shows \
repeatability; sector_delta_vs_fastest shows exactly where slower laps lose time \
(positive delta = slower in that sector). Without completed laps you cannot give \
lap-delta or consistency coaching -- say so and suggest recording full laps.

state_segmented is the richer, per-driving-state view — prefer it for technique:
- driver.trail_brake_pct / coasting_pct / steering_reversals_per_min (sawing the \
wheel = fighting the car) / throttle_stabs_per_min / exit_wheelspin_pct are direct \
technique signals. by_phase.balance_front_minus_rear per corner phase tells you \
WHERE the imbalance is (entry vs apex vs exit), which separates a line/entry-speed \
problem from a setup problem.
- reference_line.ai_brake_diff_mean: braking later/lighter (>0) or earlier/harder \
(<0) than the game's reference — concrete braking-point coaching. \
mean_abs_driving_line_offset = how far off the racing line.
- impacts.impact_events / impacts_per_10min is the REAL collision counter (from \
the smashable-scenery channels) — use it instead of g_force.peak_g_likely_impact, \
which is a cruder proxy. Each impact scrubs speed; high counts = clean-lap problem.
- body_slip.big_slide_pct = how often the whole car is sliding (car control). \
surface_context.wet_pct / curb_usage_pct: discount grip findings from wet or \
curb-riding frames and coach line choice instead.

Prioritize the biggest time/safety costs first. Be encouraging but direct. Do \
not invent telemetry that is not present."""


def _pct(mask: np.ndarray) -> float:
    return round(float(np.mean(mask)) * 100.0, 1)


def compute_coaching_stats(session_dir: Path) -> dict:
    """Reduce a session to driver-technique aggregates for an LLM to coach over.

    Returns a data payload (no verdicts). Raises FileNotFoundError if the
    session has no laps; returns {"error": ...} if there are too few frames.
    """
    frames, info = _load_session(session_dir)
    if len(frames) < 100:
        return {"error": f"Not enough data ({len(frames)} frames; need >100)."}

    accel, brake = _arr(frames, "accel"), _arr(frames, "brake")
    steer = np.abs(_arr(frames, "steer"))
    speed_mph = _arr(frames, "speed") * 2.237
    longg = _arr(frames, "acceleration_z") / 9.81
    latg = np.abs(_arr(frames, "acceleration_x") / 9.81)
    amag = np.sqrt(
        _arr(frames, "acceleration_x") ** 2
        + _arr(frames, "acceleration_y") ** 2
        + _arr(frames, "acceleration_z") ** 2
    ) / 9.81
    csf = np.maximum(_arr(frames, "tire_combined_slip_fl"), _arr(frames, "tire_combined_slip_fr"))
    csr = np.maximum(_arr(frames, "tire_combined_slip_rl"), _arr(frames, "tire_combined_slip_rr"))
    sr = np.maximum.reduce([np.abs(_arr(frames, f"tire_slip_ratio_{c}")) for c in ("fl", "fr", "rl", "rr")])
    sa_f = np.concatenate([_arr(frames, "tire_slip_angle_fl"), _arr(frames, "tire_slip_angle_fr")])
    sa_r = np.concatenate([_arr(frames, "tire_slip_angle_rl"), _arr(frames, "tire_slip_angle_rr")])

    complete = sorted(p for p in session_dir.glob("lap_*.json") if "_partial" not in p.name)
    lap_times: list[float] = []
    for p in complete:
        lap = json.loads(p.read_text())
        if lap:
            lap_times.append(round(max(f["current_lap"] for f in lap), 3))

    stats = {
        "drivetrain": DRIVETRAIN_NAMES.get(info.get("drivetrain_type", -1), "unknown"),
        "frames_analyzed": len(frames),
        "completed_laps": len(complete),
        "analyzed_partial_only": len(complete) == 0,
        "lap_times_s": lap_times,
        "inputs": {
            "full_throttle_pct": _pct(accel > 250),
            "partial_throttle_pct": _pct((accel > 10) & (accel <= 250)),
            "coasting_pct": _pct((accel < 10) & (brake < 10)),
            "braking_pct": _pct(brake > 20),
            "brake_throttle_overlap_pct": _pct((brake > 20) & (accel > 20)),
            "trail_brake_pct": _pct((brake > 20) & (steer > 20)),
            "mean_steer_abs": round(float(np.mean(steer)), 1),
        },
        "grip": {
            "front_grip_loss_pct": _pct(csf > 1.0),
            "rear_grip_loss_pct": _pct(csr > 1.0),
            "wheelspin_or_lock_pct": _pct(sr > 0.5),
            "slip_angle_front_mean_abs": round(float(np.mean(np.abs(sa_f))), 3),
            "slip_angle_rear_mean_abs": round(float(np.mean(np.abs(sa_r))), 3),
        },
        "speed_mph": {
            "top": round(float(speed_mph.max()), 1),
            "mean": round(float(speed_mph.mean()), 1),
        },
        "g_force": {
            "sustained_braking_g": round(float(np.percentile(longg, 1)), 2),
            "sustained_accel_g": round(float(np.percentile(longg, 99)), 2),
            "sustained_lateral_g": round(float(np.percentile(latg, 95)), 2),
            "peak_g_likely_impact": round(float(amag.max()), 2),
            "impact_events_over_4g": int(np.sum(amag > 4.0)),
        },
        "state_segmented": segment_session(frames),
    }

    if len(lap_times) >= 2:
        fastest = complete[int(np.argmin(lap_times))]
        ref = complete[0] if complete[0] != fastest else complete[1]
        comparison = compute_comparison(ref, fastest)
        stats["consistency"] = {
            "best_lap_s": min(lap_times),
            "lap_time_spread_s": round(max(lap_times) - min(lap_times), 3),
            "sector_delta_vs_fastest": comparison.get("sectors", []),
        }
    return stats
