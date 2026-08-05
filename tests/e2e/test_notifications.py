"""Server-driven notifications, end to end.

``add_notification`` sends a message the client turns into a shadcn toast, so
every property in the protocol -- body, loading, close button, auto-close --
only really exists if it survives that trip. These drive the real server API
and assert on the rendered toast; the props-to-toast mapping itself is pinned
by ``notifications.test.ts``.
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


def test_notifications_render_their_parts(
    leika_server: leika.Server, notify_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_notification("Export finished", "Wrote 12 files.", auto_close_seconds=None)
    leika_server.gui.add_notification("Saved", auto_close_seconds=None)
    leika_server.gui.add_notification(
        "A title long enough to fill the row and reach the corner",
        "Body copy that wraps onto a second line so the toast is tall.",
        with_close_button=True,
        auto_close_seconds=None,
    )
    expect(toasts(notify_page)).to_have_count(3, timeout=5_000)

    titled = toast_titled(notify_page, "Export finished")
    expect(titled.locator('[data-slot="toast-description"]')).to_have_text("Wrote 12 files.")
    # An empty body must not leave a blank description line under the title.
    bare = toast_titled(notify_page, "Saved")
    expect(bare.locator('[data-slot="toast-description"]')).to_have_count(0)

    # The close button sits in the top-right corner, positioned like a
    # dialog's close button rather than inline in the row. Layout offsets, so
    # an in-flight enter animation cannot skew them.
    close = toast_titled(notify_page, "A title long enough to fill the row and reach the corner")
    box = close.locator('[data-slot="toast-close"]').evaluate(
        """el => {
            const host = el.closest('[data-slot="toast"]');
            const style = getComputedStyle(el);
            return {
                position: style.position,
                top: style.top,
                right: style.right,
                overlapsText: [...host.querySelectorAll(
                    '[data-slot="toast-title"], [data-slot="toast-description"]'
                )].some((text) => {
                    const a = text.getBoundingClientRect();
                    const b = el.getBoundingClientRect();
                    return a.right > b.left && a.top < b.bottom && a.bottom > b.top;
                }),
            };
        }"""
    )
    assert box == {"position": "absolute", "top": "8px", "right": "8px", "overlapsText": False}
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


def test_handle_drives_the_notification_through_its_lifecycle(
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

    # Updating replaces the existing toast rather than stacking a second one.
    handle.update(title="Rendering", body="Frame 50 of 100")
    expect(toast.locator('[data-slot="toast-description"]')).to_have_text(
        "Frame 50 of 100", timeout=5_000
    )
    expect(toast).to_have_count(1)

    handle.remove()
    expect(toast).to_have_count(0, timeout=5_000)
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


def test_toasts_clear_a_left_docked_panel_from_the_start(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """Toasts anchor bottom-left, which is exactly where a left-docked panel
    stands. The inset that clears a DRAGGED-there panel has to hold when the
    panel starts there by configuration instead."""
    leika_server.gui.configure_theme(control_layout="left", dark_mode=True)
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    panel = page.get_by_test_id("control-panel")
    expect(panel).to_have_attribute("data-dock-side", "left", timeout=5_000)
    panel_bounds = panel.bounding_box()
    assert panel_bounds is not None

    leika_server.gui.add_notification("Export finished", "Wrote 12 files.", auto_close_seconds=None)
    toast = toast_titled(page, "Export finished")
    expect(toast).to_be_visible(timeout=5_000)
    toast_bounds = toast.bounding_box()
    assert toast_bounds is not None
    assert toast_bounds["x"] >= panel_bounds["x"] + panel_bounds["width"] - 1.0, (
        toast_bounds,
        panel_bounds,
    )
    assert page_errors == []
