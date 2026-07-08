# FH6 Tuning — Quick Reference (Cheat-Sheet)

One-page companion to **TUNING_TELEMETRY_REFERENCE.md**. Numbers here are the
verified starting bands; the full reference carries the telemetry signatures and
confidence flags behind each. Tune order is always **build → tune → driver**.

---

## Telemetry conventions (get these right or every read is wrong)

- **Slip channels** (`TireSlipRatio` longitudinal, `TireSlipAngle` lateral):
  **`0` = grip, `|v| > 1` = grip loss.** Not degrees, not %. `1.0` is the
  loss-onset edge — *not* an "optimal" target.
- **`NormalizedSuspensionTravel`:** **`~1.0` = bottoming, `~0.0` = full droop / wheel lift.**
- **Tire temp is in °F** on the wire — convert before using any °C logic.
- **Yaw rate = `AngularVelocityY`** (`Yaw` is heading, not rate).
- **Inputs `Accel`/`Brake` (0–255), `Steer` (−127..127) are raw** — normalize before use.
- **No damper channel** → differentiate suspension travel (~60 Hz) for damper velocity.
  **No per-zone tire temp** (one scalar/wheel). **No hi/lo-speed damper split.**

## Verified starting bands (priors — validate per car)

| Knob | Band |
|---|---|
| RWD diff **accel** lock | **40–60%** (use 40–50% low end for high-power builds) |
| RWD diff **decel** lock | **15–30%** |
| AWD **center** | **60–70% rear** (road); off-road runs less rear bias |
| Front **camber** | **−1.5 to −1.8°** (never past ~−2.0°); rear less negative |
| **Caster** | **5.5–6.5°** |
| **Tire pressure** | **~30–34 PSI warm, slightly higher front** — FIXED target. Forza pressure does **not** track temperature; never derive it from temp. |
| **Brake bias** | as far **rearward** as possible without the rear locking |

## Core invariants

- **Springs/ARBs set the MAGNITUDE** of weight transfer; **dampers set the RATE/timing.**
- **The stiffer axle loses grip first** → stiffer front = understeer, stiffer rear = oversteer.
- Fix the end **with** the problem (soften it) before over-stiffening the other end.
- **Downforce ∝ v²** — only make aero calls for high-speed symptoms; low-speed = mechanical.
- **ARB balance:** softer front → more oversteer; softer rear → more understeer.

## Symptom → fix (by corner phase)

**Understeer / push**
- *Entry:* soften front ARB; −front bump/rebound; +front toe-out; brake bias rearward; −decel lock; first check trail-braking (driver).
- *Apex:* +front camber; soften front ARB (or stiffen rear if no snap); raise front grip.
- *Exit (power-understeer):* −accel lock to free rotation.

**Oversteer / loose / snap**
- *Entry (lift/trail-brake):* +decel lock; +rear toe-in; soften rear.
- *Exit (power):* −accel lock; soften rear / +rear grip; +rear downforce.
- *SNAP (discontinuous):* attack the discontinuity — soften rear ARB + rear fast-rebound; +rear toe-in; raise ride height (stop rear skating); soften diff; soften front roll stiffness.

**Wheelspin (exit):** inner driven wheel spikes alone → **+accel lock**; both spike together + yaw overshoot → **−accel lock** / soften rear / +rear grip.

**Lockup (braking):** fronts lock (slip>1, no yaw) → bias **rearward** / lower pressure / trail-brake more. Rears lock + diverging yaw → bias **forward**.

**Bottoming** (travel pins ~1.0): **raise ride height first**, then stiffen springs.

## Feel → cause (the trap)

- **HEAVY / LAZY turn-in** (big steer→yaw lag, but slip angles stay < 1.0) is a
  **response-rate** problem, NOT understeer → stiffen front ARB + a little front
  compression; still lazy → lower front ride height + stiffen front springs.
- **DARTY / nervous** (over-responsive) → soften front ARB/springs, reduce front
  toe-out, add caster, raise rear grip.

## The loop

Change **one thing**, re-record, compare **phase-conditioned numbers**
(balance / slip / lag — *not* lap time on point-to-point routes), keep or revert.

---
*Distilled from TUNING_TELEMETRY_REFERENCE.md and the project's adversarially-verified research. Bands are starting priors, not finished setups.*
