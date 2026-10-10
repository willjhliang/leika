from pathlib import Path

from playwright.sync_api import Page, expect

import leika

CLIP = Path(__file__).parent / "assets" / "video.mp4"
VIDEOS = "[...document.querySelectorAll('video')]"


def setup_group(server: leika.Server):
    controls = server.gui.add_video_controls(sync_group="episode")
    grid = server.panes.add_grid(columns=2)
    panes = [
        grid.add_video(CLIP, title=f"Camera {i}", sync_group="episode", fps=10) for i in range(4)
    ]
    return controls, panes


def test_shared_dock_controls_seek_step_rate_and_fullscreen(
    leika_page: Page, leika_server: leika.Server, page_errors: list[str]
) -> None:
    setup_group(leika_server)
    page = leika_page
    page.wait_for_function(
        f"{VIDEOS}.length === 4 && {VIDEOS}.every(v => v.currentTime > .1 && !v.paused)"
    )
    expect(page.get_by_role("button", name="Pause Camera 0", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Pause Playback", exact=True).click()
    page.wait_for_function(f"{VIDEOS}.every(v => v.paused)")
    seek = page.get_by_role("slider", name="Seek Playback", exact=True)
    seek.focus()
    seek.press("Home")
    for _ in range(5):
        seek.press("ArrowRight")
    page.wait_for_function(f"{VIDEOS}.every(v => Math.abs(v.currentTime - .5) < .02 && !v.seeking)")
    page.get_by_role("button", name="Next frame Playback", exact=True).click()
    page.wait_for_function(f"{VIDEOS}.every(v => Math.abs(v.currentTime - .6) < .02)")
    page.get_by_role("button", name="Previous frame Playback", exact=True).click()
    page.wait_for_function(f"{VIDEOS}.every(v => Math.abs(v.currentTime - .5) < .02)")
    page.get_by_role("combobox", name="Playback playback speed").click()
    page.get_by_role("option", name="2×", exact=True).click()
    page.wait_for_function(f"{VIDEOS}.every(v => v.playbackRate === 2)")
    page.get_by_role("button", name="Fullscreen Camera 0", exact=True).click()
    page.wait_for_function("document.fullscreenElement !== null")
    page.get_by_role("button", name="Next frame Camera 0", exact=True).click()
    # Invisible fullscreen siblings retain the shared paused seek position.
    page.wait_for_function(f"{VIDEOS}.every(v => Math.abs(v.currentTime - .6) < .02)")
    page.get_by_role("button", name="Exit fullscreen Camera 0", exact=True).click()
    expect(seek).to_have_attribute("aria-valuenow", "0.6")
    assert not page_errors


def test_group_visibility_replacement_loop_and_client_isolation(
    leika_page: Page, leika_server: leika.Server, page_errors: list[str]
) -> None:
    controls, panes = setup_group(leika_server)
    page = leika_page
    page.wait_for_function(f"{VIDEOS}.length === 4 && {VIDEOS}.every(v => v.currentTime > .1)")
    # Hiding the dock control does not own or stop playback.
    controls.visible = False
    page.wait_for_timeout(200)
    assert page.evaluate(f"{VIDEOS}.every(v => !v.paused)")
    panes[1].visible = False
    page.wait_for_function(f"{VIDEOS}[1].paused && !{VIDEOS}[0].paused")
    page.wait_for_timeout(150)
    panes[1].visible = True
    page.wait_for_function(
        f"{VIDEOS}.every(v => !v.paused) && Math.max(...{VIDEOS}.map(v => v.currentTime)) - Math.min(...{VIDEOS}.map(v => v.currentTime)) < .08"
    )
    controls.visible = True
    page.get_by_role("button", name="Pause Playback", exact=True).click()
    other = page.context.new_page()
    try:
        other.goto(leika_server.url)
        other.wait_for_function(
            f"{VIDEOS}.length === 4 && {VIDEOS}.every(v => v.currentTime > .1 && !v.paused)"
        )
        assert page.evaluate(f"{VIDEOS}.every(v => v.paused)")
    finally:
        other.close()
    # Replacing media resets the common time, preserving manual pause.
    panes[0].update(leika_server.register_http_asset(CLIP) + "?new=1")
    page.wait_for_function(
        f"{VIDEOS}.every(v => v.readyState >= 3 && v.paused && v.currentTime < .02)"
    )
    seek = page.get_by_role("slider", name="Seek Playback", exact=True)
    seek.focus()
    seek.press("End")
    seek.press("ArrowLeft")
    page.get_by_role("button", name="Play Playback", exact=True).click()
    page.wait_for_function(
        f"{VIDEOS}.every(v => v.currentTime > .15 && v.currentTime < .7 && !v.paused)"
    )
    page.get_by_role("button", name="Loop Playback", exact=True).click()
    page.wait_for_function(f"{VIDEOS}.every(v => v.paused && v.currentTime >= v.duration - .08)")
    assert not page_errors


def test_loading_barrier_dock_collapse_and_membership_updates(
    leika_page: Page, leika_server: leika.Server, page_errors: list[str]
) -> None:
    controls, panes = setup_group(leika_server)
    page = leika_page
    page.wait_for_function(f"{VIDEOS}.length === 4 && {VIDEOS}.every(v => !v.paused)")
    panes[2].loading = "Preparing next camera"
    page.wait_for_function(f"{VIDEOS}.every(v => v.paused)")
    time = float(page.get_by_role("slider", name="Seek Playback", exact=True).input_value())
    page.wait_for_timeout(200)
    assert abs(float(page.get_by_role("slider", name="Seek Playback").input_value()) - time) < 0.02
    panes[2].loading = False
    page.wait_for_function(f"{VIDEOS}.every(v => !v.paused)")
    header = page.get_by_test_id("control-panel").locator("[data-leika-panel-header]")
    header.click(position={"x": 30, "y": 12})
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1)
    page.wait_for_timeout(200)
    assert page.evaluate(f"{VIDEOS}.every(v => !v.paused)")
    page.wait_for_timeout(400)  # Outside the header double-click interval.
    header.click(position={"x": 30, "y": 12})
    expect(page.locator("[data-dock-collapsed]")).to_have_count(0)
    panes[3].fps = 20
    expect(page.get_by_role("button", name="Next frame Playback", exact=True)).to_have_count(0)
    panes[3].sync_group = None
    expect(page.get_by_role("button", name="Next frame Playback", exact=True)).to_have_count(1)
    page.get_by_role("button", name="Pause Playback", exact=True).click()
    page.wait_for_function(f"{VIDEOS}.slice(0,3).every(v => v.paused) && !{VIDEOS}[3].paused")
    for pane in panes:
        pane.remove()
    expect(page.locator("video")).to_have_count(0)
    expect(page.get_by_role("button", name="Play Playback", exact=True)).to_be_disabled()
    controls.remove()
    expect(page.get_by_role("group", name="Playback playback", exact=True)).to_have_count(0)
    assert not page_errors


def test_dock_label_selects_standard_row_layout_without_resetting_playback(
    leika_page: Page, leika_server: leika.Server, page_errors: list[str]
) -> None:
    controls, _ = setup_group(leika_server)
    leika_server.gui.add_text("Reference", "x")
    page = leika_page
    page.wait_for_function(f"{VIDEOS}.length === 4 && {VIDEOS}.every(v => v.readyState >= 3)")
    full = page.get_by_role("group", name="Playback playback", exact=True)
    full.get_by_role("button", name="Pause Playback", exact=True).click()
    seek = full.get_by_role("slider")
    seek.focus()
    seek.press("Home")
    for _ in range(5):
        seek.press("ArrowRight")
    page.wait_for_function(f"{VIDEOS}.every(v => Math.abs(v.currentTime - .5) < .02)")
    full.get_by_role("combobox").click()
    page.get_by_role("option", name="1.5×", exact=True).click()
    full.get_by_role("button", name="Loop Playback", exact=True).click()
    expect(full.locator("span.tabular-nums")).to_have_text("0:00")
    expect(full.get_by_role("button", name="Next frame Playback", exact=True)).to_be_visible()
    assert full.bounding_box()["height"] == 32

    def assert_fits(bar):
        geometry = bar.evaluate("""el => {
            const row = el.getBoundingClientRect();
            const slider = el.querySelector('[data-slot="slider"]').getBoundingClientRect();
            const buttons = [...el.querySelectorAll('button')].map(b => b.getBoundingClientRect());
            return {sliderWidth: slider.width,
                fits: buttons.every(b => b.left >= row.left && b.right <= row.right &&
                    b.top >= row.top && b.bottom <= row.bottom)};
        }""")
        assert geometry["sliderWidth"] >= 40, geometry
        assert geometry["fits"], geometry

    assert_fits(full)
    controls.label = "Timeline"
    compact = page.get_by_role("group", name="Timeline playback", exact=True)
    expect(compact.get_by_role("button", name="Play Timeline", exact=True)).to_be_visible()
    expect(compact.get_by_role("button")).to_have_count(2)  # Play and loop; speed is a combobox.
    expect(compact.locator("span.tabular-nums")).to_have_count(0)
    expect(compact.locator('[data-slot="select-value"]')).to_have_text("1.5×")
    expect(compact.get_by_role("button", name="Loop Timeline", exact=True)).to_have_attribute(
        "aria-pressed", "false"
    )
    labelled_row = compact.locator("xpath=ancestor::*[@data-leika-gui-row]")
    assert labelled_row.bounding_box()["height"] == 24
    reference = page.get_by_role("textbox", name="Reference")
    assert compact.bounding_box()["x"] == reference.bounding_box()["x"]
    assert_fits(compact)
    compact.get_by_role("slider").focus()
    compact.get_by_role("slider").press("ArrowRight")
    page.wait_for_function(f"{VIDEOS}.every(v => v.paused && Math.abs(v.currentTime - .6) < .02)")

    controls.label = None
    expect(full.get_by_role("button", name="Next frame Playback", exact=True)).to_be_visible()
    expect(full.locator('[data-slot="select-value"]')).to_have_text("1.5×")
    expect(full.get_by_role("slider")).to_have_attribute("aria-valuenow", "0.6")
    assert full.bounding_box()["height"] == 32
    assert not page_errors
