"""End-to-end file-preview dialog tests."""

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
