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

from .utils import assert_stable_viewer


def dialog(page: Page) -> Locator:
    return page.locator('[data-slot="dialog-content"]')


def wait_until_closed(modal: leika.GuiModalHandle, timeout: float = 5.0) -> None:
    """Block until the server has torn the modal down."""
    deadline = time.monotonic() + timeout
    while not modal.closed and time.monotonic() < deadline:
        time.sleep(0.01)


def open_modal(server: leika.Server, page: Page) -> leika.GuiModalHandle:
    handle = server.gui.add_modal("Details")
    with handle:
        server.gui.add_slider("Local control", min=0.0, max=1.0, step=0.01, initial_value=0.5)
    surface = dialog(page)
    expect(surface).to_be_visible(timeout=5_000)
    expect(surface).to_have_attribute("data-dialog-presentation", "dialog")
    state = surface.evaluate(
        """surface => {
          const instance = surface.dataset.dialogInstance;
          const overlay = [...document.querySelectorAll(
            '[data-slot="dialog-overlay"]'
          )].find(element => element.dataset.dialogInstance === instance);
          return {
            popupClasses: [...surface.classList],
            overlayClasses: [...overlay.classList],
            overlayPresentation: overlay.dataset.dialogPresentation,
            backdropFilter: getComputedStyle(overlay).backdropFilter,
          };
        }"""
    )
    assert {"duration-100", "data-open:animate-in", "data-open:zoom-in-95"}.issubset(
        state["popupClasses"]
    ), state
    assert {"duration-100", "data-open:animate-in"}.issubset(state["overlayClasses"]), state
    assert state["overlayPresentation"] == "dialog", state
    assert state["backdropFilter"] == "none", state
    return handle


def test_each_dismissal_gesture_closes_and_tears_down(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """Close button, outside click, and Escape all drive the same round trip."""
    # Close button, followed all the way down to server-side teardown.
    modal = open_modal(leika_server, leika_page)
    leika_page.locator('[data-slot="dialog-close"]').click()
    expect(dialog(leika_page)).to_have_count(0, timeout=5_000)
    wait_until_closed(modal)
    assert modal.closed
    assert modal._children == {}
    assert modal.id not in leika_server.gui._modal_handle_from_uuid
    # A closed modal is not a container that can still be filled.
    with pytest.raises(RuntimeError, match="closed modal"):
        modal.add_button("Too late")

    # The backdrop covers the viewport, so a click at its top-left corner lands
    # outside the popup without hitting any other control.
    modal = open_modal(leika_server, leika_page)
    leika_page.locator('[data-slot="dialog-overlay"]').click(position={"x": 5, "y": 5})
    expect(dialog(leika_page)).to_have_count(0, timeout=5_000)
    wait_until_closed(modal)
    assert modal.closed

    modal = open_modal(leika_server, leika_page)
    leika_page.keyboard.press("Escape")
    expect(dialog(leika_page)).to_have_count(0, timeout=5_000)
    wait_until_closed(modal)
    assert modal.closed
    assert page_errors == []


def test_a_preview_opened_from_a_modal_owns_the_top_layer(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """Nested preview chrome and backdrop must sit above their parent modal."""
    modal = leika_server.gui.add_modal("Details")
    with modal:
        leika_server.gui.add_preview_button(
            "Inspect report", b"# Nested report\n\nSome prose.\n", filename="nested.md"
        )

    outer = leika_page.locator('[data-slot="dialog-content"][data-dialog-presentation="dialog"]')
    expect(outer).to_be_visible(timeout=5_000)
    outer.get_by_role("button", name="Inspect report", exact=True).click()

    viewer = leika_page.locator('[data-slot="dialog-content"][data-dialog-presentation="viewer"]')
    expect(viewer).to_be_visible(timeout=5_000)
    assert_stable_viewer(viewer)

    # Escape closes only the topmost viewer and returns to the modal beneath.
    leika_page.keyboard.press("Escape")
    expect(viewer).to_have_count(0)
    expect(outer).to_be_visible()

    outer.locator('[data-slot="dialog-close"]').click()
    expect(outer).to_have_count(0, timeout=5_000)
    wait_until_closed(modal)
    assert modal.closed
    assert page_errors == []


def test_dismissing_closes_the_modal_for_every_client(
    browser: Browser, leika_server: leika.Server
) -> None:
    """Modals added to `server.gui` are global, so dismissal is global too."""
    handle = leika_server.gui.add_modal("Details")
    with handle:
        leika_server.gui.add_text(
            None, "Shared across clients.", editable=False, markdown=True, multiline=True
        )

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
