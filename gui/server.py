import json
import re
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from telemetry.receiver import UDPReceiver
from telemetry.parser import TelemetryFrame
from telemetry.derive import derive_frame
from laps.recorder import LapRecorder

_HTML_PATH = Path(__file__).parent / "index.html"
_SESSIONS_DIR = Path("sessions")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_session_name(raw: str | None) -> str:
    """Sanitize a browser-supplied session name into a safe directory name.

    Collapses anything outside [A-Za-z0-9_-] to "_" so a name can't escape
    sessions/ (e.g. "../"). Falls back to a timestamped name when empty, so a
    click always records somewhere predictable.
    """
    cleaned = _SAFE_NAME.sub("_", (raw or "").strip()).strip("_")
    return cleaned or datetime.now().strftime("session_%Y%m%d_%H%M%S")


class _State:
    """Thread-safe holder for the latest frame and the active lap recorder.

    Recording can be toggled at runtime from the web UI, so the recorder lives
    behind the same lock as the frame: feed() runs on the UDP receiver thread
    while start/stop run on HTTP handler threads.
    """

    def __init__(self, recorder: LapRecorder | None = None, session_name: str | None = None) -> None:
        self._lock = threading.Lock()
        self._frame: dict | None = None
        self._recorder = recorder
        self._session_name = session_name if recorder is not None else None
        self._laps_saved = 0

    def update(self, frame: dict) -> None:
        with self._lock:
            self._frame = frame

    def feed(self, frame: TelemetryFrame) -> None:
        """Feed a raw frame to the active recorder, if any (receiver thread)."""
        with self._lock:
            if self._recorder is not None and self._recorder.feed(frame):
                self._laps_saved += 1

    def start_recording(self, session_name: str) -> None:
        with self._lock:
            if self._recorder is not None:
                self._recorder.flush()
            self._recorder = LapRecorder(_SESSIONS_DIR / session_name)
            self._session_name = session_name
            self._laps_saved = 0

    def stop_recording(self) -> None:
        with self._lock:
            if self._recorder is not None:
                self._recorder.flush()
            self._recorder = None
            self._session_name = None

    def snapshot(self) -> dict:
        with self._lock:
            snap = dict(self._frame) if self._frame is not None else {}
            snap["_connected"] = self._frame is not None
            snap["_recording"] = self._recorder is not None
            snap["_session_name"] = self._session_name
            snap["_laps_saved"] = self._laps_saved
            return snap


def run_gui(
    host: str = "0.0.0.0",
    port: int = 5300,
    web_port: int = 8000,
    session_name: str | None = None,
    open_browser: bool = True,
) -> None:
    """Serve the live web dashboard, fed by the UDP telemetry receiver.

    If session_name is given, laps are recorded to sessions/<name>/ as well.
    """
    initial_recorder = LapRecorder(_SESSIONS_DIR / session_name) if session_name else None
    state = _State(recorder=initial_recorder, session_name=session_name)

    # Forza zeroes distance_traveled in free roam, so integrate speed over time
    # for a "distance driven" readout that works everywhere.
    odo = {"meters": 0.0, "last_ts": None}

    def on_frame(frame: TelemetryFrame) -> None:
        state.feed(frame)
        ts = frame.timestamp_ms
        if odo["last_ts"] is not None:
            dt = (ts - odo["last_ts"]) / 1000.0
            if 0.0 < dt < 1.0:  # ignore pauses, wraps, and dropped frames
                odo["meters"] += frame.speed * dt
        odo["last_ts"] = ts
        d = derive_frame(frame)
        d["session_distance_m"] = round(odo["meters"], 1)
        state.update(d)

    receiver = UDPReceiver(host=host, port=port)
    receiver.start(on_frame)

    html = _HTML_PATH.read_text(encoding="utf-8").encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # silence per-request logging
            pass

        def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload: dict, status: int = 200) -> None:
            self._send(json.dumps(payload).encode("utf-8"), "application/json", status)

        def _read_json(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                pass
            return {}

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(html, "text/html; charset=utf-8")
            elif self.path.startswith("/data"):
                self._send_json(state.snapshot())
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            if self.path == "/record/start":
                body = self._read_json()
                name = _safe_session_name(body.get("session") if isinstance(body, dict) else None)
                state.start_recording(name)
                self._send_json({"recording": True, "session": name, "laps_saved": 0})
            elif self.path == "/record/stop":
                state.stop_recording()
                self._send_json({"recording": False})
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer((host, web_port), Handler)
    url = f"http://localhost:{web_port}/"
    rec_note = f" | recording to sessions/{session_name}" if session_name else ""
    print(f"FH6 GUI at {url}  (UDP {host}:{port}{rec_note}) - Ctrl+C to stop")
    print("Toggle recording from the GUI with the Record button.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()
        server.shutdown()
        final = state.snapshot()
        state.stop_recording()
        if final["_recording"]:
            print(f"Saved {final['_laps_saved']} complete lap(s) to sessions/{final['_session_name']}")
