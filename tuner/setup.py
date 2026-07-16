"""Setup pass — the build/tune/weight counterpart to readout.full_read.

full_read reads what the car DID (telemetry); this reads how it's CONFIGURED — the
captured tune sliders, the installed parts, and the car weight — and runs the
tune-side math that is genuinely DERIVED from the config plus the car's own weight
(ride frequency; roll-stiffness %front vs the weight split), with no fixed tuning
cutoffs anywhere.

It deliberately does NOT judge sliders against hardcoded rule-bands (camber X,
diff Y-Z, …): whether a value is "too much" is track- and car-dependent, so that
verdict comes from the telemetry read conditioned on the car's own operating points
(`main.py read <session>`) plus reasoning — never a magic number baked in here.
This pass surfaces the config and the quantities physics/geometry fix.

Config schema (all keys optional)::

    {"car": {name, pi, class, drivetrain, cylinders},
     "weight": {total_lb, front_pct},
     "build": {transmission, differential, tires_compound, ...},
     "tune": { ...the numeric TUNE_FIELDS... }}
"""
import json

from tuner.response import TUNE_FIELDS, tune_math


def setup_read(cfg: dict) -> str:
    """Render the build/tune/weight config + the config-derived tune-math (no fixed
    tuning cutoffs; track-dependent verdicts are deferred to the telemetry read)."""
    L: list[str] = ["# SETUP READ (build / tune / weight)", ""]

    car = cfg.get("car", {})
    L += ["## Car", f"    {json.dumps(car)}"]
    wt = cfg.get("weight", {})
    if wt:
        L.append(f"    weight: {json.dumps(wt)}")

    L += ["", "## Build / mods", f"    {json.dumps(cfg.get('build', {}))}"]

    tune = cfg.get("tune", {})
    L += ["", "## Tune (sliders)",
          f"    {json.dumps({k: tune.get(k) for k in TUNE_FIELDS if tune.get(k) is not None})}"]

    L += ["", "## Tune math (derived — ride frequency + roll-stiffness vs weight)"]
    if tune and wt.get("total_lb") and wt.get("front_pct") is not None:
        L.append(f"    {json.dumps(tune_math(tune, total_weight_lb=wt['total_lb'], front_weight_pct=wt['front_pct']))}")
    else:
        L.append("    (needs weight.total_lb + weight.front_pct from the upgrade screen)")

    L += ["", "## Reading this",
          "  Ride frequency and roll-bias-vs-weight are the only claims here that don't",
          "  depend on the track — both come from the config and the car's own weight.",
          "  Whether the camber / diff / brake / aero values are right is answered by the",
          "  telemetry read (`main.py read <session>`), conditioned on the car's own",
          "  speed/load/temp bands — not by fixed cutoffs."]
    return "\n".join(L)
