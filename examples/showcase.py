"""Comprehensive Leika image, Plotly, layout, and GUI showcase.

Install the optional dependency and run from the repository root::

    python -m pip install -e ".[examples]"
    python examples/showcase.py
"""

from __future__ import annotations

import io
import time
from collections import deque
from typing import Any

import numpy as np
import plotly.graph_objects as go

import leika

# Plotly's built-in named templates. Long enough to be a chore to scan by eye,
# which is the case `searchable=True` exists for; the short `Detail region`
# dropdown below is the plain default.
PLOTLY_TEMPLATES = (
    "plotly",
    "plotly_white",
    "plotly_dark",
    "ggplot2",
    "seaborn",
    "simple_white",
    "presentation",
    "xgridoff",
    "ygridoff",
    "gridon",
    "none",
)

# uPlot ships no equivalent, so the showcase names its own line styles. Each
# maps to the series options uPlot already understands; the first is what the
# chart starts with.
UPLOT_THEMES: dict[str, dict[str, Any]] = {
    "Slate": {"stroke": "#c4c4c4", "width": 2},
    "Ember": {"stroke": "#f97316", "width": 2, "fill": "rgba(249,115,22,0.15)"},
    "Ocean": {"stroke": "#38bdf8", "width": 2, "fill": "rgba(56,189,248,0.15)"},
    "Meadow": {"stroke": "#4ade80", "width": 2, "fill": "rgba(74,222,128,0.15)"},
    "Orchid": {"stroke": "#c084fc", "width": 2, "fill": "rgba(192,132,252,0.15)"},
    "Sunbeam": {"stroke": "#facc15", "width": 2, "fill": "rgba(250,204,21,0.15)"},
    "Rose": {"stroke": "#fb7185", "width": 2, "fill": "rgba(251,113,133,0.15)"},
    "Hairline": {"stroke": "#c4c4c4", "width": 1},
    "Dashed": {"stroke": "#c4c4c4", "width": 2, "dash": (6.0, 4.0)},
}


def uplot_series(theme: str) -> tuple[Any, ...]:
    """uPlot's series tuple: the x series, then the styled signal."""

    return ({}, {"label": "signal", **UPLOT_THEMES[theme]})


# Where the detail pane looks. Three named crops of the field, which is short
# enough that a plain dropdown beats a search box.
DETAIL_REGIONS: dict[str, tuple[slice, slice]] = {
    "Center": (slice(70, 230), slice(120, 360)),
    "Top left": (slice(0, 160), slice(0, 240)),
    "Bottom right": (slice(140, 300), slice(240, 480)),
}


HEIGHT = 300
WIDTH = 480
Y, X = np.mgrid[-1.0 : 1.0 : complex(HEIGHT), -1.5 : 1.5 : complex(WIDTH)]

# Coarse grid for the 3D surface pane: kept small because every update ships
# the whole z matrix to the browser.
SURFACE_AXIS = np.linspace(-2.0, 2.0, 40)
SURFACE_X, SURFACE_Y = np.meshgrid(SURFACE_AXIS, SURFACE_AXIS)
SURFACE_RADIUS = np.sqrt(SURFACE_X**2 + SURFACE_Y**2)


def render_field(
    phase: float,
    frequency: float,
    palette: str,
    offset: tuple[float, float],
    tint: tuple[int, int, int, int],
) -> np.ndarray:
    """Render a colorful RGB field without another plotting dependency."""

    shifted_x = X + float(offset[0])
    shifted_y = Y + float(offset[1])
    value = 0.5 + 0.5 * np.tanh(
        np.sin(frequency * shifted_x * 3.0 + phase)
        + np.cos(frequency * shifted_y * 4.0 - phase * 0.7)
        + 0.5 * np.sin((shifted_x + shifted_y) * 5.0 + phase * 1.4)
    )
    if palette == "Magma":
        channels = (
            255.0 * np.sqrt(value),
            165.0 * value**2,
            70.0 + 150.0 * (1.0 - value),
        )
    elif palette == "Viridis":
        channels = (
            50.0 + 180.0 * value,
            35.0 + 215.0 * np.sin(value * np.pi / 2.0),
            120.0 + 120.0 * (1.0 - value),
        )
    else:
        channels = (
            20.0 + 70.0 * value,
            40.0 + 190.0 * value,
            100.0 + 155.0 * value,
        )
    frame = np.stack(channels, axis=-1)
    alpha = 0.35 * float(tint[3]) / 255.0
    frame = frame * (1.0 - alpha) + np.asarray(tint[:3]) * alpha
    return np.clip(frame, 0.0, 255.0).astype(np.uint8)


def make_plot() -> go.Figure:
    figure = go.Figure(
        go.Scatter(
            x=[0.0],
            y=[0.0],
            mode="lines",
            line={"color": "#c4c4c4", "width": 3},
            fill="tozeroy",
            fillcolor="rgba(196,196,196,0.12)",
        )
    )
    figure.update_layout(
        # No in-figure title: the pane and the GUI row already name this plot,
        # so the top margin only has to clear the highest tick label.
        margin={"l": 42, "r": 18, "t": 10, "b": 34},
        showlegend=False,
        uirevision="leika-showcase",
    )
    return figure


def surface_height(phase: float, frequency: float) -> np.ndarray:
    """Radial ripple that shares the image panes' phase and frequency."""

    return np.sin(frequency * 2.0 * SURFACE_RADIUS - phase) * np.exp(-0.35 * SURFACE_RADIUS)


def make_surface() -> go.Figure:
    figure = go.Figure(
        go.Surface(
            x=SURFACE_AXIS,
            y=SURFACE_AXIS,
            z=surface_height(0.0, 1.2),
            colorscale="Blues",
            showscale=False,
        )
    )
    figure.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        # Keeps the camera where the user dragged it across live updates.
        uirevision="leika-showcase-surface",
        scene={"zaxis": {"range": [-1.1, 1.1]}},
    )
    return figure


def main() -> None:
    server = leika.Server(workspace_id="showcase-v1", label="Leika showcase")
    server.gui.configure_theme(control_layout="floating")

    initial = render_field(0.0, 1.2, "Ocean", (0.0, 0.0), (20, 90, 210, 45))
    grid = server.panes.add_grid(columns=2)
    field_pane = grid.add_image(
        initial,
        pane_id="field",
        title="Live NumPy field",
        fit="fill",
        image_format="jpeg",
        jpeg_quality=82,
    )
    detail_pane = grid.add_image(
        initial[DETAIL_REGIONS["Center"]],
        pane_id="detail",
        title="Detail view",
        # No `fit`: this pane follows whatever the viewer picked under
        # Settings. The field pane above pins its own, so the two show the
        # override and the default side by side.
        image_format="png",
    )
    plot_figure = make_plot()
    plot_pane = grid.add_plotly(
        plot_figure,
        pane_id="signal",
        title="Interactive Plotly",
        config={"displayModeBar": False, "responsive": True},
    )
    surface_figure = make_surface()
    surface_pane = grid.add_plotly(
        surface_figure,
        pane_id="surface",
        title="3D surface",
        config={"displayModeBar": False, "responsive": True},
    )

    with server.gui.add_folder("Playback and signal"):
        animate = server.gui.add_checkbox("Animate", initial_value=True)
        speed = server.gui.add_slider(
            "Speed",
            min=0.1,
            max=3.0,
            step=0.01,
            initial_value=1.0,
            marks=((0.1, "slow"), (3.0, "fast")),
            # The number is worth reading exactly here, and worth typing when a
            # drag cannot land on 1.00 by hand.
            show_value=True,
            hint="Fast drags stay optimistic while Python catches up.",
        )
        # The default the other way: no box, so the track takes the whole row.
        # Trail length is a feel rather than a figure -- nobody types a number
        # of samples -- which is the case `show_value` is off for.
        # No `marks`, so the ends label themselves with the numbers -- the plain
        # default, against `Speed` above naming its own ends instead.
        trail = server.gui.add_slider(
            "Trail",
            min=0.05,
            max=1.0,
            step=0.01,
            initial_value=0.6,
            hint="No number box: the marks carry the range and the shape says the rest.",
        )
        frequency = server.gui.add_number(
            "Frequency", initial_value=1.2, min=0.2, max=3.0, step=0.05
        )
        plot_range = server.gui.add_multi_slider(
            "Plot range",
            min=-3.0,
            max=3.0,
            step=0.1,
            initial_value=(-1.5, 1.5),
            min_range=0.5,
        )
        reset = server.gui.add_button("Reset timeline", icon=leika.Icon.REFRESH_CW)

    with server.gui.add_folder("Image appearance"):
        # Labelled, so it sits in the controls column beside its name -- the
        # three options still fit. Unlabelled it would take the whole row.
        palette = server.gui.add_button(("Ocean", "Magma", "Viridis"), label="Palette")
        # Three options, so no search box: the plain dropdown opens with the
        # current one already under the cursor.
        region = server.gui.add_dropdown(
            "Detail region", options=tuple(DETAIL_REGIONS), initial_value="Center"
        )
        with server.gui.add_folder("Color adjustments"):
            offset = server.gui.add_vector2("Offset", initial_value=(0.0, 0.0), step=0.05)
            tint = server.gui.add_rgba("Tint", initial_value=(20, 90, 210, 45))
            plot_color = server.gui.add_rgb("Plot line", initial_value=(196, 196, 196))
        gui_preview = server.gui.add_image(
            initial[::4, ::4],
            format="jpeg",
            jpeg_quality=75,
        )

    tabs = server.gui.add_tab_group()
    with tabs.add_tab("Charts", icon=leika.Icon.CHART_LINE):
        # The other half of the pair: a list this long earns a search box.
        plotly_theme = server.gui.add_dropdown(
            "Plotly theme",
            options=PLOTLY_TEMPLATES,
            searchable=True,
            hint="Type to filter Plotly's built-in templates.",
        )
        gui_plot = server.gui.add_plotly(
            plot_figure,
            # Twice as wide as it is tall, matching the uPlot below.
            aspect=2.0,
            config={"displayModeBar": False, "staticPlot": True},
        )
        server.gui.add_divider()
        uplot_theme = server.gui.add_dropdown(
            "uPlot theme",
            options=tuple(UPLOT_THEMES),
            searchable=True,
            hint="Type to filter the named line styles.",
        )
        x_data = np.linspace(0.0, 6.0, 120)
        uplot = server.gui.add_uplot(
            (x_data, np.sin(x_data)),
            uplot_series(uplot_theme.value),
            aspect=2.0,
        )

    with tabs.add_tab("Actions", icon=leika.Icon.BOLT):
        # The two that show off the panel lead, filled; the two that move a file
        # follow, outlined. `color` is which of the two roles a button takes,
        # not a palette.
        notify = server.gui.add_button("Show notification")
        open_modal = server.gui.add_button("Open modal")
        upload = server.gui.add_upload_button(
            "Inspect a file",
            mime_type="image/*,.txt,.json",
            icon=leika.Icon.UPLOAD,
            color="secondary",
        )
        download = server.gui.add_button(
            "Download signal CSV", icon=leika.Icon.DOWNLOAD, color="secondary"
        )

    state: dict[str, Any] = {
        "phase": 0.0,
        "start": time.monotonic(),
    }
    history_t: deque[float] = deque(maxlen=240)
    history_y: deque[float] = deque(maxlen=240)

    @plotly_theme.on_update
    def _(_) -> None:
        # The live loop keeps pushing this same figure, so the template sticks
        # without being reapplied on every frame.
        plot_figure.update_layout(template=plotly_theme.value)
        plot_pane.update(plot_figure)
        gui_plot.figure = plot_figure

    @uplot_theme.on_update
    def _(_) -> None:
        # Only the series styling changes; the loop keeps writing `data`, which
        # is a separate prop and so is left alone here.
        uplot.series = uplot_series(uplot_theme.value)

    @plot_color.on_update
    def _(_) -> None:
        red, green, blue = plot_color.value
        plot_figure.update_traces(
            line={"color": f"rgb({red},{green},{blue})"},
            fillcolor=f"rgba({red},{green},{blue},0.12)",
        )
        plot_pane.update(plot_figure)
        gui_plot.figure = plot_figure

    @reset.on_click
    def _(_) -> None:
        state["phase"] = 0.0
        state["start"] = time.monotonic()
        history_t.clear()
        history_y.clear()
        server.gui.add_notification(
            "Timeline reset", "Image and chart history were cleared.", auto_close_seconds=2.0
        )

    @notify.on_click
    def _(_) -> None:
        server.gui.add_notification(
            "Leika is live",
            f"{len(server.clients)} browser client(s) connected.",
            auto_close_seconds=2.5,
        )

    @open_modal.on_click
    def _(_) -> None:
        with server.gui.add_modal("Python-created modal"):
            server.gui.add_markdown(
                "This modal is populated through the same GUI API as the hover panel."
            )
            server.gui.add_slider("Local control", min=0.0, max=1.0, step=0.01, initial_value=0.65)

    @upload.on_upload
    def _(event: leika.GuiEvent[Any]) -> None:
        uploaded = event.value
        server.gui.add_notification(
            "File received",
            f"{uploaded.name}: {len(uploaded.content):,} bytes",
            auto_close_seconds=3.0,
        )

    @download.on_click
    def _(event: leika.GuiEvent[Any]) -> None:
        if event.client is None:
            return
        buffer = io.StringIO()
        buffer.write("time,signal\n")
        buffer.writelines(f"{x},{y}\n" for x, y in zip(history_t, history_y))
        event.client.send_file_download(
            "leika-signal.csv",
            buffer.getvalue().encode(),
        )

    pause_command = server.gui.add_command(
        "Pause animation",
        description="Toggle live image and chart updates",
        hotkey="P",
        icon=leika.Icon.PAUSE,
    )

    @pause_command.on_trigger
    def _(_) -> None:
        animate.value = not animate.value
        pause_command.label = "Pause animation" if animate.value else "Resume animation"

    @server.on_client_connect
    def _(client: leika.ClientHandle) -> None:
        client.add_notification(
            "Welcome to Leika",
            "Drag pane labels, resize dividers, or press Ctrl/Cmd+K.",
            auto_close_seconds=4.0,
        )

    print(f"Open {server.url}")
    last_tick = time.monotonic()
    last_plot = 0.0
    try:
        while True:
            now = time.monotonic()
            dt = min(now - last_tick, 0.1)
            last_tick = now
            if animate.value:
                state["phase"] += dt * float(speed.value) * 2.2

            elapsed = now - state["start"]
            signal = float(np.sin(state["phase"]))
            history_t.append(elapsed)
            history_y.append(signal)

            if animate.value:
                frame = render_field(
                    state["phase"],
                    float(frequency.value),
                    palette.value,
                    offset.value,
                    tint.value,
                )
                with server.atomic():
                    field_pane.update(frame)
                    rows, columns = DETAIL_REGIONS[region.value]
                    detail_pane.update(frame[rows, columns])
                    gui_preview.image = frame[::4, ::4]

            if now - last_plot >= 0.2:
                # How much of the buffered history the plots draw. Two points is
                # the least that is still a line.
                kept = max(2, round(len(history_t) * float(trail.value)))
                trail_t = list(history_t)[-kept:]
                trail_y = list(history_y)[-kept:]
                plot_figure.data[0].x = trail_t
                plot_figure.data[0].y = trail_y
                plot_figure.update_yaxes(range=list(plot_range.value))
                plot_pane.update(plot_figure)
                gui_plot.figure = plot_figure
                data_x = np.asarray(trail_t, dtype=np.float64)
                data_y = np.asarray(trail_y, dtype=np.float64)
                uplot.data = (data_x, data_y)
                surface_figure.data[0].z = surface_height(state["phase"], float(frequency.value))
                surface_pane.update(surface_figure)
                last_plot = now

            time.sleep(1.0 / 30.0)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
