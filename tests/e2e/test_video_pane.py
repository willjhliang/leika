from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

import leika

CLIP = Path(__file__).parent / "assets" / "video.mp4"


def test_video_live_replay_seek_and_player_identity(
    leika_page: Page, leika_server: leika.Server
) -> None:
    pane = leika_server.panes.add_video(CLIP, pane_id="video", title="Task")
    video = leika_page.locator("video")
    expect(video).to_have_count(1)
    leika_page.wait_for_function('document.querySelector("video")?.currentTime > .1')
    video.evaluate("(v) => {window.originalVideo = v; v.pause(); v.currentTime = .8;}")
    pane.title = "Renamed task"
    pane.update(CLIP)
    expect(video).to_have_attribute("aria-label", "Renamed task")
    assert video.evaluate(
        "(v) => v === window.originalVideo && v.paused && Math.abs(v.currentTime - .8) < .1"
    )
    # Replay the same declaration into a newly connecting browser.
    other = leika_page.context.new_page()
    try:
        other.goto(leika_server.url)
        other.wait_for_function('document.querySelector("video")?.currentTime > .1')
        expect(other.locator("video")).to_have_attribute("aria-label", "Renamed task")
    finally:
        other.close()
    pane.remove()
    expect(video).to_have_count(0)


def test_video_manual_pause_survives_visibility(
    leika_page: Page, leika_server: leika.Server
) -> None:
    pane = leika_server.panes.add_video(CLIP, pane_id="video", title="Task")
    video = leika_page.locator("video")
    leika_page.wait_for_function('document.querySelector("video")?.currentTime > .1')
    video.evaluate("(v) => { window.pausedVideo = v; v.pause(); }")
    pane.visible = False
    expect(video).not_to_be_visible()
    pane.visible = True
    expect(video).to_be_visible()
    leika_page.wait_for_timeout(300)
    assert video.evaluate("(v) => v === window.pausedVideo && v.paused")

    video.evaluate("(v) => v.play()")
    pane.visible = False
    leika_page.wait_for_function('document.querySelector("video").paused')
    pane.visible = True
    leika_page.wait_for_function('!document.querySelector("video").paused')


def test_video_grid_players_are_independent(leika_page: Page, leika_server: leika.Server) -> None:
    grid = leika_server.panes.add_grid(columns=2)
    first = grid.add_video(CLIP, pane_id="first", title="First")
    second = grid.add_video(CLIP, pane_id="second", title="Second")
    leika_page.wait_for_function(
        "document.querySelectorAll('video').length === 2 && "
        "[...document.querySelectorAll('video')].every(v => v.currentTime > .1)"
    )
    videos = leika_page.locator("video")
    leika_page.evaluate("window.players = [...document.querySelectorAll('video')]")
    videos.nth(0).evaluate("v => { v.pause(); v.currentTime = .5; }")
    first.update(CLIP, loading=False)
    second.title = "Other title"
    leika_page.wait_for_timeout(300)
    assert leika_page.evaluate(
        "[...document.querySelectorAll('video')].every((v, i) => v === window.players[i])"
    )
    assert videos.nth(0).evaluate("v => v.paused && Math.abs(v.currentTime - .5) < .1")
    assert videos.nth(1).evaluate("v => !v.paused")
    bounds = [v.bounding_box() for v in (videos.nth(0), videos.nth(1))]
    assert bounds[0] and bounds[1] and bounds[0]["x"] < bounds[1]["x"]
    # Changing one source replaces only that player's media instance.
    second.update(leika_server.register_http_asset(CLIP) + "?replacement=1")
    leika_page.wait_for_function("document.querySelectorAll('video')[1] !== window.players[1]")
    assert videos.nth(0).evaluate("v => v === window.players[0] && v.paused")


def test_video_compact_controls(leika_page: Page, leika_server: leika.Server) -> None:
    pane = leika_server.panes.add_video(CLIP, title="Task", autoplay=False, loop=False, fps=10)
    video = leika_page.locator("video")
    bar = leika_page.get_by_role("group", name="Task playback", exact=True)
    play = leika_page.get_by_role("button", name="Play Task", exact=True)
    seek = leika_page.get_by_role("slider", name="Seek Task", exact=True)
    leika_page.wait_for_function('document.querySelector("video")?.readyState >= 2')
    video.evaluate("v => { window.originalVideo = v; }")
    assert not video.evaluate("v => v.controls")
    leika_page.mouse.move(-1, -1)
    expect(bar).to_have_css("opacity", "0")
    video.hover()
    expect(bar).to_have_css("opacity", "1")
    bar.hover()
    expect(bar).to_have_css("opacity", "1")
    play.click()
    leika_page.wait_for_function('!document.querySelector("video").paused')
    leika_page.get_by_role("button", name="Pause Task", exact=True).click()
    leika_page.wait_for_function('document.querySelector("video").paused')

    # Clicking a control must not pin the bar open through retained focus.
    expect(play).to_be_focused()
    video.hover()
    expect(bar).to_have_css("opacity", "1")
    leika_page.mouse.move(-1, -1)
    expect(bar).to_have_css("opacity", "0")
    seek.focus()
    expect(bar).to_have_css("opacity", "0")
    seek.press("Home")
    seek.press("ArrowRight")
    leika_page.wait_for_function('Math.abs(document.querySelector("video").currentTime - .1) < .01')
    track = bar.locator('[data-slot="slider-track"]').bounding_box()
    assert track is not None
    leika_page.mouse.click(track["x"] + track["width"] * 0.75, track["y"] + track["height"] / 2)
    leika_page.wait_for_function(
        'Math.abs(document.querySelector("video").currentTime / '
        'document.querySelector("video").duration - .75) < .1'
    )
    assert video.evaluate("v => v.paused")

    leika_page.get_by_role("combobox", name="Task playback speed", exact=True).click()
    leika_page.mouse.move(-1, -1)
    expect(bar).to_have_css("opacity", "0")
    leika_page.get_by_role("option", name="2×", exact=True).click()
    video.hover()
    expect(bar).to_have_css("opacity", "1")
    leika_page.wait_for_function('document.querySelector("video").playbackRate === 2')
    pane.title = "Renamed"
    pane.update(CLIP)
    expect(
        leika_page.get_by_role("combobox", name="Renamed playback speed").locator(
            '[data-slot="select-value"]'
        )
    ).to_have_text("2×")
    assert video.evaluate("v => v === window.originalVideo && v.paused && v.playbackRate === 2")

    # Independent videos expose the same stepping and loop controls as groups.
    seek = leika_page.get_by_role("slider", name="Seek Renamed", exact=True)
    seek.focus()
    seek.press("Home")
    leika_page.get_by_role("button", name="Next frame Renamed", exact=True).click()
    leika_page.wait_for_function('Math.abs(document.querySelector("video").currentTime - .1) < .01')
    leika_page.get_by_role("button", name="Previous frame Renamed", exact=True).click()
    leika_page.wait_for_function('document.querySelector("video").currentTime < .01')
    loop = leika_page.get_by_role("button", name="Loop Renamed", exact=True)
    expect(loop).to_have_attribute("aria-pressed", "false")
    loop.click()
    expect(loop).to_have_attribute("aria-pressed", "true")
    loop.click()

    # Finish seeking before a native play request; seeks may pause the decoder.
    video.evaluate("""async v => {
        v.currentTime = v.duration - .1;
        await new Promise(resolve => v.addEventListener('seeked', resolve, {once:true}));
        await v.play();
    }""")
    leika_page.wait_for_function('document.querySelector("video").ended')
    play = leika_page.get_by_role("button", name="Play Renamed", exact=True)
    play.focus()
    play.press("Space")
    leika_page.wait_for_function(
        '!document.querySelector("video").paused && !document.querySelector("video").ended'
    )


def test_video_controls_are_optional_and_independent(
    leika_page: Page, leika_server: leika.Server
) -> None:
    grid = leika_server.panes.add_grid(columns=2)
    grid.add_video(CLIP, title="First")
    grid.add_video(CLIP, title="Second", controls=False)
    leika_page.wait_for_function(
        "document.querySelectorAll('video').length === 2 && "
        "[...document.querySelectorAll('video')].every(v => v.currentTime > .1)"
    )
    videos = leika_page.locator("video")
    videos.nth(0).hover()
    leika_page.get_by_role("button", name="Pause First", exact=True).click()
    assert videos.nth(0).evaluate("v => v.paused")
    assert videos.nth(1).evaluate("v => !v.paused && !v.controls")
    expect(leika_page.get_by_role("group", name="Second playback")).to_have_count(0)
    leika_page.get_by_role("combobox", name="First playback speed", exact=True).click()
    leika_page.get_by_role("option", name="0.5×", exact=True).click()
    leika_page.wait_for_function('document.querySelector("video").playbackRate === .5')
    assert videos.nth(1).evaluate("v => v.playbackRate === 1 && !v.paused")


def test_video_touch_controls(leika_page: Page, leika_server: leika.Server) -> None:
    leika_server.panes.add_video(CLIP, title="Touch", autoplay=False)
    browser = leika_page.context.browser
    assert browser is not None
    context = browser.new_context(
        viewport={"width": 390, "height": 700}, has_touch=True, is_mobile=True
    )
    try:
        page = context.new_page()
        page.goto(leika_server.url)
        bar = page.get_by_role("group", name="Touch playback", exact=True)
        expect(bar).to_have_css("opacity", "1")
        page.get_by_role("button", name="Play Touch", exact=True).tap()
        page.wait_for_function('!document.querySelector("video").paused')
        page.get_by_role("button", name="Pause Touch", exact=True).tap()
        page.wait_for_function('document.querySelector("video").paused')
    finally:
        context.close()


def test_video_fullscreen_keeps_player_and_controls(
    leika_page: Page, leika_server: leika.Server
) -> None:
    leika_server.panes.add_video(CLIP, title="Task", autoplay=False)
    video = leika_page.locator("video")
    bar = leika_page.get_by_role("group", name="Task playback", exact=True)
    leika_page.wait_for_function('document.querySelector("video")?.readyState >= 2')
    video.evaluate("v => { window.originalVideo = v; v.currentTime = .5; }")
    leika_page.get_by_role("button", name="Fullscreen Task", exact=True).click()
    leika_page.wait_for_function(
        'document.fullscreenElement === document.querySelector("video").parentElement'
    )
    assert video.evaluate(
        "v => v === window.originalVideo && v.paused && Math.abs(v.currentTime - .5) < .01"
    )
    video.hover()
    expect(bar).to_have_css("opacity", "1")
    bar.hover()
    expect(bar).to_have_css("opacity", "1")
    leika_page.get_by_role("combobox", name="Task playback speed", exact=True).click()
    option = leika_page.get_by_role("option", name="0.5×", exact=True)
    expect(option).to_be_visible()
    assert option.evaluate("e => document.fullscreenElement.contains(e)")
    option.click()
    leika_page.wait_for_function('document.querySelector("video").playbackRate === .5')
    leika_page.get_by_role("button", name="Exit fullscreen Task", exact=True).click()
    leika_page.wait_for_function("document.fullscreenElement === null")
    assert video.evaluate("v => v === window.originalVideo && v.paused && v.playbackRate === .5")
    leika_page.get_by_role("button", name="Fullscreen Task", exact=True).click()
    leika_page.wait_for_function("document.fullscreenElement !== null")
    # Browser-initiated exits must update the icon/label as well as our button.
    leika_page.evaluate("document.exitFullscreen()")
    expect(leika_page.get_by_role("button", name="Fullscreen Task", exact=True)).to_have_count(1)
    assert video.evaluate("v => v === window.originalVideo && v.paused")


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [1080, 720])
def test_video_control_hover_geometry(
    leika_page: Page, leika_server: leika.Server, theme: str, width: int
) -> None:
    leika_server.gui.configure_theme(theme=theme)
    grid = leika_server.panes.add_grid(columns=3)
    for i in range(3):
        grid.add_video(CLIP, title=f"Task {i}", autoplay=False)
    leika_page.set_viewport_size({"width": width, "height": 700})
    leika_page.wait_for_function(
        "dark => document.documentElement.classList.contains('dark') === dark", arg=theme == "dark"
    )
    video = leika_page.locator("video").first
    bar = leika_page.get_by_role("group", name="Task 0 playback", exact=True)
    video.hover()
    expect(bar).to_have_css("opacity", "1")
    controls = [
        bar.get_by_role("button", name="Play Task 0", exact=True),
        bar.get_by_role("combobox"),
        bar.get_by_role("button", name="Fullscreen Task 0", exact=True),
    ]
    backgrounds = []
    for control in controls:
        control.hover()
        leika_page.wait_for_timeout(200)  # Let the shared hover-color transition finish.
        backgrounds.append(
            control.evaluate("""e => {
            const r = e.getBoundingClientRect(), s = getComputedStyle(e);
            const insetTop = s.backgroundClip === 'padding-box' ? parseFloat(s.borderTopWidth) : 0;
            const insetBottom = s.backgroundClip === 'padding-box' ? parseFloat(s.borderBottomWidth) : 0;
            return {boxHeight:r.height, paintedTop:r.top + insetTop,
                paintedHeight:r.height - insetTop - insetBottom,
                color:s.backgroundColor, radius:s.borderTopLeftRadius};
        }""")
        )
    # Equal outer heights alone miss backgrounds painted over transparent borders.
    assert backgrounds[0] == backgrounds[1] == backgrounds[2], backgrounds
    assert backgrounds[0]["boxHeight"] == 24
    assert backgrounds[0]["paintedHeight"] == 22
    for rate in (1, 0.25):
        video.evaluate("(v, rate) => { v.playbackRate = rate; }", rate)
        expect(controls[1].locator('[data-slot="select-value"]')).to_have_text(f"{rate}×")
        gaps = bar.evaluate("""bar => {
            const box = selector => bar.querySelector(selector).getBoundingClientRect();
            const play = box('button[data-slot="button"] svg');
            const track = box('[data-slot="slider-track"]');
            const time = document.createRange();
            time.selectNodeContents(bar.querySelector('span[aria-hidden="true"]'));
            const text = time.getBoundingClientRect();
            const speedText = box('[data-slot="select-value"]');
            const loop = box('button[title="Loop"] svg');
            const fullscreen = [...bar.querySelectorAll('button[data-slot="button"] svg')].at(-1).getBoundingClientRect();
            return [track.left - play.right, text.left - track.right,
                speedText.left - text.right, loop.left - speedText.right,
                fullscreen.left - loop.right];
        }""")
        assert gaps == pytest.approx([12] * len(gaps), abs=0.5), gaps
