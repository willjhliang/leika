"""End-to-end file-preview dialog tests."""

from __future__ import annotations

import base64
import re
import struct
import time
import zlib
from pathlib import Path
from typing import List

import pytest
from playwright.sync_api import Locator, Page, Route, expect

import leika

from .utils import assert_stable_viewer


def _png(width: int, height: int) -> bytes:
    """A real PNG, so the browser has something it will actually decode."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    header = struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _dialog(page: Page) -> Locator:
    return page.locator('[data-slot="dialog-content"]')


def _press(page: Page, text: str) -> None:
    page.get_by_role("button", name=text).click()


@pytest.fixture()
def preview_page(leika_page: Page, page_errors: list[str]) -> Page:
    del page_errors  # Registers the listener; tests assert on it.
    return leika_page


def test_an_image_opens_in_the_dialog(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_preview_button("Show field", _png(8, 6), filename="field.png")

    _press(preview_page, "Show field")
    image = _dialog(preview_page).locator("img")
    # Header dimensions reserve the image's shape before slower decoders have
    # produced pixels; the popup must never collapse to title-bar height.
    expect(image).to_have_attribute("width", "8")
    expect(image).to_have_attribute("height", "6")
    expect(image).to_be_visible()
    # Decoded, not merely present: a broken object URL still renders an <img>.
    expect(image).to_have_js_property("naturalWidth", 8)
    expect(_dialog(preview_page)).to_contain_text("field.png")
    assert page_errors == []


def test_a_documents_images_are_fetched_beside_it(
    leika_server: leika.Server,
    preview_page: Page,
    page_errors: list[str],
    tmp_path: Path,
) -> None:
    # A path-backed document's relative images are not carried inside the
    # transfer: the server registers each one and the document arrives naming
    # URLs, which the browser fetches like any page's images. The text shows
    # without waiting for a byte of figure data.
    docs = tmp_path / "docs"
    (docs / "figures").mkdir(parents=True)
    (docs / "figures" / "plot.png").write_bytes(_png(8, 6))
    (docs / "notes.md").write_text("# Results\n\n![plot](figures/plot.png)\n")
    leika_server.gui.add_preview_button("Show notes", docs / "notes.md")

    _press(preview_page, "Show notes")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("Results")
    image = dialog.locator(".typeset img")
    expect(image).to_be_visible()
    # Decoded from the asset endpoint, not merely present as a tag.
    expect(image).to_have_js_property("naturalWidth", 8)
    src = image.get_attribute("src")
    assert src is not None and src.startswith("/leika-assets/"), src
    assert page_errors == []


def test_a_markdown_figure_expands_without_moving_its_document(
    leika_server: leika.Server,
    preview_page: Page,
    page_errors: list[str],
    tmp_path: Path,
) -> None:
    """The inline figure keeps its box while a corner opens a nested viewer."""
    (tmp_path / "figure.png").write_bytes(_png(1200, 600))
    before = "\n\n".join(
        f"Opening paragraph {index} keeps the figure below the first frame." for index in range(24)
    )
    after = "\n\n".join(
        f"Closing paragraph {index} keeps the report scrollable." for index in range(12)
    )
    report = tmp_path / "report.md"
    report.write_text(f"# Report\n\n{before}\n\n![Validation curve](figure.png)\n\n{after}\n")

    # Hold the asset so this observes the geometry reserved from its measured
    # header rather than racing the decode on localhost.
    held: List[Route] = []
    holding = True

    def hold(route: Route) -> None:
        if holding:
            held.append(route)
        else:
            route.continue_()

    preview_page.route("**/leika-assets/**", hold)
    leika_server.gui.add_preview_button("Show report", report)
    _press(preview_page, "Show report")

    outer = preview_page.get_by_role("dialog", name="report.md", exact=True)
    expect(outer).to_be_visible()
    expect(outer).to_have_css("transform", "none")
    image = outer.get_by_role("img", name="Validation curve", exact=True)
    expect(image).to_be_attached()
    expand = outer.get_by_role("button", name="Expand image: Validation curve", exact=True)
    expect(expand).to_be_attached()
    expect(expand).to_have_css("opacity", "0")

    geometry = """image => {
        const surface = image.parentElement;
        const paragraph = image.closest("p");
        const box = (element) => {
            const rect = element.getBoundingClientRect();
            return { width: rect.width, height: rect.height };
        };
        return {
            image: box(image),
            surface: box(surface),
            paragraph: box(paragraph),
            expectedImageWidth: Math.min(
                image.closest(".typeset").getBoundingClientRect().width,
                Number.parseFloat(getComputedStyle(paragraph).maxWidth),
            ),
        };
    }"""
    reserved = image.evaluate(geometry)
    assert image.get_attribute("width") == "1200"
    assert image.get_attribute("height") == "600"
    assert image.evaluate("element => element.naturalWidth") == 0
    assert reserved["image"]["width"] == pytest.approx(reserved["expectedImageWidth"], abs=0.1)
    assert reserved["image"]["height"] == pytest.approx(reserved["image"]["width"] / 2, abs=0.1)
    assert reserved["surface"] == reserved["image"]
    assert reserved["paragraph"] == reserved["image"]

    # Bring the lazy image into range while its request is still held. This can
    # materialize deferred Markdown blocks, so take the decode comparison only
    # after that independent layout work has settled.
    image.scroll_into_view_if_needed()
    deadline = time.monotonic() + 5.0
    while not held and time.monotonic() < deadline:
        preview_page.wait_for_timeout(10)
    assert held, "the figure request was supposed to still be in flight"
    preview_page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
    reserved_in_view = image.evaluate(geometry)

    # A route already delivered to this handler stays owned by it. Explicitly
    # release every captured request, and let any request which races the
    # hand-off continue immediately before removing the handler.
    holding = False
    for route in held:
        route.continue_()
    preview_page.unroute("**/leika-assets/**", hold)
    expect(image).to_have_js_property("naturalWidth", 1200)
    preview_page.wait_for_timeout(100)
    assert image.evaluate(geometry) == reserved_in_view, "the figure moved when its pixels arrived"

    image.evaluate(
        """image => {
            const frame = image.closest(".overflow-auto");
            frame.scrollTop += image.getBoundingClientRect().top
                             - frame.getBoundingClientRect().top
                             - frame.clientHeight / 3;
            return frame.scrollTop;
        }"""
    )
    image.hover()
    reading_scroll = image.evaluate('element => element.closest(".overflow-auto").scrollTop')
    assert reading_scroll > 0
    expect(expand).to_have_css("opacity", "1")
    inline_box = image.bounding_box()
    assert inline_box is not None

    address = preview_page.url
    # Settle the control's own delayed hover UI before the real click. Under
    # load, combining the pointer move and press can race WebKit's tooltip mount.
    expand.hover()
    expect(preview_page.locator('[data-slot="tooltip-content"]')).to_be_visible()
    expand.click()
    expect(_dialog(preview_page)).to_have_count(2)
    inner = preview_page.get_by_role("dialog", name="Validation curve", exact=True)
    expect(inner).to_be_visible()
    assert_stable_viewer(inner)
    expect(inner.locator('[data-slot="dialog-title"]')).to_have_text("Validation curve")
    expanded = inner.get_by_role("img", name="Validation curve", exact=True)
    expect(expanded).to_have_js_property("naturalWidth", 1200)
    expanded_box = expanded.bounding_box()
    viewport = preview_page.viewport_size
    assert expanded_box is not None and viewport is not None
    assert expanded_box["width"] > inline_box["width"] + 100
    assert expanded_box["x"] >= 0 and expanded_box["y"] >= 0
    assert expanded_box["x"] + expanded_box["width"] <= viewport["width"] + 1
    assert expanded_box["y"] + expanded_box["height"] <= viewport["height"] + 1
    assert preview_page.url == address

    preview_page.keyboard.press("Escape")
    expect(inner).to_have_count(0)
    expect(outer).to_be_visible()
    assert image.evaluate(
        'element => element.closest(".overflow-auto").scrollTop'
    ) == pytest.approx(reading_scroll, abs=1.0)

    # A tooltip restored with focus must not consume the next Escape.
    preview_page.keyboard.press("Escape")
    expect(outer).to_have_count(0)
    assert page_errors == []


def test_a_linked_markdown_image_keeps_link_and_expand_as_siblings(
    leika_server: leika.Server,
    preview_page: Page,
    page_errors: list[str],
    tmp_path: Path,
) -> None:
    """The link and its sibling expand control remain independent actions."""
    (tmp_path / "linked.png").write_bytes(_png(1200, 600))
    middle = "\n\n".join(
        f"Paragraph {index} separates the link from its destination." for index in range(30)
    )
    report = tmp_path / "links.md"
    report.write_text(
        "# Links\n\n"
        "[![Linked diagram](linked.png)](#destination)\n\n"
        f"{middle}\n\n## Destination\n\nArrived.\n"
    )
    leika_server.gui.add_preview_button("Show links", report)

    _press(preview_page, "Show links")
    outer = preview_page.get_by_role("dialog", name="links.md", exact=True)
    expect(outer).to_be_visible()
    outer_dom = _dialog(preview_page).first
    link = outer.get_by_role("link", name="Linked diagram", exact=True)
    expect(link.locator(":scope > img")).to_have_count(1)
    expect(link.get_by_role("button")).to_have_count(0)
    expand = outer.get_by_role("button", name="Expand image: Linked diagram", exact=True)
    expect(expand).to_have_count(1)

    frame = outer_dom.locator("div.overflow-auto").first
    address = preview_page.url
    start = frame.evaluate("element => element.scrollTop")
    link.get_by_role("img", name="Linked diagram", exact=True).hover()
    expect(expand).to_have_css("opacity", "1")
    expand.click()
    inner = preview_page.get_by_role("dialog", name="Linked diagram", exact=True)
    expect(inner).to_be_visible()
    assert preview_page.url == address
    assert frame.evaluate("element => element.scrollTop") == start

    preview_page.keyboard.press("Escape")
    expect(inner).to_have_count(0)
    expect(outer).to_be_visible()

    link.click()
    expect(preview_page.get_by_role("dialog")).to_have_count(1)
    assert preview_page.url == address
    assert frame.evaluate("element => element.scrollTop") > start
    assert page_errors == []


def test_a_preview_in_view_is_warmed_before_its_press(
    leika_server: leika.Server,
    preview_page: Page,
    page_errors: list[str],
    tmp_path: Path,
) -> None:
    # A preview button on screen asks for its file before anyone presses it:
    # the document and the images it names are all in the browser while the
    # reader is still elsewhere, and nothing has opened to say so.
    docs = tmp_path / "docs"
    (docs / "figures").mkdir(parents=True)
    (docs / "figures" / "plot.png").write_bytes(_png(8, 6))
    (docs / "notes.md").write_text("# Warmed\n\n![plot](figures/plot.png)\n")
    leika_server.gui.add_preview_button("Show warmed", docs / "notes.md")

    # The image arrives in the browser's cache with no press anywhere.
    preview_page.wait_for_function(
        "() => performance.getEntriesByType('resource')"
        ".some((entry) => entry.name.includes('/leika-assets/'))"
    )
    expect(_dialog(preview_page)).not_to_be_visible()

    _press(preview_page, "Show warmed")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("Warmed")
    expect(dialog.locator(".typeset img")).to_have_js_property("naturalWidth", 8)
    assert page_errors == []


def test_text_is_shown_as_itself(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_preview_button(
        "Show readings", b"time,signal\n0,0.5\n", filename="readings.csv"
    )

    _press(preview_page, "Show readings")
    expect(_dialog(preview_page).locator("pre")).to_contain_text("time,signal")
    assert page_errors == []


def test_markdown_is_rendered(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_preview_button(
        "Show notes", b"# Heading\n\nSome **bold** prose.\n", filename="notes.md"
    )

    _press(preview_page, "Show notes")
    dialog = _dialog(preview_page)
    # Rendered, not printed: the hashes became a heading and the stars bold.
    expect(dialog.get_by_role("heading", name="Heading")).to_be_visible()
    expect(dialog.locator("strong")).to_have_text("bold")
    assert page_errors == []


def test_a_markdown_reader_is_a_stable_opaque_surface(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_preview_button(
        "Show stable notes", b"# Heading\n\nSome prose.\n", filename="stable.md"
    )

    _press(preview_page, "Show stable notes")
    dialog = _dialog(preview_page)
    expect(dialog).to_be_visible()
    state = assert_stable_viewer(dialog)
    frame_background = dialog.locator('[data-slot="file-preview-reading-frame"]').evaluate(
        "frame => getComputedStyle(frame).backgroundColor"
    )

    assert {"top-4", "left-0", "translate-x-0", "translate-y-0"}.issubset(state["popupClasses"]), (
        state
    )
    assert "-translate-x-1/2" not in state["popupClasses"], state
    assert "-translate-y-1/2" not in state["popupClasses"], state
    assert frame_background not in {"transparent", "rgba(0, 0, 0, 0)"}, state
    assert page_errors == []


def test_long_markdown_defers_distant_blocks_without_removing_them(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    paragraphs = [f"Paragraph {index} of the report." for index in range(320)]
    source = "\n\n".join(
        ["# Start", "[Jump to the tail](#tail)", *paragraphs, "## Tail", "Last line."]
    )
    leika_server.gui.add_preview_button("Show long notes", source.encode(), filename="long.md")

    _press(preview_page, "Show long notes")
    dialog = _dialog(preview_page)
    frame = dialog.locator('[data-slot="file-preview-reading-frame"]')
    blocks = dialog.locator(".typeset > p")
    expect(blocks).to_have_count(322)
    far_block = blocks.nth(300)
    styles = far_block.evaluate(
        """element => {
          const style = getComputedStyle(element);
          return {
            visibility: style.contentVisibility,
            intrinsicBlockSize: style.containIntrinsicBlockSize,
          };
        }"""
    )
    assert styles["visibility"] == "auto", styles
    assert styles["intrinsicBlockSize"].startswith("auto "), styles

    # The tail has not been conditionally unmounted: native fragment behavior,
    # focus for assistive technology, and in-document search can still find it.
    tail = dialog.get_by_role("heading", name="Tail", exact=True)
    expect(tail).to_be_attached()
    dialog.get_by_role("link", name="Jump to the tail", exact=True).click()
    expect(tail).to_be_focused()
    preview_page.wait_for_function("frame => frame.scrollTop > 0", arg=frame.element_handle())
    assert page_errors == []


def _columns(page: Page, *selectors: str) -> dict[str, dict]:
    """Where each of a viewer's blocks sits inside the dialog.

    Every block is measured in the one pass, because a frame settling around
    contents that are still arriving is a different width from one moment to
    the next, and two widths read a call apart are not comparable.
    """
    return _dialog(page).evaluate(
        """(dialog, selectors) => {
          const outer = dialog.getBoundingClientRect();
          return Object.fromEntries(selectors.map((selector) => {
            const inner = dialog.querySelector(selector).getBoundingClientRect();
            return [selector, {
              dialog: outer.width,
              column: inner.width,
              left: inner.left - outer.left,
              right: outer.right - inner.right,
            }];
          }));
        }""",
        list(selectors),
    )


def _column(page: Page, selector: str) -> dict:
    """Where a viewer's content sits inside the dialog."""
    return _columns(page, selector)[selector]


def test_writing_is_set_in_a_column_and_data_spans_the_width(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # Prose uses a readable column; tabular data uses the full frame.
    leika_server.gui.add_preview_button(
        "Show notes", b"# Heading\n\n" + b"word " * 200, filename="notes.md"
    )
    leika_server.gui.add_preview_button("Show plain", b"word " * 200, filename="notes.txt")
    leika_server.gui.add_preview_button(
        "Show readings", b"time,signal\n0,0.5\n", filename="readings.csv"
    )

    for label, selector in (("Show notes", "h1"), ("Show plain", "pre")):
        _press(preview_page, label)
        expect(_dialog(preview_page)).to_be_visible()
        box = _column(preview_page, selector)
        # A measure, not a width: it is set in characters, so it stays well
        # inside the frame and centred there however wide the window is.
        assert box["column"] < box["dialog"] * 0.75, (label, box)
        assert abs(box["left"] - box["right"]) < 2.0, (label, box)
        assert box["left"] > 40.0, (label, box)
        preview_page.keyboard.press("Escape")
        expect(_dialog(preview_page)).to_have_count(0)

    _press(preview_page, "Show readings")
    data = _column(preview_page, "pre")
    assert data["column"] > data["dialog"] * 0.9, data
    assert page_errors == []


def _document(*blocks: bytes) -> bytes:
    return b"Some prose.\n\n" + b"\n\n".join(blocks) + b"\n"


def _fence(line: bytes) -> bytes:
    return b"```\n" + line + b"\n```"


#: A table of three short columns, and one whose columns cannot all be shown
#: at once however wide the window is.
SMALL_TABLE = b"| when | what | why |\n|---|---|---|\n| a | b | c |"
BIG_TABLE = (
    b"| " + b" | ".join(b"a column heading of some length" for _ in range(8)) + b" |\n"
    b"|" + b"---|" * 8 + b"\n"
    b"| " + b" | ".join(b"and a cell of about that width" for _ in range(8)) + b" |"
)


def test_a_table_is_as_wide_as_its_columns_need_and_nothing_else_is(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A table is read by the column a cell is under and the row it is in, so
    # it is the one block the measure is lifted for -- and lifted is not
    # stretched: what it asks for is what its columns come to. Everything else
    # keeps the measure, a fence included, whose slab would otherwise put an
    # edge in the document at a width nothing else in it shares.
    leika_server.gui.add_preview_button(
        "Show short",
        _document(
            SMALL_TABLE,
            _fence(b"x = 1"),
            # Wider than the measure, so what holds an image back shows in what
            # it renders at rather than only in what it was asked for.
            b"![field](data:image/png;base64," + base64.b64encode(_png(1200, 6)) + b")",
        ),
        filename="short.md",
    )
    leika_server.gui.add_preview_button(
        "Show long",
        _document(BIG_TABLE, _fence(b"x = 1  # " + b"a long line of code " * 8)),
        filename="long.md",
    )

    _press(preview_page, "Show short")
    # Decoded first, so the frame has finished settling around it.
    expect(_dialog(preview_page).locator("img")).to_have_js_property("naturalWidth", 1200)
    short = _columns(preview_page, "p", "table", "pre", "img")
    prose = short["p"]

    assert prose["column"] < prose["dialog"] * 0.75, prose
    # Three short columns are three short columns: the table fits them and
    # stops, rather than spreading them across the window. Centred, like the
    # writing, so the widths a document takes read as one column of it
    # widening and narrowing rather than as blocks that start in two places.
    assert short["table"]["column"] < prose["column"] * 0.5, short["table"]
    assert abs(short["table"]["left"] - short["table"]["right"]) < 2.0, short["table"]
    # The margins of the text, not a cap of its own: a screenshot in a window
    # with room for the whole of it used to be shown as a thumbnail.
    assert abs(short["img"]["column"] - prose["column"]) < 1.0, (short["img"], prose)

    preview_page.keyboard.press("Escape")
    expect(_dialog(preview_page)).to_have_count(0)

    _press(preview_page, "Show long")
    long = _columns(preview_page, "p", "table", "pre")

    # Wider than the writing, since its columns are, and scrolling within the
    # frame once even the frame is not enough for them.
    assert long["table"]["column"] > long["p"]["column"] * 1.25, long
    # A fence keeps the measure whatever it holds, and scrolls the code that
    # does not fit: one edge, in line with the writing, for every fence in
    # the document.
    for name, boxes in (("short", short), ("long", long)):
        fence, text = boxes["pre"], boxes["p"]
        assert abs(fence["column"] - text["column"]) < 1.0, (name, fence, text)
    assert page_errors == []


#: What a README opens with: a contents list of links into the file, and far
#: enough below it that reaching one of them is a scroll rather than a nudge.
CONTENTS_DOC = (
    b"# Notes\n\n- [Setup](#setup)\n- [Results](#results)\n- [Elsewhere](#nowhere)\n\n"
    + b"\n\n".join(b"A paragraph of the opening section." for _ in range(40))
    + b"\n\n## Setup\n\nHow the runs were configured.\n\n"
    + b"\n\n".join(b"A paragraph of the setup section." for _ in range(40))
    + b"\n\n## Results\n\nWhat came of them.\n"
)


def _scroll_top(page: Page) -> float:
    """How far the frame holding the document has been scrolled."""
    return _dialog(page).evaluate(
        """(dialog) => dialog.querySelector(".overflow-auto").scrollTop"""
    )


def test_a_link_to_a_heading_scrolls_the_document_to_it(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A contents list is the first thing in most READMEs and the links in one
    # point back into the same file. The browser's own answer -- put the
    # fragment in the address bar and jump -- is wrong twice over here: the
    # address belongs to the app rather than to the file being read, and there
    # is no id to jump to unless the renderer names the headings.
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOC, filename="notes.md")
    address = preview_page.url

    _press(preview_page, "Show notes")
    dialog = _dialog(preview_page)
    # Exactly, because the dialog's own title is "notes.md" and role-name
    # matching is by substring: warmed documents render at the open, so both
    # headings are on screen at once.
    expect(dialog.get_by_role("heading", name="Notes", exact=True)).to_be_visible()
    assert _scroll_top(preview_page) == 0.0

    # A link the document cannot answer is answered with nothing, rather than
    # with an address that says the reader was taken somewhere.
    dialog.get_by_role("link", name="Elsewhere").click()
    assert _scroll_top(preview_page) == 0.0
    assert preview_page.url == address

    dialog.get_by_role("link", name="Setup").click()
    # Smoothly, so where it lands is a moment later than the click -- and at
    # the top of the frame rather than merely somewhere on screen, the section
    # being what the reader asked to be shown. Its own section is followed by
    # another, so the frame really can put it at the top: the last heading in a
    # file would stop where the document ends however it was scrolled to.
    preview_page.wait_for_function(
        """() => {
          const dialog = document.querySelector('[data-slot="dialog-content"]');
          const frame = dialog.querySelector(".overflow-auto");
          // By its text: the dialog's own title is an h2 as well.
          const heading = [...dialog.querySelectorAll("h2")]
            .find((el) => el.textContent === "Setup");
          const offset = heading.getBoundingClientRect().top
            - frame.getBoundingClientRect().top;
          return offset >= 0 && offset < 40;
        }"""
    )
    expect(dialog.get_by_role("heading", name="Setup")).to_be_in_viewport()
    # The one thing that did not move. A preview is a window onto a file, and
    # the file's own anchors are not the app's address.
    assert preview_page.url == address
    assert page_errors == []


def test_a_link_to_a_heading_finishes_flush_after_deferred_blocks_expand(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    def tall_code_block(section: str, index: int) -> str:
        rows = "\n".join(
            f"{section} block {index:02d}, row {row:02d}: deferred layout has real height"
            for row in range(40)
        )
        return f"```text\n{rows}\n```"

    before = [tall_code_block("opening", index) for index in range(32)]
    after = [tall_code_block("closing", index) for index in range(16)]
    source = "\n\n".join(
        [
            "# Start",
            "[Jump to the tail](#tail)",
            *before,
            "## Tail",
            "The requested section starts here.",
            *after,
        ]
    )
    leika_server.gui.add_preview_button(
        "Show shifting notes", source.encode(), filename="shifting.md"
    )
    address = preview_page.url

    _press(preview_page, "Show shifting notes")
    dialog = _dialog(preview_page)
    expect(dialog).to_be_visible()
    link = dialog.get_by_role("link", name="Jump to the tail", exact=True)
    tail = dialog.get_by_role("heading", name="Tail", exact=True)
    expect(link).to_be_visible()
    expect(tail).to_be_attached()

    # The suite normally asks browsers to reduce motion. This path deliberately
    # exercises the animated carry whose destination can move as content-
    # visibility replaces the distant blocks' estimates with their real size.
    preview_page.emulate_media(reduced_motion="no-preference")
    dialog.evaluate(
        """dialog => {
          const frame = dialog.querySelector(
            '[data-slot="file-preview-reading-frame"]'
          );
          const link = [...dialog.querySelectorAll("a")].find(
            element => element.textContent === "Jump to the tail"
          );
          const tail = [...dialog.querySelectorAll("h2")].find(
            element => element.textContent === "Tail"
          );
          if (!(frame instanceof HTMLElement)
              || !(link instanceof HTMLElement)
              || !(tail instanceof HTMLElement)) {
            throw new Error("anchor regression fixture was not rendered");
          }

          const coordinate = () => tail.getBoundingClientRect().top
            - frame.getBoundingClientRect().top + frame.scrollTop;
          link.addEventListener("click", () => {
            const started = performance.now();
            const initialCoordinate = coordinate();
            let previousScrollTop = frame.scrollTop;
            const probe = {
              done: false,
              initialCoordinate,
              largestShiftWhileScrolling: 0,
            };
            window.__leikaAnchorCarryProbe = probe;

            const sample = now => {
              const scrollTop = frame.scrollTop;
              const shift = Math.abs(coordinate() - initialCoordinate);
              if (Math.abs(scrollTop - previousScrollTop) > 0.25) {
                probe.largestShiftWhileScrolling = Math.max(
                  probe.largestShiftWhileScrolling,
                  shift,
                );
              }
              previousScrollTop = scrollTop;
              if (now - started < 600) {
                requestAnimationFrame(sample);
              } else {
                probe.done = true;
              }
            };
            requestAnimationFrame(sample);
          }, { capture: true, once: true });
        }"""
    )

    link.click()
    preview_page.wait_for_function(
        "() => window.__leikaAnchorCarryProbe?.done === true", timeout=3_000
    )
    probe = preview_page.evaluate("() => window.__leikaAnchorCarryProbe")
    assert probe["largestShiftWhileScrolling"] > 500, probe

    expect(tail).to_be_focused()
    settled = tail.evaluate(
        """tail => {
          const frame = tail.closest('[data-slot="file-preview-reading-frame"]');
          return {
            offset: tail.getBoundingClientRect().top
              - frame.getBoundingClientRect().top,
            runway: frame.scrollHeight - frame.clientHeight - frame.scrollTop,
            frameHeight: frame.clientHeight,
          };
        }"""
    )
    assert abs(settled["offset"]) <= 1, settled
    assert settled["runway"] > settled["frameHeight"], settled
    assert preview_page.url == address
    assert page_errors == []


def _settled_rect(dialog: Locator) -> dict[str, int]:
    """Where the dialog is once it has stopped moving.

    A dialog opens and resizes through animations, and a rect read while one
    is still running is a frame of it rather than the answer.
    """
    return dialog.evaluate(
        """async (el) => {
          await Promise.all(
            el.getAnimations().map((animation) => animation.finished.catch(() => {}))
          );
          const box = el.getBoundingClientRect();
          return {
            x: Math.round(box.x), y: Math.round(box.y),
            width: Math.round(box.width), height: Math.round(box.height),
          };
        }"""
    )


def _opened_size(page: Page, label: str) -> tuple[int, int]:
    """The dialog's size once it has finished opening."""
    _press(page, label)
    dialog = _dialog(page)
    expect(dialog).to_be_visible()
    rect = _settled_rect(dialog)
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    return (rect["width"], rect["height"])


def test_a_document_preview_opens_the_same_size_whatever_the_file_holds(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A document has no size of its own, so the frame is the viewer's: a
    # one-line log and a thousand-line one open identically, and nothing
    # resizes as the content lands. Media is the exception, and has its own
    # test below.
    leika_server.gui.add_preview_button("Show one line", b"t,v\n", filename="tiny.csv")
    leika_server.gui.add_preview_button(
        "Show many lines", ("t,v\n" * 500).encode(), filename="long.csv"
    )
    leika_server.gui.add_preview_button("Show weights", b"\x00\x01", filename="weights.bin")
    leika_server.gui.add_preview_button("Show notes", b"# Hi\n", filename="notes.md")
    leika_server.gui.add_preview_button(
        "Show long notes", b"# Hi\n\n" + b"word " * 500, filename="long.md"
    )
    leika_server.gui.add_preview_button("Show plain", b"a line\n", filename="notes.txt")

    sizes = {
        label: _opened_size(preview_page, label)
        for label in (
            "Show one line",
            "Show many lines",
            "Show weights",
            "Show notes",
            "Show long notes",
            "Show plain",
        )
    }

    fitted = {sizes[label] for label in ("Show one line", "Show many lines", "Show weights")}
    reading = {sizes[label] for label in ("Show notes", "Show long notes", "Show plain")}
    assert len(fitted) == 1, sizes
    assert len(reading) == 1, sizes
    # Writing is read by scrolling, so its frame takes the height the window
    # has rather than the share a fitted card needs.
    assert reading.pop()[1] > fitted.pop()[1], sizes
    assert page_errors == []


def test_a_picture_preview_is_the_shape_of_the_picture(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    """Media opens at its own size, which is the whole difference from a document.

    A document's popup is a frame picked in advance; a picture's popup is the
    picture. Fitting a portrait into the document's frame left it marooned
    between two columns of empty dialog, which is what this rules out: the two
    shapes must not open the same box, and the taller picture must open the
    taller and narrower one.
    """
    leika_server.gui.add_preview_button("Show wide", _png(600, 200), filename="wide.png")
    leika_server.gui.add_preview_button("Show tall", _png(200, 600), filename="tall.png")
    leika_server.gui.add_preview_button("Show notes", b"# Hi\n", filename="notes.md")

    wide = _opened_size(preview_page, "Show wide")
    tall = _opened_size(preview_page, "Show tall")
    document = _opened_size(preview_page, "Show notes")

    assert wide != tall, (wide, tall)
    assert tall[0] < wide[0], (wide, tall)
    assert tall[1] > wide[1], (wide, tall)
    # Neither is the frame a document gets, which is the shape both used to be
    # forced into.
    assert wide[0] != document[0], (wide, document)
    assert tall[0] != document[0], (tall, document)
    assert page_errors == []


def test_a_document_is_set_larger_than_the_panel_sets_it(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The same markdown, in a panel row and in a preview. The document takes
    # its size from whatever shows it: the panel's own size in a row, and a
    # reading size in a dialog that has nothing else in it.
    leika_server.gui.add_text(
        "Notes",
        "# Heading\n\nSome prose.\n",
        editable=False,
        markdown=True,
        multiline=True,
    )
    leika_server.gui.add_preview_button(
        "Show notes", b"# Heading\n\nSome prose.\n", filename="notes.md"
    )

    def size_of(scope: Locator, selector: str) -> float:
        return scope.locator(selector).evaluate("(el) => parseFloat(getComputedStyle(el).fontSize)")

    panel = preview_page.locator("[data-leika-text-markdown]")
    expect(panel.locator("h1")).to_be_visible(timeout=15_000)
    panel_body = size_of(panel, "p")
    panel_heading = size_of(panel, "h1")
    # The panel's text size, not the browser's default.
    assert panel_body < 16.0, panel_body

    _press(preview_page, "Show notes")
    dialog = _dialog(preview_page)
    expect(dialog).to_be_visible()
    preview_body = size_of(dialog, "p")
    preview_heading = size_of(dialog, "h1")

    assert preview_body > panel_body
    # Everything scales together: the heading keeps its ratio to the body.
    assert preview_heading / preview_body == pytest.approx(panel_heading / panel_body, rel=0.01)
    assert page_errors == []


def test_a_file_with_no_viewer_says_what_it_is(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_preview_button("Show weights", b"\x00\x01\x02\x03", filename="weights.bin")

    _press(preview_page, "Show weights")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("no viewer for this kind of file")
    expect(dialog).to_contain_text("4 B")
    assert page_errors == []


def test_the_corner_downloads_the_file_being_shown(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_preview_button("Show weights", b"\x00\x01\x02\x03", filename="weights.bin")
    leika_server.gui.add_preview_button("Show readings", b"t,v\n0,1\n", filename="readings.csv")

    for press, filename in (("Show weights", "weights.bin"), ("Show readings", "readings.csv")):
        _press(preview_page, press)
        corner = _dialog(preview_page).get_by_role("link", name=f"Download {filename}")
        with preview_page.expect_download() as download_info:
            corner.click()
        assert download_info.value.suggested_filename == filename
        preview_page.keyboard.press("Escape")
        expect(_dialog(preview_page)).to_have_count(0)
    assert page_errors == []


def test_a_file_on_disk_keeps_its_name_and_closes_cleanly(
    leika_server: leika.Server,
    preview_page: Page,
    tmp_path: Path,
    page_errors: list[str],
) -> None:
    source = tmp_path / "capture.png"
    source.write_bytes(_png(4, 4))
    leika_server.gui.add_preview_button("Show capture", source)

    _press(preview_page, "Show capture")
    expect(_dialog(preview_page)).to_contain_text("capture.png")
    preview_page.keyboard.press("Escape")
    expect(_dialog(preview_page)).to_have_count(0)
    assert page_errors == []


def test_escape_closes_a_hinted_preview_every_time_and_focuses_nothing(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A hinted button is a tooltip trigger, and tooltips are what once made
    # Escape unreliable: closing with Escape put focus back on the button,
    # whose tooltip opened, and the next dialog's auto-focused download corner
    # then opened *its* tooltip -- which swallowed the next Escape, so every
    # other close needed two presses. The dialog now takes focus on its frame
    # rather than its corner buttons, and leaves focus alone on close, so no
    # tooltip ever opens by itself and one Escape means one closed preview.
    leika_server.gui.add_preview_button(
        "Show notes", b"# Hi\n", filename="notes.md", hint="The project's docs"
    )

    for _ in range(4):
        _press(preview_page, "Show notes")
        expect(_dialog(preview_page)).to_be_visible()
        # The frame itself takes focus once the dialog settles -- not the
        # download corner, whose tooltip is what used to open.
        preview_page.wait_for_function(
            """() => document.activeElement ===
                 document.querySelector('[data-slot="dialog-content"]')"""
        )
        preview_page.keyboard.press("Escape")
        expect(_dialog(preview_page)).to_have_count(0)
        # Closing is the end of reading, not a step somewhere: nothing is
        # focused afterwards, so no ring and no tooltip appear in the dock.
        assert preview_page.evaluate("document.activeElement === document.body")
    assert page_errors == []


def test_an_oversize_file_says_so_instead_of_opening(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_preview_button(
        "Show capture", b"x" * 4096, filename="capture.bin", max_bytes=1024
    )

    _press(preview_page, "Show capture")
    toast = preview_page.locator('[data-slot="toast"]')
    expect(toast).to_contain_text("Too large to preview")
    expect(_dialog(preview_page)).to_have_count(0)
    assert page_errors == []


def test_a_preview_fills_the_window_and_stays_that_way(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    """The full-window toggle, and the memory that outlives the preview.

    Kept per preview rather than for all of them. Filling the window is a
    decision about one thing being too small to read at the size it opens, and
    the next file is a different thing: enlarging a picture must not enlarge
    the document opened after it. Closing is not a retraction either -- the
    same file, opened again, comes back the way it was left.
    """
    leika_server.gui.add_preview_button("Show tall", _png(200, 600), filename="tall.png")
    leika_server.gui.add_preview_button("Show notes", b"# Hi\n", filename="notes.md")

    dialog = _dialog(preview_page)
    viewport = preview_page.viewport_size
    assert viewport is not None

    _press(preview_page, "Show tall")
    expect(dialog).to_be_visible()
    windowed = _settled_rect(dialog)
    assert windowed["width"] < viewport["width"]

    # Order in the corner: reload, download, full window, close. Left to right
    # that is the two things to do with the file, then what to do with the
    # popup, and how to leave.
    corners = dialog.evaluate(
        """el => [...el.querySelectorAll('a, button')]
             .map(node => ({
                 label: node.getAttribute('aria-label') ?? node.textContent.trim(),
                 right: node.getBoundingClientRect().right,
             }))"""
    )
    by_label = {corner["label"]: corner["right"] for corner in corners}
    download = next(right for label, right in by_label.items() if label.startswith("Download"))
    assert by_label["Reload"] < download, by_label
    assert download < by_label["Fill the window"] < by_label["Close"], by_label

    preview_page.get_by_role("button", name="Fill the window").click()
    expect(preview_page.get_by_role("button", name="Exit full window")).to_be_visible()
    expect(dialog).to_have_attribute("data-preview-fullscreen", "true")
    full = _settled_rect(dialog)
    assert (full["x"], full["y"]) == (0, 0), full
    assert full["width"] == viewport["width"], full
    assert full["height"] == viewport["height"], full

    # The whole picture is still on screen: the popup is the window's shape,
    # the picture is not, so it is fitted rather than cropped or overflowed.
    image = dialog.locator("img")
    assert image.evaluate(
        """el => {
          const box = el.getBoundingClientRect();
          return box.height <= window.innerHeight + 1 && box.width <= window.innerWidth + 1;
        }"""
    )

    # Another file is untouched by it: this button was never pressed.
    preview_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _press(preview_page, "Show notes")
    expect(dialog).to_be_visible()
    expect(dialog).not_to_have_attribute("data-preview-fullscreen", "true")

    # And the picture is still the way it was left, which is the memory half.
    preview_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _press(preview_page, "Show tall")
    expect(dialog).to_have_attribute("data-preview-fullscreen", "true")

    # Backing out of it is remembered just as well, and again only for this
    # one: the document opened in between never changed either way.
    preview_page.get_by_role("button", name="Exit full window").click()
    expect(dialog).not_to_have_attribute("data-preview-fullscreen", "true")
    preview_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _press(preview_page, "Show tall")
    expect(dialog).not_to_have_attribute("data-preview-fullscreen", "true")
    reopened = _settled_rect(dialog)
    assert reopened["width"] == windowed["width"], (reopened, windowed)
    assert page_errors == []


def test_preview_toggles_survive_page_refresh(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    """Fullscreen and contents choices persist beyond the current page."""
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOCUMENT, filename="notes.md")
    dialog = _dialog(preview_page)

    _press(preview_page, "Show notes")
    preview_page.get_by_role("button", name="Fill the window").click()
    dialog.get_by_role("button", name="Show contents").click()
    expect(dialog).to_have_attribute("data-preview-fullscreen", "true")
    expect(_contents(preview_page)).to_be_visible()

    preview_page.reload()
    _press(preview_page, "Show notes")
    expect(dialog).to_have_attribute("data-preview-fullscreen", "true")
    expect(dialog.get_by_role("button", name="Hide contents")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(_contents(preview_page)).to_be_visible()

    # Returning either toggle to its default removes that preview from the
    # persisted set; the defaults therefore survive a reload too.
    preview_page.get_by_role("button", name="Exit full window").click()
    dialog.get_by_role("button", name="Hide contents").click()
    preview_page.reload()
    _press(preview_page, "Show notes")
    expect(dialog).not_to_have_attribute("data-preview-fullscreen", "true")
    expect(dialog.get_by_role("button", name="Show contents")).to_have_attribute(
        "aria-pressed", "false"
    )
    expect(_contents(preview_page)).to_have_count(0)
    assert page_errors == []


def test_a_preview_takes_the_file_again_when_it_is_rewritten(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str], tmp_path: Path
) -> None:
    """A preview of a file follows that file, with nothing pressed.

    What it is for: a document being written, or a log being appended to,
    watched from the browser rather than reopened at every save.
    """
    document = tmp_path / "notes.md"
    document.write_text("# Results\n\nStill running.\n")
    leika_server.gui.add_preview_button("Show notes", document)

    _press(preview_page, "Show notes")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("Still running.")

    document.write_text("# Results\n\nConverged at step 4000.\n")
    expect(dialog).to_contain_text("Converged at step 4000.")
    expect(dialog).not_to_contain_text("Still running.")

    # Still the one dialog, opened once. A reload that reopened the preview
    # would be a new transfer, and everything about the popup -- its place in
    # the document, its full-window state -- would be reset with it.
    expect(dialog).to_have_count(1)
    assert page_errors == []


def test_a_rewritten_document_keeps_the_readers_place(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str], tmp_path: Path
) -> None:
    # The file arriving again must not scroll a long document back to the top:
    # what changed is usually the end of it, and the reader is somewhere in
    # the middle.
    document = tmp_path / "log.txt"
    body = "\n".join(f"step {i:04d}  loss=0.5" for i in range(400))
    document.write_text(body)
    leika_server.gui.add_preview_button("Show log", document)

    _press(preview_page, "Show log")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("step 0399")

    frame = dialog.locator("div.overflow-auto").first
    frame.evaluate("el => { el.scrollTop = 600; }")
    document.write_text(body + "\nstep 0400  loss=0.4")

    expect(dialog).to_contain_text("step 0400")
    assert frame.evaluate("el => el.scrollTop") == 600
    assert page_errors == []


def test_reload_asks_the_button_for_the_file_again(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # Contents that are computed cannot be watched -- what the function would
    # return next is only knowable by running it, and nothing but a press may
    # do that. The corner button is that press.
    presses = {"count": 0}

    def content(_: leika.GuiEvent) -> bytes:
        presses["count"] += 1
        return f"# Reading {presses['count']}\n".encode()

    leika_server.gui.add_preview_button("Show reading", content, filename="reading.md")

    _press(preview_page, "Show reading")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("Reading 1")

    dialog.get_by_role("button", name="Reload").click()
    expect(dialog).to_contain_text("Reading 2")
    expect(dialog).to_have_count(1)
    assert page_errors == []


def test_a_reload_waits_for_the_readers_scroll_to_end(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    """The actual reading frame owns native scroll start and end events."""
    presses = {"count": 0}

    def content(_: leika.GuiEvent) -> bytes:
        presses["count"] += 1
        return f"# Reading {presses['count']}\n".encode()

    leika_server.gui.add_preview_button("Show reading", content, filename="reading.md")
    _press(preview_page, "Show reading")

    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("Reading 1")
    frame = dialog.locator('[data-slot="file-preview-reading-frame"]')
    assert frame.evaluate("element => 'onscrollend' in element")

    def reload_during_scroll(displayed: int) -> None:
        next_reading = displayed + 1
        # A synthetic start without moving the frame cannot cause the browser
        # to emit its own completion event. This leaves the gate open long
        # enough to prove that an arrived replacement is held, without racing
        # a wheel or compositor animation in CI.
        frame.dispatch_event("scroll")
        dialog.get_by_role("button", name="Reload").click()
        deadline = time.monotonic() + 5.0
        while presses["count"] < next_reading and time.monotonic() < deadline:
            preview_page.wait_for_timeout(10)
        assert presses["count"] == next_reading
        preview_page.wait_for_timeout(250)
        expect(dialog).to_contain_text(f"Reading {displayed}")
        expect(dialog).not_to_contain_text(f"Reading {next_reading}")

        frame.dispatch_event("scrollend")
        expect(dialog).to_contain_text(f"Reading {next_reading}")
        expect(dialog).not_to_contain_text(f"Reading {displayed}")

    reload_during_scroll(1)
    reload_during_scroll(2)
    assert page_errors == []


#: How long one turn of the reload icon takes -- Tailwind's `animate-spin`,
#: which is what the icon is spun with. Named here only so the floor below
#: reads as the period it is, and not as a number somebody picked.
_SPIN_PERIOD_S = 1.0


def test_a_pressed_reload_finishes_the_turn_it_started(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The spin says the press was heard, and a press is nearly always heard
    # faster than the eye reads a spin: the file is local, so the answer is
    # back within a frame or two and the icon would stop a few degrees from
    # where it began. That is a twitch, and a twitch reads as the button
    # failing rather than as the file arriving. The turn under way finishes
    # first, however early the answer lands.
    leika_server.gui.add_preview_button(
        "Show reading", lambda _: b"# Reading\n", filename="reading.md"
    )

    _press(preview_page, "Show reading")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("Reading")

    icon = dialog.locator("[data-leika-preview-reload] svg")
    spinning = re.compile(r"\banimate-spin\b")
    started = time.monotonic()
    dialog.get_by_role("button", name="Reload").click()
    expect(icon).to_have_class(spinning)

    # Waits out the spin rather than timing it: what is asserted is the floor
    # a whole turn puts under it, which a slow machine can only raise.
    expect(icon).not_to_have_class(spinning)
    assert time.monotonic() - started >= _SPIN_PERIOD_S * 0.9
    assert page_errors == []


def test_a_file_a_script_sent_has_nothing_to_reload(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # `send_file_preview` comes from code, not from a component: there is no
    # button in the panel to go back to, so the dialog does not offer to.
    leika_server.gui.add_button("Send it").on_click(
        lambda event: event.client.send_file_preview("sent.md", b"# Sent\n")
    )

    _press(preview_page, "Send it")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text("Sent")
    expect(dialog.get_by_role("button", name="Reload")).to_have_count(0)
    # The rest of the corner is unaffected: the file is still here to save.
    expect(dialog.get_by_role("link", name="Download sent.md")).to_be_visible()
    assert page_errors == []


_FILLER = "Prose that is here to make the document longer than the frame.\n\n" * 12

CONTENTS_DOCUMENT = f"""# Training report

{_FILLER}
## Setup

{_FILLER}
### Seeds

Every configuration was given the same one.

## Results

{_FILLER}
##### An aside

Too deep for the list: it is four levels under the shallowest heading here.
""".encode()


def _contents(page: Page) -> Locator:
    return _dialog(page).locator("[data-leika-document-contents]")


def _show_contents(page: Page) -> Locator:
    """Stand the contents list up, and hand back the list.

    Down by default: a document opens to be read from where it starts, and a
    column of links is what a reader asks for once they want to move around
    inside the file rather than read down it.
    """
    _dialog(page).get_by_role("button", name="Show contents").click()
    return _contents(page)


def _settle(page: Page) -> None:
    """Wait out the dialog's opening before measuring anything in it.

    It opens by scaling up, so a rect read during that is a frame of the box
    rather than the box -- and a scroll computed from one lands short by
    however much of the zoom was left, which is a test failing for a reason
    that has nothing to do with what it is testing.
    """
    _dialog(page).evaluate(
        """async (el) => {
          await Promise.all(
            el.getAnimations({subtree: true})
              .map((animation) => animation.finished.catch(() => {}))
          );
        }"""
    )


def _group_gaps(page: Page) -> tuple[float, float]:
    """How much room there is either side of the writing AND its list."""
    _settle(page)
    gaps = _dialog(page).evaluate(
        """(el) => {
          const frame = el.querySelector('div.overflow-auto').getBoundingClientRect();
          const text = el.querySelector('.typeset > p').getBoundingClientRect();
          const list = el.querySelector('[data-leika-document-contents]')
                         .getBoundingClientRect();
          return [text.left - frame.left, frame.right - list.right];
        }"""
    )
    return (gaps[0], gaps[1])


def _writing_gaps(page: Page) -> tuple[float, float]:
    """How much room there is either side of the column of writing."""
    _settle(page)
    gaps = _dialog(page).evaluate(
        """(el) => {
          const frame = el.querySelector('div.overflow-auto').getBoundingClientRect();
          const text = el.querySelector('.typeset > p').getBoundingClientRect();
          return [text.left - frame.left, frame.right - text.right];
        }"""
    )
    return (gaps[0], gaps[1])


def test_a_document_lists_its_own_contents_beside_it(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    """The contents list: what is in it, and what following one does."""
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOCUMENT, filename="notes.md")

    _press(preview_page, "Show notes")
    # Nothing in the margin until the corner button is pressed.
    expect(_contents(preview_page)).to_have_count(0)
    contents = _show_contents(preview_page)
    expect(contents).to_be_visible()

    # Three levels down from the shallowest heading, and no further: a list of
    # every subsection is the document again, in outline.
    expect(contents.get_by_role("link")).to_have_text(
        ["Training report", "Setup", "Seeds", "Results"]
    )

    # In the right-hand margin: past the writing, not before it.
    _settle(preview_page)
    assert _dialog(preview_page).evaluate(
        """el => {
             const list = el.querySelector('[data-leika-document-contents]');
             const text = el.querySelector('.typeset > p');
             return list.getBoundingClientRect().left
                    >= text.getBoundingClientRect().right;
           }"""
    )

    frame = _dialog(preview_page).locator("div.overflow-auto").first
    assert frame.evaluate("el => el.scrollTop") == 0
    address = preview_page.url

    contents.get_by_role("link", name="Results").click()
    # Carried, and by the same code that carries a link written in the file:
    # the document scrolls and the app's address is untouched.
    expect(_dialog(preview_page)).to_be_visible()
    preview_page.wait_for_function(
        "() => document.querySelector('[data-slot=dialog-content] div.overflow-auto').scrollTop > 0"
    )
    assert preview_page.url == address

    # And the list stays where it is while the document moves under it.
    assert (
        contents.evaluate(
            "el => Math.round(el.getBoundingClientRect().top"
            " - el.closest('div.overflow-auto').getBoundingClientRect().top)"
        )
        == 0
    )
    assert page_errors == []


def test_the_writing_and_its_contents_are_centred_together(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # What is being read decides what is centred. With the list down that is
    # the writing, and it sits in the middle of the frame; with the list up it
    # is the pair of them, so the writing steps left by half of what the list
    # takes rather than staying put with the list hung off the edge.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOCUMENT, filename="notes.md")

    _press(preview_page, "Show notes")
    expect(_dialog(preview_page)).to_contain_text("Training report")
    left, right = _writing_gaps(preview_page)
    assert abs(left - right) < 2.0, (left, right)

    expect(_show_contents(preview_page)).to_be_visible()
    outer_left, outer_right = _group_gaps(preview_page)
    assert abs(outer_left - outer_right) < 2.0, (outer_left, outer_right)

    # And the writing really did move over: the list is not hanging in a
    # margin that was already empty.
    shifted, _ = _writing_gaps(preview_page)
    assert shifted < left - 50.0, (shifted, left)
    assert page_errors == []


def test_a_narrow_preview_keeps_its_width_for_the_document(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # There is no margin to put a list in, so there is no list. The document
    # gets the width, which is what it was going to be shown at anyway.
    preview_page.set_viewport_size({"width": 900, "height": 800})
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOCUMENT, filename="notes.md")

    _press(preview_page, "Show notes")
    expect(_dialog(preview_page)).to_contain_text("Training report")
    # Asked for and still not given: the button is offered on the strength of
    # the file's headings, and the room is a separate question that CSS
    # answers.
    expect(_show_contents(preview_page)).to_be_hidden()

    # Widen the window and it appears, without the preview being reopened or
    # asked again.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    expect(_contents(preview_page)).to_be_visible()
    assert page_errors == []


def test_a_document_in_the_panel_has_no_contents_column(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A panel row is the width of a panel: there is no margin there to put a
    # list in, and asking for one is a decision the preview makes alone.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_text(
        None, CONTENTS_DOCUMENT.decode(), editable=False, markdown=True, multiline=True
    )

    expect(preview_page.get_by_role("heading", name="Training report")).to_be_visible()
    assert preview_page.locator("[data-leika-document-contents]").count() == 0
    assert page_errors == []


def _marked(page: Page) -> list[str]:
    """The contents entries wearing the mark. Exactly one, always."""
    return _contents(page).locator("a[aria-current]").all_inner_texts()


def test_the_contents_marks_the_section_being_read(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    """The entry for the section at the top of the view, marked as you go."""
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOCUMENT, filename="notes.md")

    _press(preview_page, "Show notes")
    expect(_show_contents(preview_page)).to_be_visible()
    _settle(preview_page)
    frame = _dialog(preview_page).locator("div.overflow-auto").first

    # At the top of a document, before any heading has been scrolled past, the
    # reader is in its first section.
    assert _marked(preview_page) == ["Training report"]

    # Scrolled until the next heading is at the top of the frame, the mark is
    # on it -- and off the one before.
    setup = _dialog(preview_page).get_by_role("heading", name="Setup")
    frame.evaluate(
        """(el, heading) => {
             el.scrollTop += heading.getBoundingClientRect().top
                             - el.getBoundingClientRect().top;
           }""",
        setup.element_handle(),
    )
    expect(_contents(preview_page).get_by_role("link", name="Setup")).to_have_attribute(
        "aria-current", "true"
    )
    assert _marked(preview_page) == ["Setup"]

    # The rule down the left of the entry is marked with it. It is the part of
    # the mark that can be seen without reading anything.
    rules = _contents(preview_page).evaluate(
        """el => {
             const colour = (link) => getComputedStyle(
               link.closest('li')).borderLeftColor;
             return {
               marked: colour(el.querySelector('a[aria-current]')),
               rest: colour(el.querySelector('a:not([aria-current])')),
             };
           }"""
    )
    assert rules["marked"] != rules["rest"], rules

    # Following an entry marks the section it lands in, which is the same rule
    # answering the same question: what is at the top of the view now.
    _contents(preview_page).get_by_role("link", name="Results").click()
    expect(_contents(preview_page).get_by_role("link", name="Results")).to_have_attribute(
        "aria-current", "true"
    )

    # And back where it started, so the mark is not a one-way trip.
    frame.evaluate("el => { el.scrollTop = 0; }")
    expect(_contents(preview_page).get_by_role("link", name="Training report")).to_have_attribute(
        "aria-current", "true"
    )
    assert page_errors == []


def test_a_section_the_scroll_cannot_reach_is_still_marked(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A document whose last sections are shorter than the frame runs out of
    # scroll before their headings reach the top of it. The mark must not be
    # left on a section that has gone off the screen, so at the bottom the
    # question is asked of what is visible instead.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    document = (
        f"# Report\n\n{_FILLER}## Long middle\n\n{_FILLER}"
        "## Nearly the end\n\nOne line.\n\n## The end\n\nAnd one more.\n"
    ).encode()
    leika_server.gui.add_preview_button("Show notes", document, filename="notes.md")

    _press(preview_page, "Show notes")
    expect(_show_contents(preview_page)).to_be_visible()
    _settle(preview_page)
    frame = _dialog(preview_page).locator("div.overflow-auto").first
    frame.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    # The mark is measured on an animation frame, so it lands a beat after the
    # scroll rather than with it. There is no particular entry to wait for --
    # which one is right is what this is asking -- so it is a wait for the
    # measuring to have happened at all.
    preview_page.wait_for_timeout(300)

    marked = _contents(preview_page).locator("a[aria-current]")
    expect(marked).to_have_count(1)
    # Whatever it landed on, it is on the screen -- which is the whole rule.
    assert marked.evaluate(
        """el => {
             const frame = el.closest('div.overflow-auto').getBoundingClientRect();
             const id = 'user-content-' + el.getAttribute('href').slice(1);
             const heading = document.getElementById(id).getBoundingClientRect();
             return heading.top >= frame.top - 1 && heading.top < frame.bottom;
           }"""
    ), marked.inner_text()
    assert page_errors == []


def test_a_document_that_fits_marks_its_first_section(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A document shorter than the frame is scrolled to its end from the
    # moment it opens, by the arithmetic -- but the reader is at the top of
    # it, and the top of it is the first section. Getting this wrong marked
    # the second entry of every short file.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button(
        "Show notes",
        b"# Report\n\nOne paragraph.\n\n## Files\n\nAnd one more.\n",
        filename="notes.md",
    )

    _press(preview_page, "Show notes")
    expect(_show_contents(preview_page)).to_be_visible()
    _settle(preview_page)
    preview_page.wait_for_timeout(300)
    assert _marked(preview_page) == ["Report"]
    assert page_errors == []


def _contents_offset(page: Page) -> dict[str, float]:
    """Where the contents sit relative to the document, and to the frame."""
    _settle(page)
    return _dialog(page).evaluate(
        """el => {
             const frame = el.querySelector('div.overflow-auto').getBoundingClientRect();
             const doc = el.querySelector('.typeset').getBoundingClientRect();
             const list = el.querySelector('[data-leika-document-contents]')
                            .getBoundingClientRect();
             return {
               fromDocument: list.left - doc.right,
               fromFrame: frame.right - list.right,
             };
           }"""
    )


def test_the_contents_hang_off_the_document_not_the_window(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The list is a list of what is beside it, so it stays beside it. Sized
    # from the frame instead, it was pinned to the frame's edge -- and filling
    # the window walked it another hundred pixels away from the document while
    # the reader watched.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOCUMENT, filename="notes.md")

    _press(preview_page, "Show notes")
    expect(_show_contents(preview_page)).to_be_visible()
    windowed = _contents_offset(preview_page)

    preview_page.get_by_role("button", name="Fill the window").click()
    expect(_dialog(preview_page)).to_have_attribute("data-preview-fullscreen", "true")
    full = _contents_offset(preview_page)

    assert abs(full["fromDocument"] - windowed["fromDocument"]) < 1.0, (windowed, full)
    # And it really is a wider window: the frame's own edge moved well away.
    assert full["fromFrame"] - windowed["fromFrame"] > 50.0, (windowed, full)
    assert page_errors == []


def test_the_contents_stand_a_gutter_off_the_writing(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The space between the writing and its list is the space the popup
    # already uses: a block that takes the full width -- a table -- stops that
    # same distance short of the popup's edge, being the dialog's padding and
    # the reading column's together. One gutter width on the surface, rather
    # than a second one invented for the list.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    # Wide enough that it really does take the full width: a table narrower
    # than the measure is centred in the column and insets itself.
    row = "| " + " | ".join(f"a column heading {index}" for index in range(8)) + " |\n"
    table = row + "|" + "---|" * 8 + "\n" + row * 3
    leika_server.gui.add_preview_button(
        "Show notes", CONTENTS_DOCUMENT + f"\n{table}\n".encode(), filename="notes.md"
    )

    _press(preview_page, "Show notes")
    expect(_show_contents(preview_page)).to_be_visible()
    _settle(preview_page)
    measured = _dialog(preview_page).evaluate(
        """el => {
             const popup = el.getBoundingClientRect();
             const doc = el.querySelector('.typeset').getBoundingClientRect();
             const table = el.querySelector('.typeset-scroll').getBoundingClientRect();
             const list = el.querySelector('[data-leika-document-contents]')
                            .getBoundingClientRect();
             return {gap: list.left - doc.right, inset: table.left - popup.left};
           }"""
    )
    assert measured["inset"] > 0, measured
    assert abs(measured["gap"] - measured["inset"]) < 1.0, measured
    assert page_errors == []


def test_the_contents_toggle_is_remembered_for_that_file(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The same memory full-window has, kept the same way and for the same
    # reason: whether a file is long enough to want a list beside it is a fact
    # about that file, and the next one is a different file. So the answer
    # follows the document rather than the session, and closing the preview is
    # not a retraction of it.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button("Show notes", CONTENTS_DOCUMENT, filename="notes.md")
    leika_server.gui.add_preview_button("Show other", CONTENTS_DOCUMENT, filename="other.md")
    dialog = _dialog(preview_page)

    _press(preview_page, "Show notes")
    expect(dialog.get_by_role("button", name="Show contents")).to_have_attribute(
        "aria-pressed", "false"
    )
    expect(_show_contents(preview_page)).to_be_visible()
    expect(dialog.get_by_role("button", name="Hide contents")).to_have_attribute(
        "aria-pressed", "true"
    )

    preview_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _press(preview_page, "Show notes")
    expect(_contents(preview_page)).to_be_visible()

    # A remembered list mounts with the popup. Let its initial observer-backed
    # heading measurement settle; just before Seeds is still Setup, and a
    # stale or wrongly scaled position would mark Seeds early.
    _settle(preview_page)
    frame = dialog.locator("div.overflow-auto").first
    seeds = dialog.get_by_role("heading", name="Seeds")
    seeds_top = frame.evaluate(
        """(el, heading) =>
             el.scrollTop + heading.getBoundingClientRect().top
                          - el.getBoundingClientRect().top""",
        seeds.element_handle(),
    )
    # The section line has 24px of arrival slack. Stay a known distance above
    # it rather than using a percentage whose pixel distance varies with font
    # metrics and browser layout.
    frame.evaluate("(el, top) => { el.scrollTop = top - 40; }", seeds_top)
    expect(_contents(preview_page).get_by_role("link", name="Setup")).to_have_attribute(
        "aria-current", "true"
    )
    frame.evaluate("el => { el.scrollTop = 0; }")

    # Another file is untouched by it: this document was never asked.
    preview_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _press(preview_page, "Show other")
    expect(dialog).to_contain_text("Training report")
    expect(_contents(preview_page)).to_have_count(0)

    # And taking it back down is remembered just as well.
    preview_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _press(preview_page, "Show notes")
    dialog.get_by_role("button", name="Hide contents").click()
    expect(_contents(preview_page)).to_have_count(0)
    preview_page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _press(preview_page, "Show notes")
    expect(dialog).to_contain_text("Training report")
    expect(_contents(preview_page)).to_have_count(0)
    assert page_errors == []


def test_a_document_with_no_headings_is_not_offered_a_contents_list(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The button says there is something to stand up. A file with nothing to
    # list would answer a press with no visible change at all, which is worse
    # than not offering.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button(
        "Show flat", CONTENTS_DOCUMENT.replace(b"#", b""), filename="flat.md"
    )
    leika_server.gui.add_preview_button("Show shot", _png(200, 120), filename="shot.png")

    _press(preview_page, "Show flat")
    expect(_dialog(preview_page)).to_contain_text("Training report")
    expect(_dialog(preview_page).get_by_role("button", name="Show contents")).to_have_count(0)

    # Nor is anything that is not a document. There is no writing to list.
    preview_page.keyboard.press("Escape")
    expect(_dialog(preview_page)).to_have_count(0)
    _press(preview_page, "Show shot")
    expect(_dialog(preview_page).locator("img")).to_be_visible()
    expect(_dialog(preview_page).get_by_role("button", name="Show contents")).to_have_count(0)
    assert page_errors == []


def _sectioned_document() -> bytes:
    """A file with more sections than a contents list can show at once."""
    sections = "".join(f"## Section {index}\n\nOne line about it.\n\n" for index in range(40))
    return f"# Report\n\n{_FILLER}{sections}".encode()


def test_the_contents_stay_where_the_reader_left_them(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # Two scrolls, and each is its own. A list longer than the window has a
    # scroll of the reader's, and it was being taken back off them: the marked
    # entry was pulled into view on every frame the document scrolled in, so
    # looking ahead in the list and then reading on by a line snapped the list
    # shut. It follows the MARK now, and the mark had not moved.
    preview_page.set_viewport_size({"width": 1400, "height": 800})
    leika_server.gui.add_preview_button("Show notes", _sectioned_document(), filename="notes.md")

    _press(preview_page, "Show notes")
    contents = _show_contents(preview_page)
    expect(contents).to_be_visible()
    _settle(preview_page)
    frame = _dialog(preview_page).locator("div.overflow-auto").first

    # The reader looks ahead down the list, while the document stays put.
    contents.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    parked = contents.evaluate("el => el.scrollTop")
    assert parked > 0, "the list should be long enough to scroll"

    # Then reads on a little, without leaving the section they are in.
    frame.evaluate("el => { el.scrollTop += 40; }")
    preview_page.wait_for_timeout(300)
    assert contents.evaluate("el => el.scrollTop") == parked
    assert _marked(preview_page) == ["Report"]

    # It does still come back when the mark moves, which is what moving it is
    # for: an entry nobody can see marks nothing.
    frame.evaluate("el => { el.scrollTop = el.scrollHeight; }")
    preview_page.wait_for_timeout(300)
    assert contents.evaluate(
        """el => {
             const list = el.getBoundingClientRect();
             const entry = el.querySelector('a[aria-current]').getBoundingClientRect();
             return entry.top >= list.top - 1 && entry.bottom <= list.bottom + 1;
           }"""
    ), _marked(preview_page)
    assert page_errors == []


def _long_document() -> bytes:
    body = "\n\n".join(f"Paragraph {index} of the report." for index in range(120))
    return f"# Report\n\n{body}\n".encode()


def test_only_the_document_scrolls_not_the_dialog_around_it(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The popup holds a document's frame; the frame holds the scroll. When the
    # frame carried a height of its own -- the window less a hand-counted 6rem
    # of chrome -- the count came out 3px under what the chrome measured, and
    # those 3px made the popup a scroller too. Reaching the end of a document
    # then chained the scroll outwards and shifted the dialog under the reader.
    # The frame is sized by layout now, so the two cannot disagree; its
    # overscroll containment also keeps the end of a document from being
    # passed outwards even if they did.
    leika_server.gui.add_preview_button("Show report", _long_document(), filename="report.md")

    _press(preview_page, "Show report")
    dialog = _dialog(preview_page)
    expect(dialog).to_be_visible()
    # The dialog paints from transfer metadata before the Blob has been read.
    # Wait for the document's final block so this measures the reading layout,
    # not WebKit's otherwise-valid initial spinner frame.
    expect(dialog.get_by_text("Paragraph 119 of the report.", exact=True)).to_be_attached()

    frame = dialog.locator("div.overflow-auto").first

    measure = """(element) => element.scrollHeight - element.clientHeight"""
    assert frame.evaluate(measure) > 0, "the document should have somewhere to scroll"
    assert dialog.evaluate(measure) == 0, "the popup itself should not scroll"

    # Scroll well past the end of the document, then back past the start.
    frame.hover()
    for _ in range(30):
        preview_page.mouse.wheel(0, 400)
    preview_page.wait_for_timeout(200)
    assert frame.evaluate("(element) => element.scrollTop") > 0
    assert dialog.evaluate("(element) => element.scrollTop") == 0

    for _ in range(30):
        preview_page.mouse.wheel(0, -400)
    preview_page.wait_for_timeout(200)
    assert dialog.evaluate("(element) => element.scrollTop") == 0
    assert page_errors == []


def test_a_long_filename_does_not_push_the_dialog_into_overflow(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The title is the one piece of the popup's chrome whose height is not
    # known in advance, and a name long enough to wrap is what a counted
    # deduction cannot survive. Layout absorbs it into the frame instead.
    name = "a-report-with-a-name-long-enough-to-wrap-the-title-twice-over.md"
    leika_server.gui.add_preview_button("Show report", _long_document(), filename=name)

    _press(preview_page, "Show report")
    dialog = _dialog(preview_page)
    expect(dialog).to_contain_text(name)
    assert dialog.evaluate("(element) => element.scrollHeight - element.clientHeight") == 0
    assert page_errors == []


def test_a_document_does_not_reflow_as_its_figures_arrive(
    leika_server: leika.Server,
    preview_page: Page,
    page_errors: list[str],
    tmp_path: Path,
) -> None:
    # A figure is fetched beside its document rather than carried inside it,
    # which is what makes a preview open at the speed of the click. The cost
    # was that the browser did not know how big one was until it landed, so it
    # left no room and laid the document out again for every arrival -- under
    # a reader who had been reading since the text appeared. The server
    # measures what it serves and says so in the URL, so the boxes are the
    # right shape from the first paint and the pictures drop into them.
    tmp_path.joinpath("figure.png").write_bytes(_png(600, 400))
    blocks = []
    for index in range(5):
        blocks.append(f"Paragraph {index} of the report.")
        blocks.append(f"![Figure {index}](figure.png)")
    document = tmp_path / "report.md"
    document.write_text("# Report\n\n" + "\n\n".join(blocks) + "\n")

    # Held, so that "before the figures arrive" is a state with a duration
    # rather than a race against localhost.
    held: List[Route] = []
    holding = True

    def hold(route: Route) -> None:
        if holding:
            held.append(route)
        else:
            route.continue_()

    preview_page.route("**/leika-assets/**", hold)

    leika_server.gui.add_preview_button("Show report", document)
    _press(preview_page, "Show report")
    frame = _dialog(preview_page).locator("div.overflow-auto").first
    images = _dialog(preview_page).locator("img")
    expect(images).to_have_count(5)

    # Exercise every lazy boundary while the pixel requests are held. This
    # separates any deferred document materialization from image decode.
    for index in range(5):
        images.nth(index).scroll_into_view_if_needed()
    deadline = time.monotonic() + 5.0
    while not held and time.monotonic() < deadline:
        preview_page.wait_for_timeout(10)
    assert held, "the figure requests were supposed to still be in flight"
    preview_page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )

    height = "(element) => element.scrollHeight"
    reserved = frame.evaluate(height)
    # Nothing has decoded, and the document is already its full height: the
    # room is reserved from the markup, not discovered from the pictures.
    assert preview_page.evaluate(
        """() => [...document.querySelectorAll('[data-slot="dialog-content"] img')]
             .every((image) => image.naturalWidth === 0)"""
    ), "the figures were supposed to still be in flight"
    assert reserved > 5 * 400, "no room was left for the figures"

    holding = False
    for route in held:
        route.continue_()
    preview_page.unroute("**/leika-assets/**", hold)
    for index in range(5):
        images.nth(index).scroll_into_view_if_needed()
        expect(images.nth(index)).to_have_js_property("naturalWidth", 600)
    preview_page.wait_for_timeout(200)

    assert frame.evaluate(height) == reserved, "the document changed height when its figures landed"
    assert page_errors == []
