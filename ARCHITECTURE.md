# ARCHITECTURE — fh6-tuner

Onboarding for anyone taking this project over cold. Read this, then
`TUNING_TELEMETRY_REFERENCE.md`, and you're current.

## What this is
A Forza Horizon 6 telemetry auto-tuner. It listens to FH6's **Data Out UDP**
stream, records laps, and turns telemetry into recommendations across three
pillars in priority order: **BUILD** (parts / PI ceiling) → **TUNE** (sliders) →
**DRIVER** (technique). The design bias is **AI/MCP reasoning over hardcoded
heuristics**: the analysis layer emits rich *evidence*; an AI reasons over it
using the reference document.

## Run it
Run from the project root:
- `python main.py gui` — live dashboard (`--record <name>` to also record,
  `--no-browser` headless)
- `python main.py record <name>` — record laps → `sessions/<name>/lap_*.json`
- `python main.py analyze <session>` — offline heuristic findings
- `python main.py mcp` (or `python mcp_server.py`) — MCP server for AI tuning

**Analysis functions take a `pathlib.Path`, not a str:**
`summarize_session(Path("sessions/x"), goal="race")`. Goals: balanced, race,
drift, rally, topspeed, drag.

**Smoke test** (proves the analysis path is wired) — record or supply a session,
then from the project root:
```python
from pathlib import Path
from tuner.summary import summarize_session
s = summarize_session(Path("sessions/<name>"), goal="race")["state_segmented"]
print(s["response"], s["worst_corners"]["corners_detected"])
```
Expect `state_segmented` with `damper_histogram` / `response` / `worst_corners`
populated and a steer→yaw lag in the low-hundreds of ms.

## File map
- `telemetry/parser.py` — Data Out packet → `TelemetryFrame` (88 fields: sled + 12-byte
  Horizon gap [CarGroup/Smashable] + Car Dash). `tire_temp_to_celsius` (FH6 temp is °F).
- `telemetry/derive.py` — shared per-frame derivations (speed/rpm/g/temps) for gui + web.
- `tuner/segment.py` — **the analysis engine.** `segment_session(frames)` → state-segmented
  EVIDENCE: per-phase balance (entry/apex/exit), traction circle, gearing, driver timers,
  chassis attitude, body slip, wheel speeds, raw suspension, surface, powertrain, tire-temp
  balance, impacts, **damper_histogram, response (steer→yaw lag = sharp-vs-heavy), worst_corners**.
  Consumes all 88 fields. Emits evidence, NOT verdicts.
- `tuner/summary.py` — `summarize_session` (tune payload + `TUNING_GUIDANCE`); embeds
  `segment_session` under `state_segmented`.
- `tuner/coach.py` — `compute_coaching_stats` (driver payload + `COACHING_GUIDANCE`).
- `tuner/build.py` — `compute_build_signals` (build/PI payload + `BUILD_GUIDANCE`).
- `tuner/analyzer.py` — `_load_session` (prefers complete laps, falls back to `_partial`);
  `_shift_rpm_ratio` (gear=11 fix); offline `compute_recommendations`.
- `mcp_server.py` — MCP tools (list/summarize/coach/build/compare). **Loads
  `TUNING_TELEMETRY_REFERENCE.md` into the AI instructions** (single source of truth).
- `main.py` — CLI entry point (gui / listen / record / analyze / compare / mcp / web).
- `telemetry/receiver.py` — UDP receiver (binds the Data Out port, yields frames).
- `gui/server.py` + `gui/index.html` — live web dashboard; `dashboard/live.py` — terminal
  dashboard (`main.py listen`).
- `laps/recorder.py` — writes `lap_*.json` + `session_info.json` (this is the recorder behind
  gotcha #3); `laps/comparator.py` — `compute_comparison` (sector compare; MCP `compare_laps`).
- `web/` — multi-tenant cloud app (Google OIDC + per-user UDP port). Functionality complete;
  see the README's Cloud section to deploy.
- `forza_capture.py` — **READ-ONLY** screen driver for the in-game Upgrade/Tune menus
  (mss + pyautogui + Windows OCR). Modes: `shot`, `walk [ncats]` (mods), `tune` (tune tabs),
  `keys <k,k>`, `nudge <key> <n>`. Safety: only opens/reads (Enter→Esc), never confirms
  purchases. `ocr_captures.py` OCRs `captures/*.png`.
- `TUNING_TELEMETRY_REFERENCE.md` — definitive bidirectional tuning↔telemetry reference
  (every knob's signature, symptom→fix tables, feel dictionary incl. "feels heavy", target
  traces, confidence ledger). Wired into MCP guidance.
- `tunes/*.json` — structured build+tune snapshots per car (`fh6-tune/v1`).
- `sessions/<name>/` — recorded laps + `session_info.json` (gitignored; supply your own).

## CRITICAL gotchas (each has bitten us)
1. **Slider value-setting via screen automation is UNRELIABLE** — Tune sliders have
   key-repeat acceleration; presses jump non-deterministically (saw +3 → +12, 25 → 100 → 0).
   **Do NOT auto-set tune values — give the user exact numbers to set by hand** (proven path).
2. **Never auto-buy mods** without reading the projected PI first. Capture tool is read-only.
3. **Recorder can MIX cars into one session** if not restarted on a car change (it appends
   laps + overwrites `session_info`). Always verify car identity per lap by `car_ordinal`.
   Known: 348=2005 Ford GT, 2793=Ferrari 330 P4, 2297=2012 911 GT3 RS, 398=MR2 GT, 3781=992 GT3 RS.
4. **Unit traps:** tire temp = °F (convert); slip channels are NORMALIZED (0=grip, |v|>1=loss),
   not deg/%; yaw rate = `angular_velocity_y`; any gear outside 1..10 (e.g. 11) = neutral/
   reverse/mid-shift (the `_shift_rpm_ratio` fix masks the whole range, not a literal `==11`);
   `power`/`torque` SPIKE at standstill/collision (use percentile not max — handled);
   collisions spike g (filtered via |g|<4 + percentiles).
5. **`distance_traveled` resets per checkpoint** — use speed-integrated `track.distance_driven_m`.
6. **TA / point-to-point has no lap splits** (`lap_number` stays 0); analysis falls back to
   partial laps. A position-based lap splitter is not built.
7. **"Heavy" ≠ understeer.** Heavy/sluggish is a RESPONSE-RATE complaint (see `response`
   steer→yaw lag + roll-rate + damper_histogram), fixed via roll stiffness / damping /
   ride-height — distinct from a grip/balance (understeer) problem. The reference's Feel
   Dictionary spells this out.

## Open / next steps
- `web/` cloud deploy: functionality is done; hosting is left to the deployer (see README).
- Position-based lap splitter (true per-lap times in TA) — not built.
- Re-verify the reference's **DO NOT RELY ON** items before hard-coding any (see its
  Confidence Ledger) — e.g. exact damper-histogram zone %, rake-as-aero, drivetrain aero
  fractions.
- A robust closed-loop slider value-setter is unsolved (see gotcha 1).
