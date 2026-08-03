"""Comprehensive Leika image, Plotly, layout, and GUI showcase.

Install the optional dependency and run from the repository root::

    python -m pip install -e ".[examples]"
    python examples/showcase.py
"""

from __future__ import annotations

import io
import struct
import time
import zlib
from collections import deque
from pathlib import Path
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

# The one thing here that is a file before it is a preview. Everything else
# the showcase shows is made up as it runs.
ASSETS = Path(__file__).resolve().parent / "assets"

# A file with no file behind it: bytes made up on the spot and previewed as
# markdown, which the dialog renders the way `add_text(markdown=True)` does.
NOTES_MD = """\
# Showcase notes

The controls on the left drive four panes: a NumPy field, a crop of it, a live
Plotly chart and a 3D surface.

## Files

| Button | What it does |
| --- | --- |
| Download signal CSV | Saves the chart's history as a file |
| Preview signal CSV | Shows those same rows here instead |
| Preview the field | The frame the pane is showing, as a PNG |
| Watch the ripple | A clip of the same field, read off disk |

Every viewer opens the same window: writing is set in a column like this
one, data runs the full width, and pictures sit in the middle of it.

A preview holds the whole file in the tab, so anything past **64 MiB** is
declined with a notification rather than opened.
"""

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


def png_bytes(frame: np.ndarray) -> bytes:
    """Encode an RGB array as a PNG, with nothing but the standard library.

    Leika takes NumPy arrays directly, so the showcase has no image library
    of its own; a preview wants a file, and this is the shortest bridge
    between the two. Each row is prefixed with a zero -- PNG's "no filter" --
    and the lot is deflated into a single data chunk.
    """
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
        # 8 bits per sample, color type 2: RGB, no palette and no alpha.
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
        format="jpeg",
        jpeg_quality=82,
    )
    detail_pane = grid.add_image(
        initial[DETAIL_REGIONS["Center"]],
        pane_id="detail",
        title="Detail view",
        # No `fit`: this pane follows whatever the viewer picked under
        # Settings. The field pane above pins its own, so the two show the
        # override and the default side by side.
        format="png",
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
        # The default the other way: no box, so the track takes the whole
        # row, and no `marks`, so the ends label themselves with the numbers.
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
        # Toggles rather than buttons: the palette is a state the image is
        # in, not an action. Single-select (the default) also means required,
        # so the image always has a palette to render with.
        palette = server.gui.add_toggle(
            ("Ocean", "Magma", "Viridis"), label="Palette", color="secondary"
        )
        # Three options, so no search box: the plain dropdown opens with the
        # current one already under the cursor.
        region = server.gui.add_dropdown(
            "Detail region", options=tuple(DETAIL_REGIONS), initial_value="Center"
        )
        # Buttons this time, because a nudge happens and is over. Parted, since
        # the two are opposite moves rather than one control with two ends.
        nudge = server.gui.add_button(
            ("Left", "Right"), label="Nudge", color="secondary", merge=False
        )
        # A toggle with no label takes the row, exactly as a button does.
        pin = server.gui.add_toggle("Pin the detail view", color="secondary")
        with server.gui.add_folder("Color adjustments"):
            offset = server.gui.add_vector2("Offset", initial_value=(0.0, 0.0), step=0.05)
            tint = server.gui.add_rgba("Tint", initial_value=(20, 90, 210, 45))
            plot_color = server.gui.add_rgb("Plot line", initial_value=(196, 196, 196))
            # A single button with a label: it gives up the full width and
            # takes the controls column, at the height every other row is.
            revert = server.gui.add_button("Revert", label="Colors", color="secondary")
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
        # Toggles rather than buttons: these two stay where they are put, and
        # both can be on at once, so the row is `multiple`.
        plot_overlays = server.gui.add_toggle(
            ("Grid", "Zero line"),
            label="Overlays",
            multiple=True,
            initial_value="Grid",
            color="secondary",
        )
        gui_plot = server.gui.add_plotly(
            plot_figure,
            # Twice as wide as it is tall.
            aspect=2.0,
            config={"displayModeBar": False, "staticPlot": True},
        )

    with tabs.add_tab("Actions", icon=leika.Icon.BOLT):
        # The two that show off the panel lead, filled and merged into one
        # block: neighbours in a row are joined unless told otherwise, and the
        # value says which face was pressed. The two that move a file follow,
        # outlined and each on its own row.
        panel_actions = server.gui.add_button(("Notify", "Open modal"))
        upload = server.gui.add_upload_button(
            "Inspect a file",
            mime_type="image/*,.txt,.json",
            icon=leika.Icon.UPLOAD,
            color="secondary",
        )

        # The contents are made when the button is pressed, so the CSV holds
        # the signal as it stood at that moment rather than at startup.
        def signal_csv(event: leika.GuiEvent[Any]) -> bytes:
            buffer = io.StringIO()
            buffer.write("time,signal\n")
            buffer.writelines(f"{x},{y}\n" for x, y in zip(history_t, history_y))
            return buffer.getvalue().encode()

        server.gui.add_download_button(
            "Download signal CSV",
            signal_csv,
            filename="leika-signal.csv",
            icon=leika.Icon.DOWNLOAD,
            color="secondary",
        )
        # The same contents, shown instead of saved: worth a look before it is
        # worth a file. One producer serves both buttons.
        server.gui.add_preview_button(
            "Preview signal CSV",
            signal_csv,
            filename="leika-signal.csv",
            icon=leika.Icon.EYE,
            color="secondary",
        )
        server.gui.add_preview_button(
            "Read the notes",
            NOTES_MD.encode(),
            filename="notes.md",
            icon=leika.Icon.BOOK_OPEN,
            color="secondary",
        )

        # The field as a file: the same frame the pane is showing, encoded
        # when the button is pressed, so the preview is of the animation as
        # it stands rather than as it started.
        def field_png(event: leika.GuiEvent[Any]) -> bytes:
            return png_bytes(
                render_field(
                    state["phase"],
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
            color="secondary",
        )
        # A file on disk rather than bytes made up on the spot -- the path is
        # read when the button is pressed, and its own name is what the
        # preview is titled with.
        server.gui.add_preview_button(
            "Watch the ripple",
            ASSETS / "ripple.mp4",
            icon=leika.Icon.FILM,
            color="secondary",
        )
        # A form: a note is worth reading once it is finished, not at every
        # keystroke. Fields still report every edit; `on_submit` adds the commit.
        with server.gui.add_form(label="Annotation") as annotation:
            # Enter in a single-line text input submits the form, so this row
            # doubles as the fast path: type a title, press Enter.
            note_title = server.gui.add_text("Title", "Interesting spike")
            note_body = server.gui.add_text("Note", "", multiline=True)
            # One at a time, so a note always carries exactly one level.
            note_level = server.gui.add_toggle(
                ("Info", "Warning"), label="Level", color="secondary"
            )
        log = server.gui.add_text(
            None, "_Nothing logged yet._", editable=False, markdown=True, multiline=True
        )
        # The same commit semantics with one field to commit: no popout, no row
        # of its own, just the field wearing a send button. A broadcast is worth
        # sending when it is written, not letter by letter.
        with server.gui.add_mini_form() as broadcast:
            message = server.gui.add_text("Broadcast", "")
        # A list is a stack of text boxes and the whole tuple as its value: the
        # viewer types in one, adds, removes, or drags one somewhere else, and
        # every one of those arrives as the list now reads. Labelled, so it
        # takes the controls column with its label beside the first entry.
        watchlist = server.gui.add_list(
            "Watch for",
            ("phase drift", "edge ringing"),
            hint="Drag an entry to reorder it.",
        )
        watching = server.gui.add_text(None, "", editable=False, markdown=True, multiline=True)
        # The same stack with an answer on each row: the value is the
        # (text, checked) pairs, so a tick arrives with the words it is
        # against -- and stays with them when the entry is dragged elsewhere.
        todo = server.gui.add_checklist(
            "To do",
            (("Sweep the offset", True), "Log the ringing", "Export the run"),
            hint="Drag an entry to reorder it; its tick goes with it.",
        )
        # Frozen, the words are fixed too and all there is to do is work
        # through them, which is the checklist a list cannot be. The rows stop
        # being fields and become what they say.
        preflight = server.gui.add_checklist(
            "Before a run",
            ("Warm up the source", ("Zero the offset", True), "Clear the log"),
            frozen=True,
        )
        progress = server.gui.add_text(None, "", editable=False, markdown=True, multiline=True)

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

    @plot_overlays.on_update
    def _(_) -> None:
        overlays = plot_overlays.value
        plot_figure.update_xaxes(showgrid="Grid" in overlays, zeroline="Zero line" in overlays)
        plot_figure.update_yaxes(showgrid="Grid" in overlays, zeroline="Zero line" in overlays)
        plot_pane.update(plot_figure)
        gui_plot.figure = plot_figure

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

    @panel_actions.on_click
    def _(event: leika.GuiEvent[Any]) -> None:
        # One handler for the row: `value` is the face that was pressed, and a
        # second press of the same one arrives again rather than being
        # swallowed as an unchanged value.
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

    @nudge.on_click
    def _(event: leika.GuiEvent[Any]) -> None:
        step = 0.1 if event.target.value == "Right" else -0.1
        x, y = offset.value
        offset.value = (round(x + step, 2), y)

    # The last few submissions, newest first: enough to show the form doing
    # something, few enough that the tab does not start scrolling.
    entries: deque[str] = deque(maxlen=3)

    @annotation.on_submit
    def _(_) -> None:
        title = note_title.value.strip() or "Untitled"
        body = note_body.value.strip()
        # Stamped at the submit, which is the point of the form: the note is
        # anchored to the moment it was filed, not the moment typing started.
        at = time.monotonic() - state["start"]
        entries.appendleft(
            f"- `t={at:5.1f}s` **{title}** ({note_level.value[0]})"
            + (f" -- {body}" if body else "")
        )
        log.value = "\n".join(entries)
        # Assigning a value pushes it to every client, so the form empties
        # itself for the next note.
        note_title.value = ""
        note_body.value = ""
        server.gui.add_notification("Annotation logged", title, auto_close_seconds=2.0)

    @watchlist.on_update
    def _(_) -> None:
        # Reads the list back as it now stands, whichever of the four ways it
        # was changed -- typed in, added to, removed from, or dragged about.
        kept = [entry.strip() for entry in watchlist.value if entry.strip()]
        watching.value = "" if not kept else "_Watching: " + ", ".join(kept) + "._"

    def show_progress(_: Any = None) -> None:
        # `checked` is the question a checklist is usually asked, without the
        # comprehension over the pairs.
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

    print(f"Open {server.url}")
    frame_interval = 1.0 / 30.0
    last_tick = time.monotonic()
    next_frame = last_tick
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
                    palette.value[0],
                    offset.value,
                    tint.value,
                )
                with server.atomic():
                    field_pane.update(frame)
                    if not pin.value:
                        rows, columns = DETAIL_REGIONS[region.value]
                        detail_pane.update(frame[rows, columns])
                    gui_preview.image = frame[::4, ::4]

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
            surface_figure.data[0].z = surface_height(state["phase"], float(frequency.value))
            surface_pane.update(surface_figure)

            # Sleep to the next 30 Hz deadline rather than for a fixed
            # interval, so frame work does not subtract from the frame rate.
            # After an overrun, restart the schedule instead of bursting.
            next_frame += frame_interval
            delay = next_frame - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_frame = time.monotonic()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
