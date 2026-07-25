"""Server-driven notifications, end to end.

``add_notification`` sends a message the client turns into a shadcn toast, so
every property in the protocol -- body, loading, close button, auto-close --
only really exists if it survives that trip. These drive the real server API
and assert on the rendered toast.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Locator, Page, expect

import leika


@pytest.fixture()
def notify_page(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> Page:
    del page_errors  # Registers the pageerror listener; tests assert on it.
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    return page


def toasts(page: Page) -> Locator:
    return page.locator('[data-slot="toast"]')


def toast_titled(page: Page, title: str) -> Locator:
    return toasts(page).filter(has=page.locator('[data-slot="toast-title"]', has_text=title))


def test_notification_renders_title_and_body(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_notification("Export finished", "Wrote 12 files.", auto_close_seconds=None)

    toast = toasts(notify_page)
    expect(toast).to_have_count(1, timeout=5_000)
    expect(toast.locator('[data-slot="toast-title"]')).to_have_text("Export finished")
    expect(toast.locator('[data-slot="toast-description"]')).to_have_text("Wrote 12 files.")
    assert page_errors == []


def test_notification_without_a_body_renders_no_description(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_notification("Saved", auto_close_seconds=None)

    toast = toasts(notify_page)
    expect(toast).to_have_count(1, timeout=5_000)
    expect(toast.locator('[data-slot="toast-title"]')).to_have_text("Saved")
    # An empty body must not leave a blank description line under the title.
    expect(toast.locator('[data-slot="toast-description"]')).to_have_count(0)
    assert page_errors == []


def test_close_button_is_shown_only_when_requested(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_notification(
        "Dismissable", with_close_button=True, auto_close_seconds=None
    )
    leika_server.gui.add_notification("Pinned", with_close_button=False, auto_close_seconds=None)

    expect(toasts(notify_page)).to_have_count(2, timeout=5_000)
    dismissable = toast_titled(notify_page, "Dismissable")
    pinned = toast_titled(notify_page, "Pinned")
    expect(dismissable.locator('[data-slot="toast-close"]')).to_have_count(1)
    expect(pinned.locator('[data-slot="toast-close"]')).to_have_count(0)

    # Toasts collapse into a stack and expand on hover, so reaching the older
    # one's close button means hovering the stack first -- as a user would.
    # Only the frontmost toast is hoverable while collapsed.
    pinned.hover()
    expect(dismissable).to_have_attribute("data-expanded", "", timeout=5_000)

    # The close button really dismisses, and only its own toast.
    dismissable.locator('[data-slot="toast-close"]').click()
    expect(dismissable).to_have_count(0, timeout=5_000)
    expect(pinned).to_have_count(1)
    assert page_errors == []


def test_loading_notification_shows_a_spinner(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    handle = leika_server.gui.add_notification(
        "Rendering", "Frame 1 of 100", loading=True, auto_close_seconds=None
    )

    toast = toasts(notify_page)
    expect(toast).to_have_count(1, timeout=5_000)
    spinner = toast.locator('[data-slot="toast-icon"] .animate-spin')
    expect(spinner).to_have_count(1)

    # Clearing `loading` swaps the spinner out in place.
    handle.loading = False
    expect(spinner).to_have_count(0, timeout=5_000)
    expect(toast).to_have_count(1)
    assert page_errors == []


def test_handle_updates_the_notification_in_place(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    handle = leika_server.gui.add_notification(
        "Rendering", "Frame 1 of 100", auto_close_seconds=None
    )
    expect(toasts(notify_page)).to_have_count(1, timeout=5_000)

    handle.update(title="Rendering", body="Frame 50 of 100")
    expect(toasts(notify_page).locator('[data-slot="toast-description"]')).to_have_text(
        "Frame 50 of 100", timeout=5_000
    )
    # Updating replaces the existing toast rather than stacking a second one.
    expect(toasts(notify_page)).to_have_count(1)
    assert page_errors == []


def test_handle_removes_the_notification(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    handle = leika_server.gui.add_notification("Working", auto_close_seconds=None)
    expect(toasts(notify_page)).to_have_count(1, timeout=5_000)

    handle.remove()
    expect(toasts(notify_page)).to_have_count(0, timeout=5_000)
    assert page_errors == []


def test_updating_a_dismissed_notification_does_not_resurrect_it(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    handle = leika_server.gui.add_notification(
        "Working", with_close_button=True, auto_close_seconds=None
    )
    toast = toasts(notify_page)
    expect(toast).to_have_count(1, timeout=5_000)
    toast.locator('[data-slot="toast-close"]').click()
    expect(toast).to_have_count(0, timeout=5_000)

    # A dismissal is the user's final word: late progress updates from the
    # server must not bring the toast back.
    handle.update(body="Still going")
    notify_page.wait_for_timeout(500)
    expect(toast).to_have_count(0)
    assert page_errors == []


def test_notification_auto_closes(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_notification("Brief", auto_close_seconds=1.0)

    toast = toasts(notify_page)
    expect(toast).to_have_count(1, timeout=5_000)
    expect(toast).to_have_count(0, timeout=5_000)
    assert page_errors == []
