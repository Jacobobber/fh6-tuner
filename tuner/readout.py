"""Full read — one consolidated pass that surfaces EVERY signal segment_session
produces, organized and lightly interpreted, so nothing computed is left unread.

`segment_session` returns everything but the curated KEY-SIGNALS printout shows a
subset; this renders the complete evidence (balance by phase + speed/load/temp
band, dampers, response, grip, driver, drivetrain, chassis, impacts) plus the
tune-sheet math when the car weight is supplied. Markdown, human- and AI-readable.
"""
import json

from tuner.response import _load_frames, tune_math
from tuner.segment import segment_session


def _flag_balance(v: float | None) -> str:
    if v is None:
        return ""
    if v > 0.10:
        return "  <- understeer"
    if v < -0.10:
        return "  <- OVERSTEER"
    return "  <- ~neutral"


def _kv(d: dict, keys: tuple[str, ...]) -> list[str]:
    return [f"    {k}: {d[k]}" for k in keys if isinstance(d, dict) and d.get(k) is not None]


def _band_block(title: str, band: dict | None) -> list[str]:
    out = [f"  {title}:"]
    if not isinstance(band, dict) or "band_edges" not in band:
        note = band.get("note", "(unavailable)") if isinstance(band, dict) else "(unavailable)"
        out.append(f"    {note}")
        return out
    out.append(f"    edges {band['band_edges']}  (data-derived thirds of this session)")
    for name in ("low", "mid", "high"):
        b = band.get(name)
        if not isinstance(b, dict) or "balance_front_minus_rear" not in b:
            out.append(f"    {name:<5} (too few frames)")
            continue
        bal = b["balance_front_minus_rear"]
        out.append(
            f"    {name:<5} bal {bal:+.2f}{_flag_balance(bal)}"
            f"  | front_cs {b.get('front_combined_slip')}  rear_cs {b.get('rear_combined_slip')}"
            f"  ({b.get('frames')} fr)"
        )
    return out


def full_read(seg: dict, *, weight_lb: float | None = None,
              front_weight_pct: float | None = None, tune: dict | None = None) -> str:
    """Render the complete evidence dict as an organized, interpreted read."""
    L: list[str] = ["# FULL TELEMETRY READ", ""]

    L += ["## Session & data quality"]
    L += _kv(seg, ("sample_rate_hz", "moving_minutes", "race_on_pct"))
    if "derived_thresholds" in seg:
        L.append(f"    derived_thresholds: {json.dumps(seg['derived_thresholds'])}")
    if "phase_time_pct" in seg:
        L.append(f"    phase_time_pct: {json.dumps(seg['phase_time_pct'])}")
    if "timing" in seg:
        L.append(f"    timing: {json.dumps(seg['timing'])}")
    if "impacts" in seg:
        L.append(f"    impacts: {json.dumps(seg['impacts'])}")

    L += ["", "## Balance (>0 understeer / <0 oversteer)"]
    bp = seg.get("by_phase", {})
    for ph in ("corner_entry", "corner_apex", "corner_exit"):
        b = bp.get(ph)
        if isinstance(b, dict):
            bal = b.get("balance_front_minus_rear")
            L.append(f"  {ph:<13} bal {bal:+.2f}{_flag_balance(bal)}  | front_cs {b.get('front_combined_slip')} rear_cs {b.get('rear_combined_slip')}")
    L += _band_block("apex by SPEED band", seg.get("apex_by_speed_band"))
    L += _band_block("cornering by SPEED band", seg.get("cornering_by_speed_band"))
    L += _band_block("cornering by LOAD band (lateral g)", seg.get("cornering_by_load_band"))
    L += _band_block("cornering by TEMP band (tyre C)", seg.get("cornering_by_temp_band"))
    if "worst_corners" in seg:
        L.append(f"  worst_corners: {json.dumps(seg['worst_corners'])}")

    for title, key in (
        ("## Grip / traction circle", "traction_circle"),
        ("## Dampers (mm/s, per-corner comp/reb + distribution)", "damper_histogram"),
        ("## Response (steer->yaw)", "response"),
        ("## Driver inputs", "driver"),
        ("## Drivetrain / gearing", "gearing"),
    ):
        if key in seg:
            L += ["", title, f"    {json.dumps(seg[key])}"]

    # extended blocks (chassis attitude, wheel speeds, tyre temps, surface, etc.)
    L += ["", "## Chassis / extended blocks"]
    known = {"sample_rate_hz", "moving_minutes", "race_on_pct", "derived_thresholds", "phase_time_pct",
             "timing", "impacts", "by_phase", "apex_by_speed_band", "cornering_by_speed_band",
             "cornering_by_load_band", "cornering_by_temp_band", "worst_corners",
             "traction_circle", "damper_histogram", "response", "driver", "gearing"}
    for k, v in seg.items():
        if k not in known:
            L.append(f"  {k}: {json.dumps(v)}")

    L += ["", "## Tune math (ride frequency + roll-stiffness)"]
    if tune and weight_lb and front_weight_pct is not None:
        L.append(f"    {json.dumps(tune_math(tune, total_weight_lb=weight_lb, front_weight_pct=front_weight_pct))}")
    else:
        L.append("    (supply tune + weight_lb + front_weight_pct — from the upgrade-screen capture)")
    return "\n".join(L)


def read_session(session: str, *, weight_lb: float | None = None,
                 front_weight_pct: float | None = None, tune: dict | None = None) -> str:
    """Load a recorded session, run the full analysis, and return the complete read."""
    frames = _load_frames(session)
    if not frames:
        raise ValueError(f"no frames in sessions/{session}/ — check the name (ls sessions/)")
    return full_read(segment_session(frames), weight_lb=weight_lb,
                     front_weight_pct=front_weight_pct, tune=tune)
