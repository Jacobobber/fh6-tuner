"""Multi-tenant cloud web app for the FH6 tuner.

Google OIDC login + email allowlist + secure sessions, plus zero-client per-user
telemetry: each user is assigned a dedicated UDP port at /connect and points the
game's Data Out at it; the ingest listener attributes datagrams by arrival port,
never by source IP. State, recordings, and analysis are all scoped to the
authenticated user_id, so no one can read another's data. Telemetry on the wire
is unauthenticated UDP (the game can't add auth) — acceptable for a small,
trusted, invited group and non-sensitive game data.

The app is sub-path aware: mounted under e.g. /forza (uvicorn --root-path or a
proxy), redirects and in-page links honor the prefix via root_path + <base>.
"""
import html
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from tuner.analyzer import compute_recommendations
from tuner.summary import summarize_session, GOALS
from tuner.build import compute_build_signals
from tuner.coach import compute_coaching_stats
from web.config import Settings
from web.hub import TelemetryHub, _safe
from web.ingest import UDPIngest

_SESSIONS = Path("sessions")
_DASHBOARD = Path(__file__).resolve().parent.parent / "gui" / "index.html"
_GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"

_LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FH6 Tuner — Sign in</title><style>
body{background:#0d1117;color:#e6edf3;font-family:ui-monospace,"Cascadia Code",monospace;
display:grid;place-items:center;height:100vh;margin:0}
.card{background:#161b22;border:1px solid #2a3240;border-radius:12px;padding:32px 40px;text-align:center;max-width:340px}
h1{color:#58a6ff;font-size:18px;letter-spacing:.08em;margin:0 0 8px}
p{color:#8b949e;font-size:13px}
a.btn{display:inline-block;margin-top:16px;padding:10px 18px;background:#58a6ff;color:#0d1117;
border-radius:8px;text-decoration:none;font-weight:700}
</style></head><body><div class="card"><h1>FH6 TUNER</h1>
<p>Live telemetry — invited users only.</p>
<a class="btn" href="auth/google">Sign in with Google</a></div></body></html>"""

_DENIED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>FH6 Tuner — Access denied</title><style>
body{{background:#0d1117;color:#e6edf3;font-family:ui-monospace,monospace;display:grid;place-items:center;height:100vh;margin:0}}
.card{{background:#161b22;border:1px solid #f85149;border-radius:12px;padding:32px 40px;text-align:center;max-width:380px}}
h1{{color:#f85149;font-size:18px}} p{{color:#8b949e;font-size:13px}}
a{{color:#58a6ff}}</style></head><body><div class="card"><h1>Access denied</h1>
<p><b>{email}</b> is not on the allowlist. Ask the owner to add you, or
<a href="logout">try another account</a>.</p></div></body></html>"""

# Tokenized template (avoids brace-escaping against the CSS) — see connect().
_CONNECT_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FH6 Tuner — Connect your game</title><style>
body{background:#0d1117;color:#e6edf3;font-family:ui-monospace,"Cascadia Code",monospace;
display:grid;place-items:center;min-height:100vh;margin:0}
.card{background:#161b22;border:1px solid #2a3240;border-radius:12px;padding:28px 36px;max-width:460px}
h1{color:#58a6ff;font-size:18px;letter-spacing:.08em;margin:0 0 4px}
.dim{color:#8b949e;font-size:12px} ol{font-size:14px;line-height:1.7;padding-left:20px}
b.v{color:#3fb950} code{background:#0d1117;border:1px solid #2a3240;border-radius:6px;padding:1px 6px}
a.btn{display:inline-block;margin-top:16px;padding:10px 18px;background:#58a6ff;color:#0d1117;
border-radius:8px;text-decoration:none;font-weight:700}
</style></head><body><div class="card"><h1>CONNECT YOUR GAME</h1>
<p class="dim">Signed in as __EMAIL__ · <a href="logout" style="color:#58a6ff">log out</a></p>
<p>In FH6: <b>Settings → HUD and Gameplay → Data Out</b></p>
<ol><li>Enable <b>Data Out</b>.</li>
<li>Data Out IP Address → <code><b class="v">__HOST__</b></code></li>
<li>Data Out IP Port → <code><b class="v">__PORT__</b></code></li>
<li>Data Out Packet Format → <b>Car Dash</b></li></ol>
<p class="dim">This port is yours alone — it's how the server knows the telemetry is you.
Keep it to yourself.</p>
<a class="btn" href=".">Open my dashboard</a></div></body></html>"""


def optional_user(request: Request) -> dict | None:
    """The logged-in user from the session, or None. Module-level for testability."""
    return request.session.get("user")


def require_user(request: Request) -> dict:
    """Dependency that 401s unless a user is in the session."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _uid(user: dict) -> str:
    """Stable per-user key: the Google subject id, falling back to email."""
    return user.get("sub") or user["email"]


_ROOT_PATH_RE = re.compile(r"^(?:/[A-Za-z0-9_-]+)*$")


def _rp(request: Request) -> str:
    """The validated ASGI root_path (mount prefix, e.g. '/forza'); '' at the root.

    Validated so a proxy-supplied root_path can't smuggle a protocol-relative
    open-redirect ('//evil.com') or markup into the <base> tag.
    """
    rp = request.scope.get("root_path", "") or ""
    return rp if _ROOT_PATH_RE.match(rp) else ""


def _inject_base(document: str, root_path: str) -> str:
    """Add <base href> so the page's relative links/fetches honor the mount prefix."""
    safe = html.escape(root_path, quote=True)
    return document.replace("<head>", f'<head><base href="{safe}/">', 1)


def _user_session(user: dict, name: str) -> Path:
    """Resolve a session dir under the caller's own user_id, or 404.

    user_id is server-derived (never client-supplied) and both segments are
    sanitized, so a user can only ever reach their own sessions.
    """
    d = _SESSIONS / _safe(_uid(user)) / _safe(name)
    if not d.is_dir() or not any(d.glob("lap_*.json")):
        raise HTTPException(status_code=404, detail="No such session")
    return d


def create_app(settings: Settings | None = None, *, start_ingest: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    hub = TelemetryHub(
        bind_host=settings.udp_bind,
        public_host=settings.udp_public_host,
        port_base=settings.udp_port_base,
        port_count=settings.udp_port_count,
        sessions_root=str(_SESSIONS),
    )
    ingest = UDPIngest(hub)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_ingest:
            ingest.start()
        try:
            yield
        finally:
            if start_ingest:
                ingest.stop()

    app = FastAPI(title="fh6-tuner cloud", lifespan=lifespan)
    app.state.settings = settings
    app.state.hub = hub
    app.state.ingest = ingest

    if not settings.session_secret and settings.https:
        raise RuntimeError(
            "FH6_SESSION_SECRET must be set for an HTTPS/production deployment "
            "(needed for forgery-safe sessions that survive restarts)."
        )
    secret = settings.session_secret or secrets.token_urlsafe(32)
    if not settings.session_secret:
        print("WARNING: FH6_SESSION_SECRET not set — using an ephemeral key; "
              "sessions will not persist across restarts (dev only).")
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        same_site="lax",
        https_only=settings.https,
    )

    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=_GOOGLE_METADATA,
        client_kwargs={"scope": "openid email profile"},
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request):
        if request.session.get("user"):
            return RedirectResponse(_rp(request) + "/")
        return HTMLResponse(_inject_base(_LOGIN_PAGE, _rp(request)))

    @app.get("/auth/google")
    async def auth_google(request: Request):
        return await oauth.google.authorize_redirect(request, settings.base_url + "/auth/callback")

    @app.get("/auth/callback")
    async def auth_callback(request: Request):
        try:
            token = await oauth.google.authorize_access_token(request)
        except OAuthError:
            raise HTTPException(status_code=400, detail="OAuth exchange failed")
        info = token.get("userinfo") or {}
        email = (info.get("email") or "").lower()
        if not info.get("email_verified") or not settings.is_allowed(email):
            denied = _DENIED_PAGE.format(email=html.escape(email or "unknown"))
            return HTMLResponse(_inject_base(denied, _rp(request)), status_code=403)
        request.session["user"] = {"email": email, "sub": info.get("sub"), "name": info.get("name")}
        return RedirectResponse(_rp(request) + "/connect")

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse(_rp(request) + "/login")

    @app.get("/me")
    def me(user: dict = Depends(require_user)) -> dict:
        return {"email": user["email"], "name": user.get("name"), "port": hub.port_for_user(_uid(user))}

    @app.get("/connect", response_class=HTMLResponse)
    def connect(request: Request, user: dict | None = Depends(optional_user)):
        if not user:
            return RedirectResponse(_rp(request) + "/login")
        port = hub.assign_port(_uid(user))
        html = (_CONNECT_PAGE
                .replace("__HOST__", settings.udp_public_host)
                .replace("__PORT__", str(port))
                .replace("__EMAIL__", user["email"]))
        return HTMLResponse(_inject_base(html, _rp(request)))

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, user: dict | None = Depends(optional_user)):
        if not user:
            return RedirectResponse(_rp(request) + "/login")
        return HTMLResponse(_inject_base(_DASHBOARD.read_text(encoding="utf-8"), _rp(request)))

    @app.get("/data")
    def data(user: dict = Depends(require_user)) -> JSONResponse:
        snap = hub.snapshot(_uid(user))
        snap["_authenticated_as"] = user["email"]
        return JSONResponse(snap)

    @app.post("/record/start")
    async def record_start(request: Request, user: dict = Depends(require_user)):
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = body.get("session") if isinstance(body, dict) else None
        uid = _uid(user)
        hub.assign_port(uid)  # ensure per-user state exists even before /connect
        saved = hub.start_recording(uid, name or "session")
        return {"recording": True, "session": saved}

    @app.post("/record/stop")
    def record_stop(user: dict = Depends(require_user)):
        hub.stop_recording(_uid(user))
        return {"recording": False}

    # --- Per-user analysis (scoped to the caller's own sessions/<user_id>/) ---
    @app.get("/api/sessions")
    def api_sessions(user: dict = Depends(require_user)) -> dict:
        base = _SESSIONS / _safe(_uid(user))
        if not base.is_dir():
            return {"sessions": []}
        return {"sessions": sorted(
            d.name for d in base.iterdir() if d.is_dir() and any(d.glob("lap_*.json"))
        )}

    @app.get("/api/sessions/{name}/recommendations")
    def api_recommendations(name: str, user: dict = Depends(require_user)) -> dict:
        return compute_recommendations(_user_session(user, name))

    @app.get("/api/sessions/{name}/summary")
    def api_summary(name: str, goal: str = "balanced", user: dict = Depends(require_user)) -> dict:
        if goal not in GOALS:
            raise HTTPException(status_code=400, detail=f"Unknown goal; choose one of: {', '.join(GOALS)}.")
        return summarize_session(_user_session(user, name), goal=goal)

    @app.get("/api/sessions/{name}/coach")
    def api_coach(name: str, user: dict = Depends(require_user)) -> dict:
        return compute_coaching_stats(_user_session(user, name))

    @app.get("/api/sessions/{name}/build")
    def api_build(name: str, user: dict = Depends(require_user)) -> dict:
        return compute_build_signals(_user_session(user, name))

    return app
