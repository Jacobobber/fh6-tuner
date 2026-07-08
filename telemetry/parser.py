from dataclasses import dataclass, asdict
import struct

SLED_FORMAT = "<iI fff fff fff fff fff ffff ffff ffff ffff ffff ffff ffff ffff ffff iiiii"
DASH_FORMAT = "<fff f f f ffff f f f f f f f H BBBBBB bbb"

# Forza Horizon inserts a 12-byte block between the sled and the dash data that
# the Forza Motorsport "Car Dash" layout does not have. Verified against a live
# FH6 feed: the dash block (Position, Speed, ...) starts 12 bytes after the
# 232-byte sled, so the full packet is 324 bytes.
HORIZON_GAP = 12
# The 12-byte Horizon block FM's layout lacks: CarGroup, SmashableVelDiff (m/s),
# SmashableMass (kg). Parsed (not skipped) so every wire field is captured.
GAP_FORMAT = "<I f f"

SLED_SIZE = struct.calcsize(SLED_FORMAT)
DASH_SIZE = struct.calcsize(DASH_FORMAT)
GAP_SIZE = struct.calcsize(GAP_FORMAT)
DASH_OFFSET = SLED_SIZE + HORIZON_GAP
PACKET_SIZE = DASH_OFFSET + DASH_SIZE


@dataclass
class TelemetryFrame:
    # Sled
    is_race_on: int
    timestamp_ms: int
    engine_max_rpm: float
    engine_idle_rpm: float
    current_engine_rpm: float
    acceleration_x: float
    acceleration_y: float
    acceleration_z: float
    velocity_x: float
    velocity_y: float
    velocity_z: float
    angular_velocity_x: float
    angular_velocity_y: float
    angular_velocity_z: float
    yaw: float
    pitch: float
    roll: float
    norm_suspension_fl: float
    norm_suspension_fr: float
    norm_suspension_rl: float
    norm_suspension_rr: float
    tire_slip_ratio_fl: float
    tire_slip_ratio_fr: float
    tire_slip_ratio_rl: float
    tire_slip_ratio_rr: float
    wheel_rotation_speed_fl: float
    wheel_rotation_speed_fr: float
    wheel_rotation_speed_rl: float
    wheel_rotation_speed_rr: float
    wheel_on_rumble_fl: float
    wheel_on_rumble_fr: float
    wheel_on_rumble_rl: float
    wheel_on_rumble_rr: float
    wheel_in_puddle_fl: float
    wheel_in_puddle_fr: float
    wheel_in_puddle_rl: float
    wheel_in_puddle_rr: float
    surface_rumble_fl: float
    surface_rumble_fr: float
    surface_rumble_rl: float
    surface_rumble_rr: float
    tire_slip_angle_fl: float
    tire_slip_angle_fr: float
    tire_slip_angle_rl: float
    tire_slip_angle_rr: float
    tire_combined_slip_fl: float
    tire_combined_slip_fr: float
    tire_combined_slip_rl: float
    tire_combined_slip_rr: float
    suspension_travel_fl: float
    suspension_travel_fr: float
    suspension_travel_rl: float
    suspension_travel_rr: float
    car_ordinal: int
    car_class: int
    car_performance_index: int
    drivetrain_type: int
    num_cylinders: int
    # Forza Horizon block (the 12 bytes the FM layout lacks)
    car_group: int
    smashable_vel_diff: float
    smashable_mass: float
    # Car Dash
    position_x: float
    position_y: float
    position_z: float
    speed: float
    power: float
    torque: float
    tire_temp_fl: float
    tire_temp_fr: float
    tire_temp_rl: float
    tire_temp_rr: float
    boost: float
    fuel: float
    distance_traveled: float
    best_lap: float
    last_lap: float
    current_lap: float
    current_race_time: float
    lap_number: int
    race_position: int
    accel: int
    brake: int
    clutch: int
    hand_brake: int
    gear: int
    steer: int
    norm_driving_line: int
    norm_ai_brake_diff: int

    def to_dict(self) -> dict:
        return asdict(self)


def parse_packet(data: bytes) -> "TelemetryFrame | None":
    if len(data) < PACKET_SIZE:
        return None
    sled_vals = struct.unpack_from(SLED_FORMAT, data, 0)
    if sled_vals[0] == 0:  # IsRaceOn
        return None
    gap_vals = struct.unpack_from(GAP_FORMAT, data, SLED_SIZE)
    dash_vals = struct.unpack_from(DASH_FORMAT, data, DASH_OFFSET)
    return TelemetryFrame(*sled_vals, *gap_vals, *dash_vals)


def tire_temp_to_celsius(fahrenheit: float) -> float:
    """Convert a Forza tire-temperature reading to Celsius.

    Forza Data Out reports TireTemp in Fahrenheit (per the official FH6 spec),
    but the rest of the tool reasons in Celsius, so convert at the point of use.
    """
    return (fahrenheit - 32.0) * 5.0 / 9.0
