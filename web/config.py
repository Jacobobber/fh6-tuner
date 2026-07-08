import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    """Cloud web-app configuration, sourced from environment variables."""

    google_client_id: str
    google_client_secret: str
    session_secret: str
    allowlist: frozenset[str]
    base_url: str
    udp_bind: str
    udp_port_base: int
    udp_port_count: int
    udp_public_host: str

    @classmethod
    def from_env(cls) -> "Settings":
        allow = {
            email.strip().lower()
            for email in os.environ.get("FH6_ALLOWLIST", "").split(",")
            if email.strip()
        }
        base_url = os.environ.get("FH6_BASE_URL", "http://localhost:8000").rstrip("/")
        public_host = os.environ.get("FH6_UDP_PUBLIC_HOST", "") or (urlparse(base_url).hostname or "localhost")
        return cls(
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            session_secret=os.environ.get("FH6_SESSION_SECRET", ""),
            allowlist=frozenset(allow),
            base_url=base_url,
            udp_bind=os.environ.get("FH6_UDP_BIND", "0.0.0.0"),
            udp_port_base=int(os.environ.get("FH6_UDP_PORT_BASE", "53000")),
            udp_port_count=int(os.environ.get("FH6_UDP_PORT_COUNT", "16")),
            udp_public_host=public_host,
        )

    @property
    def https(self) -> bool:
        return self.base_url.startswith("https")

    def is_allowed(self, email: str | None) -> bool:
        """True only if email is non-empty and on the allowlist (fail-closed)."""
        return bool(email) and email.strip().lower() in self.allowlist
