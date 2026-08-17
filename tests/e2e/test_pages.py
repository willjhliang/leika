from __future__ import annotations

import numpy as np
from playwright.sync_api import Page, expect

import leika


def test_page_selector_switches_scoped_panes_and_restores_the_active_page(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """Pages may reuse pane IDs without sharing content or browser choice."""

    analysis = leika_server.pages.add("Analysis", page_id="analysis")
    leika_server.panes.add_image(
        np.zeros((8, 8, 3), dtype=np.uint8),
        pane_id="shared",
        title="Main pane",
    )
    analysis.panes.add_image(
        np.full((8, 8, 3), 255, dtype=np.uint8),
        pane_id="shared",
        title="Analysis pane",
    )

    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )

    trigger = page.locator("[data-leika-page-selector]")
    expect(trigger).to_be_visible(timeout=5_000)
    expect(trigger).to_have_attribute("aria-label", "Page: Main")
    expect(trigger).to_have_attribute("aria-haspopup", "listbox")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_role("combobox", name="Page: Main", exact=True)).to_have_count(1)
    expect(page.locator('[data-viewport-pane="shared"]')).to_have_count(1)
    expect(page.locator('[data-viewport-pane-title="shared"]')).to_have_text("Main pane")

    trigger.click()
    expect(trigger).to_have_attribute("aria-expanded", "true")
    menu = page.locator('[data-slot="select-content"]')
    expect(menu).to_have_attribute("data-align-trigger", "false")
    expect(menu).to_have_attribute("data-side", "bottom")
    main_option = page.get_by_role("option", name="Main", exact=True)
    analysis_option = page.get_by_role("option", name="Analysis", exact=True)
    expect(main_option).to_be_visible()
    expect(analysis_option).to_be_visible()
    analysis_option.click()

    expect(trigger).to_have_attribute("aria-label", "Page: Analysis")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(page.locator('[data-viewport-pane="shared"]')).to_have_count(1)
    expect(page.locator('[data-viewport-pane-title="shared"]')).to_have_text("Analysis pane")

    # The selected row must not change the selector from a dropdown into an
    # item-aligned overlay when it happens to be the first option.
    trigger.click()
    expect(menu).to_have_attribute("data-align-trigger", "false")
    expect(menu).to_have_attribute("data-side", "bottom")
    page.keyboard.press("Escape")

    # Page choice is browser-owned alongside layouts and returns after the
    # connection replay, even though the default page is declared first.
    page.reload()
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    expect(trigger).to_have_attribute("aria-label", "Page: Analysis", timeout=10_000)
    expect(page.locator('[data-viewport-pane-title="shared"]')).to_have_text("Analysis pane")

    # The identically named pane on the other page is still its own owner.
    trigger.click()
    page.get_by_role("option", name="Main", exact=True).click()
    expect(page.locator('[data-viewport-pane-title="shared"]')).to_have_text("Main pane")
    assert page_errors == []
