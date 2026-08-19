"""Comprehensive Leika image, matplotlib, Plotly, viser, layout, and GUI showcase.

Install the optional dependency and run from the repository root::

    python -m pip install -e ".[examples]"
    python examples/showcase.py
"""

from __future__ import annotations

import io
import struct
import threading
import time
import warnings
import zlib
from collections import deque
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Protocol, TypeVar

import numpy as np
import plotly.graph_objects as go
import viser
from matplotlib.axes import Axes
from matplotlib.figure import Figure

import leika

# Plotly templates used to demonstrate a searchable dropdown.
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

ASSETS = Path(__file__).resolve().parent / "assets"

NOTES_MD = """\
# Showcase notes

The controls on the left drive four panes: a NumPy field, a live viser point
cloud, a Plotly chart and a 3D surface.

## Files

| Button | What it does |
| --- | --- |
| Download signal CSV | Saves the chart's history as a file |
| Preview signal CSV | Shows those same rows here instead |
| Preview the field | The frame the pane is showing, as a PNG |
| Watch the ripple | A clip of the same field, read off disk |

Every viewer opens the same window: writing is set in a column like this
one, data runs the full width, and pictures sit in the middle of it.

The Python preview transfer declines source files past **64 MiB**. For a
transferred file, the browser renders plain/prose/source text through **16 MiB**
and Markdown through **1 MiB** to bound parse and DOM expansion. It keeps the
received Blob available to download when inline rendering is declined.
"""

CLOUD_SHAPES = ("Gaussian", "Shell", "Spiral")


class _Stoppable(Protocol):
    def stop(self) -> object: ...


TStoppable = TypeVar("TStoppable", bound=_Stoppable)


def _stop_safely(label: str, stop: Callable[[], object]) -> None:
    """Stop one owned service without replacing an active application error."""

    try:
        stop()
    except Exception as error:
        warnings.warn(f"Failed to stop {label}: {error}", RuntimeWarning, stacklevel=2)


class _ShowcaseLifetime:
    """Own every background service created during partial or complete setup."""

    def __init__(self) -> None:
        self.stopping = threading.Event()
        self._stack = ExitStack()

    def own(self, label: str, resource: TStoppable) -> TStoppable:
        self._stack.callback(_stop_safely, label, resource.stop)
        return resource

    def close(self) -> None:
        self.stopping.set()
        self._stack.close()


HEIGHT = 300
WIDTH = 480
Y, X = np.mgrid[-1.0 : 1.0 : complex(HEIGHT), -1.5 : 1.5 : complex(WIDTH)]

# Leika relays a matplotlib figure exactly as composed -- no recoloring -- so a
# figure styled for a white page is wrong the moment a viewer switches to the
# dark theme. One mid gray reads against both.
FIGURE_INK = "#8a8a8a"
FIGURE_FILL = "#6aa9d8"


def png_bytes(frame: np.ndarray) -> bytes:
    """Encode an RGB array as a minimal PNG using the standard library."""
    height, width, _ = frame.shape
    rows = b"".join(b"\x00" + frame[row].tobytes() for row in range(height))

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


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


def cloud_points(shape: str, count: int) -> np.ndarray:
    """Points for the viser scene. The 3D data is Leika's only in the sense
    that Leika's controls choose it; viser owns the scene that draws it."""

    rng = np.random.default_rng(0)
    if shape == "Shell":
        directions = rng.normal(size=(count, 3))
        directions /= np.linalg.norm(directions, axis=1, keepdims=True)
        return (directions * rng.uniform(0.9, 1.0, (count, 1))).astype(np.float32)
    if shape == "Spiral":
        t = np.linspace(0.0, 6.0 * np.pi, count)
        radius = np.linspace(0.15, 1.2, count)
        return np.stack(
            [radius * np.cos(t), radius * np.sin(t), np.linspace(-1.0, 1.0, count)],
            axis=-1,
        ).astype(np.float32)
    return rng.normal(scale=0.5, size=(count, 3)).astype(np.float32)


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
        margin={"l": 42, "r": 18, "t": 10, "b": 34},
        showlegend=False,
        uirevision="leika-showcase",
    )
    return figure


def style_axes(axes: Axes) -> None:
    """Apply the two-theme styling. Called again after every ``clear()``."""

    axes.set_facecolor("none")
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.spines["left"].set_color(FIGURE_INK)
    axes.spines["bottom"].set_color(FIGURE_INK)
    axes.tick_params(colors=FIGURE_INK, labelsize=9)
    axes.set_xlabel("signal", color=FIGURE_INK, fontsize=9)
    axes.set_ylabel("count", color=FIGURE_INK, fontsize=9)


def make_distribution() -> Figure:
    """Build the figure the matplotlib pane relays.

    Constructed through ``Figure`` rather than ``pyplot``: nothing here is
    ever shown locally, so there is no backend or figure manager to involve.
    """

    # Sized generously against the type: the pane scales the SVG to fit, so a
    # small figure would land with text twice the size of the Plotly pane's.
    figure = Figure(figsize=(7.5, 4.6), layout="constrained", facecolor="none")
    style_axes(figure.add_subplot())
    return figure


def draw_distribution(figure: Figure, values: list[float]) -> None:
    """Redraw the trailing signal's histogram in place."""

    axes = figure.axes[0]
    axes.clear()
    style_axes(axes)
    axes.set_xlim(-1.0, 1.0)
    if values:
        axes.hist(values, bins=24, range=(-1.0, 1.0), color=FIGURE_FILL, edgecolor="none")
        axes.axvline(float(np.mean(values)), color=FIGURE_INK, linewidth=1.0, linestyle="--")


def _run_showcase(lifetime: _ShowcaseLifetime) -> None:
    server = lifetime.own(
        "Leika server",
        leika.Server(workspace_id="showcase-v2", label="Live signals"),
    )
    server.gui.configure_theme(control_layout="floating")
    analysis_page = server.pages.add("Analysis", page_id="analysis")
    scene_page = server.pages.add("3D scene", page_id="scene")

    initial = render_field(0.0, 1.2, "Ocean", (0.0, 0.0), (20, 90, 210, 45))
    grid = server.panes.add_grid(columns=2)
    field_pane = grid.add_image(
        initial,
        pane_id="field",
        title="Live NumPy field",
        fit="fill",
        format="jpeg",
        jpeg_quality=82,
    )
    # Released viser does not report its chosen port for port=0, so use a
    # concrete starting port; viser probes upward when it is occupied.
    viser_server = lifetime.own(
        "Viser server",
        viser.ViserServer(port=8081, verbose=False),
    )
    scene_page.panes.add_viser(
        viser_server,
        pane_id="scene",
        title="Live viser scene",
    )
    plot_figure = make_plot()
    plot_pane = grid.add_plotly(
        plot_figure,
        pane_id="signal",
        title="Interactive Plotly",
        config={"displayModeBar": False, "responsive": True},
    )
    distribution_figure = make_distribution()
    distribution_pane = analysis_page.panes.add_matplotlib(
        distribution_figure,
        pane_id="distribution",
        title="matplotlib distribution",
    )
    # Synchronous GUI callbacks run on worker threads while the animation loop
    # owns the same timeline and Plotly figure. One lock makes every snapshot
    # and paired publication coherent; server.atomic() groups transport only.
    state_lock = threading.RLock()
    state: dict[str, Any] = {
        "phase": 0.0,
        "start": time.monotonic(),
        "signal": [],
        "distribution_revision": 0,
    }
    history_t: deque[float] = deque(maxlen=240)
    history_y: deque[float] = deque(maxlen=240)

    with server.gui.add_folder("Playback and signal"):
        animate = server.gui.add_checkbox("Animate", initial_value=True)
        speed = server.gui.add_slider(
            "Speed",
            min=0.1,
            max=3.0,
            step=0.01,
            initial_value=1.0,
            marks=((0.1, "slow"), (3.0, "fast")),
            show_value=True,
            hint="Fast drags stay optimistic while Python catches up.",
        )
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
        reset = server.gui.add_button("Reset timeline", icon=leika.Icon.REFRESH_CW, color="inverse")

    with server.gui.add_folder("Image appearance"):
        palette = server.gui.add_toggle(("Ocean", "Magma", "Viridis"), label="Palette")
        nudge = server.gui.add_button(("Left", "Right"), label="Nudge", merge=False)
        with server.gui.add_folder("Color adjustments"):
            offset = server.gui.add_vector2("Offset", initial_value=(0.0, 0.0), step=0.05)
            tint = server.gui.add_rgba("Tint", initial_value=(20, 90, 210, 45))
            plot_color = server.gui.add_rgb("Plot line", initial_value=(196, 196, 196))
            revert = server.gui.add_button("Revert", label="Colors")
        gui_preview = server.gui.add_image(
            initial[::4, ::4],
            format="jpeg",
            jpeg_quality=75,
        )

    with server.gui.add_folder("3D scene"):
        cloud_shape = server.gui.add_dropdown(
            "Cloud shape", options=CLOUD_SHAPES, initial_value="Gaussian"
        )
        cloud_count = server.gui.add_slider(
            "Points", min=500, max=20_000, step=500, initial_value=6_000
        )
        cloud_size = server.gui.add_slider(
            "Point size", min=0.005, max=0.06, step=0.005, initial_value=0.02
        )
        cloud_color = server.gui.add_rgb("Cloud color", initial_value=(230, 180, 80))
        spin = server.gui.add_toggle("Spin the cloud")

    tabs = server.gui.add_tab_group()
    with tabs.add_tab("Charts", icon=leika.Icon.CHART_LINE):
        plotly_theme = server.gui.add_dropdown(
            "Plotly theme",
            options=PLOTLY_TEMPLATES,
            searchable=True,
            hint="Type to filter Plotly's built-in templates.",
        )
        plot_overlays = server.gui.add_toggle(
            ("Grid", "Zero line"),
            label="Overlays",
            multiple=True,
            initial_value="Grid",
        )
        gui_plot = server.gui.add_plotly(
            plot_figure,
            aspect=2.0,
            config={"displayModeBar": False, "staticPlot": True},
        )

    with tabs.add_tab("Actions", icon=leika.Icon.BOLT):
        panel_actions = server.gui.add_button(("Notify", "Open modal"))
        upload = server.gui.add_upload_button(
            "Inspect a file",
            mime_type="image/*,.txt,.json",
            icon=leika.Icon.UPLOAD,
        )

        with server.gui.add_popup("Popup example"):
            server.gui.add_text(
                None,
                "A popup is a folder-like container that keeps its controls behind one row.",
                editable=False,
                markdown=True,
                multiline=True,
            )
            server.gui.add_checkbox("Show guides", initial_value=True)
            with server.gui.add_folder("Nested group", expand_by_default=False):
                server.gui.add_slider(
                    "Guide opacity",
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    initial_value=0.7,
                )

        def signal_csv(event: leika.GuiEvent[Any]) -> bytes:
            buffer = io.StringIO()
            with state_lock:
                samples = tuple(zip(history_t, history_y))
            buffer.write("time,signal\n")
            buffer.writelines(f"{x},{y}\n" for x, y in samples)
            return buffer.getvalue().encode()

        server.gui.add_download_button(
            "Download signal CSV",
            signal_csv,
            filename="leika-signal.csv",
            icon=leika.Icon.DOWNLOAD,
        )
        server.gui.add_preview_button(
            "Preview signal CSV",
            signal_csv,
            filename="leika-signal.csv",
            icon=leika.Icon.EYE,
        )
        server.gui.add_preview_button(
            "Read the notes",
            NOTES_MD.encode(),
            filename="notes.md",
            icon=leika.Icon.BOOK_OPEN,
        )

        def field_png(event: leika.GuiEvent[Any]) -> bytes:
            with state_lock:
                phase = state["phase"]
            return png_bytes(
                render_field(
                    phase,
                    float(frequency.value),
                    palette.value[0],
                    offset.value,
                    tint.value,
                )
            )

        server.gui.add_preview_button(
            "Preview the field",
            field_png,
            filename="leika-field.png",
            icon=leika.Icon.IMAGE,
        )
        server.gui.add_preview_button(
            "Watch the ripple",
            ASSETS / "ripple.mp4",
            icon=leika.Icon.FILM,
        )
        with server.gui.add_form(label="Annotation") as annotation:
            note_title = server.gui.add_text("Title", "Interesting spike")
            note_body = server.gui.add_text("Note", "", multiline=True)
            note_level = server.gui.add_toggle(("Info", "Warning"), label="Level")
        log = server.gui.add_text(
            None, "_Nothing logged yet._", editable=False, markdown=True, multiline=True
        )
        with server.gui.add_mini_form() as broadcast:
            message = server.gui.add_text("Broadcast", "")
        watchlist = server.gui.add_list(
            "Watch for",
            ("phase drift", "edge ringing"),
            hint="Drag an entry to reorder it.",
        )
        watching = server.gui.add_text(None, "", editable=False, markdown=True, multiline=True)
        todo = server.gui.add_checklist(
            "To do",
            (("Sweep the offset", True), "Log the ringing", "Export the run"),
            hint="Drag an entry to reorder it; its tick goes with it.",
        )
        preflight = server.gui.add_checklist(
            "Before a run",
            ("Warm up the source", ("Zero the offset", True), "Clear the log"),
            frozen=True,
        )
        server.gui.add_radio_list(
            "Density",
            ("Compact", ("Comfortable", True), "Spacious"),
            hint="Choose one density or edit and reorder the choices.",
        )
        server.gui.add_radio_list(
            "Quality",
            (("Draft", True), "Balanced", "Maximum"),
            frozen=True,
        )
        progress = server.gui.add_text(None, "", editable=False, markdown=True, multiline=True)

    def publish_plot_locked() -> None:
        """Publish both copies while state_lock protects the shared figure."""

        plot_pane.update(plot_figure)
        gui_plot.figure = plot_figure

    @plotly_theme.on_update
    def _(_) -> None:
        with state_lock:
            plot_figure.update_layout(template=plotly_theme.value)
            with server.atomic():
                publish_plot_locked()

    @plot_overlays.on_update
    def _(_) -> None:
        with state_lock:
            overlays = plot_overlays.value
            plot_figure.update_xaxes(showgrid="Grid" in overlays, zeroline="Zero line" in overlays)
            plot_figure.update_yaxes(showgrid="Grid" in overlays, zeroline="Zero line" in overlays)
            with server.atomic():
                publish_plot_locked()

    @plot_color.on_update
    def _(_) -> None:
        with state_lock:
            red, green, blue = plot_color.value
            plot_figure.update_traces(
                line={"color": f"rgb({red},{green},{blue})"},
                fillcolor=f"rgba({red},{green},{blue},0.12)",
            )
            with server.atomic():
                publish_plot_locked()

    @reset.on_click
    def _(_) -> None:
        with state_lock:
            state["phase"] = 0.0
            state["start"] = time.monotonic()
            history_t.clear()
            history_y.clear()
            state["signal"] = []
            plot_figure.data[0].x = []
            plot_figure.data[0].y = []
            with server.atomic():
                publish_plot_locked()
            state["distribution_revision"] += 1
        server.gui.add_notification(
            "Timeline reset", "Chart history was cleared and phase reset.", auto_close_seconds=2.0
        )

    @panel_actions.on_click
    def _(event: leika.GuiEvent[Any]) -> None:
        if event.target.value == "Notify":
            server.gui.add_notification(
                "Leika is live",
                f"{len(server.clients)} browser client(s) connected.",
                auto_close_seconds=2.5,
            )
            return
        with server.gui.add_modal("Python-created modal"):
            server.gui.add_text(
                None,
                "This modal is populated through the same GUI API as the hover panel.",
                editable=False,
                markdown=True,
                multiline=True,
            )
            server.gui.add_slider("Local control", min=0.0, max=1.0, step=0.01, initial_value=0.65)

    @revert.on_click
    def _(_) -> None:
        offset.value = (0.0, 0.0)
        tint.value = (20, 90, 210, 45)
        plot_color.value = (196, 196, 196)

    def rebuild_cloud(_: object = None) -> None:
        points = cloud_points(cloud_shape.value, int(cloud_count.value))
        colors = np.tile(np.asarray(cloud_color.value, dtype=np.uint8), (len(points), 1))
        # Re-adding under the same name replaces the node, and the handle it
        # returns is what the loop below spins.
        with state_lock:
            state["cloud"] = viser_server.scene.add_point_cloud(
                "/cloud",
                points=points,
                colors=colors,
                point_size=float(cloud_size.value),
            )

    cloud_shape.on_update(rebuild_cloud)
    cloud_count.on_update(rebuild_cloud)
    cloud_size.on_update(rebuild_cloud)
    cloud_color.on_update(rebuild_cloud)
    rebuild_cloud()

    @nudge.on_click
    def _(event: leika.GuiEvent[Any]) -> None:
        step = 0.1 if event.target.value == "Right" else -0.1
        x, y = offset.value
        offset.value = (round(x + step, 2), y)

    entries: deque[str] = deque(maxlen=3)

    @annotation.on_submit
    def _(_) -> None:
        title = note_title.value.strip() or "Untitled"
        body = note_body.value.strip()
        with state_lock:
            started = state["start"]
        at = time.monotonic() - started
        entries.appendleft(
            f"- `t={at:5.1f}s` **{title}** ({note_level.value[0]})"
            + (f" -- {body}" if body else "")
        )
        log.value = "\n".join(entries)
        note_title.value = ""
        note_body.value = ""
        server.gui.add_notification("Annotation logged", title, auto_close_seconds=2.0)

    @watchlist.on_update
    def _(_) -> None:
        kept = [entry.strip() for entry in watchlist.value if entry.strip()]
        watching.value = "" if not kept else "_Watching: " + ", ".join(kept) + "._"

    def show_progress(_: Any = None) -> None:
        done = len(todo.checked) + len(preflight.checked)
        total = len(todo.value) + len(preflight.value)
        progress.value = f"_{done} of {total} ticked._"

    show_progress()
    todo.on_update(show_progress)
    preflight.on_update(show_progress)

    @broadcast.on_submit
    def _(_) -> None:
        text = message.value.strip()
        if not text:
            return
        server.gui.add_notification("Broadcast", text, auto_close_seconds=3.0)
        message.value = ""

    @upload.on_upload
    def _(event: leika.GuiEvent[Any]) -> None:
        uploaded = event.value
        server.gui.add_notification(
            "File received",
            f"{uploaded.name}: {len(uploaded.content):,} bytes",
            auto_close_seconds=3.0,
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

    # Redrawing matplotlib and serializing to SVG costs about 50 ms -- a frame
    # and a half of the budget below -- so it runs on its own thread, reading
    # the snapshot the loop publishes rather than the deque. Only this thread
    # ever touches the figure. A thread does not make it free, since the SVG
    # backend holds the GIL throughout; once a second is what keeps the loop
    # at 30 fps. A matplotlib pane is a picture, not a live chart.
    stopping = lifetime.stopping

    # A paused reset gets one cleared snapshot; otherwise paused charts stay still.
    def refresh_distribution() -> None:
        last_revision = -1
        while not stopping.is_set():
            animating = animate.value
            with state_lock:
                revision = int(state["distribution_revision"])
                values = list(state["signal"]) if animating or revision != last_revision else None
            if values is not None:
                draw_distribution(distribution_figure, values)
                distribution_pane.update(distribution_figure)
                last_revision = revision
            stopping.wait(1.0)

    threading.Thread(target=refresh_distribution, daemon=True).start()

    print(f"Open {server.url}")
    simulation_interval = 1.0 / 30.0
    # Viser keeps its smooth simulation cadence, while Leika publishes one
    # coherent image/Plotly state below a busy browser's sustained capacity.
    publish_interval = 1.0 / 15.0
    last_tick = time.monotonic()
    next_simulation = last_tick
    next_publish = last_tick
    try:
        while True:
            now = time.monotonic()
            dt = min(now - last_tick, 0.1)
            last_tick = now
            animating = animate.value
            with state_lock:
                if animating:
                    state["phase"] += dt * float(speed.value) * 2.2
                    elapsed = now - state["start"]
                    signal = float(np.sin(state["phase"]))
                    history_t.append(elapsed)
                    history_y.append(signal)
                if animating and spin.value:
                    # Only the node's rotation changes, so the points themselves
                    # are not resent: a quaternion about z, wxyz as viser wants it.
                    half = state["phase"] * 0.5
                    state["cloud"].wxyz = (float(np.cos(half)), 0.0, 0.0, float(np.sin(half)))

            if animating and now >= next_publish:
                with state_lock:
                    frame = render_field(
                        state["phase"],
                        float(frequency.value),
                        palette.value[0],
                        offset.value,
                        tint.value,
                    )
                    kept = max(2, round(len(history_t) * float(trail.value)))
                    trail_t = list(history_t)[-kept:]
                    trail_y = list(history_y)[-kept:]
                    plot_figure.data[0].x = trail_t
                    plot_figure.data[0].y = trail_y
                    plot_figure.update_yaxes(range=list(plot_range.value))
                    with server.atomic():
                        field_pane.update(frame)
                        gui_preview.image = frame[::4, ::4]
                        publish_plot_locked()
                    # Published for the distribution thread. Building the list
                    # here keeps deque iteration on the thread that appends to it.
                    state["signal"] = list(history_y)
                next_publish += publish_interval
                after_publish = time.monotonic()
                if next_publish <= after_publish:
                    next_publish = after_publish + publish_interval
            elif not animating:
                # Resume with one current frame, never a catch-up burst.
                next_publish = now

            # Sleep to the next 30 Hz deadline rather than for a fixed
            # interval, so frame work does not subtract from the frame rate.
            # After an overrun, restart the schedule instead of bursting.
            next_simulation += simulation_interval
            delay = next_simulation - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_simulation = time.monotonic()
    except KeyboardInterrupt:
        pass


def main() -> None:
    lifetime = _ShowcaseLifetime()
    try:
        _run_showcase(lifetime)
    except KeyboardInterrupt:
        pass
    finally:
        lifetime.close()


if __name__ == "__main__":
    main()
