import json
from pathlib import Path
import numpy as np
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def _load_lap(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _lap_distance(frames: list[dict]) -> np.ndarray:
    """Distance into the lap (0-based).

    Forza's distance_traveled is cumulative across the whole session, not reset
    per lap. Subtracting the lap's starting value gives distance-into-lap so two
    laps align by track position.
    """
    dist = np.array([f["distance_traveled"] for f in frames])
    return dist - dist.min()


def _interp(frames: list[dict], key: str, distances: np.ndarray) -> np.ndarray:
    src_dist = _lap_distance(frames)
    src_vals = np.array([f[key] for f in frames])
    # Remove duplicate distances to avoid interp errors
    _, unique_idx = np.unique(src_dist, return_index=True)
    src_dist = src_dist[unique_idx]
    src_vals = src_vals[unique_idx]
    return np.interp(distances, src_dist, src_vals)


def compute_comparison(lap1_path: Path, lap2_path: Path, num_sectors: int = 10) -> dict:
    """Sector-by-sector lap delta as structured data (shared by CLI and MCP)."""
    lap1 = _load_lap(lap1_path)
    lap2 = _load_lap(lap2_path)
    if not lap1 or not lap2:
        return {"error": "One or both lap files are empty."}

    # Align both laps on a common distance axis (shortest lap caps the range)
    max_dist = min(_lap_distance(lap1).max(), _lap_distance(lap2).max())
    distances = np.linspace(0, max_dist, 500)
    edges = np.linspace(0, max_dist, num_sectors + 1)

    lap1_time, lap2_time = _interp(lap1, "current_lap", distances), _interp(lap2, "current_lap", distances)
    lap1_speed, lap2_speed = _interp(lap1, "speed", distances), _interp(lap2, "speed", distances)
    lap1_brake, lap2_brake = _interp(lap1, "brake", distances), _interp(lap2, "brake", distances)

    sectors = []
    for i in range(num_sectors):
        mask = (distances >= edges[i]) & (distances < edges[i + 1])
        if not mask.any():
            continue
        t1 = float(lap1_time[mask][-1] - lap1_time[mask][0])
        t2 = float(lap2_time[mask][-1] - lap2_time[mask][0])
        sectors.append({
            "sector": i + 1,
            "lap1_time_s": round(t1, 3),
            "lap2_time_s": round(t2, 3),
            "delta_s": round(t2 - t1, 3),
            "speed_delta_mph": round(float((lap2_speed[mask] - lap1_speed[mask]).mean()) * 2.237, 1),
            "brake_delta": round(float((lap2_brake[mask] - lap1_brake[mask]).mean()), 1),
        })

    total_t1, total_t2 = lap1[-1]["current_lap"], lap2[-1]["current_lap"]
    return {
        "lap1": lap1_path.name,
        "lap2": lap2_path.name,
        "lap1_total_s": round(total_t1, 3),
        "lap2_total_s": round(total_t2, 3),
        "total_delta_s": round(total_t2 - total_t1, 3),
        "sectors": sectors,
        "note": "Positive delta means lap 2 is slower in that sector.",
    }


def compare_laps(lap1_path: Path, lap2_path: Path) -> None:
    """Print a sector-by-sector lap comparison."""
    result = compute_comparison(lap1_path, lap2_path)
    if "error" in result:
        console.print(f"[red]{result['error']}[/red]")
        return

    table = Table(title="Lap Comparison", box=box.ROUNDED)
    table.add_column("Sector", style="cyan")
    table.add_column("Lap 1 Time", justify="right")
    table.add_column("Lap 2 Time", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Speed Delta (mph)", justify="right")
    table.add_column("Brake Delta", justify="right")

    for s in result["sectors"]:
        delta = s["delta_s"]
        delta_str = f"[red]+{delta:.3f}s[/red]" if delta > 0 else f"[green]{delta:.3f}s[/green]"
        table.add_row(
            f"S{s['sector']}",
            f"{s['lap1_time_s']:.3f}s",
            f"{s['lap2_time_s']:.3f}s",
            delta_str,
            f"{s['speed_delta_mph']:+.1f}",
            f"{s['brake_delta']:+.1f}",
        )

    total_delta = result["total_delta_s"]
    sign = "+" if total_delta > 0 else ""
    color = "red" if total_delta > 0 else "green"
    console.print(table)
    console.print(
        f"\nOverall: Lap 1 [cyan]{result['lap1_total_s']:.3f}s[/cyan] | "
        f"Lap 2 [cyan]{result['lap2_total_s']:.3f}s[/cyan] | "
        f"Delta [{color}]{sign}{total_delta:.3f}s[/{color}]"
    )
    console.print("[dim]Positive delta = Lap 2 is slower in that sector[/dim]")
