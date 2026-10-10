"""Empty slots and renderer transitions preserve the browser workspace."""

from pathlib import Path

import numpy as np
from playwright.sync_api import expect

CLIP = Path(__file__).parent / "assets" / "video.mp4"


def geometry(page):
    return page.locator("[data-viewport-pane]").evaluate_all("""els => Object.fromEntries(els.map(e => {
      const r=e.getBoundingClientRect();
      return [e.dataset.viewportPane, [r.x,r.y,r.width,r.height]];
    }))""")


def test_empty_slots_release_players_and_keep_layout_on_replay(
    leika_page, leika_server, page_errors
):
    page, server = leika_page, leika_server
    server.gui.add_video_controls(sync_group="episode")
    grid = server.panes.add_grid(columns=2)
    panes = [grid.add_pane(pane_id=f"slot-{i}", title=f"Camera {i}") for i in range(4)]
    expect(page.locator("[data-viewport-pane]")).to_have_count(4)
    expect(page.locator("video")).to_have_count(0)
    expect(page.get_by_role("button", name="Play Playback", exact=True)).to_be_disabled()
    baseline = geometry(page)
    assert baseline["slot-0"][1] == baseline["slot-1"][1]
    assert baseline["slot-2"][1] == baseline["slot-3"][1] > baseline["slot-0"][1]
    for pane in reversed(panes[:3]):
        pane.set_video(CLIP, sync_group="episode", fps=10)
    page.wait_for_function(
        "document.querySelectorAll('video').length === 3 && [...document.querySelectorAll('video')].every(v => v.readyState >= 3 && !v.paused)"
    )
    empty = page.locator('[data-viewport-pane="slot-3"]')
    empty.hover()
    expect(empty.locator("[data-viewport-pane-renderer] > *")).to_have_count(0)
    page.get_by_role("button", name="Pause Playback", exact=True).click()
    page.wait_for_function("[...document.querySelectorAll('video')].every(v => v.paused)")
    page.evaluate('window.retired = document.querySelector("video")')
    panes[0].clear()
    expect(page.locator("video")).to_have_count(2)
    page.wait_for_function("!window.retired.isConnected && window.retired.paused")
    panes[0].set_image(np.full((30, 40, 3), 127, np.uint8))
    expect(page.locator('[data-viewport-pane="slot-0"] img')).to_have_count(1)
    assert geometry(page) == baseline
    # A fresh browser has no saved layout; reverse content publication must not
    # alter the stable grid declaration order on initial replay.
    context = page.context.browser.new_context(
        viewport={"width": 960, "height": 700}, reduced_motion="reduce"
    )
    try:
        fresh = context.new_page()
        fresh.on("pageerror", lambda error: page_errors.append(str(error)))
        fresh.goto(server.url)
        expect(fresh.locator("[data-viewport-pane]")).to_have_count(4)
        expect(fresh.locator("video")).to_have_count(2)
        assert geometry(fresh) == baseline
        fresh.reload()
        expect(fresh.locator("video")).to_have_count(2)
        assert geometry(fresh) == baseline
    finally:
        context.close()
    for pane in panes:
        pane.clear()
    expect(page.locator("video, [data-viewport-pane] img")).to_have_count(0)
    expect(page.get_by_role("button", name="Play Playback", exact=True)).to_be_disabled()
    assert geometry(page) == baseline
    assert not page_errors


def test_clear_releases_iframe_and_preserves_loading_bindings(
    leika_page, leika_server, page_errors
):
    page, server = leika_page, leika_server
    page.route(
        "https://pane.example.test/**",
        lambda route: route.fulfill(body="<html>Scene</html>", content_type="text/html"),
    )
    selection = server.gui.add_checkbox("Selection", initial_value=False)
    pane = server.panes.add_pane(pane_id="preview", title="Preview")
    pane.invalidate_on(selection)
    pane.set_viser("https://pane.example.test/")
    expect(page.locator("iframe")).to_have_count(1)
    page.evaluate('window.retired = document.querySelector("iframe")')
    pane.clear(loading="Preparing")
    expect(page.locator("iframe")).to_have_count(0)
    expect(page.get_by_text("Preparing", exact=True)).to_be_visible()
    assert page.evaluate("!window.retired.isConnected")
    pane.set_video(CLIP, loading=False)
    page.wait_for_function('document.querySelector("video")?.readyState >= 3')

    @selection.on_update
    def _(_):
        pane.clear(loading="Waiting")

    page.get_by_role("checkbox", name="Selection", exact=True).click()
    expect(page.locator("video")).to_have_count(0)
    expect(page.get_by_text("Waiting", exact=True)).to_be_visible()
    pane.set_image(np.zeros((10, 12, 3), np.uint8), loading=False)
    expect(page.locator('[data-viewport-pane="preview"] img')).to_be_visible()
    expect(page.get_by_text("Waiting", exact=True)).to_have_count(0)
    assert not page_errors
