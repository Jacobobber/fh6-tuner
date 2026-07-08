"""MCP server for the FH6 tuner.

Exposes recorded telemetry as tools so an MCP client (Claude Desktop, Claude
Code, etc.) can read a session and produce tune advice through conversation,
using your Claude subscription instead of a separate API key.

Run directly over stdio:  python mcp_server.py
"""
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from tuner.summary import summarize_session, TUNING_GUIDANCE, GOALS
from tuner.analyzer import compute_recommendations
from tuner.build import compute_build_signals, BUILD_GUIDANCE
from tuner.coach import compute_coaching_stats, COACHING_GUIDANCE
from laps.comparator import compute_comparison

SESSIONS_DIR = Path(__file__).parent / "sessions"
_REFERENCE_PATH = Path(__file__).parent / "TUNING_TELEMETRY_REFERENCE.md"


def _load_reference() -> str:
    """Append the full tuning<->telemetry reference so the AI reasons over it.

    Single source of truth: the bidirectional map, symptom->fix tables, feel
    dictionary, and target traces live in TUNING_TELEMETRY_REFERENCE.md, not
    duplicated into the guidance strings. Degrades silently if the file is gone.
    """
    try:
        return (
            "\n\n# ===== FULL TUNING <-> TELEMETRY REFERENCE (consult for every recommendation) =====\n\n"
            + _REFERENCE_PATH.read_text(encoding="utf-8")
        )
    except OSError:
        return ""


_FRAMING = (
    "This server analyzes recorded Forza Horizon telemetry to make a car as fast "
    "as possible across three layers, in priority order: BUILD (part upgrades — "
    "build_recommendations) sets the Performance Index ceiling, TUNE "
    "(summarize_session) optimizes within it, and the DRIVER (coach_session) "
    "extracts it. When asked to make a car faster, address all three in that "
    "order — build, then tune, then driving.\n\n"
)

mcp = FastMCP(
    "fh6-tuner",
    instructions=_FRAMING + BUILD_GUIDANCE + "\n\n" + TUNING_GUIDANCE + "\n\n" + COACHING_GUIDANCE + _load_reference(),
)


def _session_path(session_name: str) -> Path:
    path = SESSIONS_DIR / session_name
    if not path.is_dir():
        raise ValueError(
            f"No session '{session_name}'. Use list_sessions to see what is recorded."
        )
    return path


@mcp.tool()
def list_sessions() -> list[str]:
    """List recorded session names available under sessions/."""
    if not SESSIONS_DIR.is_dir():
        return []
    return sorted(
        d.name for d in SESSIONS_DIR.iterdir()
        if d.is_dir() and any(d.glob("lap_*.json"))
    )


@mcp.tool()
def list_laps(session_name: str) -> list[str]:
    """List the lap files recorded in a session (e.g. lap_000.json)."""
    return sorted(p.name for p in _session_path(session_name).glob("lap_*.json"))


@mcp.tool()
def summarize_session(session_name: str, goal: str = "balanced") -> dict:
    """Summarize a session's telemetry for tune analysis.

    goal is one of: balanced, race, drift, rally, topspeed, drag. Returns
    aggregated stats (suspension, tire slip, diff slip, gearing, G-forces).
    Reason over this to produce full-tune-sheet recommendations.
    """
    if goal not in GOALS:
        raise ValueError(f"Unknown goal '{goal}'. Choose one of: {', '.join(GOALS)}.")
    return summarize_session(_session_path(session_name), goal=goal)


@mcp.tool()
def heuristic_recommendations(session_name: str) -> dict:
    """Run the offline heuristic analyzer and return its findings as data."""
    return compute_recommendations(_session_path(session_name))


@mcp.tool()
def build_recommendations(session_name: str) -> dict:
    """Summarize a session for BUILD/upgrade advice — the PI-ceiling layer.

    Returns car context (PI, class, drivetrain, cylinders) plus build-diagnostic
    data: power and RPM/gear usage, driven-axle wheelspin and L/R asymmetry, the
    grip ceiling and front/rear balance, and a directional limiting-factor hint.
    Reason over this to recommend upgrades, then pair with summarize_session
    (tune) and coach_session (driver) — in the order build -> tune -> driver.
    """
    return compute_build_signals(_session_path(session_name))


@mcp.tool()
def coach_session(session_name: str) -> dict:
    """Summarize a session for DRIVER coaching (technique, not car setup).

    Returns aggregates over inputs (throttle/brake/steer), grip-loss, trail
    braking, robust g-forces (impacts separated out), and lap-to-lap
    consistency. Reason over this to give prioritized driving feedback.
    """
    return compute_coaching_stats(_session_path(session_name))


@mcp.tool()
def compare_laps(session_name: str, lap_a: str, lap_b: str) -> dict:
    """Compare two laps (filenames within the session) sector by sector."""
    session = _session_path(session_name)
    lap1, lap2 = session / lap_a, session / lap_b
    for lap in (lap1, lap2):
        if not lap.is_file():
            raise ValueError(f"No lap file '{lap.name}'. Use list_laps to see options.")
    return compute_comparison(lap1, lap2)


if __name__ == "__main__":
    mcp.run()
