import queue
from pathlib import Path

import click
from rich.console import Console

from telemetry.receiver import UDPReceiver
from telemetry.parser import TelemetryFrame
from dashboard.live import run_dashboard
from laps.recorder import LapRecorder
from laps.comparator import compare_laps
from tuner.analyzer import analyze_session
from gui.server import run_gui

console = Console()


def _frame_iterator(receiver: UDPReceiver, frame_queue: "queue.Queue[TelemetryFrame | None]"):
    """Yield frames from the queue until None sentinel is received."""
    while True:
        frame = frame_queue.get()
        if frame is None:
            break
        yield frame


@click.group()
def cli():
    """FH6 telemetry auto-tuner. Configure Data Out in FH6 settings first (see README)."""
    pass


@cli.command()
@click.option("--port", default=5300, help="UDP port (default: 5300)")
@click.option("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
def listen(port: int, host: str):
    """Show live telemetry dashboard."""
    frame_queue: queue.Queue[TelemetryFrame | None] = queue.Queue(maxsize=60)
    receiver = UDPReceiver(host=host, port=port)

    console.print(f"[cyan]Listening on {host}:{port} ...[/cyan] (Ctrl+C to stop)")
    receiver.start(lambda f: frame_queue.put(f, block=False) if not frame_queue.full() else None)

    try:
        run_dashboard(_frame_iterator(receiver, frame_queue))
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()
        frame_queue.put(None)


@cli.command()
@click.argument("session_name")
@click.option("--port", default=5300, help="UDP port (default: 5300)")
@click.option("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
def record(session_name: str, port: int, host: str):
    """Record laps to sessions/SESSION_NAME/ while showing live dashboard."""
    session_dir = Path("sessions") / session_name
    session_dir.mkdir(parents=True, exist_ok=True)

    frame_queue: queue.Queue[TelemetryFrame | None] = queue.Queue(maxsize=60)
    receiver = UDPReceiver(host=host, port=port)
    lap_recorder = LapRecorder(session_dir)
    laps_saved = [0]

    def on_frame(frame: TelemetryFrame) -> None:
        if lap_recorder.feed(frame):
            laps_saved[0] += 1
        try:
            frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    console.print(f"[cyan]Recording to {session_dir}[/cyan] (Ctrl+C to stop)")
    receiver.start(on_frame)

    try:
        run_dashboard(_frame_iterator(receiver, frame_queue))
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()
        lap_recorder.flush()
        frame_queue.put(None)
        console.print(f"[green]Saved {laps_saved[0]} complete lap(s) to {session_dir}[/green]")


@cli.command()
@click.argument("lap1", type=click.Path(exists=True, path_type=Path))
@click.argument("lap2", type=click.Path(exists=True, path_type=Path))
def compare(lap1: Path, lap2: Path):
    """Compare two lap JSON files sector by sector."""
    compare_laps(lap1, lap2)


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def analyze(session_dir: Path):
    """Print offline heuristic tune recommendations for a session.

    For goal-aware, full-tune-sheet advice, run the MCP server (`python
    main.py mcp`) and ask Claude to analyze the session.
    """
    analyze_session(session_dir)


@cli.command()
@click.option("--port", default=5300, help="UDP port (default: 5300)")
@click.option("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
@click.option("--web-port", default=8000, help="Web GUI port (default: 8000)")
@click.option("--record", "session_name", default=None, help="Also record laps to sessions/NAME/")
@click.option("--no-browser", is_flag=True, help="Do not auto-open a browser (use in containers)")
def gui(port: int, host: str, web_port: int, session_name: str | None, no_browser: bool):
    """Serve the live web telemetry dashboard."""
    run_gui(
        host=host,
        port=port,
        web_port=web_port,
        session_name=session_name,
        open_browser=not no_browser,
    )


@cli.command()
def mcp():
    """Run the MCP server (stdio) so Claude can analyze recorded sessions."""
    from mcp_server import mcp as mcp_app

    mcp_app.run()


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
@click.option("--web-port", default=8000, help="Web port (default: 8000)")
def web(host: str, web_port: int):
    """Run the multi-tenant cloud web app (Google-auth gated).

    Requires the web extras (pip install -r requirements-web.txt) and the
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FH6_ALLOWLIST, FH6_SESSION_SECRET,
    and FH6_BASE_URL environment variables (see the README's Cloud section).
    """
    import os

    import uvicorn

    from web.app import create_app

    # FH6_ROOT_PATH (e.g. /forza) when served under a sub-path behind a proxy.
    uvicorn.run(create_app(), host=host, port=web_port, root_path=os.environ.get("FH6_ROOT_PATH", ""))


if __name__ == "__main__":
    cli()
