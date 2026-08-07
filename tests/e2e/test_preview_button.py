"""End-to-end file-preview dialog tests."""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

import leika


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
    expect(image).to_be_visible()
    # Decoded, not merely present: a broken object URL still renders an <img>.
    expect(image).to_have_js_property("naturalWidth", 8)
    expect(_dialog(preview_page)).to_contain_text("field.png")
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


def _opened_size(page: Page, label: str) -> tuple[int, int]:
    """The dialog's size once it has finished opening."""
    _press(page, label)
    dialog = _dialog(page)
    expect(dialog).to_be_visible()
    size = dialog.evaluate(
        """async (el) => {
          await Promise.all(
            el.getAnimations().map((animation) => animation.finished.catch(() => {}))
          );
          const box = el.getBoundingClientRect();
          return [Math.round(box.width), Math.round(box.height)];
        }"""
    )
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    return tuple(size)


def test_a_preview_opens_the_same_size_whatever_the_file_holds(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # The frame is the viewer's, never the file's: a one-line log and a
    # thousand-line one open identically, so nothing resizes as content lands.
    leika_server.gui.add_preview_button("Show one line", b"t,v\n", filename="tiny.csv")
    leika_server.gui.add_preview_button(
        "Show many lines", ("t,v\n" * 500).encode(), filename="long.csv"
    )
    leika_server.gui.add_preview_button("Show field", _png(8, 6), filename="field.png")
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
            "Show field",
            "Show weights",
            "Show notes",
            "Show long notes",
            "Show plain",
        )
    }

    fitted = {
        sizes[label] for label in ("Show one line", "Show many lines", "Show field", "Show weights")
    }
    reading = {sizes[label] for label in ("Show notes", "Show long notes", "Show plain")}
    assert len(fitted) == 1, sizes
    assert len(reading) == 1, sizes
    # Writing is read by scrolling, so its frame takes the height the window
    # has rather than the share a fitted picture needs.
    assert reading.pop()[1] > fitted.pop()[1], sizes
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
