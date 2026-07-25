from __future__ import annotations

import time

from playwright.sync_api import Browser, expect

import leika

from .utils import find_gui_input


def test_values_synchronize_and_disconnects_are_removed(
    browser: Browser, leika_server: leika.Server
) -> None:
    slider = leika_server.gui.add_slider(
        "Shared gain", min=0.0, max=10.0, step=0.1, initial_value=1.0
    )
    context = browser.new_context(viewport={"width": 800, "height": 600}, reduced_motion="reduce")
    first = context.new_page()
    second = context.new_page()
    errors: list[str] = []
    first.on("pageerror", lambda error: errors.append(str(error)))
    second.on("pageerror", lambda error: errors.append(str(error)))
    try:
        for page in (first, second):
            page.goto(leika_server.url)
            page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
            page.wait_for_function(
                "() => !document.body.innerText.includes('Connecting...')",
                timeout=15_000,
            )
        deadline = time.monotonic() + 3.0
        while len(leika_server.clients) != 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(leika_server.clients) == 2

        source = find_gui_input(first, "Shared gain")
        observer = find_gui_input(second, "Shared gain")
        source.fill("7.5")
        source.press("Enter")
        expect(observer).to_have_value("7.5", timeout=5_000)
        deadline = time.monotonic() + 2.0
        while slider.value != 7.5 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert slider.value == 7.5

        first.close()
        deadline = time.monotonic() + 3.0
        while len(leika_server.clients) != 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(leika_server.clients) == 1
        assert errors == []
    finally:
        context.close()
