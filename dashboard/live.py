from typing import Iterator

from rich import box
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from telemetry.parser import TelemetryFrame, tire_temp_to_celsius


def fmt_time(seconds: float) -> str:
    if seconds <= 0:
        return "--:--.---"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


def bar(
    value: float,
    min_val: float,
    max_val: float,
    width: int = 10,
    color: str = "green",
) -> Text:
    fraction = max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
    filled = int(fraction * width)
    return Text("█" * filled + "░" * (width - filled), style=color)


def signed_bar(
    value: float,
    scale: float,
    width: int = 10,
    neg_color: str = "red",
    pos_color: str = "green",
) -> Text:
    """Bar centered on zero. ``scale`` is the magnitude mapping to a full half-bar."""
    fraction = max(-1.0, min(1.0, value / scale)) if scale else 0.0
    cells = int(abs(fraction) * width)
    if fraction < 0:
        left = Text("░" * (width - cells) + "█" * cells, style=neg_color)
        right = Text("░" * width, style=pos_color)
    else:
        left = Text("░" * width, style=neg_color)
        right = Text("█" * cells + "░" * (width - cells), style=pos_color)
    out = Text()
    out.append_text(left)
    out.append("|", style="white")
    out.append_text(right)
    return out


def _temp_color(temp_c: float) -> str:
    # temp_c is Celsius (callers convert from the wire Fahrenheit). The grip
    # window is approximate (~75-110 C); Forza's exact ideal is unverified.
    if temp_c < 75.0:
        return "cyan"
    if temp_c < 110.0:
        return "green"
    if temp_c < 125.0:
        return "yellow"
    return "red"


def make_engine_panel(f: TelemetryFrame) -> Panel:
    mph = f.speed * 2.237
    rpm_fraction = (
        f.current_engine_rpm / f.engine_max_rpm if f.engine_max_rpm else 0.0
    )
    rpm_color = "green" if rpm_fraction < 0.85 else "red"

    body = Text()
    body.append(f"Speed   {mph:6.1f} mph\n", style="bold cyan")
    body.append(
        f"RPM     {int(f.current_engine_rpm):5d} / {int(f.engine_max_rpm):5d} rpm\n"
    )
    body.append(f"Gear    {f.gear}\n")
    body.append("RPM     ")
    body.append_text(bar(rpm_fraction, 0.0, 1.0, width=20, color=rpm_color))

    return Panel(body, title="Engine", box=box.ROUNDED)


def make_lap_panel(f: TelemetryFrame) -> Panel:
    body = Text()
    body.append(f"Current  {fmt_time(f.current_lap)}\n", style="bold")
    body.append(f"Best     {fmt_time(f.best_lap)}\n", style="green")
    body.append(f"Last     {fmt_time(f.last_lap)}\n")
    body.append(f"Lap      {f.lap_number}")

    return Panel(body, title="Lap Timer", box=box.ROUNDED)


def make_tire_panel(f: TelemetryFrame) -> Panel:
    table = Table(box=box.SIMPLE, expand=True, show_header=False)
    table.add_column(justify="center")
    table.add_column(justify="center")

    corners = {
        "FL": (tire_temp_to_celsius(f.tire_temp_fl), f.tire_combined_slip_fl),
        "FR": (tire_temp_to_celsius(f.tire_temp_fr), f.tire_combined_slip_fr),
        "RL": (tire_temp_to_celsius(f.tire_temp_rl), f.tire_combined_slip_rl),
        "RR": (tire_temp_to_celsius(f.tire_temp_rr), f.tire_combined_slip_rr),
    }

    def cell(label: str) -> Text:
        temp, slip = corners[label]
        text = Text()
        text.append(f"{label}\n", style="bold")
        text.append(f"{temp:5.1f}C\n", style=_temp_color(temp))
        text.append(f"slip {slip:4.2f}")
        return text

    table.add_row(cell("FL"), cell("FR"))
    table.add_row(cell("RL"), cell("RR"))

    return Panel(table, title="Tires", box=box.ROUNDED)


def make_suspension_panel(f: TelemetryFrame) -> Panel:
    # Normalized suspension travel is 0..1; recenter so 0.5 reads as neutral,
    # positive = compression, negative = extension.
    corners = {
        "FL": f.norm_suspension_fl,
        "FR": f.norm_suspension_fr,
        "RL": f.norm_suspension_rl,
        "RR": f.norm_suspension_rr,
    }

    body = Text()
    for label, value in corners.items():
        body.append(f"{label} ")
        body.append_text(
            signed_bar(value - 0.5, 0.5, width=8, neg_color="cyan", pos_color="magenta")
        )
        body.append(f" {value - 0.5:+.2f}\n")

    return Panel(body, title="Suspension", box=box.ROUNDED)


def make_gforce_panel(f: TelemetryFrame) -> Panel:
    lateral = f.acceleration_x / 9.81
    longitudinal = f.acceleration_z / 9.81

    body = Text()
    body.append("Lat  ")
    body.append_text(
        signed_bar(lateral, 2.0, width=10, neg_color="blue", pos_color="red")
    )
    body.append(f" {lateral:+.2f} g\n")
    body.append("Long ")
    body.append_text(
        signed_bar(longitudinal, 2.0, width=10, neg_color="red", pos_color="green")
    )
    body.append(f" {longitudinal:+.2f} g")

    return Panel(body, title="G-Force", box=box.ROUNDED)


def run_dashboard(frame_source: Iterator[TelemetryFrame]) -> None:
    layout = Layout()
    layout.split_column(
        Layout(name="top", size=7),
        Layout(name="middle", size=12),
        Layout(name="bottom", size=7),
    )
    layout["top"].split_row(Layout(name="engine"), Layout(name="lap"))
    layout["bottom"].split_row(Layout(name="suspension"), Layout(name="gforce"))

    with Live(layout, refresh_per_second=30, screen=True):
        for frame in frame_source:
            layout["engine"].update(make_engine_panel(frame))
            layout["lap"].update(make_lap_panel(frame))
            layout["middle"].update(make_tire_panel(frame))
            layout["suspension"].update(make_suspension_panel(frame))
            layout["gforce"].update(make_gforce_panel(frame))
