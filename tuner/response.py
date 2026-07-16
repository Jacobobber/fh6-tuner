"""Empirical tune-response model.

Turns each recorded lap into a ``(tune -> outcome-metrics)`` row and learns, per
car, how moving a slider shifts the telemetry — so a proposed change can be
PREDICTED before driving instead of guessed.

This is deliberately NOT a physics simulation. Forza's physics is closed and
proprietary, so we cannot replicate it; instead we fit an empirical delta model
to laps the user already drives. It starts coarse and sharpens with every added
lap — and single-slider A/Bs (the "one change at a time" discipline) are exactly
the clean observations that train it, so the tedious verify-runs are what
eventually let us skip them.

Store: ``data/tune_responses.jsonl`` (append-only, one JSON row per ingested lap).
Each lap MUST be paired with the tune it ran (captured via forza_capture); the
telemetry stream does not carry the tune sheet, so the pairing is the plumbing.
"""
import glob
import json
from pathlib import Path

from tuner.segment import segment_session

STORE = Path("data/tune_responses.jsonl")

# Tunable slider values we track (the model INPUTS). Numeric so deltas are trivial.
TUNE_FIELDS: tuple[str, ...] = (
    "tire_press_f", "tire_press_r", "final_drive",
    "camber_f", "camber_r", "toe_f", "toe_r", "caster",
    "arb_f", "arb_r", "spring_f", "spring_r", "rh_f", "rh_r",
    "reb_f", "reb_r", "bump_f", "bump_r",
    "aero_f", "aero_r", "brake_bal", "brake_press", "diff_accel", "diff_decel",
)

# Outcome metrics (the OUTPUTS), pulled from segment_session by dotted path. Kept
# to speed-banded balance/slip so predictions land on the band a lever affects.
METRIC_PATHS: dict[str, str] = {
    "apex_bal_slow": "apex_by_speed_band.slow.balance_front_minus_rear",
    "apex_bal_med": "apex_by_speed_band.medium.balance_front_minus_rear",
    "apex_bal_fast": "apex_by_speed_band.fast.balance_front_minus_rear",
    "apex_fcs_slow": "apex_by_speed_band.slow.front_combined_slip",
    "apex_fcs_med": "apex_by_speed_band.medium.front_combined_slip",
    "apex_fcs_fast": "apex_by_speed_band.fast.front_combined_slip",
    "apex_bal": "by_phase.corner_apex.balance_front_minus_rear",
    "apex_fcs": "by_phase.corner_apex.front_combined_slip",
    "entry_bal": "by_phase.corner_entry.balance_front_minus_rear",
    "exit_bal": "by_phase.corner_exit.balance_front_minus_rear",
    "exit_wheelspin": "driver.exit_wheelspin_pct",
    "braking_lockup": "driver.braking_lockup_pct",
    "max_speed_mph": "gearing.max_speed_mph",
    "max_lat_g": "traction_circle.max_lat_g",
}


def _dig(d: dict, path: str) -> float | None:
    cur: object = d
    for key in path.split("."):
        if not isinstance(cur, dict) or cur.get(key) is None:
            return None
        cur = cur[key]
    return cur if isinstance(cur, (int, float)) else None


def _load_frames(session: str) -> list[dict]:
    frames: list[dict] = []
    for f in sorted(glob.glob(f"sessions/{session}/*.json")):
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        frames.extend(data if isinstance(data, list) else data.get("frames", []))
    return frames


def extract_metrics(seg: dict) -> dict[str, float]:
    """Flatten the segment_session output to the tracked outcome metrics."""
    out: dict[str, float] = {}
    for name, path in METRIC_PATHS.items():
        v = _dig(seg, path)
        if v is not None:
            out[name] = round(float(v), 4)
    return out


def ingest(session: str, tune: dict, *, car: str, track: str = "goliath",
           label: str = "") -> dict:
    """Analyze a session and append one ``(tune -> metrics)`` row to the store."""
    frames = _load_frames(session)
    if not frames:
        raise ValueError(
            f"no frames in sessions/{session}/ — check the session name (ls sessions/)"
        )
    seg = segment_session(frames)
    row = {
        "car": car, "session": session, "track": track, "label": label,
        "frames": len(frames),
        "tune": {k: tune.get(k) for k in TUNE_FIELDS},
        "metrics": extract_metrics(seg),
    }
    STORE.parent.mkdir(exist_ok=True)
    with STORE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def _rows(car: str | None = None) -> list[dict]:
    if not STORE.exists():
        return []
    rows = [json.loads(ln) for ln in STORE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [r for r in rows if car is None or r["car"] == car]


def sensitivities(car: str) -> dict[str, dict[str, float]]:
    """Clean single-slider response: for lap pairs differing in exactly ONE slider,
    the mean metric change per unit of that slider. These are the trustworthy
    observations (no confounding) that drive prediction."""
    rows = _rows(car)
    acc: dict[str, dict[str, list[float]]] = {}
    for a in rows:
        for b in rows:
            changed = [k for k in TUNE_FIELDS
                       if a["tune"].get(k) is not None and b["tune"].get(k) is not None
                       and abs(b["tune"][k] - a["tune"][k]) > 1e-9]
            if len(changed) != 1:
                continue
            slider = changed[0]
            step = b["tune"][slider] - a["tune"][slider]
            for m in a["metrics"]:
                if m in b["metrics"]:
                    acc.setdefault(slider, {}).setdefault(m, []).append(
                        (b["metrics"][m] - a["metrics"][m]) / step
                    )
    return {s: {m: round(sum(v) / len(v), 4) for m, v in md.items()} for s, md in acc.items()}


def predict(car: str, tune_delta: dict[str, float]) -> dict[str, dict]:
    """Predict metric deltas for a proposed tune change (coarse linear superposition
    of learned single-slider sensitivities). Flags sliders with no clean data yet."""
    sens = sensitivities(car)
    pred: dict[str, float] = {}
    unknown: list[str] = []
    for slider, step in tune_delta.items():
        if slider not in sens:
            unknown.append(slider)
            continue
        for metric, per_unit in sens[slider].items():
            pred[metric] = round(pred.get(metric, 0.0) + per_unit * step, 4)
    return {
        "predicted_metric_delta": pred,
        "sliders_without_data": unknown,
        "note": "coarse linear model; unknown sliders need a clean single-change A/B to learn",
    }


# --- Tune-sheet math (needs the car's WEIGHT; telemetry does not carry it, so
# these take weight from the in-game upgrade screen / a tune snapshot). ---
_FORZA_FREQ_K = 19.56  # Forza-applied form (motion ratio ~1): rate = Hz²·axle_lb / 19.56


def ride_frequency_hz(spring_rate_lb_in: float | None, axle_weight_lb: float) -> float | None:
    """Undamped body ride frequency — the correct CROSS-CAR spring metric (raw
    lb/in can't be compared across cars of different mass). Grip presets ~2.5 Hz."""
    if not spring_rate_lb_in or axle_weight_lb <= 0:
        return None
    return round((spring_rate_lb_in * _FORZA_FREQ_K / axle_weight_lb) ** 0.5, 2)


def tune_math(tune: dict, *, total_weight_lb: float, front_weight_pct: float) -> dict:
    """Ride frequencies + roll-stiffness distribution from a captured tune + the
    car's weight. Ride frequency normalizes spring choice across cars; roll-stiffness
    %front vs weight %front flags LOAD SENSITIVITY — the heavier axle makes
    proportionally less grip, so it wants roll bias LESS front than the weight split;
    a roll bias MORE front than the weight tends to understeer.
    """
    fw = total_weight_lb * front_weight_pct
    rw = total_weight_lb * (1.0 - front_weight_pct)
    fr_f = ride_frequency_hz(tune.get("spring_f"), fw)
    fr_r = ride_frequency_hz(tune.get("spring_r"), rw)
    sf, sr = tune.get("spring_f"), tune.get("spring_r")
    af, ar = tune.get("arb_f"), tune.get("arb_r")
    spring_pct_f = round(sf / (sf + sr), 3) if sf and sr else None
    roll = {
        "springs_pct_front": spring_pct_f,
        "arb_pct_front": round(af / (af + ar), 3) if af and ar else None,
        "weight_pct_front": round(front_weight_pct, 3),
    }
    if spring_pct_f is not None:
        diff = round(spring_pct_f - front_weight_pct, 3)
        roll["springs_minus_weight_pct_front"] = diff
        direction = (
            "more front than weight -> understeer-leaning" if diff > 0
            else "less front than weight -> rotation-leaning" if diff < 0
            else "matches the weight split"
        )
        roll["flag"] = (f"spring roll-bias {diff:+.3f} vs weight ({direction}); tyre load "
                        "sensitivity favours a touch LESS front roll-bias than the weight split")
    return {
        "ride_freq_hz": {
            "front": fr_f, "rear": fr_r,
            "front_minus_rear": round(fr_f - fr_r, 2) if (fr_f and fr_r) else None,
        },
        "roll_stiffness_pct_front": roll,
        "note": "ride freq exact (motion-ratio~1 assumption); roll %front approximate (Forza ARB units abstract). Weight from the upgrade screen, not telemetry.",
    }
