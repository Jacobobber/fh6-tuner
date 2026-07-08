import json
from pathlib import Path

import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

DRIVETRAIN_NAMES = {0: "FWD", 1: "RWD", 2: "AWD"}

# status -> rich color for rendering findings
_STATUS_COLOR = {"ok": "green", "warn": "yellow", "bad": "red", "info": "cyan", "none": "dim"}


def _load_session(session_dir: Path) -> tuple[list[dict], dict]:
    lap_files = sorted(session_dir.glob("lap_*.json"))
    if not lap_files:
        raise FileNotFoundError(f"No lap files in {session_dir}")
    # Prefer complete laps, but fall back to partial laps when none completed
    # (free roam, or recording stopped mid-lap) so the run still gets analyzed.
    complete = [lf for lf in lap_files if "_partial" not in lf.name]
    use = complete or lap_files
    frames: list[dict] = []
    for lf in use:
        with open(lf) as f:
            frames.extend(json.load(f))
    info_path = session_dir / "session_info.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    return frames, info


def _arr(frames: list[dict], key: str) -> np.ndarray:
    return np.array([f[key] for f in frames], dtype=float)


def _shift_rpm_ratio(frames: list[dict]) -> float | None:
    """Mean upshift RPM as a fraction of max RPM, or None if too few shifts.

    Forza sends gear=11 (neutral) for a frame or two *during* a shift, so a raw
    3->4 change reads as a spurious 3->11 "upshift" caught at the lift point.
    Forward-fill the last real gear (1..10) so only true gear-up transitions
    count, with RPM sampled at the genuine shift frame.
    """
    rpms = _arr(frames, "current_engine_rpm")
    max_rpms = _arr(frames, "engine_max_rpm")
    gears = np.array([f["gear"] for f in frames], dtype=float)
    gears[(gears < 1) | (gears > 10)] = np.nan  # neutral/reverse/mid-shift
    valid = np.where(~np.isnan(gears), np.arange(gears.size), 0)
    np.maximum.accumulate(valid, out=valid)     # forward-fill last real gear
    real = gears[valid]
    upshifts = np.where(np.diff(real) > 0)[0]
    ratios = [rpms[i] / max_rpms[i] for i in upshifts if max_rpms[i] > 0]
    return float(np.mean(ratios)) if len(ratios) > 5 else None


def compute_recommendations(session_dir: Path) -> dict:
    """Heuristic tune analysis as structured data (shared by CLI and MCP).

    Returns {"car", "frames", "findings": [{area, status, detail, value}]}.
    Raises FileNotFoundError if the session has no lap files; returns a
    findings list with a single "none" entry if there are too few frames.
    """
    frames, info = _load_session(session_dir)
    n = len(frames)
    drivetrain = info.get("drivetrain_type", -1)
    car = {
        "performance_index": info.get("car_performance_index", "unknown"),
        "drivetrain": DRIVETRAIN_NAMES.get(drivetrain, "unknown"),
        "car_class": info.get("car_class", "unknown"),
    }
    if n < 100:
        return {
            "car": car,
            "frames": n,
            "findings": [{
                "area": "Data",
                "status": "none",
                "detail": "Not enough data for reliable analysis (need >100 frames).",
                "value": n,
            }],
        }

    findings: list[dict] = []

    # --- Suspension ---
    susp_f = np.concatenate([_arr(frames, "norm_suspension_fl"), _arr(frames, "norm_suspension_fr")])
    susp_r = np.concatenate([_arr(frames, "norm_suspension_rl"), _arr(frames, "norm_suspension_rr")])
    for axle, std in (("Front", float(np.std(susp_f))), ("Rear", float(np.std(susp_r)))):
        if std > 0.30:
            status, detail = "warn", f"Too soft (std={std:.2f}) - stiffen springs/ARB"
        elif std < 0.05:
            status, detail = "info", f"Too stiff (std={std:.2f}) - soften springs/ARB"
        else:
            status, detail = "ok", f"OK (std={std:.2f})"
        findings.append({"area": f"Suspension {axle}", "status": status, "detail": detail, "value": round(std, 4)})

    # --- Bottoming out (normalized travel near 1.0 = compression exhausted) ---
    for axle, arr in (("Front", susp_f), ("Rear", susp_r)):
        bottom_frac = float(np.mean(arr > 0.95))
        if bottom_frac > 0.05:
            status, detail = "bad", f"Bottoming out {bottom_frac:.0%} of the time - raise ride height, then stiffen springs if already maxed"
        elif bottom_frac > 0.01:
            status, detail = "warn", f"Occasional bottoming ({bottom_frac:.0%}) - add ride height or bump stiffness"
        else:
            status, detail = "ok", f"No bottoming ({bottom_frac:.0%})"
        findings.append({"area": f"Ride Height {axle}", "status": status, "detail": detail, "value": round(bottom_frac, 4)})

    # --- Differential ---
    slip_fl, slip_fr = _arr(frames, "tire_slip_ratio_fl"), _arr(frames, "tire_slip_ratio_fr")
    slip_rl, slip_rr = _arr(frames, "tire_slip_ratio_rl"), _arr(frames, "tire_slip_ratio_rr")
    if drivetrain in (1, 2):  # RWD or AWD - check rear diff
        d = float(np.mean(np.abs(slip_rl - slip_rr)))
        status, detail = ("warn", f"Rear diff too open (L/R diff={d:.3f}) - increase accel lock") if d > 0.15 \
            else ("ok", f"Rear diff OK (L/R diff={d:.3f})")
    elif drivetrain == 0:  # FWD - check front diff
        d = float(np.mean(np.abs(slip_fl - slip_fr)))
        status, detail = ("warn", f"Front diff too open (L/R diff={d:.3f}) - increase accel lock") if d > 0.15 \
            else ("ok", f"Front diff OK (L/R diff={d:.3f})")
    else:
        d, status, detail = 0.0, "none", "Drivetrain unknown - no diff advice"
    findings.append({"area": "Differential", "status": status, "detail": detail, "value": round(d, 4)})

    # --- Tire grip / load (combined slip: 0 = full grip, |slip| > 1 = sliding) ---
    comb_fl, comb_fr = _arr(frames, "tire_combined_slip_fl"), _arr(frames, "tire_combined_slip_fr")
    comb_rl, comb_rr = _arr(frames, "tire_combined_slip_rl"), _arr(frames, "tire_combined_slip_rr")
    front_slip = float(np.mean(np.concatenate([comb_fl, comb_fr])))
    rear_slip = float(np.mean(np.concatenate([comb_rl, comb_rr])))
    for axle, m in (("Front", front_slip), ("Rear", rear_slip)):
        if m > 0.3:
            status, detail = "bad", f"Tire overloaded/sliding (combined slip {m:.3f}) - soften that axle, reduce camber, or check alignment"
        elif m < 0.05:
            status, detail = "info", f"Tire underworked (combined slip {m:.3f}) - room for more aggressive alignment"
        else:
            status, detail = "ok", f"Grip OK (combined slip {m:.3f})"
        findings.append({"area": f"Tire Grip {axle}", "status": status, "detail": detail, "value": round(m, 4)})

    # --- Tire pressure: Forza emits no pressure field, and in-game pressure does
    # not track temperature as real physics would, so give a fixed warm baseline
    # rather than inferring it from telemetry. ---
    findings.append({
        "area": "Tire Pressure",
        "status": "info",
        "detail": "Baseline ~30-34 PSI warm, slightly higher front (not measurable from telemetry). Lower it for grip/compliance on rough surfaces; raise it for sharper turn-in.",
        "value": None,
    })

    # --- Gearing ---
    ratio = _shift_rpm_ratio(frames)
    if ratio is None:
        findings.append({"area": "Gearing", "status": "none", "detail": "Not enough gear changes to analyze", "value": None})
    elif ratio < 0.85:
        findings.append({"area": "Gearing", "status": "warn", "detail": f"Shifting at {ratio:.0%} of max RPM - final drive too short, lengthen gears", "value": round(ratio, 3)})
    elif ratio > 0.98:
        findings.append({"area": "Gearing", "status": "bad", "detail": f"Hitting rev limiter ({ratio:.0%}) - lengthen top gear", "value": round(ratio, 3)})
    else:
        findings.append({"area": "Gearing", "status": "ok", "detail": f"Shift points OK ({ratio:.0%} of max RPM)", "value": round(ratio, 3)})

    # --- Balance / alignment (front vs rear lateral slip angle is a cleaner
    # understeer/oversteer signal than combined slip; both are normalized) ---
    sa_f = np.concatenate([_arr(frames, "tire_slip_angle_fl"), _arr(frames, "tire_slip_angle_fr")])
    sa_r = np.concatenate([_arr(frames, "tire_slip_angle_rl"), _arr(frames, "tire_slip_angle_rr")])
    front_sa, rear_sa = float(np.mean(np.abs(sa_f))), float(np.mean(np.abs(sa_r)))
    balance = front_sa - rear_sa
    if balance > 0.05:
        findings.append({"area": "Balance/Alignment", "status": "warn", "detail": f"Understeer (front slip angle {front_sa:.3f} > rear {rear_sa:.3f}) - soften front ARB/springs, add front camber, or reduce front toe", "value": round(balance, 4)})
    elif balance < -0.05:
        findings.append({"area": "Balance/Alignment", "status": "bad", "detail": f"Oversteer (rear slip angle {rear_sa:.3f} > front {front_sa:.3f}) - soften rear ARB/springs, add rear camber, or raise diff decel lock", "value": round(balance, 4)})
    else:
        findings.append({"area": "Balance/Alignment", "status": "ok", "detail": f"Balanced (front slip angle {front_sa:.3f} / rear {rear_sa:.3f})", "value": round(balance, 4)})

    return {"car": car, "frames": n, "findings": findings}


def analyze_session(session_dir: Path) -> None:
    """Print heuristic tune recommendations for a recorded session."""
    result = compute_recommendations(session_dir)
    car = result["car"]
    console.print(Panel(
        f"Car PI: {car['performance_index']} | Drivetrain: {car['drivetrain']} | Frames: {result['frames']}",
        title="Session Info",
    ))

    table = Table(title="Tune Recommendations", box=box.ROUNDED, show_header=True)
    table.add_column("Area", style="bold cyan", width=20)
    table.add_column("Recommendation")
    for f in result["findings"]:
        color = _STATUS_COLOR.get(f["status"], "white")
        table.add_row(f["area"], f"[{color}]{f['detail']}[/{color}]")
    console.print(table)
