from pathlib import Path

import numpy as np

from telemetry.parser import tire_temp_to_celsius
from tuner.analyzer import _load_session, _arr, _shift_rpm_ratio, DRIVETRAIN_NAMES
from tuner.segment import segment_session

# Tuning goals: how the recommendations should be weighted.
GOALS = {
    "balanced": "A do-everything setup. Balance grip, stability, and straight-line speed.",
    "race": "Circuit racing on tarmac. Maximize cornering grip and stability under braking.",
    "drift": "Sustained oversteer on demand. Favor rear rotation, throttle steerability, and angle control.",
    "rally": "Mixed-surface and dirt. Favor compliance, ride height, and traction over flat-out grip.",
    "topspeed": "Maximum terminal velocity. Minimize drag, lengthen gearing, stabilize at high speed.",
    "drag": "Standing-start acceleration. Maximize launch traction and shift-point efficiency.",
}

# Domain guidance for whatever LLM consumes the summary (used as MCP server
# instructions). Kept here so the tuning knowledge lives with the data shape.
TUNING_GUIDANCE = """You are an expert Forza Horizon tuning engineer reading \
summarized telemetry from real driven laps. Produce concrete, directional tune \
changes a player applies in the in-game tune menu, across the full tune sheet: \
tire pressure, gearing (final drive and individual ratios), alignment (camber, \
toe, caster), anti-roll bars, springs, ride height, damping (bump and rebound), \
aero (front/rear downforce), braking (balance and pressure), and differential \
(acceleration and deceleration lock).

How to read the summary (all slip fields are Forza-normalized: 0 = full grip, \
|value| >= 1.0 = loss of grip; 1.0 is the grip-LOSS onset, so do NOT assume peak \
grip sits just below 1.0 -- the optimal sub-1.0 value is undocumented):
- tire_temp_c_mean is already Celsius (the wire unit is Fahrenheit, converted \
here). Forza tire pressure does NOT track temperature like real physics, so \
never tie a pressure change to a temperature reading.
- suspension_bottoming_fraction near/above ~0.05 means that axle is bottoming \
out: raise ride height first, then stiffen springs only if ride height is maxed.
- normalized_suspension_travel std: high = that axle's spring/ARB too soft; very \
low = too stiff (a directional heuristic, not a calibrated threshold).
- tire_slip_angle front vs rear is the primary balance signal: front higher = \
understeer (soften front ARB/springs, add front camber, reduce front toe); rear \
higher = oversteer (soften rear ARB/springs, add rear camber, raise diff decel \
lock). Cross-check against tire_combined_slip balance.
- tire_combined_slip high sustained = tire overloaded/sliding (soften that axle, \
reduce camber, fix alignment); near 0 = under-worked (room for more aggressive \
alignment).
- driven_axle_lr_slip_diff high = open differential losing drive: add accel diff \
lock. Baselines: RWD accel 40-60% (use the 40-50% LOW end for HIGH-POWER builds \
to cut exit snap) / decel 15-30%; FWD accel 20-30% / decel \
0-10%; AWD center 60-70%. Fix corner-EXIT oversteer by lowering accel lock \
~2-3%; corner-ENTRY oversteer by raising decel lock ~2-3%.
- anti-roll bars shift balance, not absolute grip: softer front -> more \
oversteer; softer rear -> more understeer.
- gearing.mean_upshift_rpm_fraction_of_max well below ~0.85 = gears too short \
(lengthen final drive); >= ~0.98 = hitting the limiter (lengthen top gear). This \
top-level metric is WEAK: it only samples shift instants and is blind to an \
over-tall top gear. Prefer state_segmented.gearing: top_gear_max_rpm_pct well \
below ~0.95 means the top gear never reaches redline even at top speed (gearing \
too LONG -> shorten final drive); on_throttle_below_powerband_pct high (>~0.30) \
means lots of throttle time below 70% redline (lugging out of corners -> shorten \
final drive and/or tighten gear spacing); rpm_pct_at_max_speed near redline is \
the target.
- tire pressure is not in telemetry: recommend a fixed baseline ~30-34 PSI warm, \
slightly higher front, adjusted by goal (lower for grip/compliance off-road, \
higher for turn-in response).
- camber baseline about -1.5 to -1.8 deg front (slightly less rear); use \
tire_combined_slip/temperature only as a cross-check.

state_segmented is the MOST IMPORTANT block: it splits the lap by driving state \
so slip is read in context (a flat lap-mean buries corner behaviour under \
straight-line frames). Always prefer it over the lap-mean fields above.
- by_phase has corner_entry (trail-braking/turn-in), corner_apex (mid-corner, \
off the pedals), corner_exit (on-throttle), and straight. Read balance PER \
PHASE, not overall.
- balance_front_minus_rear: >0 = understeer (front sliding more), <0 = oversteer \
(rear sliding more) in THAT phase. Entry oversteer vs exit oversteer need \
different fixes: entry -> raise diff DECEL lock / soften front-of-entry; exit -> \
lower diff ACCEL lock / soften rear ARB / add rear downforce. Apex understeer -> \
front ARB/camber/aero or (if traction_use is already ~1.0) it is a grip-ceiling \
build limit, not a tune fix.
- rear_slip_ratio_signed in corner_exit strongly positive = power-down wheelspin \
(raise accel diff lock, or it is driver over-throttle - see driver block). \
front_slip_ratio_signed strongly negative under braking = lockup (lower brake \
pressure / shift bias rearward).
- traction_circle.peak_combined_g is the grip ceiling actually reached; per-phase \
traction_use near 1.0 means the tire is maxed there (a build/grip limit), well \
below 1.0 means unused grip (tune or driver).
- driver block separates pillars: high exit_wheelspin_pct WITH the exit-phase \
oversteer = likely DRIVER over-throttle, not tune; high steering_reversals_per_min \
= sawing the wheel / fighting the car; high coasting_pct = lost time (brake \
earlier-and-shorter or get to throttle sooner); low trail_brake_pct on a circuit \
= leaving entry time on the table. Attribute a problem to the DRIVER when it \
coincides with messy inputs, to the TUNE when balance is off with clean inputs, \
to the BUILD when traction_use is already maxed.

state_segmented also exposes the rest of the channels - use them:
- powertrain.peak_power_rpm / peak_torque_rpm define the gearing TARGET: size \
gearing so on-throttle RPM stays between peak torque and redline, shifting at/just \
past peak power. Cross-check against the gearing block.
- body_slip (car sideslip from velocity, independent of tire slip): \
mean_abs_slip_deg_cornering and big_slide_pct rising = the whole chassis is \
sliding (oversteer/drift) - a chassis-level confirmation of the slip-angle \
balance. Trust it only when velocity_z_vs_speed_ratio is ~1.0 (that confirms \
velocity is car-local so the sideslip math holds); if it drifts from 1.0, ignore \
body_slip.
- tire_temps balance (Celsius): FH6 temp-to-grip is UNVERIFIED (project memory \
refutes "temp zone = peak grip"; no validated window). Read these as which axle/\
side is WORKING harder, not as grip - judge grip from slip/balance. \
front_minus_rear_c >0 = front axle working harder (forward bias / understeer \
tendency - matches a front-heavy slip-angle balance); left_minus_right_c far from \
0 = one side loaded more (camber/pressure asymmetry, or a track with more turns \
one way - cross-check the route). Do not infer "cold = low grip" or chase a temp \
window; tune camber/pressure by grip-sweep.
- chassis_attitude.body_roll_deg_per_g high = soft ARB/springs (stiffen for \
response); large brake_dive/accel_squat = soften compression/extension damping or \
adjust ride; high pitch/roll rates = under-damped transients.
- wheel_speeds corroborate the diff/slip story (only when tyre_baseline_available): \
rear_wheelspin_index_on_throttle > 1 = rear spinning up; front_lockup_index_braking \
< 1 = fronts locking under brakes; lr_wheelspeed_diff = open-diff scrabble.
- raw_suspension.*_bottoming_pct_raw is the reliable bottoming signal (normalized \
travel saturates); if set, raise ride height then stiffen.
- surface_context: if wet_pct or curb_usage_pct is high, DISCOUNT grip/slip \
findings from those frames (water and curbs corrupt them) and note it; rough \
surfaces argue for softer suspension.
- driver_inputs.handbrake_pct high off-road/drift only; clutch_usage for launch/shift \
technique. reference_line.ai_brake_diff_mean signals whether the driver brakes \
earlier/later than the game line. track.elevation_range_m / distance_m give route \
context (hills change gearing/power demand). timing.best_lap_s for pace; laps_seen \
for consistency. airborne.airtime_pct flags jumps that invalidate grip readings.

Newer state_segmented evidence blocks: CONDITIONING BANDS — apex_by_speed_band / \
cornering_by_speed_band, cornering_by_load_band (lateral g), cornering_by_temp_band \
(tyre °C): READ THE BAND A LEVER ACTS THROUGH, never the blended per-phase mean — \
aero effects live in the HIGH speed band, tyre load-sensitivity understeer shows only \
in the HIGH-load band, grip loss shows in the HOT band. Bands are DATA-DERIVED: the \
low/mid/high edges are the terciles of THIS session's own distribution (reported as \
band_edges), NOT fixed cutoffs — they adapt to the car and track, so compare within a \
session, not across. damper_histogram is real mm/s per CORNER; read comp_reb_balance_iqr \
(~0.5 = even through the car's own inter-quartile velocity band) — per-corner asymmetry \
is the signal — plus abs_mm_s p50/p90 for how spiky the input is (no fixed regimes). response.steer_to_yaw_lag_ms (the sharp-vs-heavy \
signal — high ms = lazy/heavy turn-in, a RESPONSE-rate complaint DISTINCT from \
understeer, fixed via roll stiffness/damping/ride-height not balance); worst_corners \
(per-individual-corner balance, +understeer / -oversteer, to target one corner). For \
SPRINGS use tune_math RIDE FREQUENCY (Hz, cross-car-comparable) not raw lb/in, and \
roll-stiffness %front vs WEIGHT %front (heavier axle wants LESS front bias — more front \
= understeer-prone); both need the car weight from the upgrade screen. A FULL bidirectional tuning<->telemetry reference (every knob's \
signature, symptom->fix tables, the feel dictionary incl. "feels heavy", target \
traces) is appended to these MCP instructions — consult it. REFUTED, do not assert: \
"AWD dominates S1 / RWD only B-A" and "RWD powerbuilds hold the fastest times" — \
RWD is viable at S1, and rear wheelspin is a diff/balance TUNING problem, not \
"too much power".

Tailor every recommendation to the stated goal. Be specific and directional \
(increase / decrease / keep) with a target or magnitude, and justify each from \
the data. Do not invent telemetry that is not present."""


def summarize_session(session_dir: Path, goal: str = "balanced") -> dict:
    """Reduce a recorded session to a compact stats payload for an LLM.

    Raises FileNotFoundError if the session has no laps, ValueError for an
    unknown goal, and returns {"error": ...} if there are too few frames.
    """
    if goal not in GOALS:
        raise ValueError(f"Unknown goal '{goal}'. Choose one of: {', '.join(GOALS)}.")

    frames, info = _load_session(session_dir)
    if len(frames) < 100:
        return {"error": f"Not enough data ({len(frames)} frames; need >100)."}

    def axle_pair(prefix: str) -> dict:
        fl, fr = _arr(frames, f"{prefix}_fl"), _arr(frames, f"{prefix}_fr")
        rl, rr = _arr(frames, f"{prefix}_rl"), _arr(frames, f"{prefix}_rr")
        return {
            "front_mean": round(float(np.mean(np.concatenate([fl, fr]))), 4),
            "rear_mean": round(float(np.mean(np.concatenate([rl, rr]))), 4),
            "front_std": round(float(np.std(np.concatenate([fl, fr]))), 4),
            "rear_std": round(float(np.std(np.concatenate([rl, rr]))), 4),
        }

    slip_fl, slip_fr = _arr(frames, "tire_slip_ratio_fl"), _arr(frames, "tire_slip_ratio_fr")
    slip_rl, slip_rr = _arr(frames, "tire_slip_ratio_rl"), _arr(frames, "tire_slip_ratio_rr")
    accel_g = _arr(frames, "acceleration_x") / 9.81
    long_g = _arr(frames, "acceleration_z") / 9.81
    ratio = _shift_rpm_ratio(frames)
    susp_front = np.concatenate([_arr(frames, "norm_suspension_fl"), _arr(frames, "norm_suspension_fr")])
    susp_rear = np.concatenate([_arr(frames, "norm_suspension_rl"), _arr(frames, "norm_suspension_rr")])
    yaw_rate = np.abs(_arr(frames, "angular_velocity_y"))  # rad/s
    steer = np.abs(_arr(frames, "steer"))  # -127..127
    best = _arr(frames, "best_lap")  # 0 until a lap completes
    best_lap_s = round(float(best[best > 0].min()), 3) if (best > 0).any() else None
    # Robust peak power: raw max() reads ~850hp from standstill/collision spikes;
    # take the 99.5th pct over moving, wide-open-throttle frames instead.
    pw = _arr(frames, "power")
    _wot = (_arr(frames, "speed") > 3.0) & (_arr(frames, "accel") > 230)
    peak_power_hp = round(float(np.percentile(pw[_wot], 99.5)) / 745.7) if _wot.any() else round(float(pw.max()) / 745.7)

    return {
        "goal": goal,
        "goal_description": GOALS[goal],
        "car": {
            "ordinal": info.get("car_ordinal", "unknown"),
            "performance_index": info.get("car_performance_index", "unknown"),
            "drivetrain": DRIVETRAIN_NAMES.get(info.get("drivetrain_type", -1), "unknown"),
            "car_class": info.get("car_class", "unknown"),
            "num_cylinders": info.get("num_cylinders", "unknown"),
        },
        "frames_analyzed": len(frames),
        "normalized_suspension_travel": axle_pair("norm_suspension"),
        "suspension_bottoming_fraction": {
            "front": round(float(np.mean(susp_front > 0.95)), 4),
            "rear": round(float(np.mean(susp_rear > 0.95)), 4),
        },
        "tire_combined_slip": axle_pair("tire_combined_slip"),
        "tire_slip_angle": axle_pair("tire_slip_angle"),
        "driven_axle_lr_slip_diff": {
            "front": round(float(np.mean(np.abs(slip_fl - slip_fr))), 4),
            "rear": round(float(np.mean(np.abs(slip_rl - slip_rr))), 4),
        },
        "tire_temp_c_mean": {
            c: round(tire_temp_to_celsius(float(np.mean(_arr(frames, f"tire_temp_{c}")))), 1)
            for c in ("fl", "fr", "rl", "rr")
        },
        "gearing": {
            "mean_upshift_rpm_fraction_of_max": round(ratio, 3) if ratio is not None else None,
            "max_engine_rpm": round(float(np.max(_arr(frames, "engine_max_rpm"))), 0),
        },
        "max_speed_mph": round(float(np.max(_arr(frames, "speed"))) * 2.237, 1),
        "max_power_hp": peak_power_hp,
        "lateral_g": {
            "max_left": round(float(np.max(accel_g)), 2),
            "max_right": round(float(np.min(accel_g)), 2),
        },
        "longitudinal_g": {
            "max_accel": round(float(np.max(long_g)), 2),
            "max_braking": round(float(np.min(long_g)), 2),
        },
        "rotation": {
            "mean_abs_yaw_rate_rad_s": round(float(np.mean(yaw_rate)), 4),
            "max_abs_yaw_rate_rad_s": round(float(np.max(yaw_rate)), 4),
            "mean_abs_steer_input": round(float(np.mean(steer)), 1),
        },
        "best_lap_s": best_lap_s,
        "state_segmented": segment_session(frames),
    }
