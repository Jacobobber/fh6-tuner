import socket
import threading
from typing import Callable

from telemetry.parser import TelemetryFrame, parse_packet, PACKET_SIZE


class UDPReceiver:
    def __init__(self, host: str = "0.0.0.0", port: int = 5300):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self, callback: Callable[[TelemetryFrame], None]) -> None:
        """Start receiving in a background daemon thread."""
        self._running = True
        self._thread = threading.Thread(
            target=self._listen, args=(callback,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._sock:
            self._sock.close()

    def _listen(self, callback: Callable[[TelemetryFrame], None]) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)
        self._sock.bind((self.host, self.port))
        while self._running:
            try:
                data, _ = self._sock.recvfrom(PACKET_SIZE + 64)
                frame = parse_packet(data)
                if frame is not None:
                    callback(frame)
            except socket.timeout:
                continue
            except OSError:
                break
