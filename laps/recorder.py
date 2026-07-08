import json
from pathlib import Path
from telemetry.parser import TelemetryFrame


def save_lap(frames: list[TelemetryFrame], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump([frame.to_dict() for frame in frames], f)


class LapRecorder:
    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._current_lap: list[TelemetryFrame] = []
        self._lap_count = self._next_lap_index()
        self._prev_lap_number = -1
        self._prev_current_lap = 0.0
        self._session_info_saved = False

    def _next_lap_index(self) -> int:
        """Continue numbering after laps already in the session dir.

        The GUI can start recording into an existing session, so don't clobber
        previously saved laps (lap_000.json, lap_001.json, ...).
        """
        indices = []
        for path in self.session_dir.glob("lap_*.json"):
            if "_partial" in path.name:
                continue
            try:
                indices.append(int(path.stem.split("_")[1]))
            except (IndexError, ValueError):
                continue
        return max(indices) + 1 if indices else 0

    def feed(self, frame: TelemetryFrame) -> bool:
        """Feed a frame. Returns True if a lap was just completed and saved."""
        # Save session info on first valid frame
        if not self._session_info_saved and frame.car_ordinal != 0:
            self._save_session_info(frame)
            self._session_info_saved = True

        # Detect lap boundary: lap_number increased, or current_lap reset to near 0 from >5s
        lap_completed = False
        if self._prev_lap_number >= 0:
            lap_number_advanced = frame.lap_number > self._prev_lap_number
            time_reset = (self._prev_current_lap > 5.0 and frame.current_lap < 1.0)
            if (lap_number_advanced or time_reset) and len(self._current_lap) > 10:
                lap_path = self.session_dir / f"lap_{self._lap_count:03d}.json"
                save_lap(self._current_lap, lap_path)
                self._lap_count += 1
                self._current_lap = []
                lap_completed = True

        self._current_lap.append(frame)
        self._prev_lap_number = frame.lap_number
        self._prev_current_lap = frame.current_lap
        return lap_completed

    def _save_session_info(self, frame: TelemetryFrame) -> None:
        info = {
            "car_ordinal": frame.car_ordinal,
            "car_class": frame.car_class,
            "car_performance_index": frame.car_performance_index,
            "drivetrain_type": frame.drivetrain_type,
            "num_cylinders": frame.num_cylinders,
        }
        with open(self.session_dir / "session_info.json", "w") as f:
            json.dump(info, f, indent=2)

    def flush(self) -> None:
        """Save any in-progress lap on shutdown."""
        if len(self._current_lap) > 10:
            lap_path = self.session_dir / f"lap_{self._lap_count:03d}_partial.json"
            save_lap(self._current_lap, lap_path)
