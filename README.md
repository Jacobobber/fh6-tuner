# fh6-tuner

Telemetry auto-tuner for Forza Horizon 6. Listens to the game's Data Out UDP
stream, shows a live dashboard, records laps, compares them, and produces tune
recommendations.

> **New here?** Start with **[ARCHITECTURE.md](ARCHITECTURE.md)** — file map,
> how to run, and the gotchas that have bitten us. The analysis engine is
> `tuner/segment.py` (`segment_session` → state-segmented *evidence*: per-phase
> balance, traction circle, gearing, dampers, steer→yaw response lag, per-corner
> balance — all 88 telemetry fields). The deterministic layer produces evidence; the
> **AI reasons over it using [TUNING_TELEMETRY_REFERENCE.md](TUNING_TELEMETRY_REFERENCE.md)**
> (every tuning knob's telemetry signature, symptom→fix tables, a driver-feel
> dictionary, target traces), which the MCP server loads into its instructions.

## Configure FH6 Data Out

In the game: **Settings > HUD and Gameplay > Data Out**.

1. Enable **Data Out**.
2. Set **Data Out IP Address** to your PC's local IP. Find it by running
   `ipconfig` and reading the IPv4 Address (e.g. `192.168.1.42`).
3. Set **Data Out IP Port** to `5300`.
4. Set **Data Out Packet Format** to **Car Dash**.

The tool listens on port `5300` for the Car Dash packet layout.

## Install

```
pip install -r requirements.txt
```

## Commands

```
python main.py gui
```
Live web dashboard showing all telemetry (speed/RPM/gear, tire temps and slip,
suspension travel, G-force pad, pedal inputs, lap timer, a rolling history
chart, and a full raw-field table). Opens `http://localhost:8000` in your
browser. Add `--record mysession` to record laps at the same time, or
`--no-browser` when running headless / in a container.

```
python main.py listen
```
Terminal dashboard only. Streams telemetry to the console without recording.

```
python main.py record mysession
```
Live dashboard plus recording. Each completed lap is written to
`sessions/mysession/lap_001.json`, `lap_002.json`, and so on.

```
python main.py compare sessions/mysession/lap_001.json sessions/mysession/lap_002.json
```
Compares two recorded laps side by side: lap times, sector splits, and where one
lap gains or loses against the other.

```
python main.py analyze sessions/mysession
```
Prints offline heuristic tune recommendations for a session. No network, no
API key.

## AI tune analysis via MCP

For goal-aware, full-tune-sheet advice, the tuner runs as an MCP server. Your
MCP client (Claude Desktop, Claude Code) talks to it and reasons over the
telemetry using your existing Claude subscription. No API key, no per-call
billing.

A car's pace stacks in three layers, in priority order: **build** (part upgrades,
which set the Performance Index ceiling) → **tune** (sliders, PI-neutral) →
**driver**. The server exposes a tool for each, plus session helpers:
`list_sessions`, `list_laps`, `compare_laps`, `summarize_session` (goal-aware
**tuning** stats), `heuristic_recommendations`, `build_recommendations`
(**upgrade**/PI-ceiling signals — power vs grip-limited diagnosis, drivetrain,
tire-compound/width direction), and `coach_session` (**driver** technique). Ask
Claude to "make this car faster" and it works the three in order — build, then
tune, then driving. Laps that were never completed (free roam, or recording
stopped mid-lap) are still analyzed — the tools fall back to the partial lap when
no full lap was recorded.

Register it with Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "fh6-tuner": {
      "command": "python",
      "args": ["/path/to/fh6-tuner/main.py", "mcp"]
    }
  }
}
```

Then ask Claude things like "summarize my `mysession` session for a drift build
and give me a full tune," or "compare lap_000 and lap_001 in `mysession`." Goals
are `balanced`, `race`, `drift`, `rally`, `topspeed`, `drag`.

To run the server in the container instead, point `command` at `docker`:

```json
{
  "mcpServers": {
    "fh6-tuner": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-v", "fh6-sessions:/app/sessions",
               "fh6-tuner", "python", "main.py", "mcp"]
    }
  }
}
```

## Docker

```
docker compose up --build
```

Serves the GUI at `http://localhost:8000` and listens for telemetry on UDP
`5300`. Recorded laps persist to `./sessions` on the host. Point FH6's Data Out
IP at your machine's LAN IP (Docker Desktop forwards the published ports to
`localhost`).

Build/run manually:

```
docker build -t fh6-tuner .
docker run --rm -p 8000:8000 -p 5300:5300/udp -v ${PWD}/sessions:/app/sessions fh6-tuner
```

## Cloud (multi-user, invited)

A hosted version lets an invited group each stream their **own** telemetry and
view their own dashboard, gated by Google sign-in. Each user points their game's
Data Out at a **dedicated UDP port** the server assigns them at login; telemetry
is attributed by that port (never by source IP, which collides under CGNAT), so
users only ever see their own data. No client install.

> Security note: the game can't authenticate or encrypt its UDP, so the telemetry
> stream is unauthenticated plaintext and the per-user port is a weak bearer key.
> Fine for a small, trusted, invited group and non-sensitive game data — not for
> public or sensitive use. Sign-in still gates all dashboard viewing.

Install the web extras:

```
pip install -r requirements-web.txt
```

Create a Google OAuth client:

1. In the Google Cloud console, create an **OAuth 2.0 Client ID** (type: Web
   application).
2. Add an **Authorized redirect URI** of `<your-base-url>/auth/callback` (e.g.
   `https://tuner.example.com/auth/callback`, or
   `http://localhost:8000/auth/callback` for local testing).
3. Set the environment variables:

```
GOOGLE_CLIENT_ID=...             # from the OAuth client
GOOGLE_CLIENT_SECRET=...          # from the OAuth client
FH6_ALLOWLIST=you@gmail.com,friend@gmail.com   # comma-separated; who may sign in
FH6_SESSION_SECRET=...            # long random string; keep stable across restarts
FH6_BASE_URL=https://tuner.example.com           # public URL (use https in prod)
FH6_UDP_PUBLIC_HOST=tuner.example.com            # host users point Data Out at (defaults to BASE_URL host)
FH6_UDP_PORT_BASE=53000           # first telemetry port (default 53000)
FH6_UDP_PORT_COUNT=16             # pool size = max concurrent users (default 16)
```

Then run:

```
python main.py web
```

Open the UDP port range **`FH6_UDP_PORT_BASE` .. `+FH6_UDP_PORT_COUNT-1`** on
your host's firewall/security group. Each user signs in, lands on **`/connect`**,
and is shown the host + their assigned port to enter in **Settings → HUD and
Gameplay → Data Out** (Packet Format: **Car Dash**). Only allowlisted,
Google-verified emails are admitted (anyone else gets an access-denied page). In
production, run it behind a TLS-terminating reverse proxy (e.g. Caddy) so
`FH6_BASE_URL` is `https://` and session cookies are marked secure.

### Serving it behind Cloudflare (sub-path deploy)

If your site (`example.com`) sits behind Cloudflare, two things matter:

- **The web UI can live under a sub-path** like `/forza`. Run the app on a host
  with a public IP (a VPS or Fly.io), set `FH6_ROOT_PATH=/forza` and
  `FH6_BASE_URL=https://example.com/forza`, and route the path to it — either a
  **Cloudflare Tunnel** (`cloudflared`) public-hostname rule for `example.com`
  path `/forza/*` → `http://localhost:8000`, or a proxied `forza.example.com`
  subdomain (simpler — no `FH6_ROOT_PATH` needed). Set the Google OAuth
  **redirect URI** to `https://example.com/forza/auth/callback` (or the subdomain
  equivalent).
- **The telemetry UDP cannot go through Cloudflare.** Its proxy only carries
  HTTP/S (raw UDP is Spectrum/enterprise), so the game must reach the app server
  **directly**. Add a **DNS-only ("grey-cloud") record** — e.g.
  `telemetry.example.com` → the server's public IP — set
  `FH6_UDP_PUBLIC_HOST=telemetry.example.com`, and open the UDP port range on the
  host firewall. The `/connect` page then shows users that host + their port.

So: dashboard/auth at `example.com/forza` (via Cloudflare), telemetry to
`telemetry.example.com:<port>` (direct to the box). Using a subdomain for the web
UI avoids the sub-path plumbing entirely if you'd prefer.

## Understanding the recommendations

`analyze` reports suggested direction and magnitude for each adjustable area:

- **Suspension stiffness** — softer absorbs bumps and improves grip on rough
  surfaces; stiffer sharpens response and reduces body roll on smooth tracks.
  Direction comes from how much normalized suspension travel varies per axle.
- **Ride height** — flagged when normalized suspension travel pins near full
  compression (bottoming out). Raise ride height first; stiffen springs only if
  it is already at maximum.
- **Differential** — controls how power is split between driven wheels.
  Higher acceleration lock drives the car straighter out of corners; lower
  lock frees rotation but can spin an inside wheel. Driven from the left/right
  slip difference on the driven axle.
- **Tire grip / load** — read from combined slip per axle. Sustained high slip
  means the tire is overloaded and sliding (soften that axle, reduce camber, or
  fix alignment); very low slip means it is underworked.
- **Tire pressure** — Forza emits no pressure telemetry, and in-game pressure
  does not track tire temperature the way real physics would, so the tool gives
  a fixed warm-target baseline (~30-34 PSI, slightly higher front) rather than
  inferring it from the data.
- **Gearing** — final drive and individual ratios. Shorter gearing accelerates
  harder; longer gearing raises top speed. The offline `analyze` reads upshift
  RPM versus redline; the segment engine additionally checks top-gear RPM at your
  max speed to catch an over-tall final.
- **Balance / alignment** — front-vs-rear lateral slip angle. Higher front slip
  angle is understeer (soften the front, add front camber, add front toe-out for
  turn-in); higher rear is oversteer (soften the rear, add rear camber, add rear
  toe-in, or add diff deceleration lock).

Recommendations are directional guidance from the recorded data, not a finished
setup. Apply one change at a time and re-record to confirm it helped.

## License

[MIT](LICENSE).

## Disclaimer

This is an independent, fan-made tool. It is **not affiliated with, endorsed by,
or sponsored by** Microsoft, Turn 10 Studios, or Playground Games. "Forza" and
"Forza Horizon" are trademarks of Microsoft Corporation. The tool only reads the
game's opt-in **Data Out** telemetry stream and reads on-screen values via OCR;
it does not modify the game or its files.
