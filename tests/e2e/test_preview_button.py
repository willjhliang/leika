"""A preview button, from the press to what ends up on screen.

``filePreview.test.ts`` pins which viewer a name and a type call for, and
``test_preview_button.py`` pins what the handle does with a press. What is left
is the trip: the file crossing the wire, the browser assembling it, and the
right element appearing in the dialog with the file actually in it.
"""

from __future__ import annotations

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


def _column(page: Page, selector: str) -> dict:
    """Where a viewer's content sits inside the dialog."""
    return _dialog(page).evaluate(
        """(dialog, selector) => {
          const outer = dialog.getBoundingClientRect();
          const inner = dialog.querySelector(selector).getBoundingClientRect();
          return {
            dialog: outer.width,
            column: inner.width,
            left: inner.left - outer.left,
            right: outer.right - inner.right,
          };
        }""",
        selector,
    )


def test_writing_is_set_in_a_column_and_data_spans_the_width(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # A line run to the width this dialog wants for images is hard to carry
    # your eye back along, so markdown and plain text take a measure and the
    # margins a page would give them. A CSV row is a record rather than a
    # sentence, and the width is there to be used.
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
        assert box["column"] < box["dialog"] / 1.5, (label, box)
        # Centred, with margins on both sides rather than a column pinned left.
        assert abs(box["left"] - box["right"]) < 2.0, (label, box)
        assert box["left"] > 40.0, (label, box)
        preview_page.keyboard.press("Escape")
        expect(_dialog(preview_page)).to_have_count(0)

    _press(preview_page, "Show readings")
    data = _column(preview_page, "pre")
    # No margins at all: the data runs the width of the frame it is in.
    assert data["column"] > data["dialog"] / 1.5, data
    assert page_errors == []


def test_every_preview_opens_the_same_size(
    leika_server: leika.Server, preview_page: Page, page_errors: list[str]
) -> None:
    # Sized to its contents, a one-line file would open a sliver of a dialog
    # and the next a tall one, moving the close button every time -- and the
    # type of the file would be deciding the shape of the window, which is
    # not something the reader asked about.
    leika_server.gui.add_preview_button("Show one line", b"t,v\n", filename="tiny.csv")
    leika_server.gui.add_preview_button(
        "Show many lines", ("t,v\n" * 500).encode(), filename="long.csv"
    )
    leika_server.gui.add_preview_button("Show notes", b"# Hi\n", filename="notes.md")
    leika_server.gui.add_preview_button("Show field", _png(8, 6), filename="field.png")
    leika_server.gui.add_preview_button("Show weights", b"\x00\x01", filename="weights.bin")

    sizes = {}
    for label in (
        "Show one line",
        "Show many lines",
        "Show notes",
        "Show field",
        "Show weights",
    ):
        _press(preview_page, label)
        dialog = _dialog(preview_page)
        expect(dialog).to_be_visible()
        # The dialog zooms open, so a rect read on the first frame is a rect
        # of the animation rather than of the dialog.
        sizes[label] = dialog.evaluate(
            """async (el) => {
              let previous = null;
              for (let frame = 0; frame < 60; frame += 1) {
                const box = el.getBoundingClientRect();
                const current = [Math.round(box.width), Math.round(box.height)];
                if (previous !== null && String(current) === String(previous)) {
                  return current;
                }
                previous = current;
                await new Promise((resolve) => requestAnimationFrame(resolve));
              }
              return previous;
            }"""
        )
        preview_page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)

    assert len(set(tuple(size) for size in sizes.values())) == 1, sizes
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
    # One control in one place, whatever the file turned out to be: the same
    # corner works for a viewer the dialog could fill and one it could not.
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
