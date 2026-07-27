"""Modals, and the client's ability to dismiss them.

A modal is created from Python but dismissed from the browser, so closing is a
round trip: the client asks, the server tears down the contained components, and
the modal leaves the screen only when that removal echoes back. These drive the
real server API and assert on both ends of that trip.
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Browser, Locator, Page, expect

import leika


def dialog(page: Page) -> Locator:
    return page.locator('[data-slot="dialog-content"]')


def wait_until_closed(modal: leika.GuiModalHandle, timeout: float = 5.0) -> None:
    """Block until the server has torn the modal down."""
    deadline = time.monotonic() + timeout
    while not modal.closed and time.monotonic() < deadline:
        time.sleep(0.01)


@pytest.fixture()
def modal(leika_server: leika.Server, leika_page: Page) -> leika.GuiModalHandle:
    handle = leika_server.gui.add_modal("Details")
    with handle:
        leika_server.gui.add_slider("Local control", min=0.0, max=1.0, step=0.01, initial_value=0.5)
    expect(dialog(leika_page)).to_be_visible(timeout=5_000)
    return handle


def test_close_button_dismisses_the_modal(
    leika_page: Page, modal: leika.GuiModalHandle, page_errors: list[str]
) -> None:
    leika_page.locator('[data-slot="dialog-close"]').click()

    expect(dialog(leika_page)).to_have_count(0, timeout=5_000)
    wait_until_closed(modal)
    assert modal.closed
    assert page_errors == []


def test_clicking_outside_dismisses_the_modal(
    leika_page: Page, modal: leika.GuiModalHandle, page_errors: list[str]
) -> None:
    # The backdrop covers the viewport, so a click at its top-left corner lands
    # outside the popup without hitting any other control.
    leika_page.locator('[data-slot="dialog-overlay"]').click(position={"x": 5, "y": 5})

    expect(dialog(leika_page)).to_have_count(0, timeout=5_000)
    wait_until_closed(modal)
    assert modal.closed
    assert page_errors == []


def test_escape_dismisses_the_modal(
    leika_page: Page, modal: leika.GuiModalHandle, page_errors: list[str]
) -> None:
    leika_page.keyboard.press("Escape")

    expect(dialog(leika_page)).to_have_count(0, timeout=5_000)
    wait_until_closed(modal)
    assert modal.closed
    assert page_errors == []


def test_dismissing_removes_the_contained_components(
    leika_server: leika.Server, leika_page: Page, modal: leika.GuiModalHandle
) -> None:
    """Teardown is the server's, so dismissing must not strand the children."""
    leika_page.locator('[data-slot="dialog-close"]').click()
    wait_until_closed(modal)

    assert modal._children == {}
    assert modal.id not in leika_server.gui._modal_handle_from_uuid
    # A closed modal is not a container that can still be filled.
    with pytest.raises(RuntimeError, match="closed modal"):
        modal.add_button("Too late")


def test_dismissing_closes_the_modal_for_every_client(
    browser: Browser, leika_server: leika.Server
) -> None:
    """Modals added to `server.gui` are global, so dismissal is global too."""
    handle = leika_server.gui.add_modal("Details")
    with handle:
        leika_server.gui.add_markdown("Shared across clients.")

    context = browser.new_context(viewport={"width": 800, "height": 600}, reduced_motion="reduce")
    first = context.new_page()
    second = context.new_page()
    try:
        for page in (first, second):
            page.goto(leika_server.url)
            page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
            expect(dialog(page)).to_be_visible(timeout=15_000)

        first.locator('[data-slot="dialog-close"]').click()

        expect(dialog(first)).to_have_count(0, timeout=5_000)
        expect(dialog(second)).to_have_count(0, timeout=5_000)
        wait_until_closed(handle)
        assert handle.closed
    finally:
        context.close()
