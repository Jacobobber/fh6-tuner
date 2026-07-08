# The Tuning ↔ Telemetry Reference (FH6 AI Tuner)

> Definitive bidirectional reference: every tuning element, its telemetry signature (MoTeC-style real-world + FH6 normalized channels), the target/ideal, and which way to move it for a symptom.
>
> **Confidence + verification flags** are carried through from the research findings. Anything marked **DO NOT RELY ON** has `verified=false` and must not be hard-coded as a rule without independent confirmation. "not-checked" = drawn from established vehicle-dynamics practice but not independently re-verified this pass; treat as high-prior but confirmable. "verified=true" items are the few that were positively confirmed.
>
> **FH6 normalized-slip convention used throughout:** `0 = grip`, `|value| > 1 = significant loss`. Applies to both `TireSlipRatio` (longitudinal) and `TireSlipAngle` (lateral). `NormalizedSuspensionTravel`: `~1.0 = bottoming`, `~0.0 = full droop / wheel lift`.

---

## TABLE OF CONTENTS

1. [The Bidirectional Map](#1-the-bidirectional-map) — every tuning element
2. [Telemetry → Fix Tables](#2-telemetry--fix-tables) — symptom by corner phase
3. [The Feel Dictionary](#3-the-feel-dictionary) — driver term → data → cause → fix
4. [What You Want](#4-what-you-want) — ideal traces, distributions, targets
5. [The Process](#5-the-process) — iterative setup loop, A/B, driver vs car
6. [Forza Translation & Caveats](#6-forza-translation--caveats)

---

# 1. THE BIDIRECTIONAL MAP

Read each element as four parts: **(a) mechanical effect**, **(b) telemetry signature** (real-world MoTeC + FH6 normalized), **(c) target/ideal**, **(d) symptom → direction**.

A few invariants underpin the whole map:

- **Springs/ARBs set the MAGNITUDE of weight transfer; dampers set the RATE/timing.** Steady-state balance is a spring/ARB/aero/weight job; transient (first ~0.5 s of an event) balance is a damper/ARB job.
- **Total roll stiffness sets roll ANGLE, not steady-state lateral load transfer.** The front/rear *split* sets steady-state balance. (high confidence)
- **The relatively STIFFER axle loses grip first.** Stiffer front → understeer; stiffer rear → oversteer. Always fix the end *with* the problem when possible (soften it) rather than over-stiffening the other end into a new problem.
- **Downforce scales with v²** — aero is near-zero at low speed, dominant at high speed. Any aero call must be conditioned on the speed where the symptom appears.

---

## 1.1 Springs (front / rear rate)

**(a) Mechanical.** Front-vs-rear stiffness sets mid-corner balance; the stiffer axle loses grip first. Springs also set the *magnitude* of low-frequency weight transfer (pitch under brake/throttle, roll in cornering) and the bump compliance / platform height behavior. Think in **ride frequency**, not raw rate: `f = (1/2π)·√(wheelRate/cornerMass)`. The heavier end needs a higher raw rate to match frequency.

**(b) Telemetry signature.**
- *MoTeC:* suspension-travel (damper-pot) peak-to-peak amplitude and decay; stiffer = smaller amplitude, faster decay. Pitch trace under braking/accel. Understeer gradient (steer vs latG).
- *FH6 normalized:* per-wheel `NormalizedSuspensionTravel` time-history — softer springs show larger 0→high swings under brake (front travel up), throttle (rear travel up), and corner load-up. Roll = outer-corner travel rising while inner drops. Pitch = front-pair vs rear-pair travel divergence. Mid-corner balance read via `TireSlipAngle`: front pair crosses 1.0 before rear = front-stiff understeer; rear first = rear-stiff oversteer.

**(c) Target.** Travel stays in the productive mid-band (~0.2–0.8 normalized), never pinned at 1.0 (bottoming) or 0.0 (droop). Smooth single-overshoot settle. Front and rear reach the limit together (slip angles cross 1.0 nearly simultaneously), slight rear-led for stability. Frequency guide: street ~1.0–1.5 Hz, track ~1.5–2.0 Hz, race ~2.0–3.0+ Hz, **rear ~10–20% above front** for flat ride / pitch control. (high confidence; "not-checked")

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Persistent understeer (front saturates first) | **Soften front** springs (don't just stiffen rear) |
| Persistent oversteer (rear saturates first) | **Soften rear** springs |
| Pitches/porpoises over bumps, won't settle | Raise **rear** rate so rear freq sits 10–20% above front |
| Lazy/late turn-in, composed but slow front | Raise **front** frequency (stiffer front) |
| Wallowing, slow to settle, huge travel swings | Stiffen both ends |
| Skates/harsh, loses grip over bumps | Soften both ends |
| Slow/floaty/unresponsive but balance OK | Stiffen both ends (raise whole frequency band) |
| Forza weight-distribution correction | Shift ~4 kgf/mm front↔rear per 1% deviation from 50/50, then bias by symptom |

> Surface rule: smoother track → stiffer; rougher/rally → softer (Forza halves rally spring stiffness vs road). There is a floor on softness — too soft = vague, slow, bottoming-prone even with correct balance.

---

## 1.2 Ride Height (front / rear, and rake)

**(a) Mechanical.** Lower CG → less lateral & longitudinal weight transfer → more mechanical grip, flatter/more responsive car. Lower is the road-racing default; raise only when forced (curbs, terrain, bottoming). Front/rear **split (rake)** is a balance + aero-platform tool: more rake (rear up) shifts balance toward oversteer, loads the front, and on aero cars sets wing angle-of-attack and floor sealing.

**(b) Telemetry signature.**
- *MoTeC:* lower static damper-pot readings, less roll angle, less load transfer per latG. Front vs rear ride-height channels give static rake; aero balance inferred from front/rear compression rising with speed.
- *FH6 normalized:* at rest, travel sits closer to compressed end; sustained latG slightly higher (more grip), roll (outer−inner travel delta) smaller. **Watch the cost:** travel histogram shifting toward 1.0 (bottoming) on compressions. Raising rear above front correlates with reduced mid-corner front slip (more front grip) and a looser rear.

**(c) Target.** Lowest height that does **not** bottom (travel pinning at 1.0) on the roughest part of the lap/curbs. Aero builds: rake set to keep floor in its downforce window without bottoming at top speed. Mechanical builds: small rake to fine-trim toward neutral.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Rolls too much / sluggish direction change | Lower ride height (and/or stiffen) |
| Bottoming (travel hits 1.0, grip spike-loss) | **Raise** height first, then consider stiffening springs |
| Mild understeer, want more rotation/front load | Raise rear a touch (more rake) |
| Loose/nervous rear, aero too peaky | Lower rear / reduce rake |
| Off-road / clearance needed | Raise height + halve spring stiffness for compliance |

> Rake-as-aero-knob (more rake = more front aero + more drag) and the "lower front / more rake moves CofP rearward" rule are **DO NOT RELY ON** (verified=false, medium confidence). Verify against bottoming at top speed before chasing balance with rake.

---

## 1.3 Anti-Roll Bars (front / rear)

**(a) Mechanical.** Adds **roll** stiffness without adding heave/ride (vertical bump) stiffness — unlike springs, which add both. **Total** ARB sets roll angle; the **front/rear split** sets steady-state under/oversteer (stiffer end loses grip first). ARBs also change the **speed** of weight transfer (transient/turn-in balance). Over-stiffening past a point **reduces** grip at that end and can lift the inside wheel.

**(b) Telemetry signature.**
- *Steady-state invariance (high confidence):* on a fixed-radius skidpad, stiffening both ARBs equally drops roll angle but leaves total inside→outside load transfer unchanged. *FH6:* left/right `NormalizedSuspensionTravel` delta shrinks on both axles; total limit latG and per-wheel slip onset governed by the *split*, not the total.
- *Balance (split):* *FH6* front `TireSlipAngle`/slip crosses loss before rear = understeer (stiff front); rear first = oversteer (stiff rear). Yaw rate vs steering: stiff front → yaw lags steer; stiff rear → yaw leads steer.
- *Transient:* stiffer end shortens steer→yaw lag; left/right travel delta builds more steeply right after turn-in; possible small yaw overshoot then settle.
- *Over-stiff:* inside-wheel travel **pinned at full droop** mid-corner (wheel lift); that axle's slip jumps past 1.0 as a **cliff** rather than rolling in gradually.

**(c) Target.** Roll angle in a usable window (keeps camber/geometry in range, gives feel, doesn't pitch/heave). Neutral-to-slight-understeer: front and rear slip cross 1.0 nearly together, rears marginally later. Both tires on an axle stay loaded (inside travel not pinned at droop). Slip onset gradual, not a cliff.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Too much body roll / lazy platform, balance OK | Stiffen **both** ends |
| Darty/skating over bumps, lifts inside wheel, snaps | Soften **both** ends |
| Mid-corner understeer (front slips first) | **Soften front ARB** or stiffen rear ARB |
| Mid-corner oversteer (rear slips first) | **Stiffen front ARB** or soften rear ARB |
| Vague/slow turn-in | Stiffen front ARB (quicker front load) |
| Snap/loose ONLY on entry (mid-corner fine) | Soften **rear** ARB (slow rear roll-rate) |
| Need roll control but soft ride for bumps/kerbs | Stiffen ARB, leave springs |
| Lifting inside wheel / grip cliff at one end | **Soften** that end's ARB until inside wheel stays planted |
| Platform/aero height moving in heave | That's a **spring** job — ARB won't fix it |

> Method: use springs to set ride frequency/heave/aero platform, then ARBs to fine-trim roll angle and balance. Tune **relative** front-to-rear, one end at a time, raise stiffness incrementally and stop one step before inside-load/grip drops.

---

## 1.4 Dampers (bump/compression + rebound/extension; low-speed vs high-speed)

**(a) Mechanical.** Bump resists compression; rebound resists extension. Dampers control the **rate** of weight transfer, not its steady-state magnitude — they shape the transient (first fraction of a second) and therefore "feel": sharpness, responsiveness, heaviness, float. **Low-speed** damping (near-zero velocity bins) = driver-induced body control (roll/pitch/dive/squat); **high-speed** damping (outer tail) = track-induced shock control (kerbs, bumps, landings). **FH6 exposes only one bump and one rebound scalar per axle** — no LS/HS split, no knee. LS vs HS is therefore an *analysis* distinction in Forza, not a tunable knob.

**(b) Telemetry signature.**
- *Damper-velocity histogram* (the canonical tool): differentiate `NormalizedSuspensionTravel` per wheel at ~60 Hz, compression positive / rebound negative, bin into a histogram.
  - Healthy = symmetric **bell centered at 0**, peak in low-speed range, ~even comp/reb area.
  - Skewed to compression = soft bump / under-sprung. Skewed to rebound = rebound too stiff (packing down).
  - Tall narrow central spike = too stiff (barely moving, harsh, **over-damped → heavy**). Wide/flat with central dip = too soft (**under-damped → nervous/floaty**).
- *Transient:* over-damped → g/yaw **lag** input, slow rise, no overshoot, travel barely moves. Under-damped → g/yaw **overshoot** then decaying oscillation; travel **rings** after a bump.
- *Wheel hop:* fast (~12–18 Hz) oscillation on the travel trace + rapid `TireSlipRatio` oscillation crossing |1| on that wheel.

**(c) Target.** Symmetric bell, peak near zero, front shape ≈ rear, comp area ≈ reb area, low-speed region taller than high-speed. **datamc starting reference: ~25% of samples in each of the four zones (LS-comp, LS-reb, HS-comp, HS-reb) at a 100 mm/s crossover.** Crossover convention ~50 mm/s (race practice) to ~100 mm/s (datamc); "not cast in stone." Critically-near-damped transient: input → prompt rise, ≤tiny overshoot, settles in ~one cycle. Goal in load terms: **minimum tire-load variation** through the event.

> The specific **"~12% central-bin peak"** rule and the **front/rear damper histogram-equalization** detail are **DO NOT RELY ON** (verified=false, medium confidence — could not re-confirm the 12% figure from a primary source). Use bell symmetry + the ~25%-per-zone split as the robust targets.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Feels HEAVY/sluggish on turn-in | Soften dampers (esp. **rebound** first) |
| Nervous/floaty/twitchy, oscillates after bumps | Stiffen bump + rebound until it settles in ~1 cycle |
| Reduce understeer / add front rotation | Soften **front** damping |
| Reduce oversteer | Soften **rear** damping |
| Post-bump ringing | +Rebound |
| Lagging/heavy turn-in | −Rebound |
| Harsh kerb skip / slip spikes over bumps | −Bump (and check ride height/springs) |
| Entry understeer (transient) | Soften front (front rebound esp.) OR stiffen rear |
| Entry/lift oversteer (transient) | Stiffen front rebound / soften rear |
| Wheel hop under accel/over bumps | First −bump (let wheel absorb), then ensure rebound high enough to stop ring; if persists, soften springs / raise height |

> Baselines (high confidence): bump ≈ 40–67% of rebound (≈two-thirds), ~40% typical road. Lower = softer/grippier, higher = firmer/sharper. Common Forza recipe: **soft bump + stiff rebound** (wheels compress fast over obstacles, chassis resists rising under brake/accel). Set rear dampers near front, shift with which axle has stiffer springs (~0.2 damper units per 1% front weight shift). Directional: softer front rebound = entry oversteer; softer rear rebound = entry understeer.

---

## 1.5 Differential — Acceleration Lock

**(a) Mechanical.** Forces the two driven wheels toward equal speed **under throttle**. Controls corner-**exit** traction and power-on balance.

**(b) Telemetry signature.**
- *MoTeC:* on-throttle, left/right driven-wheel speeds converge as lock rises; open/low-lock shows inner driven wheel spiking above outer on exit.
- *FH6:* on-throttle driven-wheel `TireSlipRatio`. High lock → both move together (small split). Low lock → **inner driven wheel spikes >1 alone** (inside-wheel spin). Excessive lock → **both driven wheels climb past 1 together** at exit (power-on/axle oversteer), often with yaw overshoot.

**(c) Target.** On exit both driven wheels just at the edge of grip (slip approaching but not sustained >1), small split closing smoothly as throttle rises, no isolated inner spike. FH6 RWD road race accel lock typically **40–60%** — use the **low end (40–50%) for high-power builds** (lower lock lets the inside wheel spin up independently, less exit snap); drift 80–100%.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Power-on / exit oversteer | **Decrease** accel lock (2–3% steps) |
| Inside-wheel spin on exit / one wheel lit | **Increase** accel lock |
| Power-understeer (pushes wide on throttle) | Decrease accel lock to free rotation |

> Tune accel lock **before** decel.

---

## 1.6 Differential — Deceleration (Coast) Lock

**(a) Mechanical.** Couples driven wheels **off-throttle / under braking**. Controls turn-**entry** and lift-off stability.

**(b) Telemetry signature.**
- *MoTeC:* off-throttle, driven-wheel speeds stay coupled with high lock; diverge with low lock (inner rear decelerating faster).
- *FH6:* with brake>0 or throttle=0, high decel → driven slip ratios move together, yaw tracks steering smoothly. Low decel → rear slip/yaw builds faster than front, yaw overshoots = **lift-off oversteer** on entry. Too-high decel → front slip exceeds rear on entry (push, nose runs wide).

**(c) Target.** Yaw rises to match steering without overshoot, no rear step-out on lift, no nose-wide push. FH6 RWD road race decel lock typically **15–30%** (lower than accel).

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Turn-entry / lift-off oversteer | **Increase** decel lock (2–3% steps) |
| Lift-off / entry understeer (won't tuck in) | **Decrease** decel lock |

> Tune decel **after** accel lock is settled.

---

## 1.7 Differential — Preload

**(a) Mechanical.** Sets breakaway/initial-lock torque; dominates at low torque and at turn-in before accel/decel ramps engage.

**(b) Telemetry signature.** *FH6:* at near-zero longitudinal input mid-corner, high preload → minimal driven-wheel speed/slip split despite steering; low preload → expected geometric speed difference with no isolated spin. Nervous high-preload car shows small yaw jitter / twitchy slip-angle at low-speed transitions.

**(c) Target.** Minimum preload that gives acceptable low-speed traction without a twitchy, darty feel; smooth transition from near-open into ramp lock.

**(d) Symptom → direction.** *(verified=true, medium confidence)*
| Symptom | Move |
|---|---|
| Nervous/darty at turn-in or low-speed transitions; induced over/understeer before throttle/brake load builds | **Decrease** preload |
| Poor low-speed traction / inner wheel lights up from near-stop; vague off-power coupling | **Increase** preload |

> Treat preload as the last/coarse trim after accel and decel ramps.

---

## 1.8 AWD Center Differential (front/rear torque split)

**(a) Mechanical.** Primary AWD rotation-vs-traction knob, distinct from per-axle locks.

**(b) Telemetry signature.** *FH6:* on throttle, rear-biased → rear pair slip ratio rises ahead of front (freer rotation, yaw tracks/overshoots steering); front-biased → front pair slip rises first, front slip **angle** grows beyond rear (understeer push, yaw lags). Excessive rear bias → rear slip sustained >1 (power-on oversteer).

**(c) Target.** Rear-biased split giving RWD-like rotation while keeping traction; front slip angle ≈ or just under rear. FH6 road race AWD center typically **60–70% rear** (verified-research band, matches the analyzer); dirt/rally and cross-country run less rear bias (~50–60%). **FH6 AWD feels sluggish/understeery toward the low end (~55% rear) on road builds — bias up within the band before touching per-axle locks.**

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| AWD power-on understeer / sluggish, won't rotate | **Increase** rear bias |
| AWD power-on or exit oversteer | **Decrease** rear bias (more front) and/or lower rear accel lock |

> Set center balance before fine-trimming per-axle accel/decel locks.

**Diff diagnostic routing (the master channel — medium confidence, verified=false).** Build three conditioned aggregates per corner from the driven-wheel L/R split: (1) **on-throttle** delta → accel lock; (2) **off-throttle/braking** delta → decel lock; (3) **near-zero-longitudinal-load** delta → preload. Distinguish *one wheel spiking* (inside spin → raise accel lock) from *both spiking together* (axle breakaway → lower accel lock / lower rear bias). Cross-reference yaw-vs-steering overshoot to confirm direction and separate driver from tune.

---

## 1.9 Aerodynamics — Front / Rear Downforce, Balance

**(a) Mechanical.** Downforce ∝ v² → near-zero grip at low speed, dominant at high speed. **Aero balance = front-DF / total-DF** (center-of-pressure split); moves balance like ARBs/springs but **only in the high-speed domain**. Downforce always costs drag, and **rear wings cost far more drag per unit DF than front splitters.**

**(b) Telemetry signature.**
- *MoTeC:* lateral-g-vs-speed curve **rises** with speed when aero works; flat/falling = aero not contributing. G-G colored by speed.
- *FH6:* slip near 0 at high speed while holding high latG = aero loading tires. **Slip |>1 appearing ONLY above a speed threshold = aero-domain loss** (fix with DF). Slip |>1 in slow corners (aero dead) = mechanical (don't touch aero). Balance: compare front vs rear `TireSlipAngle` **specifically in high-speed corners** — front>rear at speed = high-speed understeer (too much rear DF); rear>front = high-speed oversteer.

**(c) Target.** Lateral-g ceiling rising monotonically with speed; tires <1 through fast sweepers. Balance ~**0.40–0.45 front fraction** for balanced/AWD road; ~**0.50–0.55** for RWD needing rear stability. Driver-confidence ideal: **slight rear bias at low/mid speed, migrating toward neutral at high speed.** Aero efficiency: >0.85 excellent, 0.70–0.85 average, <0.70 poor.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Instability/slip>1 ONLY at high speed | Aero-balance problem → DF sliders (NOT springs/ARB/diff) |
| Slip>1 in slow corners | Mechanical → don't touch aero |
| High-speed understeer | +Front DF or −Rear DF (CofP forward) |
| High-speed oversteer | +Rear DF or −Front DF (CofP rearward) |
| Entry oversteer in SLOW corners | −Front DF / +Rear DF (more rear bias) |
| Lazy turn-in in FAST corners | +Front DF / −Rear DF |
| Top speed too low AND car stable | Reduce DF (rear first — cheaper grip to give up) |
| Need high-speed-corner grip, straight to recover on | Add DF (accept top-speed hit) |

> Drivetrain start points: **AWD = max front DF, MIN rear DF** (drivetrain already supplies rear traction; rear DF only adds drag). RWD = front ~60–80%, rear ~60–90% of range. FWD = high front, low-moderate rear. Set aero balance **by speed band**, not lap-mean: low-speed band → mechanical, high-speed band → aero. A balance **flip** across bands means one knob won't fix it. The rake/ride-height aero-migration items are **DO NOT RELY ON** (verified=false, medium confidence).

---

## 1.10 Camber (front / rear)

**(a) Mechanical.** Negative camber compensates body-roll-induced positive camber on the loaded outside tire, keeping the patch flat at peak lateral load. Caster adds dynamic negative camber, letting you reduce static.

**(b) Telemetry signature.**
- *Real-world:* 3-point pyrometer inner/mid/outer, read **at corner exit**. Too little neg camber → **outer edge hottest**; too much → **inner edge hottest**; correct → three zones in a tight band, mid near average. Excess static neg camber also reduces longitudinal grip (earlier |slip|>1 onset under brake/accel).
- *FH6:* the on-screen Heat view exposes 3 zones/tire. **But UDP likely exposes one scalar temp/wheel** (see caveats), so cross-tread diagnosis may be screen-only.

**(c) Target.** Inner-to-outer spread ~**10–15 °F** (real-world ~5–10 °C, never much beyond 10 °C in Forza), inner slightly hotter, mid at midpoint — **AND** maximized peak lateral G / minimized |slip|>1 time. Grip-optimal camber may run a slightly hotter inner edge. FH6 front start ~**−1.5 to −1.8°** (verified-research band, matches the analyzer), avoid exceeding ~**−2.0°** front; rear less negative than front. Real-world ~−2.5° (purpose-built) to −4.0° (street-derived) front.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Outer edge hotter at exit / lacking turn-in grip | Add negative camber |
| Inner edge hotter at exit / braking instability | Reduce negative camber toward zero |
| Temps look even but car is slow / won't hold line | Ignore flat-temp result; sweep camber **by grip** |
| Mid-corner understeer | Add front negative camber |

> Method: sweep camber, log temp spread **+ peak latG** per setting, pick where **grip peaks** (not merely flattest spread). Per-axle independently. The chassis-specific static baselines are medium confidence (verified=false). UDP per-zone-temp availability is a confirmed open question (verified=true) — if scalar-only, tune camber by grip-sweep, not spread.

---

## 1.11 Toe (front / rear)

**(a) Mechanical.** Front toe-**out** sharpens turn-in; toe-**in** adds straight-line stability (at the cost of scrub + the opposite trait). Rear toe-**in** stabilizes the rear axle, reduces power-on/transition oversteer; rear toe-out makes the rear loose.

**(b) Telemetry signature.**
- *FH6:* front toe-out → yaw builds earlier per steering input (sharper yaw trace, quicker front slip-angle onset); excess front toe → both fronts carry steady slip angle on straights + front temps creep up. Rear toe-in → yaw on throttle-up stays closer to commanded (less overshoot, delayed rear slip-angle onset under power); excess rear toe-in → steady rear heating on straights + drag (lower top speed).

**(c) Target.** Adjustments in tenths of a degree. Classic race compromise: small front toe-OUT for response + small rear toe-IN for stability. Rear toe-in baseline ~**0.1–0.2°**. Minimize total toe — every extra ~2–3 mm can raise tire wear 50–70% real-world.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Lazy / understeery turn-in | Add front toe-**out** |
| Nervous, darts/weaves on straights | Add front toe-**in** (toward zero/slight positive) |
| Fronts overheating with no obvious cause | Reduce total front toe magnitude |
| Snap / throttle-on oversteer, loose rear in transitions | Add rear toe-**in** 0.1–0.2° |
| Car dead/draggy, rear won't rotate, top speed down | Reduce rear toe-in toward zero |

---

## 1.12 Caster (front)

**(a) Mechanical.** Positive caster generates self-aligning torque (stability + steering feel) and adds dynamic negative camber to the loaded outside wheel during cornering.

**(b) Telemetry signature.** *FH6:* more caster → steadier yaw on long straights (less weave/correction), heavier but more progressive turn-in. Too much → oversteer/camber snap as the outside front over-cambers at high steering angles (abrupt balance flip or outside-front slip-angle spike at large lock).

**(c) Target.** FH6 practical range ~**5.5–6.5°** (start ~5.5, or default if higher); above ~6.0° can get snappy. Real-world track pushes higher (+7°). Match left/right.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Weaves on long straights, needs constant correction | Add caster a few tenths |
| Steering too heavy / snappy oversteer on turn-in | Reduce caster |
| Numb / vague (no limit feel) | Add caster (biggest feel lever) |

> Strategy: raise caster for dynamic camber, then back off **static** camber toward zero to recover braking/straight-line grip while keeping mid-corner patch.

---

## 1.13 Brake Bias & Pressure

**(a) Mechanical.** Front-biased brakes lock fronts first → brake-induced **entry understeer**; rear-biased lock rears first → **entry oversteer/spin**. Brake pressure scaling sets peak force.

**(b) Telemetry signature.**
- *MoTeC:* under braking, a locked wheel's speed drops sharply (>~20 mph below its axle partner = locked). Front lock = both fronts dip, steer rises but yaw doesn't follow (goes straight). Rear lock = rears collapse, yaw spikes/overshoots.
- *FH6:* on the locking axle, `TireSlipRatio` spikes >1 during the brake zone (throttle=0, brake high). Front-pair >1 + low yaw response = brake understeer; rear-pair >1 + diverging yaw = brake oversteer. Locked tire flat-spots → localized temp spike.
- *Brake trace shape ("shark fin"):* steep rise to a single clean peak, then smooth tapered release overlapping rising steer. Bad: slow ramp (decel left on table), flat plateau held too long, jagged/stepped release (micro-locks), or a vertical drop at apex (unloads front → mid-corner understeer).

**(c) Target.** Bias as far **rearward** as possible without the rear locking/stepping out. Ideal: all four reach lockup threshold near-simultaneously. Front slip ratio rides just under 1.0 at peak (threshold braking), easing toward 0 as brake releases and steering builds. Below ~15–20% pressure once heavily turned in.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Entry understeer / fronts lock (front slip>1, no yaw) | Shift bias **rearward** (or lower total pressure / trail-brake more) |
| Entry oversteer / rears lock / spins on brakes | Shift bias **forward** |
| Front locks even with smooth input | Reduce peak brake pressure |
| Jagged release w/ micro-locks | Driver: smoother modulation (load-cell pedal) |
| Brake held too long to apex | Driver: begin trailing off sooner |
| Sudden apex drop causing understeer | Driver: trail-brake longer/more gradually |

> The shark-fin trace is primarily a **driver** signature — but lower brake-pressure scaling is the setup lever if it locks even with clean input.

---

## 1.14 Tire Pressure (per corner)

**(a) Mechanical.** Sets contact-patch size/shape and is a thermal-balance tool. Over-pressure crowns the tread (center-heavy); under-pressure dishes it (edge-heavy). Both shrink the effective patch. Lowering a tire's pressure makes it run **hotter**.

**(b) Telemetry signature.**
- *Pyrometer (3-point):* balanced = center ≈ average of inner+outer. Over-pressure = **middle hotter** than edges. Under-pressure = **middle colder** than edges. (Inner-vs-outer spread is a **camber** problem, not pressure — pressure governs **center-vs-edges**.)
- *Responsiveness:* under-pressure → vaguer, slower yaw response, sidewall flex (delayed latG build). Over-pressure → twitchy/snappy, lower peak latG, faster drop-off once center overheats.
- *FH6:* over/under-pressured tire shows earlier slip-ratio/slip-angle runaway (lower grip ceiling) + a hotter localized temp zone; pressure climbs over a stint as temp builds.

**(c) Target.** Hot pressures inside the sim/manufacturer window (reference: ACC/iRacing GT3 ~1.50–1.55 bar hot; optimal tire temp ~80–90 °C GT3, broader ~85–105 °C). Middle tread ≈ average of inner+outer (flat patch). All four converge into window within the first few laps.

> **FH6 caveat.** The temp numbers above are other-sim priors (ACC/iRacing) and are **not verified for FH6** — project memory refutes "temp zone = peak grip" and finds no validated FH6 temp window. In FH6, set pressure to the fixed ~30-34 psi warm target (slightly higher front) and tune camber/pressure **by grip** (peak latG, |slip| under 1 hold), not by chasing a temp window. Read tire temps only as which axle/side is working harder, not as grip.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Center hotter than edges OR pressure above window | **Lower** cold pressure |
| Center colder than edges OR pressure below window | **Raise** cold pressure |
| Car vague / slow to respond | Raise pressure (sharper, less ultimate grip) |
| Twitchy / grip falls off fast / center cooking | Lower pressure |
| One tire stays too cold / under-gripping | **Lower** that corner's pressure (heats it faster) |
| One tire overheats / center crown / fast grip drop | **Raise** that corner's pressure |
| Cold track / hot track | Start higher / start lower |

> Per-corner thermal cross-balance (lower pressure → hotter) is medium confidence (verified=false). Use as fine cross-balance only; see the FH6 caveat in 1.14(c) - do not tune to a temp window in FH6.

---

## 1.15 Weight, Ballast & Polar Moment of Inertia

**(a) Mechanical.** **PMI (yaw inertia)** sets how fast the car starts/stops rotating, *independent of grip* — mass at the ends (engine over nose, fuel/cargo in tail) raises it; mass near center lowers it. **Front/rear distribution** sets the baseline under/oversteer tendency (50/50 pushes on turn-in; ~40/60–35/65 frees rotation, trades entry stability). **Total mass** scales grip-limited cornering + accel; reducing it only changes PMI/balance depending on *where* removed.

**(b) Telemetry signature.**
- *PMI:* yaw rate (`AngularVelocityY`) rises slowly after steering input, overshoots/decays slowly in transitions; latG ramps gradually; in chicanes the yaw trace can't keep up with the wheel. **Per-wheel slip angles stay modest** — the discriminator that it's inertia, **not** grip.
- *Distribution:* front-biased → front slip saturates before rear (understeer), hotter front temps, higher front travel; rear-biased → rears break first on entry/throttle, yaw overshoots commanded.
- *Total mass:* lower mass → higher peak lat/long g, lower travel per corner, steadier temps, faster yaw build.
- *Low-PMI double-edge:* agile but **snap-prone** — rear slip jumps <1→>>1 in a few frames with a sharp yaw spike + counter-steer, rather than gradual saturation.

**(c) Target.** Crisp low-lag steer→yaw correspondence, prompt yaw build/decay, quick reversals. Front and rear slip reaching the limit together, even temps. Yaw quick but progressive — fast turn-in without an abrupt spike; a small counter-steer catches it.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Feels heavy, won't turn in, lazy in chicanes **despite grip** | Move ballast toward **center** (lower PMI); strip nose/tail overhang weight |
| Too darty/snappy in transitions, hard to catch | Allow more mass toward the ends (**raise** PMI) |
| Understeer / won't rotate, hot front tires | Shift weight **rearward** (verify it's distribution, not PMI/grip) |
| Loose on entry/throttle, rear lets go first | Shift weight **forward** |
| Sluggish everywhere, lazy turn-in, tires overheating | Reduce weight (prefer pulling from the ends to also cut PMI) |
| Fast but darty/unstable | A touch of **central** ballast settles it without much PMI penalty |
| Snappy, spins with no warning, agile but scary | Move mass back toward ends (raise PMI) and/or shift balance slightly forward |

> Forza upgrade priority: Tires, Brakes, Weight reduction **before** power. Match PMI to driver skill, not just lap-time theory (low-PMI snap risk, verified=true, medium confidence). Distribution can be hit with central ballast (low PMI, agile) or end ballast (high PMI, calmer).

---

## 1.16 Gearing — Final Drive & Individual Ratios

**(a) Mechanical.** **Final drive** is the master knob: raise = shorten ALL gears (more accel, lower top speed); lower = lengthen all (less accel, higher top speed). **Individual ratios** control RPM drop per upshift — big gaps drop the engine out of the power band; close ratios keep it in but need more gears.

**(b) Telemetry signature.**
- *Too short (final drive too high):* bounces off rev limiter on the straight, RPM pinned + speed plateaued; high slip ratio on corner-exit upshifts (torque multiplication).
- *Too tall:* engine bogs below the power band on exit, RPM low, sluggish longitudinal accel, never reaches redline.
- *Gear gap too wide:* large RPM drop at each upshift landing below the torque peak; longitudinal-accel **dips** after the shift then slowly recovers.

**(c) Target.** On the longest straight, reach top gear's redline (or speed-trap target) right at the end — not bouncing early, not still pulling. Every corner exit: engine in or just below peak-power RPM. After each upshift, RPM lands at/just above the start of the strong power band — minimal accel sag.

**(d) Symptom → direction.**
| Symptom | Move |
|---|---|
| Hitting rev limiter on the straight, capped speed | **Lower** final drive (lengthen) |
| Great top end but slow off corners / bogs | **Raise** final drive (shorten) |
| Twisty point-to-point | Shorter overall gearing |
| Open road / speed traps | Longer gearing |
| Car bogs / accel drops right after an upshift | Tighten that ratio (close gap) or add a gear |
| Engine screams between shifts, too many tiny gaps | Widen ratios / use fewer gears |

> 6–7 speeds for road, 8–10 for drag/extreme power. Set final drive first (overall length), then fine-tune individual gaps.

---

# 2. TELEMETRY → FIX TABLES (by corner phase)

**Phase segmentation first.** Never act on a lap-mean balance number — the same car can understeer on entry and oversteer on exit. Segment every corner: **Straight → Braking → Turn-in/Entry → Mid/Apex → Exit**.

FH6 phase thresholds (sim-community heuristics — *calibrate per car/class*, verified=true that they're heuristics not constants):
- **Straight:** |latG| < ~0.3 g and small steer
- **Braking:** brake > ~5% and throttle ~0
- **Turn-in/Entry:** steer rising AND brake still > 0 (trail overlap)
- **Mid/Apex:** brake ~0, throttle ~0, |latG| near segment max at lowest speed (one speed minimum = one apex)
- **Exit:** throttle rising AND |steer| decreasing

Validate by overlaying detected boundaries on raw speed/steer/pedal traces before trusting aggregates. Keep the physics math (gradient, g-g, slip balance) fixed; only move segmentation cutoffs.

---

## 2.1 UNDERSTEER (push)

`front TireSlipAngle > rear`; measured yaw **below** reference `yaw_ref = v·δ/(L + Kus·v²)`; steer climbs but yaw flat.

| Phase | Likely cause | Fix + direction |
|---|---|---|
| **Entry** | Front bar too stiff, front rebound too high, brake bias too forward, decel lock too high, square-wave brake release (no front load) | Soften front ARB; −front bump/rebound; add front toe-out; shift brake bias rearward; −decel lock; **first** check trail-braking (driver) |
| **Mid** | Static front-stiff balance, too little front camber, front over-pressure, too little front aero (fast corners) | Soften front ARB/spring; +front negative camber; −front pressure; +front DF (high-speed only) |
| **Exit** | Accel diff lock too high, FWD wheelspin, rear too soft/loose forcing throttle-off | −accel diff lock (frees front rotation); FWD: −front diff lock; soften rear spring/bump |

---

## 2.2 OVERSTEER / LOOSE / SNAP

`rear TireSlipAngle > front`; measured yaw **above** reference; on exit driven `TireSlipRatio` spikes positive (wheelspin) with the yaw spike. SNAP = a yaw **step** (not ramp) + opposite-lock burst.

| Phase | Likely cause | Fix + direction |
|---|---|---|
| **Entry / lift** | Decel lock too low, rear bar too stiff, rear toe-out, front too stiff | +decel lock 2–3%; rear toe-IN; soften front ARB |
| **Mid** | Rear-stiff balance, too little rear camber, rear under-pressure, too little rear aero (fast) | Soften rear ARB/spring; +rear camber; adjust rear pressure; +rear DF (high-speed) |
| **Exit** | Accel lock too high, rear too loose, over-throttle | −accel diff lock 2–3%/step; rear toe-IN; soften rear spring/bump; +rear DF; manage throttle (driver) |
| **SNAP (any)** | Discontinuous grip transition — diff grabby, fast-rebound too stiff, rear skating over bumps | Attack the discontinuity: soften rear ARB + rear fast-rebound; +rear toe-in; raise ride height (stop rear skating); soften diff; soften front roll stiffness so balance shift is gentler |

> Attribution: rear slip spikes with throttle >~90% = driver over-throttle (coach). Persists with smooth inputs = loose tune. Don't fix understeer purely by adding rear stiffness if the rear is already marginal — you convert push into snap.

---

## 2.3 WHEELSPIN (exit traction loss)

Driven `TireSlipRatio` spikes positive as throttle goes down.

| Pattern | Cause | Fix |
|---|---|---|
| Inner driven wheel only spikes >1 | Diff accel lock too low (open behavior) | **+accel lock** |
| Both driven wheels >1 together + yaw overshoot | Accel lock too high / too little rear grip | **−accel lock**, soften rear, +rear grip, or −power |
| FWD pushes wide on power | Front diff lock too high | −front diff lock, soften front |
| RWD snap on power | — | Soften diff accel + rear ARB, +rear toe-in |
| AWD won't rotate on power | Rear bias too low | +rear bias |

---

## 2.4 LOCKUP (braking)

`TireSlipRatio` strongly **negative**; wheel speed dives toward 0 while car speed stays high.

| Pattern | Cause | Fix |
|---|---|---|
| Both fronts lock | Bias too far forward OR front pressure too high | Bias **rearward** / lower front pressure / lower total brake pressure |
| Rears lock / snap on entry | Bias too rearward | Bias **forward** |
| Single front locks first | Corner-weight / camber / pressure imbalance on that side | Check that corner's weight/camber/pressure |
| Locks even with smooth pedal | Brake pressure scaling too high | Reduce peak brake pressure |

---

## 2.5 INSTABILITY UNDER BRAKING

Yaw non-zero and **growing during straight-line braking** (should be ~0); steering corrections appear in the braking phase.

| Mode | Signature | Fix |
|---|---|---|
| **(a) Rear-light / rear locks** | Rear slip ratio more negative than front; rear travel toward droop | Bias **forward**; soften rear / −rear rebound (keep rear loaded); +rear grip margin; −decel lock if diff drags rear; ease trail-brake (driver) |
| **(b) Front-wander** | Nose darts, won't track straight under heavy braking | Bias slightly **rearward** (unload fronts); soften front compression; even up corner weights; −front rebound |

> Identify which axle's slip ratio goes negative first, act on **that** axle. Forward bias shift is the fastest reversible cure for braking-zone oversteer.

---

## 2.6 WILL-NOT-ROTATE / LACKS FRONT END

Measured yaw far below reference and barely responds to **added** steer; front slip angle high/pinned while **rear slip angle unusually LOW** (rear over-gripping).

| Cause | Fix |
|---|---|
| Rear over-gripping (won't let car pivot) | Reduce rear toe-IN toward neutral; stiffen rear ARB a touch; soften front ARB/spring; +front negative camber; correct front pressure |
| Diff locking out rotation | **−accel diff lock**; check decel lock so inside rear can rotate the car |
| (AWD) | +rear bias |

---

## 2.7 BOTTOMING

`NormalizedSuspensionTravel` **pinned at ~1.0**, coincident with a brief per-wheel |slip| spike past 1.0 and a g-trace glitch. (Near 0.0 = opposite failure: droop / wheel lift / unloaded.)

| Pattern | Fix (in order) |
|---|---|
| Front pins at 1.0 + momentary push | **Raise front height first**, then stiffen front spring |
| Rear pins + snap | Raise rear, then stiffen rear |
| Repeated one-corner clipping | Ride-height or corner-weight imbalance |
| Travel near 0.0 (droop/wheel lift) | The OTHER fixes: too stiff/too high or excessive transfer — soften or lower that corner; or soften the ARB holding it |

> Use the **1.0-pinning event** as the bottoming signal, **not** a travel-variance threshold (the analyzer's 0.30/0.05 std-dev cutoffs are unvalidated heuristics — carry-over caution).

---

# 3. THE FEEL DICTIONARY

Driver subjective term → telemetry signature → tuning cause → fix. Each is a complete entry. (All high confidence, "not-checked," except the FFB fork noted under VAGUE.)

---

### HEAVY / SLUGGISH / LAZY / RELUCTANT-TO-TURN
A **response-rate** complaint (how fast the car builds yaw), *distinct from understeer* (a grip/balance complaint) — they co-exist but fix differently.

- **Signature.** *MoTeC:* slow rise time on latG after the steering step (big steer→latG lag); high peak roll angle, low roll velocity; driver adds MORE lock than geometry needs while latG still climbing; US/OS channel positive at turn-in. *FH6:* steer rises but yaw (`AngularVelocityY`) + latG lag by noticeable frames; **per-wheel slip ANGLE stays well under 1.0** (tires gripping, just not loaded — confirms response, not grip-loss); large slow inside/outside travel delta (slow-developing roll); front slip angle modestly > rear on entry.
- **Cause.** Too-low roll/pitch stiffness or too-high rebound damping → weight transfers too slowly; or genuinely too soft/low.
- **Fix.** First stiffen **front ARB** + add a little **front compression damping** (cheap, reversible). Still lazy → lower front ride height + stiffen front springs. Lazy AND pushes → it's understeer balance, shift toward front by softening the **rear** ARB/spring. Also: front toe-OUT and slightly less caster/trail quicken bite; get tires to temp / correct front pressure. **Every move trades toward darty — one step at a time.**

---

### DARTY / NERVOUS / TWITCHY
The over-responsive twin of HEAVY; often the result of over-correcting a lazy car.

- **Signature.** *MoTeC:* high Steering Wheel Reversal Rate, latG/yaw overshoot + oscillate after input, transient rear slip-angle spikes. *FH6:* yaw overshoots/rings after steering steps; rear slip ANGLE brief excursions toward/over 1.0 on entry + over bumps while fronts stay planted; jittery low-damped travel; many small steering reversals (sawing); latG jumps abruptly.
- **Cause.** Too much front roll/compression stiffness; too little compliance; front toe-out; too little caster; rear grip marginal relative to front.
- **Fix.** Soften front ARB/springs, reduce front compression; raise ride height slightly for bump compliance; reduce front toe-out (toward zero/slight toe-IN); add caster/trail for self-centering; raise rear grip relative to front (soften rear ARB/spring, a touch of rear toe-IN); add a little rebound to settle oscillation. Darty AND rear-happy → stabilize tail first. Nervous over bumps specifically → raise height + soften fast-bump/rebound.

---

### VAGUE / NUMB
No clear signal of where the limit is. **Important fork:** in high-FFB sims, "numb" is frequently a **hardware/FFB** problem (clipping, rig flex), NOT setup. In a telemetry/FH6 context (no high-fidelity FFB), "vague" is a **vehicle-behavior** problem: grip→slip with no progressive build.

- **Signature.** *MoTeC:* gradual low-gradient self-aligning-torque / steering-load trace (no clear peak before the slide); FFB clipping = flat-topped force trace pinned at max. *FH6:* slip ANGLE climbs toward 1.0 with no abrupt yaw/g change to warn (no telemetry "shoulder"); latG plateaus softly; platform never firmly loads the outside front. **FH6 exposes no FFB-force channel — vague-from-FFB is invisible in telemetry.**
- **Cause.** Insufficient self-aligning torque (low caster), under-inflation, front never "sets," cold tires. (Or FFB clipping in a high-FFB sim.)
- **Fix.** **Add caster/trail first** (biggest feel lever). Raise tire pressure if under-inflated; stiffen front spring/ARB + add front compression so the front sets decisively; get tires to temp. FFB form (sim hardware only): reduce FFB gain to stop clipping, stiffen rig, cut steering damping filter. **Always rule out FFB/rig before chasing setup in a high-FFB sim.**

---

### PUSHY / UNDERSTEER ('won't turn', plows)
Front reaches slip limit before rear; nose runs wide; adding lock worsens it. **Diagnose by phase** (see §2.1).

- **Signature.** Positive US/OS angle; front slip angle > rear; latG plateaus below max while steer rises; FH6 measured yaw below reference, front slip pinned near/over 1.0, rears lower.
- **Cause/Fix.** Shift balance toward front: reduce front roll stiffness OR increase rear. By phase — entry: soften front ARB, −front bump, +front toe-out, trail-brake (driver); mid: soften front ARB/spring, +front camber, −front pressure, +front aero (fast); exit: −accel diff lock, soften rear, FWD reduce wheelspin. **Don't fix push purely by adding rear stiffness if the rear is marginal — converts to snap.**

---

### LOOSE / SNAP-OVERSTEER
Rear reaches limit before front; tail rotates faster than commanded. SNAP = abrupt, low-warning (grip or even understeer straight into breakaway). See §2.2.

- **Signature.** Negative US/OS angle; rear slip angle > front; sharp yaw spike + corrective steer reversal; SNAP = yaw **step** not ramp, rear slip jumping >1 in one frame + opposite-lock burst. FH6 measured yaw above reference; on exit driven slip ratio spikes positive (wheelspin) with the yaw spike.
- **Cause/Fix.** Shift toward rear (stiffen front OR soften rear) — but for SNAP the priority is removing the **discontinuity**: raise rear grip margin and make rear unloading progressive (soften rear ARB + rear fast-rebound, +rear toe-in, raise ride height so rear stops skating, soften diff, soften front roll stiffness). A yaw STEP → attack diff/fast-dampers/aero balance, not just static balance.

---

### PLANTED (the target end-state)
Stable, predictable, communicates the limit progressively, tolerates mid-corner inputs.

- **Signature.** US/OS angle near zero across the corner; latG at the grip ceiling, held flat through mid-corner; smooth yaw tracking steering, settles without ringing; low reversal rate; full traction-circle perimeter usage. *FH6:* front and rear slip ANGLE **matched and both <1.0** through mid-corner; measured yaw closely tracks reference; travel controlled (not at 1.0, not at 0.0), inside/outside settling smoothly; combined-slip near but not over 1.0 at the limit.
- **Fix.** **None — planted is the convergence point.** When the analyzer sees matched slip angles + yaw-tracks-reference + controlled travel + low reversal rate, report "balanced/planted, no change" and pivot to the **DRIVER** pillar (using the full traction circle? consistent apexes?). If planted but slow, the limit is **BUILD** (grip/power ceiling) or driver — not tune. Don't tune a planted car toward a number.

---

### UNSTABLE UNDER BRAKING
See §2.5 — two modes: **(a) rear-locking/rear-light** (tail comes around) and **(b) front-wander** (nose darts, won't track straight). Identify which axle's slip ratio goes negative first; act on that axle. Forward bias shift is the fastest reversible cure for mode (a).

---

### LACKS FRONT END / WON'T ROTATE
A rotation complaint (yaw generation), not outright front sliding. See §2.6. **Tell:** US/OS angle stays positive and does NOT decrease as the driver adds lock — more steer isn't buying rotation; FH6 rear slip angle unusually LOW (rear over-gripping). Free up rotation by raising relative rear slip / lowering rear over-grip (reduce rear toe-in, stiffen rear ARB a touch, soften front, +front camber) and **−accel diff lock**.

---

### LACKS REAR / NEEDS REAR STABILITY
The rear has too little grip margin (loose family). Fixes mirror oversteer (§2.2): soften rear ARB/spring, +rear toe-in, +rear camber, +rear DF (high-speed), −accel diff lock on exit. On RWD at speed, **+rear DF is the primary rear-stability tool** before touching diff/springs.

---

# 4. WHAT YOU WANT (targets / ideal traces)

### G-G / Traction Circle
- **Shape:** filled, smooth, roughly elliptical "D" — **more lateral than longitudinal g**, with a pointed braking pole (aero drag adds high-speed decel). Reaching tire max (~1.0–1.5 g slick-style). Continuous braking→cornering→accel transitions, **no large empty wedges**.
- **Filled shoulders** = good trail-brake (braking→lateral) and throttle-blend (lateral→accel) overlap.
- **Symmetric** left/right on a symmetric track.
- **Diagnosis lives in the GAPS:** data short of the boundary with full poles = **driver** leaving grip on the table (coach). Uniformly compressed / clipped poles = **setup/grip limit** (tune). Empty shoulders = no trail-brake / no throttle-blend (driver). Lateral pole much smaller one side = L/R imbalance (alignment/corner-weight/track).

### Speed Trace
- One clean speed minimum per corner (one apex, not a double-apex hesitation).
- On the longest straight, top gear reaches redline / speed-trap target right at the end — not bouncing early, not still pulling.

### Slip Ratio (longitudinal) Targets
- Held in a small-magnitude band (FH6 near 0), symmetric L/R.
- Under braking: no wheel dives to zero; front rides just under lock at peak.
- On exit: driven wheels just above ground speed / at the spin threshold, not sustained >1.

### Slip Angle (lateral) Targets
- Front and rear **balanced** through mid-corner (small front−rear delta), both near force peak, slight rear-led bias = classic neutral-to-slight-understeer race balance.
- Report PER PHASE: flat entry, neutral mid, slightly understeering exit = a good balanced car. **Watch for sign flips within one corner** (entry push → exit snap) that a lap-mean hides.

### Damper-Velocity Histogram
- **Symmetric bell/cone centered at 0**, peak in the low-speed range, ~even comp/reb area, front shape ≈ rear, low-speed region taller than high-speed.
- Starting split target (datamc): **~25% per zone** (LS-comp, LS-reb, HS-comp, HS-reb) at ~100 mm/s crossover.
- No twin peaks, no peak sitting on the LS/HS transition.
- *(The "~12% central-bin peak" target is **DO NOT RELY ON** — verified=false.)*

### Tire-Temp Distribution
- **Cross-tread:** inner-to-outer spread ~10–15 °F, inner slightly hotter, mid at midpoint, read **at corner exit**. (Cross-tread is camber [edges] + pressure [center-vs-edges]; **likely screen-only in FH6 UDP** — see caveats.)
- **Axle/side:** both axles inside the target window with the desired bias; L/R near-equal on a symmetric circuit. Matrix: front-cold/rear-optimal = understeer; front-optimal/rear-cold = oversteer; both cold or both hot = overall grip loss. **(FH6: this temp-to-balance matrix is unverified - see the 1.14(c) caveat. Call under/oversteer from slip-angle balance, not temps.)**

### Suspension-Travel Usage
- Stays in the productive mid-band (~0.2–0.8 normalized), uses most of available travel over a lap **without clipping** either stop, L/R symmetric on a symmetric track. Zero (or rare, worst-curb-only) readings at 1.0.

### Balance Per Phase
- **Braking:** speed falling steeply, brake near peak then bleeding, longG near the braking pole, minimal lock.
- **Turn-in/Entry:** brake curve crossing rising steer (filled shoulder), gradient near neutral, no coasting gap.
- **Mid/Apex:** single speed minimum, |latG| at the lateral pole, neutral gradient, steady (non-oscillating) steer, throttle ~0.
- **Exit:** throttle feeding in as steer unwinds (filled exit shoulder), path on the accel side, driven slip ratio near optimum without runaway, slight stable understeer.

### Understeer/Oversteer Gradient
- Near neutral (slight predictable understeer = fast-and-stable target). MoTeC i2 channel: `Oversteer = sign(latG)·(wheelbase·latG/speed² − steer_rad)`; positive = understeer, negative = oversteer; gate below ~50 km/h, smooth ~0.2 s. FH6: both the gradient and the steer-vs-latG plot work directly (latG, longG, steer all available); cross-check with slip-angle magnitudes (front>rear = understeer per SAE J670/ISO 8855).

### Input Traces
- **Brake:** sharp spike to threshold, smooth progressive taper to ~zero at/after apex, taper overlapping the steering build, below ~15–20% once heavily turned in.
- **Steering:** one smooth arc per corner, peak near turn-in tapering to exit, no added lock mid-corner, no high-frequency corrections.
- **Throttle:** progressive roll-on from apex reaching 100% as the car straightens, driven slip just at the spin threshold, no yaw spike, no on-off stabbing.

---

# 5. THE PROCESS (iterative setup loop)

**The discipline that makes telemetry tuning work — and the part most amateurs skip.**

1. **Baseline.** Establish a repeatable reference: same car, same fuel/tire state, multiple clean laps. Log the baseline telemetry. You cannot evaluate a change without a stable reference.
2. **Segment, don't average.** Run phase segmentation on every corner before reading any balance number. A lap-mean balance is meaningless.
3. **Locate the worst phase.** For each corner, find the phase with the largest gradient deviation (US/OS angle) or the emptiest g-g region.
4. **Driver vs car triage (do this BEFORE turning a knob).** In that phase:
   - Check **g-g utilization** — data short of the boundary with otherwise full poles = **driver** (coach, don't tune). Capped/asymmetric = **setup**.
   - Check the **input overlap trace** — square brake release, early throttle, coasting gap = **driver**.
   - Check the **yaw-deviation discriminator** — over/understeer that only appears when the driver lifts/adds steer = driver-caused (coach); persists with clean inputs = tune-caused.
   - **A balance fault is only tune-actionable if the driver inputs in that phase are clean.** You can't diagnose entry balance from a square-wave brake release — the front was never loaded.
5. **One change at a time.** Change a single parameter, in the documented direction, by a small increment (e.g. diff in 2–3% steps, ARB one click). Multiple simultaneous changes make attribution impossible.
6. **A/B back-to-back.** Re-run the same reference laps. Compare the same phase windows directly against baseline telemetry — not against memory or feel alone.
7. **Verify the predicted signature moved.** A change is validated only when the telemetry signature shifted the predicted way (e.g. front slip-angle onset now matches rear; yaw now tracks reference). If the signature didn't move, the diagnosis was wrong — revert and re-triage.
8. **Re-trim the order:** roll/balance via bars first, ride/heave via springs, transient via dampers, then diff (accel before decel before preload), then aero by speed band, then alignment by temp/grip sweep. Set overall stiffness level first, then front/rear bias.
9. **Stop when planted.** When slip angles are matched, yaw tracks reference, travel is controlled, and reversal rate is low — stop. Don't tune a planted car toward a number; chase feel/lap-time. If planted but slow, the limit is **build or driver**, not tune.

> **Separating driver from car is the whole game.** The single G-G mostly diagnoses *driver use*; pair it with slip-angle/yaw to separate driver from tune. The yaw-deviation + clean-input check is what distinguishes driver-caused from tune-caused over/understeer — the symptom alone never does.

---

# 6. FORZA TRANSLATION & CAVEATS

### What FH6 normalized telemetry gives you
> Channel names below are the FH6 **Data Out (Car Dash)** wire fields; per-wheel channels carry `FrontLeft/FrontRight/RearLeft/RearRight` suffixes. This project's parser exposes them as snake_case (e.g. `tire_slip_ratio_fl`, `norm_suspension_fl`, `angular_velocity_y`, `accel`). Watch the two traps flagged below.
- **`TireSlipRatio`** (longitudinal) and **`TireSlipAngle`** (lateral), per wheel, **0 = grip, |v|>1 = loss.** This is the workhorse — front-vs-rear slip-angle delta is the direct under/oversteer discriminator; driven-wheel slip-ratio split (conditioned on throttle/brake state) is the diff discriminator.
- **`NormalizedSuspensionTravel`** per wheel (0 = droop, 1 = bump). Differentiate at the packet rate (~60 Hz; this capture set runs ~62.5 Hz) to synthesize a damper-velocity signal and histogram it (the only way to get damper diagnostics — there is no damper channel). 1.0-pinning = bottoming.
- **`AccelerationX` (lateral), `AccelerationZ` (longitudinal)** → G-G plot and gradient.
- **Yaw rate = `AngularVelocityY`** (there is no field literally named `YawRate`; `Yaw` is heading, not rate), with **`Steer`, `Speed`** → reference-yaw comparison, the cleanest driver-vs-tune separator.
- **`WheelRotationSpeed`** per wheel → the literal lock/spin detector behind slip ratio.
- **Input channels:** `Accel`, `Brake`, `Steer` — **raw integers, NOT pre-normalized** (`Accel`/`Brake` 0–255, `Steer` −127..127); divide before use.

### What is NOT measurable in FH6 (real-world rules that break or go screen-only)
- **No hi/lo-speed damper split, no damper knee** — FH6 has one bump + one rebound scalar per axle. LS vs HS is an **analysis** distinction for diagnosis, not a tunable knob. High-speed/kerb behavior is reached via overall bump/rebound + springs + ride height.
- **Cross-tread tire temperature (inner/mid/outer)** — the on-screen Heat view shows 3 zones, but **UDP likely exposes only one scalar temp per wheel** (verified=true open question — confirm against the FH6 Data Out spec before building a temp-spread camber recommender). If scalar-only: **tune camber by grip-sweep** (peak latG / |slip|<1 hold time), not by inner/outer spread, and prompt the user to glance at the Heat view for the split the UDP can't give.
- **Tire temp units:** FH6 tire temp is in **°F, not °C** (known code bug per project memory) — account for this in any temp-window logic.
- **No FFB-force channel** — "vague/numb from FFB clipping" is invisible in telemetry. Only the vehicle-behavior form of vagueness shows up.
- **No true tire-vs-heading slip angle in MoTeC i2 either** — the US/OS channel is an *approximation* unless modeled. FH6's `TireSlipAngle` is a more direct read than i2's derived channel.

### Where real-world rules need Forza-specific calibration
- **Phase-detection thresholds** (0.3 g straight cutoff, 5% pedal, 50 km/h gradient gate, slip-angle overlap thresholds) are **sim-community heuristics, not vehicle-dynamics constants** (verified=true). The underlying physics (gradient formula, traction-circle constraint, slip-angle balance sign) is car-independent and fixed. Calibrate thresholds per car/class by visual overlay; never move the physics math.
- **Aero/balance by speed band** is the FH6 upgrade to lap-mean balance (parallels the state-aware slip work). Band frames by speed (e.g. low <100, mid 100–160, high >160 km/h — **thresholds need FH6 validation**) and assign the knob by band: high-speed-band imbalance → aero; low-speed-band → mechanical. Opposite-direction imbalance across bands → fix each band independently; same-direction → suspect a global cause (weight/alignment).
- **Numeric setup ranges** (RWD accel 40–60% / low end for high-power, decel 15–30%, AWD center 60–70% rear, caster 5.5–6.5°, camber −1.5 to −1.8° front) are FH6 starting bands carried from the verified findings and kept in sync with the analyzer; treat as priors, validate per car.

### Partial-lap / free-roam gap (project-known)
The analyzer skips `_partial` laps, so free-roam drives currently get no analysis. Any per-corner methodology above should be reachable from partial-lap segments for the coaching module, not gated on full clean laps.

---

## CONFIDENCE LEDGER (what to trust how much)

- **High confidence, established practice (treat as solid, confirmable):** spring/ARB/damper balance rules; the magnitude-vs-rate split; total-roll-stiffness invariance; damper-velocity histogram as primary diagnostic; phase segmentation; trail-brake overlap; g-g gap reading; brake bias/pressure rules; tire-pressure center-vs-edge rule; gearing; weight/distribution; the full Feel Dictionary; diff accel/decel/AWD-center rules.
- **verified=true (positively confirmed this pass):** phase-detection thresholds are heuristics not constants; diff preload symptom→fix; low-PMI snap double-edge; UDP per-zone-temp availability is a genuine open question.
- **DO NOT RELY ON (verified=false — confirm independently before hard-coding):**
  - Front/rear slip-angle delta as the *sole* mechanical-balance discriminator (medium confidence — the mechanism is sound, the magnitude mapping is not verified).
  - Rake-as-aero-balance knob and lower-front/more-rake-moves-CofP-rearward.
  - Drivetrain-gated aero start points as exact numbers (AWD min-rear-DF logic is sound; the precise fractions are not verified).
  - Ride-height/rake dynamic aero-migration and "stiffen springs ~20–60% when adding aero."
  - The "~12% damper central-bin peak" target and front/rear histogram-equalization detail.
  - Chassis-specific static camber baselines.
  - Per-corner tire-pressure thermal cross-balance precise magnitudes.
  - The diff driven-wheel-split conditioned-aggregate routing (the *approach* is sound; the exact thresholds are unverified).
