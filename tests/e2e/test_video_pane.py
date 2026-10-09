from pathlib import Path

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
