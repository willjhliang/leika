"""The titlebar, and the navigation sheet it opens on narrow viewports.

`configure_theme(titlebar_content=...)` is the only way to render the titlebar,
and its buttons collapse into a sheet below the `sm` breakpoint. That sheet is
the app's third dismissable surface, so it is checked against the same corner
the dialog and toast pin their close buttons to.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

import leika

TITLEBAR: leika.theme.TitlebarConfig = {
    "buttons": (
        {"text": "Docs", "icon": leika.Icon.FILE_TEXT, "href": "https://example.com/docs"},
        {"text": "Source", "icon": "github", "href": "https://example.com/src"},
    ),
    "image": None,
}


@pytest.fixture()
def narrow_page(leika_server: leika.Server, page: Page, page_errors: list[str]) -> Page:
    del page_errors  # Registers the pageerror listener; tests assert on it.
    leika_server.gui.configure_theme(titlebar_content=TITLEBAR)
    # Below Tailwind's `sm` breakpoint, which is where the buttons collapse.
    page.set_viewport_size({"width": 500, "height": 700})
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    return page


def test_navigation_collapses_into_a_sheet(narrow_page: Page, page_errors: list[str]) -> None:
    trigger = narrow_page.get_by_label("Open navigation")
    expect(trigger).to_be_visible(timeout=5_000)
    trigger.click()

    sheet = narrow_page.locator('[data-slot="sheet-content"]')
    expect(sheet).to_be_visible(timeout=5_000)
    expect(sheet.get_by_text("Docs")).to_be_visible()
    assert page_errors == []


def test_sheet_close_button_sits_in_the_top_right_corner(
    narrow_page: Page, page_errors: list[str]
) -> None:
    """The same corner the dialog and toast use, so dismissal is one habit."""
    narrow_page.get_by_label("Open navigation").click()
    close = narrow_page.locator('[data-slot="sheet-close"]')
    expect(close).to_be_visible(timeout=5_000)

    placement = close.evaluate(
        """el => {
            const style = getComputedStyle(el)
            return {position: style.position, top: style.top, right: style.right}
        }"""
    )
    assert placement == {"position": "absolute", "top": "8px", "right": "8px"}

    close.click()
    expect(narrow_page.locator('[data-slot="sheet-content"]')).to_have_count(0, timeout=5_000)
    assert page_errors == []
