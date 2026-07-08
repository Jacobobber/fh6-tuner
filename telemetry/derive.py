from telemetry.parser import TelemetryFrame, tire_temp_to_celsius


def derive_frame(f: TelemetryFrame) -> dict:
    """Frame dict plus the convenience fields the dashboards need.

    Shared by the local GUI (gui/server.py) and the cloud app (web/) so the
    Fahrenheit->Celsius conversion lives in exactly one place. Per-session fields
    like session_distance_m are added by the caller (they need cross-frame state).
    """
    d = f.to_dict()
    d["speed_mph"] = round(f.speed * 2.237, 1)
    d["speed_kph"] = round(f.speed * 3.6, 1)
    d["rpm_frac"] = round(f.current_engine_rpm / f.engine_max_rpm, 4) if f.engine_max_rpm else 0.0
    d["lat_g"] = round(f.acceleration_x / 9.81, 2)
    d["long_g"] = round(f.acceleration_z / 9.81, 2)
    for c in ("fl", "fr", "rl", "rr"):  # wire temp is Fahrenheit; expose Celsius
        d[f"tire_temp_c_{c}"] = round(tire_temp_to_celsius(getattr(f, f"tire_temp_{c}")), 1)
    return d
