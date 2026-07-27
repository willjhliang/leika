"""Comprehensive Leika image, Plotly, layout, and GUI showcase.

Install the optional dependency and run from the repository root::

    python -m pip install -e ".[plotly]"
    python examples/showcase.py
"""

from __future__ import annotations

import io
import time
from collections import deque
from typing import Any, cast

import numpy as np
import plotly.graph_objects as go

import leika

HEIGHT = 300
WIDTH = 480
Y, X = np.mgrid[-1.0 : 1.0 : complex(HEIGHT), -1.5 : 1.5 : complex(WIDTH)]


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
        margin={"l": 42, "r": 18, "t": 38, "b": 34},
        title="Live signal",
        showlegend=False,
        uirevision="leika-showcase",
    )
    return figure


def main() -> None:
    server = leika.Server(workspace_id="showcase-v1")
    server.gui.configure_theme(
        control_layout="floating",
        dark_mode=True,
    )

    initial = render_field(0.0, 1.2, "Ocean", (0.0, 0.0), (20, 90, 210, 45))
    grid = server.panes.add_grid(columns=2)
    field_pane = grid.add_image(
        initial,
        pane_id="field",
        title="Live NumPy field",
        fit="cover",
        image_format="jpeg",
        jpeg_quality=82,
    )
    detail_pane = grid.add_image(
        initial[70:230, 120:360],
        pane_id="detail",
        title="Detail view",
        fit="contain",
        image_format="png",
    )
    plot_figure = make_plot()
    plot_pane = grid.add_plotly(
        plot_figure,
        pane_id="signal",
        title="Interactive Plotly",
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
            hint="Fast drags stay optimistic while Python catches up.",
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
        palette = server.gui.add_button_group("Palette", options=("Ocean", "Magma", "Viridis"))
        fit = server.gui.add_dropdown(
            "Fit", options=("cover", "contain", "fill"), initial_value="cover"
        )
        with server.gui.add_folder("Color adjustments"):
            offset = server.gui.add_vector2("Offset", initial_value=(0.0, 0.0), step=0.05)
            tint = server.gui.add_rgba("Tint", initial_value=(20, 90, 210, 45))
            plot_color = server.gui.add_rgb("Plot line", initial_value=(196, 196, 196))
        server.gui.add_divider()
        gui_preview = server.gui.add_image(
            initial[::4, ::4], label="GUI image preview", format="jpeg", jpeg_quality=75
        )

    with server.gui.add_folder("Pane visibility", expand_by_default=False):
        show_field = server.gui.add_checkbox("Live field", initial_value=True)
        show_detail = server.gui.add_checkbox("Detail", initial_value=True)
        show_plot = server.gui.add_checkbox("Plotly", initial_value=True)
        detail_title = server.gui.add_text("Detail title", initial_value="Detail view")

    with server.gui.add_folder("Panel theme", expand_by_default=False):
        dark_mode = server.gui.add_checkbox("Dark mode", initial_value=True)
        panel_layout = server.gui.add_dropdown(
            "Layout", options=("floating", "fixed", "collapsible")
        )

    tabs = server.gui.add_tab_group()
    with tabs.add_tab("Charts", icon=leika.Icon.CHART_LINE):
        gui_plot = server.gui.add_plotly(
            plot_figure,
            aspect=1.6,
            config={"displayModeBar": False, "staticPlot": True},
        )
        x_data = np.linspace(0.0, 6.0, 120)
        uplot = server.gui.add_uplot(
            (x_data, np.sin(x_data)),
            ({}, {"label": "signal", "stroke": "#c4c4c4", "width": 2}),
            title="Fast uPlot preview",
            aspect=2.0,
        )

    with tabs.add_tab("Actions", icon=leika.Icon.BOLT):
        notify = server.gui.add_button("Show notification")
        open_modal = server.gui.add_button("Open modal")
        upload = server.gui.add_upload_button(
            "Inspect a file", mime_type="image/*,.txt,.json", icon=leika.Icon.UPLOAD
        )
        download = server.gui.add_button("Download signal CSV", icon=leika.Icon.DOWNLOAD)

    with server.gui.add_form(submit_label="Apply", label="Rename main pane") as form:
        title_input = server.gui.add_text("Title", initial_value="Live NumPy field")

    state: dict[str, Any] = {
        "phase": 0.0,
        "start": time.monotonic(),
    }
    history_t: deque[float] = deque(maxlen=240)
    history_y: deque[float] = deque(maxlen=240)

    def apply_theme(_: Any = None) -> None:
        server.gui.configure_theme(
            control_layout=cast(Any, panel_layout.value),
            dark_mode=dark_mode.value,
        )

    for control in (panel_layout, dark_mode):
        control.on_update(apply_theme)

    @fit.on_update
    def _(_) -> None:
        field_pane.fit = cast(Any, fit.value)

    @plot_color.on_update
    def _(_) -> None:
        red, green, blue = plot_color.value
        plot_figure.update_traces(
            line={"color": f"rgb({red},{green},{blue})"},
            fillcolor=f"rgba({red},{green},{blue},0.12)",
        )
        plot_pane.update(plot_figure)
        gui_plot.figure = plot_figure

    @show_field.on_update
    def _(_) -> None:
        field_pane.visible = show_field.value

    @show_detail.on_update
    def _(_) -> None:
        detail_pane.visible = show_detail.value

    @show_plot.on_update
    def _(_) -> None:
        plot_pane.visible = show_plot.value

    @detail_title.on_update
    def _(_) -> None:
        detail_pane.title = detail_title.value or "Detail view"

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

    @form.on_submit
    def _(_) -> None:
        field_pane.title = title_input.value.strip() or "Live NumPy field"

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
                    detail_pane.update(frame[70:230, 120:360])
                    gui_preview.image = frame[::4, ::4]

            if now - last_plot >= 0.2:
                plot_figure.data[0].x = list(history_t)
                plot_figure.data[0].y = list(history_y)
                plot_figure.update_yaxes(range=list(plot_range.value))
                plot_pane.update(plot_figure)
                gui_plot.figure = plot_figure
                data_x = np.asarray(history_t, dtype=np.float64)
                data_y = np.asarray(history_y, dtype=np.float64)
                uplot.data = (data_x, data_y)
                last_plot = now

            time.sleep(1.0 / 30.0)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
