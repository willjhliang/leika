"""Regenerate the light/dark component screenshots and gallery page.

The registry below supplies both each screenshot and its displayed snippet.
Run ``make gallery`` after visual client changes.
"""

from __future__ import annotations

import argparse
import os
import stat
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "_static" / "gallery"

VIEWPORT = {"width": 960, "height": 700}
# Padding of page around the captured element, in CSS pixels.
SHOT_PAD = 8
# Retina-density captures; the page displays them at CSS size via :width:.
SCALE = 2


@dataclass
class Entry:
    """One gallery component: its docs identity and the code that builds it."""

    slug: str
    title: str
    ref: str  # method name on GuiApi, for the API cross-reference
    code: str
    blurb: str = ""
    # What to capture: a panel row, an open form popout, a dialog, a toast,
    # or the command palette.
    kind: str = "row"
    # Seconds to let the component settle before the shot (plotly ships its
    # renderer to the client on first use).
    settle: float = 0.25
    handles: dict = field(default_factory=dict)


ENTRIES = [
    (
        "Controls",
        [
            Entry(
                slug="slider",
                title="Slider",
                ref="add_slider",
                code="""\
                gui.add_slider(
                    "Speed",
                    min=0.1,
                    max=3.0,
                    step=0.01,
                    initial_value=1.0,
                    marks=((0.1, "slow"), (3.0, "fast")),
                    show_value=True,
                )""",
            ),
            Entry(
                slug="multi-slider",
                title="Multi slider",
                ref="add_multi_slider",
                code="""\
                gui.add_multi_slider(
                    "Plot range", min=-3.0, max=3.0, step=0.1, initial_value=(-1.5, 1.5)
                )""",
            ),
            Entry(
                slug="number",
                title="Number",
                ref="add_number",
                code='gui.add_number("Frequency", initial_value=1.2, min=0.2, max=3.0, step=0.05)',
            ),
            Entry(
                slug="vector2",
                title="Vector2",
                ref="add_vector2",
                code='gui.add_vector2("Offset", initial_value=(0.0, 0.0), step=0.05)',
            ),
            Entry(
                slug="vector3",
                title="Vector3",
                ref="add_vector3",
                code='gui.add_vector3("Position", initial_value=(0.0, 0.0, 0.0), step=0.05)',
            ),
            Entry(
                slug="text",
                title="Text",
                ref="add_text",
                code='gui.add_text("Title", "Phase sweep")',
            ),
            Entry(
                slug="multiline-text",
                title="Multiline text",
                ref="add_text",
                code="""\
                gui.add_text("Notes", "Sweep the gain\\nbefore exporting.", multiline=True, rows=2)""",
            ),
            Entry(
                slug="markdown-text",
                title="Markdown text",
                ref="add_text",
                code="""\
                gui.add_text(
                    None, "**Markdown** rendered as prose.", editable=False, markdown=True
                )""",
            ),
            Entry(
                slug="list",
                title="List",
                ref="add_list",
                code='gui.add_list("Watch for", ("phase drift", "edge ringing"))',
            ),
            Entry(
                slug="checklist",
                title="Checklist",
                ref="add_checklist",
                code="""\
                gui.add_checklist("To do", (("Sweep gain", True), "Log results", "Export frames"))""",
            ),
            Entry(
                slug="frozen-checklist",
                title="Frozen checklist",
                ref="add_checklist",
                code="""\
                gui.add_checklist("Checks", (("Lint", True), ("Types", True), "Browser"), frozen=True)""",
            ),
            Entry(
                slug="checkbox",
                title="Checkbox",
                ref="add_checkbox",
                code='gui.add_checkbox("Animate", initial_value=True)',
            ),
            Entry(
                slug="dropdown",
                title="Dropdown",
                ref="add_dropdown",
                code='gui.add_dropdown("Mode", options=("Fast", "Accurate", "Debug"))',
            ),
            Entry(
                slug="searchable-dropdown",
                title="Searchable dropdown",
                ref="add_dropdown",
                code="""\
                gui.add_dropdown(
                    "Theme", options=("plotly", "plotly_dark", "ggplot2", "seaborn"), searchable=True
                )""",
            ),
            Entry(
                slug="toggle",
                title="Toggle",
                ref="add_toggle",
                code='gui.add_toggle("Pin the view")',
            ),
            Entry(
                slug="toggle-group",
                title="Toggle group",
                ref="add_toggle",
                code='gui.add_toggle(("Ocean", "Magma", "Viridis"), label="Palette")',
            ),
            Entry(
                slug="rgb",
                title="RGB color",
                ref="add_rgb",
                code='gui.add_rgb("Plot line", initial_value=(196, 196, 196))',
            ),
            Entry(
                slug="rgba",
                title="RGBA color",
                ref="add_rgba",
                code='gui.add_rgba("Tint", initial_value=(20, 90, 210, 45))',
            ),
            Entry(
                slug="progress-bar",
                title="Progress bar",
                ref="add_progress_bar",
                code="gui.add_progress_bar(60.0)",
            ),
            Entry(
                slug="divider",
                title="Divider",
                ref="add_divider",
                code="gui.add_divider()",
            ),
            Entry(
                slug="button",
                title="Button",
                ref="add_button",
                code='gui.add_button("Run")',
            ),
            Entry(
                slug="button-group",
                title="Button group",
                ref="add_button",
                code='gui.add_button(("Start", "Stop"), label="Capture")',
            ),
            Entry(
                slug="upload-button",
                title="Upload button",
                ref="add_upload_button",
                code='gui.add_upload_button("Import image", mime_type="image/png", icon=leika.Icon.UPLOAD)',
            ),
            Entry(
                slug="download-button",
                title="Download button",
                ref="add_download_button",
                code="""\
                gui.add_download_button(
                    "Download CSV", b"a,b\\n1,2\\n", filename="data.csv", icon=leika.Icon.DOWNLOAD
                )""",
            ),
            Entry(
                slug="preview-button",
                title="Preview button",
                ref="add_preview_button",
                code="""\
                gui.add_preview_button(
                    "Read notes", b"# Notes\\n", filename="notes.md", icon=leika.Icon.BOOK_OPEN
                )""",
            ),
        ],
    ),
    (
        "Containers and Overlays",
        [
            Entry(
                slug="folder",
                title="Folder",
                ref="add_folder",
                code="""\
                with gui.add_folder("Playback"):
                    gui.add_checkbox("Animate", initial_value=True)
                    gui.add_slider("Speed", min=0.1, max=3.0, step=0.01, initial_value=1.0)""",
            ),
            Entry(
                slug="form",
                title="Form",
                ref="add_form",
                blurb="One row that opens a popout of fields with reset and submit.",
                kind="form",
                code="""\
                with gui.add_form(label="Annotation"):
                    gui.add_text("Label", "")
                    gui.add_dropdown("Severity", options=("Info", "Warning"))""",
            ),
            Entry(
                slug="mini-form",
                title="Mini form",
                ref="add_mini_form",
                blurb="A single field whose send button rides the row.",
                code="""\
                with gui.add_mini_form():
                    gui.add_text("Broadcast", "")""",
            ),
            Entry(
                slug="tab-group",
                title="Tab group",
                ref="add_tab_group",
                code="""\
                tabs = gui.add_tab_group()
                with tabs.add_tab("Signal"):
                    gui.add_slider("Gain", min=0.0, max=2.0, step=0.01, initial_value=1.0)
                with tabs.add_tab("Style"):
                    gui.add_rgb("Plot line", initial_value=(196, 196, 196))""",
            ),
            Entry(
                slug="modal",
                title="Modal",
                ref="add_modal",
                kind="modal",
                code="""\
                with gui.add_modal("Session details"):
                    gui.add_text(None, "Connected for 12 minutes.", editable=False)
                    gui.add_button("Close")""",
            ),
            Entry(
                slug="notification",
                title="Notification",
                ref="add_notification",
                kind="toast",
                code="""\
                gui.add_notification("Export finished", "Wrote 12 files.", auto_close_seconds=None)""",
            ),
            Entry(
                slug="command",
                title="Command",
                ref="add_command",
                blurb="Registered commands appear in the palette (Cmd/Ctrl+K).",
                kind="palette",
                code="""\
                gui.add_command(
                    "Reset view", description="Recenter the workspace", hotkey="R", icon=leika.Icon.REFRESH_CW
                )""",
            ),
        ],
    ),
    (
        "Content",
        [
            Entry(
                slug="image",
                title="Image",
                ref="add_image",
                code="""\
                gradient = np.linspace(0, 255, 640, dtype=np.uint8)
                gui.add_image(np.tile(gradient, (200, 1))[..., None].repeat(3, axis=-1), label="Preview")""",
            ),
            Entry(
                slug="html",
                title="HTML",
                ref="add_html",
                code='gui.add_html("<b>Custom markup</b> rendered as-is")',
            ),
            Entry(
                slug="plotly",
                title="Plotly figure",
                ref="add_plotly",
                code="""\
                import plotly.graph_objects as go

                fig = go.Figure(go.Scatter(y=[1.0, 2.4, 1.6, 3.1]))
                fig.update_layout(margin=dict(l=32, r=8, t=8, b=24))
                gui.add_plotly(fig, aspect=2.0, config={"displayModeBar": False})""",
                settle=4.0,
            ),
        ],
    ),
]


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace a generated page only after its complete contents are durable."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"refusing to replace non-regular gallery page: {path}")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def wait_for_scheme(page, scheme: str) -> None:
    page.emulate_media(color_scheme=scheme)
    page.wait_for_function(
        "scheme => document.documentElement.classList.contains('dark') === (scheme === 'dark')",
        arg=scheme,
        timeout=10_000,
    )


def locate_target(page, entry: Entry):
    """Return the element to capture, driving any open/close interaction."""
    if entry.kind == "row":
        container = page.locator("[data-leika-generated-gui] [data-leika-gui-container]").first
        # Visible children only: an upload button, for instance, leads with a
        # hidden file input.
        row = container.locator(":scope > *:visible")
        row.first.wait_for(state="visible", timeout=10_000)
        count = row.count()
        if count != 1:
            raise SystemExit(f"{entry.slug}: expected 1 rendered component, found {count}")
        return row.first
    if entry.kind == "form":
        # The popout opens over the panel, partly covering its own trigger
        # row; capturing both keeps the row from appearing sliced.
        row = page.locator("[data-leika-generated-gui] [data-leika-gui-container]").first.locator(
            ":scope > *:visible"
        )
        row.first.wait_for(state="visible", timeout=10_000)
        page.locator("[data-leika-form-trigger]").click()
        popover = page.locator("[data-leika-form-popover]")
        popover.wait_for(state="visible", timeout=10_000)
        return [row.first, popover]
    if entry.kind == "modal":
        dialog = page.locator('[data-slot="dialog-content"]')
        dialog.wait_for(state="visible", timeout=10_000)
        return dialog
    if entry.kind == "toast":
        toast = page.locator('[data-slot="toast"]')
        toast.wait_for(state="visible", timeout=10_000)
        return toast
    if entry.kind == "palette":
        page.keyboard.press("ControlOrMeta+k")
        palette = page.locator("[data-leika-command-palette]")
        palette.wait_for(state="visible", timeout=10_000)
        return palette
    raise SystemExit(f"{entry.slug}: unknown kind {entry.kind!r}")


def release_target(page, entry: Entry) -> None:
    """Dismiss whatever `locate_target` opened, so the next entry starts clean."""
    if entry.kind in ("form", "palette"):
        page.keyboard.press("Escape")
    elif entry.kind == "toast":
        page.locator('[data-slot="toast-close"]').click()
        page.locator('[data-slot="toast"]').wait_for(state="detached", timeout=10_000)


# Include overflowing descendant ink, but ignore fixed elements and cap
# invisible hit-area overflow at the configured padding.
_INK_BOX_JS = """
(el, pad) => {
  const r = el.getBoundingClientRect();
  let [x1, y1, x2, y2] = [r.left, r.top, r.right, r.bottom];
  for (const d of el.querySelectorAll("*")) {
    const b = d.getBoundingClientRect();
    if (b.width === 0 || b.height === 0) continue;
    const cs = getComputedStyle(d);
    if (cs.position === "fixed" || cs.visibility === "hidden") continue;
    x1 = Math.min(x1, b.left);
    y1 = Math.min(y1, b.top);
    x2 = Math.max(x2, b.right);
    y2 = Math.max(y2, b.bottom);
  }
  x1 = Math.max(x1, r.left - pad);
  y1 = Math.max(y1, r.top - pad);
  x2 = Math.min(x2, r.right + pad);
  y2 = Math.min(y2, r.bottom + pad);
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}
"""


def capture(page, elements, path: Path) -> tuple[int, int]:
    """Screenshot the elements' combined ink with breathing room.

    Returns the capture's CSS-pixel size.
    """
    if not isinstance(elements, list):
        elements = [elements]
    boxes = [el.evaluate(_INK_BOX_JS, SHOT_PAD) for el in elements]
    x1 = min(b["x"] for b in boxes)
    y1 = min(b["y"] for b in boxes)
    x2 = max(b["x"] + b["width"] for b in boxes)
    y2 = max(b["y"] + b["height"] for b in boxes)
    clip = {
        "x": max(x1 - SHOT_PAD, 0),
        "y": max(y1 - SHOT_PAD, 0),
        "width": (x2 - x1) + 2 * SHOT_PAD,
        "height": (y2 - y1) + 2 * SHOT_PAD,
    }
    page.screenshot(path=str(path), clip=clip)
    return round(clip["width"]), round(clip["height"])


def snippet(entry: Entry) -> str:
    return textwrap.dedent(entry.code)


def display_path(path: Path) -> str:
    """Show repository paths relatively and external paths as given."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def write_page() -> None:
    """Write the raw-HTML gallery grid to ``docs/gallery.md``."""
    doc = ROOT / "docs" / "gallery.md"
    lines = [
        "% Generated by scripts/gallery.py -- edit the registry there and rerun",
        "% `make gallery` (or `--page-only` for markup changes); the",
        "% screenshots and this page are written together.",
        "",
        "# Gallery",
        "",
        "Every GUI component, as the browser renders it; each tile links to",
        "its API reference. `gui` is `server.gui` -- or any",
        "[container](api/gui_handles.rst) such as a folder, tab, or modal,",
        "which accepts the same calls. The figures follow the documentation's",
        "light or dark theme.",
        "",
    ]
    for group, entries in ENTRIES:
        lines += [f"## {group}", "", "```{raw} html", '<div class="gallery-grid">']
        for entry in entries:
            lines += [
                f'<a class="gallery-card" href="api/gui.html#leika.GuiApi.{entry.ref}">',
                '<span class="gallery-media">',
                f'<img class="only-light" src="_static/gallery/{entry.slug}-light.png"'
                f' alt="{entry.title}" loading="lazy">',
                f'<img class="only-dark" src="_static/gallery/{entry.slug}-dark.png"'
                f' alt="{entry.title}" loading="lazy">',
                "</span>",
                '<span class="gallery-caption">',
                f"<span>{entry.title}</span>",
                f"<code>{entry.ref}()</code>",
                "</span>",
                "</a>",
            ]
        lines += ["</div>", "```", ""]
    _atomic_write_text(doc, "\n".join(lines) + "\n")
    print(f"wrote {display_path(doc)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="directory for the captured screenshots",
    )
    parser.add_argument(
        "--page-only",
        action="store_true",
        help="rewrite docs/gallery.md from the registry without recapturing",
    )
    args = parser.parse_args()
    if args.page_only:
        write_page()
        return 0

    args.out.mkdir(parents=True, exist_ok=True)

    import numpy as np
    from playwright.sync_api import sync_playwright

    import leika

    server = leika.Server(host="127.0.0.1", port=0, workspace_id="gallery", verbose=False)
    gui = server.gui
    exec_ns = {"gui": gui, "leika": leika, "np": np}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(
                viewport=VIEWPORT, device_scale_factor=SCALE, reduced_motion="reduce"
            )
            page = context.new_page()
            page.emulate_media(color_scheme="light")
            page.goto(server.url)
            page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
            page.wait_for_function(
                "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
            )
            # Hide panel chrome that borders the captured component.
            page.add_style_tag(
                content="[data-leika-panel-header] { visibility: hidden !important; }"
            )

            for _, entries in ENTRIES:
                for entry in entries:
                    gui.reset()
                    wait_for_scheme(page, "light")
                    exec(snippet(entry), dict(exec_ns))  # noqa: S102 -- our own registry
                    page.wait_for_timeout(int(entry.settle * 1000))
                    # Repaint one mounted target in both themes before dismissal.
                    target = locate_target(page, entry)
                    for scheme in ("light", "dark"):
                        wait_for_scheme(page, scheme)
                        page.wait_for_timeout(150)
                        capture(page, target, args.out / f"{entry.slug}-{scheme}.png")
                    release_target(page, entry)
                    print(f"captured {entry.slug}")
            browser.close()
    finally:
        server.stop()

    if args.out.resolve() == DEFAULT_OUT.resolve():
        write_page()
    else:
        print("skipped docs/gallery.md because --out is not the documentation gallery")
    total = sum(len(entries) for _, entries in ENTRIES)
    print(f"captured {total} components into {display_path(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
