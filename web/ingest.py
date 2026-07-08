"""UDP ingest for the cloud app: bind the whole port pool and route by port.

One selector loop on a daemon thread services every pool port. A datagram's
arrival port identifies the user (see TelemetryHub); the source IP is never used.
"""
import selectors
import socket
import threading

from telemetry.parser import parse_packet, PACKET_SIZE
from web.hub import TelemetryHub


class UDPIngest:
    def __init__(self, hub: TelemetryHub) -> None:
        self._hub = hub
        self._selector = selectors.DefaultSelector()
        self._socks: list[socket.socket] = []
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        for port in self._hub.ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self._hub.bind_host, port))
            sock.setblocking(False)
            self._selector.register(sock, selectors.EVENT_READ, port)
            self._socks.append(sock)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while self._running:
            for key, _mask in self._selector.select(timeout=1.0):
                port, sock = key.data, key.fileobj
                while True:  # drain everything buffered on this port
                    try:
                        data, _addr = sock.recvfrom(PACKET_SIZE + 64)
                    except (BlockingIOError, OSError):
                        break
                    frame = parse_packet(data)
                    if frame is not None:
                        self._hub.feed(port, frame)

    def stop(self) -> None:
        self._running = False
        for sock in self._socks:
            try:
                self._selector.unregister(sock)
            except (KeyError, ValueError):
                pass
            sock.close()
        self._socks.clear()
