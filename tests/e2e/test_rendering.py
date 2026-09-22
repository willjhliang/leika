"""Rendering preferences change actual images, independently in each browser."""

from __future__ import annotations

import threading
from urllib.parse import urlsplit

import numpy as np
from playwright.sync_api import expect

from .test_refresh_barrier import slow_proxy
from .test_settings import close_settings, open_settings


def select_rendering(page, value):
    pane = open_settings(page)
    pane.locator("[data-leika-settings-rendering]").click()
    page.get_by_role("option", name=value, exact=True).click()
    expect(pane.locator("[data-leika-settings-rendering]")).to_contain_text(value)
    close_settings(page)


def image_width(page):
    return page.locator('[data-viewport-pane="image"] img').evaluate("img => img.naturalWidth")


def wait_width(page, expression):
    page.wait_for_function(
        """expr => {
      const img=document.querySelector('[data-viewport-pane="image"] img');
      return img && img.complete && img.naturalWidth > 0 &&
        (expr[0] === "equal" ? img.naturalWidth === expr[1] : img.naturalWidth < expr[1]);
    }""",
        arg=expression,
    )


def test_presets_apply_to_paused_images_persist_and_do_not_degrade_other_viewers(
    leika_server, page, browser, page_errors
):
    rng = np.random.default_rng(5)
    source = rng.integers(0, 256, (1200, 1600, 3), np.uint8)
    handle = leika_server.panes.add_image(source, pane_id="image", format="jpeg")
    page.goto(leika_server.url)
    wait_width(page, ["equal", 1600])
    auto_width = image_width(page)
    select_rendering(page, "Performance")
    wait_width(page, ["less", auto_width])
    performance_width = image_width(page)
    assert performance_width <= auto_width / 2 + 1

    context = browser.new_context(viewport={"width": 960, "height": 700}, reduced_motion="reduce")
    try:
        other = context.new_page()
        other.goto(leika_server.url)
        wait_width(other, ["equal", 1600])
        select_rendering(other, "Quality")
        wait_width(other, ["equal", 1600])
        # Settings apply to the existing static image, without Python update().
        page.reload()
        wait_width(page, ["equal", performance_width])
        settings = open_settings(page)
        expect(settings.locator("[data-leika-settings-rendering]")).to_contain_text("Performance")
        close_settings(page)
        select_rendering(page, "Auto")
        wait_width(page, ["equal", auto_width])
        assert image_width(other) == 1600
        before = [
            view.locator('[data-viewport-pane="image"] img').get_attribute("src")
            for view in (page, other)
        ]
        handle.update(source[::-1].copy())
        for view, previous in zip((page, other), before):
            view.wait_for_function(
                "old => document.querySelector('[data-viewport-pane=\"image\"] img').src !== old",
                arg=previous,
            )
        wait_width(page, ["equal", auto_width])
        wait_width(other, ["equal", 1600])
        np.testing.assert_array_equal(handle.image, source[::-1])
        before_resize = page.locator('[data-viewport-pane="image"] img').get_attribute("src")
        page.set_viewport_size({"width": 720, "height": 700})
        page.wait_for_function(
            "old => document.querySelector('[data-viewport-pane=\"image\"] img').src !== old",
            arg=before_resize,
        )
        wait_width(page, ["equal", auto_width])
        assert image_width(other) == 1600
    finally:
        context.close()
    assert page_errors == []


def test_auto_adapts_to_measured_link_speed_and_recovers(leika_server, page, browser, page_errors):
    source = np.random.default_rng(8).integers(0, 256, (600, 900, 3), np.uint8)
    pane = leika_server.panes.add_image(source, pane_id="image", format="jpeg", jpeg_quality=85)
    stop = threading.Event()
    failures = []

    def stream():
        try:
            while not stop.wait(0.15):
                pane.update(source)
        except Exception as error:
            failures.append(error)

    with slow_proxy(urlsplit(leika_server.url).port) as (url, slow):
        page.goto(url)
        wait_width(page, ["equal", 900])
        context = browser.new_context(viewport={"width": 720, "height": 700})
        worker = threading.Thread(target=stream, daemon=True)
        try:
            other = context.new_page()
            other.goto(leika_server.url)
            wait_width(other, ["equal", 900])
            slow.set()
            worker.start()
            wait_width(page, ["less", 900])
            assert image_width(page) >= 630  # Auto never discards more than 30% per axis.
            assert image_width(other) == 900  # A fast Auto viewer stays full resolution.
            slow.clear()
            wait_width(page, ["equal", 900])
            assert image_width(other) == 900
        finally:
            stop.set()
            if worker.ident is not None:
                worker.join(5)
            context.close()
    assert not worker.is_alive()
    assert failures == []
    assert page_errors == []
