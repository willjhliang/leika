from pathlib import Path

from playwright.sync_api import Page, expect

import leika

CLIP = Path(__file__).parent / "assets" / "video.mp4"


def test_video_live_replay_seek_and_player_identity(
    leika_page: Page, leika_server: leika.Server
) -> None:
    pane = leika_server.panes.add_video_gallery({"Task": CLIP}, pane_id="videos")
    video = leika_page.locator("video")
    expect(video).to_have_count(1)
    leika_page.wait_for_function('document.querySelector("video")?.currentTime > .1')
    video.evaluate("(v) => {window.originalVideo = v; v.pause(); v.currentTime = .8;}")
    pane.title = "Changed title"
    pane.update({"Renamed task": CLIP})
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
    pane = leika_server.panes.add_video_gallery({"Task": CLIP}, pane_id="videos")
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
