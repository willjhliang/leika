from __future__ import annotations

import numpy as np
from playwright.sync_api import Page, expect

import leika


def test_single_page_header_is_a_static_title(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """A workspace with nowhere to switch has no page-menu affordance."""

    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )

    title = page.locator("[data-leika-page-title]")
    expect(title).to_be_visible(timeout=5_000)
    expect(title).to_have_text("Main")
    expect(title.locator("svg")).to_have_count(0)
    expect(page.locator("[data-leika-page-selector]")).to_have_count(0)
    expect(page.get_by_role("combobox", name="Page: Main", exact=True)).to_have_count(0)

    title.click()
    expect(page.get_by_role("listbox")).to_have_count(0)
    expect(page.get_by_role("option")).to_have_count(0)
    assert page_errors == []


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


def _center_pixel(page: Page, pane_id: str) -> tuple[int, int, int, int]:
    """Read one rendered image pixel without depending on screenshots."""

    values = page.locator(f'[data-viewport-pane-content="{pane_id}"] img').evaluate(
        """async (image) => {
            await image.decode();
            const canvas = document.createElement("canvas");
            canvas.width = image.naturalWidth;
            canvas.height = image.naturalHeight;
            const context = canvas.getContext("2d", {willReadFrequently: true});
            context.drawImage(image, 0, 0);
            return Array.from(
                context.getImageData(
                    Math.floor(canvas.width / 2),
                    Math.floor(canvas.height / 2),
                    1,
                    1,
                ).data,
            );
        }"""
    )
    return tuple(values)


def _start_pane_host_observer(page: Page) -> None:
    page.evaluate(
        """() => {
            window.__leikaPaneHostCounts = [];
            const workspace = document.querySelector("[data-viewport-workspace]");
            const inspect = () => {
                window.__leikaPaneHostCounts.push(
                    workspace.querySelectorAll("[data-viewport-pane]").length,
                );
            };
            window.__leikaPaneHostObserver = new MutationObserver(inspect);
            window.__leikaPaneHostObserver.observe(workspace, {
                childList: true,
                subtree: true,
            });
            inspect();
        }"""
    )


def _assert_no_empty_workspace(page: Page) -> None:
    counts = page.evaluate("() => window.__leikaPaneHostCounts")
    assert counts
    assert min(counts) > 0, counts


def _connection_badge_width(page: Page) -> float:
    bounds = page.locator("[data-leika-connection-trigger]").bounding_box()
    assert bounds is not None
    return bounds["width"]


def _assert_connection_badge_padding(page: Page) -> None:
    padding = page.locator("[data-leika-connection-trigger]").evaluate(
        "element => { const style = getComputedStyle(element); "
        "return [style.paddingLeft, style.paddingRight]; }"
    )
    assert padding == ["4px", "8px"]


def _assert_page_refreshing(page: Page, refreshing: bool) -> None:
    connection = page.locator("[data-leika-connection-trigger]")
    label = connection.locator("[data-leika-connection-label]")
    spinner = connection.locator('[data-slot="spinner"]')
    live_status = page.locator('span[role="status"][aria-live="polite"][aria-atomic="true"]')
    workspace = page.locator("[data-viewport-workspace]")
    canvas = page.locator("[data-viewport-grid-canvas]")
    _assert_connection_badge_padding(page)
    expect(page.locator("[data-viewport-page-refreshing]")).to_have_count(0)
    expect(live_status).to_have_count(1)

    if refreshing:
        expect(connection).to_have_attribute("data-leika-page-refreshing", "true")
        expect(connection).to_have_attribute("aria-label", "Loading page; connection details")
        expect(label).to_have_text("Loading")
        expect(spinner).to_have_count(1)
        assert spinner.evaluate("element => getComputedStyle(element).color") == label.evaluate(
            "element => getComputedStyle(element).color"
        )
        expect(live_status).to_have_text("Loading page")
        expect(workspace).to_have_attribute("aria-busy", "true")
        expect(canvas).to_have_attribute("inert", "")
        return

    expect(connection).not_to_have_attribute("data-leika-page-refreshing", "true")
    expect(connection).to_have_attribute("aria-label", "Connected; connection details")
    expect(label).to_have_text("Connected")
    expect(spinner).to_have_count(0)
    expect(live_status).to_have_text("")
    expect(workspace).to_have_attribute("aria-busy", "false")
    expect(canvas).not_to_have_attribute("inert", "")


def _reset_pane_host_observations(page: Page) -> None:
    page.evaluate(
        """() => {
            const workspace = document.querySelector("[data-viewport-workspace]");
            window.__leikaPaneHostCounts = [
                workspace.querySelectorAll("[data-viewport-pane]").length,
            ];
        }"""
    )


def test_page_switch_keeps_pixels_visible_and_revalidates_a_cached_page(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """A cache miss retains the old page; a cache hit precedes its replay."""

    old_main_pixel = (16, 32, 48, 255)
    latest_main_pixel = (224, 112, 40, 255)
    analysis_pixel = (80, 144, 208, 255)
    main = leika_server.panes.add_image(
        np.full((16, 16, 4), old_main_pixel, dtype=np.uint8),
        pane_id="main-image",
        title="Main image",
        format="png",
    )
    analysis = leika_server.pages.add("Analysis", page_id="analysis")
    analysis.panes.add_image(
        np.full((16, 16, 4), analysis_pixel, dtype=np.uint8),
        pane_id="analysis-image",
        title="Analysis image",
        format="png",
    )

    page.goto(leika_server.url)
    page.wait_for_selector('[data-viewport-workspace][aria-busy="false"]', timeout=15_000)
    expect(page.locator('[data-viewport-pane-title="main-image"]')).to_have_text("Main image")
    assert _center_pixel(page, "main-image") == old_main_pixel
    settled_badge_width = _connection_badge_width(page)

    trigger = page.locator("[data-leika-page-selector]")
    _start_pane_host_observer(page)

    # Analysis has never been loaded. Pause its entire server replay and prove
    # the outgoing page remains painted until the new target is ready.
    with leika_server.atomic():
        trigger.click()
        page.get_by_role("option", name="Analysis", exact=True).click()
        page.wait_for_timeout(50)
        expect(trigger).to_have_attribute("aria-label", "Page: Analysis")
        expect(page.locator('[data-viewport-pane-title="main-image"]')).to_have_text("Main image")
        assert _center_pixel(page, "main-image") == old_main_pixel
        _assert_no_empty_workspace(page)

        _assert_page_refreshing(page, True)
        assert _connection_badge_width(page) < settled_badge_width

    expect(page.locator('[data-viewport-pane-title="analysis-image"]')).to_have_text(
        "Analysis image"
    )
    _assert_page_refreshing(page, False)
    assert _center_pixel(page, "analysis-image") == analysis_pixel
    _assert_no_empty_workspace(page)

    # Update Main while its stream is inactive. On return, pause replay again:
    # the previously loaded model must be available from the browser cache,
    # then reconcile to the authoritative inactive updates after replay.
    main.update(np.full((16, 16, 4), latest_main_pixel, dtype=np.uint8))
    main.title = "Updated main image"
    _reset_pane_host_observations(page)
    with leika_server.atomic():
        trigger.click()
        page.get_by_role("option", name="Main", exact=True).click()
        page.wait_for_timeout(50)
        expect(trigger).to_have_attribute("aria-label", "Page: Main")
        expect(page.locator('[data-viewport-pane-title="main-image"]')).to_have_text("Main image")
        assert _center_pixel(page, "main-image") == old_main_pixel
        _assert_no_empty_workspace(page)
        _assert_page_refreshing(page, True)
        assert _connection_badge_width(page) < settled_badge_width

    expect(page.locator('[data-viewport-pane-title="main-image"]')).to_have_text(
        "Updated main image"
    )
    _assert_page_refreshing(page, False)
    page.wait_for_function(
        """async ([paneId, expected]) => {
            const image = document.querySelector(
                '[data-viewport-pane-content="' + paneId + '"] img',
            );
            if (image === null) return false;
            await image.decode();
            const canvas = document.createElement("canvas");
            canvas.width = image.naturalWidth;
            canvas.height = image.naturalHeight;
            const context = canvas.getContext("2d", {willReadFrequently: true});
            context.drawImage(image, 0, 0);
            const actual = Array.from(
                context.getImageData(
                    Math.floor(canvas.width / 2),
                    Math.floor(canvas.height / 2),
                    1,
                    1,
                ).data,
            );
            return actual.every((value, index) => value === expected[index]);
        }""",
        arg=["main-image", latest_main_pixel],
        timeout=5_000,
    )
    _assert_no_empty_workspace(page)
    assert page_errors == []
