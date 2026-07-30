"""A download button, from the press to the file the browser ends up with.

``test_download_button.py`` pins what the handle does with a press and
``test_file_download.py`` pins what goes on the wire; neither presses anything.
What is left is the trip: a real click reaching the callback, the chunks
reassembling in the browser, and the file arriving under the right name.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, expect

import leika


def _button(page: Page, text: str) -> Locator:
    return page.get_by_role("button", name=text)


def test_a_press_downloads_the_file(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_download_button(
        "Export",
        b"time,signal\n0,0.5\n",
        filename="readings.csv",
    )

    with leika_page.expect_download() as download_info:
        _button(leika_page, "Export").click()
    download = download_info.value

    assert download.suggested_filename == "readings.csv"
    assert Path(download.path()).read_bytes() == b"time,signal\n0,0.5\n"
    assert page_errors == []


def test_a_file_on_disk_is_streamed_and_keeps_its_name(
    leika_server: leika.Server, leika_page: Page, tmp_path: Path, page_errors: list[str]
) -> None:
    # Past the one-chunk mark, so the browser has to reassemble the parts
    # rather than just take the only one.
    contents = bytes(range(256)) * 8192
    source = tmp_path / "capture.bin"
    source.write_bytes(contents)
    leika_server.gui.add_download_button("Save capture", source)

    with leika_page.expect_download() as download_info:
        _button(leika_page, "Save capture").click()
    download = download_info.value

    assert download.suggested_filename == "capture.bin"
    assert Path(download.path()).read_bytes() == contents
    assert page_errors == []


def test_a_send_without_an_immediate_save_offers_the_file_as_a_link(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # No button reaches this any more -- a press is its own ask, so the button
    # saves -- but `send_file_download` still offers the other half, and the
    # toast it puts up is only reachable through a browser. The name rides on
    # the anchor rather than on the transfer.
    send = leika_server.gui.add_button("Offer")

    @send.on_click
    def _(event: leika.GuiEvent[Any]) -> None:
        assert event.client is not None
        event.client.send_file_download("report.csv", b"a,b\n", save_immediately=False)

    _button(leika_page, "Offer").click()
    link = leika_page.locator('[data-slot="toast"] a[download]')
    expect(link).to_have_attribute("download", "report.csv")
    assert page_errors == []


def test_the_button_is_shut_until_the_file_is_out(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # Held for as long as the contents take to make, so the impatient second
    # click never reaches the callback.
    release = threading.Event()

    def contents(event: leika.GuiEvent[Any]) -> bytes:
        release.wait(timeout=15.0)
        return b"done"

    leika_server.gui.add_download_button("Export", contents, filename="n.txt")
    button = _button(leika_page, "Export")

    button.click()
    expect(button).to_be_disabled()
    with leika_page.expect_download():
        release.set()
    expect(button).to_be_enabled()
    assert page_errors == []
