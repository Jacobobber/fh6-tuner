"""Per-user telemetry state for the cloud app.

Each user is assigned a dedicated UDP port at login; the ingest listener routes
a datagram to a user purely by the port it arrived on (never by source IP, which
collides under CGNAT). State is keyed by user_id, so one user can never address
another's telemetry.
"""
import re
import threading
import time
from pathlib import Path

from laps.recorder import LapRecorder
from telemetry.parser import TelemetryFrame
from telemetry.derive import derive_frame

_SAFE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_FRAMES_PER_SEC = 240  # game is ~60Hz; anything far above is abuse → drop


def _safe(part: str) -> str:
    cleaned = _SAFE.sub("_", (part or "").strip()).strip("_")
    return cleaned or "unnamed"


class UserState:
    """One user's latest frame, odometer, and (optional) lap recorder."""

    def __init__(self, sessions_root: Path, user_id: str) -> None:
        self._lock = threading.Lock()
        self._sessions_root = sessions_root
        self._user_id = user_id
        self._frame: dict | None = None
        self._odo: dict = {"meters": 0.0, "last_ts": None}
        self._recorder: LapRecorder | None = None
        self._session_name: str | None = None
        self._laps_saved = 0
        self._win_start = 0.0
        self._win_count = 0
        self.last_seen = 0.0

    def feed(self, frame: TelemetryFrame) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._win_start >= 1.0:
                self._win_start, self._win_count = now, 0
            self._win_count += 1
            if self._win_count > _MAX_FRAMES_PER_SEC:
                return  # per-user rate cap: drop excess
            if self._recorder is not None and self._recorder.feed(frame):
                self._laps_saved += 1
            ts = frame.timestamp_ms
            if self._odo["last_ts"] is not None:
                dt = (ts - self._odo["last_ts"]) / 1000.0
                if 0.0 < dt < 1.0:  # ignore pauses, wraps, dropped frames
                    self._odo["meters"] += frame.speed * dt
            self._odo["last_ts"] = ts
            d = derive_frame(frame)
            d["session_distance_m"] = round(self._odo["meters"], 1)
            self._frame = d
            self.last_seen = now

    def start_recording(self, name: str) -> str:
        with self._lock:
            if self._recorder is not None:
                self._recorder.flush()
            safe = _safe(name)
            self._recorder = LapRecorder(self._sessions_root / _safe(self._user_id) / safe)
            self._session_name = safe
            self._laps_saved = 0
            return safe

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


class TelemetryHub:
    """Owns the UDP port pool, user↔port assignment, and per-user state."""

    def __init__(self, *, bind_host: str, public_host: str, port_base: int,
                 port_count: int, sessions_root: str | Path) -> None:
        self._lock = threading.Lock()
        self.bind_host = bind_host
        self.public_host = public_host
        self.ports = list(range(port_base, port_base + port_count))
        self._sessions_root = Path(sessions_root)
        self._user_by_port: dict[int, str] = {}
        self._port_by_user: dict[str, int] = {}
        self._state: dict[str, UserState] = {}

    def assign_port(self, user_id: str) -> int:
        """Return the user's port, assigning a free one from the pool if needed."""
        with self._lock:
            if user_id in self._port_by_user:
                return self._port_by_user[user_id]
            free = [p for p in self.ports if p not in self._user_by_port]
            if not free:
                raise RuntimeError("Telemetry port pool exhausted; raise FH6_UDP_PORT_COUNT.")
            port = free[0]
            self._user_by_port[port] = user_id
            self._port_by_user[user_id] = port
            self._state[user_id] = UserState(self._sessions_root, user_id)
            return port

    def port_for_user(self, user_id: str) -> int | None:
        with self._lock:
            return self._port_by_user.get(user_id)

    def _state_for(self, user_id: str | None) -> "UserState | None":
        # Lock only the dict lookup; UserState has its own lock for the work.
        with self._lock:
            return self._state.get(user_id) if user_id is not None else None

    def feed(self, port: int, frame: TelemetryFrame) -> None:
        """Route a parsed frame to the user who owns this port (ingest thread)."""
        with self._lock:
            user_id = self._user_by_port.get(port)
            state = self._state.get(user_id) if user_id is not None else None
        if state is not None:  # datagram on an unassigned port → ignored
            state.feed(frame)

    def snapshot(self, user_id: str) -> dict:
        state = self._state_for(user_id)
        if state is None:
            return {"_connected": False, "_recording": False, "_session_name": None, "_laps_saved": 0}
        return state.snapshot()

    def start_recording(self, user_id: str, name: str) -> str | None:
        state = self._state_for(user_id)
        return state.start_recording(name) if state is not None else None

    def stop_recording(self, user_id: str) -> None:
        state = self._state_for(user_id)
        if state is not None:
            state.stop_recording()
