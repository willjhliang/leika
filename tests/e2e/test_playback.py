from __future__ import annotations

from playwright.sync_api import Browser, Page, expect

import leika


def test_custom_playback_commands_shared_state_and_reconnect(
    leika_server: leika.Server, page: Page, browser: Browser, page_errors: list[str]
) -> None:
    bar = leika_server.gui.add_playback(duration=10, fps=10)
    events: list[leika.PlaybackEvent] = []
    bar.on_update(events.append)
    page.goto(leika_server.url)
    expect(page.get_by_role("button", name="Play Playback", exact=True)).to_be_visible()
    page.get_by_role("button", name="Next frame Playback").evaluate(
        "el => { for (let i = 0; i < 5; i++) el.click(); }"
    )
    expect(page.get_by_role("slider", name="Seek Playback")).to_have_attribute(
        "aria-valuenow", "0.5"
    )
    page.get_by_role("button", name="Play Playback", exact=True).click()
    expect(page.get_by_role("button", name="Pause Playback", exact=True)).to_be_visible()
    assert bar.playing
    # The bar does not invent time while the application is busy.
    bar.buffering = True
    expect(page.get_by_role("status").filter(has_text="Preparing content")).to_be_attached()
    page.get_by_role("button", name="Pause Playback", exact=True).click()
    expect(page.get_by_role("button", name="Play Playback", exact=True)).to_be_visible()
    assert bar.time == 0.5 and not bar.playing
    bar.buffering = False
    seek = page.get_by_role("slider", name="Seek Playback")
    seek.focus()
    seek.press("End")
    expect(seek).to_have_attribute("aria-valuenow", "10")
    page.get_by_role("button", name="Previous frame Playback").click()
    expect(seek).to_have_attribute("aria-valuenow", "9.9")
    page.get_by_role("button", name="Loop Playback", exact=True).click()
    expect(page.get_by_role("button", name="Loop Playback", exact=True)).to_have_attribute(
        "aria-pressed", "false"
    )
    page.get_by_role("combobox", name="Playback playback speed").click()
    page.get_by_role("option", name="2×", exact=True).click()
    expect(page.get_by_role("combobox", name="Playback playback speed")).to_contain_text("2×")
    bar.update(time=3.2, playing=True)
    peer = browser.new_page()
    try:
        peer.goto(leika_server.url)
        expect(peer.get_by_role("slider", name="Seek Playback")).to_have_attribute(
            "aria-valuenow", "3.2"
        )
        peer.get_by_role("button", name="Pause Playback", exact=True).click()
        expect(page.get_by_role("button", name="Play Playback", exact=True)).to_be_visible()
        page.reload()
        expect(page.get_by_role("slider", name="Seek Playback")).to_have_attribute(
            "aria-valuenow", "3.2"
        )
        assert not bar.playing and bar.speed == 2
        bar.disabled = True
        expect(page.get_by_role("button", name="Play Playback", exact=True)).to_be_disabled()
        bar.remove()
        expect(page.get_by_role("group", name="Playback playback")).to_have_count(0)
    finally:
        peer.close()
    assert not page_errors
    assert [e.state.time for e in events[:5]] == [0.1, 0.2, 0.3, 0.4, 0.5]


def test_playback_reconnect_after_replacing_duration(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    bar = leika_server.gui.add_playback(duration=0, loop=True)
    bar.update(time=0, duration=0.85, fps=1 / 0.034, buffering=False)
    page.goto(leika_server.url)
    page.get_by_role("button", name="Next frame Playback").click()
    expect(page.get_by_role("slider", name="Seek Playback")).to_have_attribute(
        "aria-valuenow", "0.034"
    )
    for duration in (10, 0.85):
        bar.update(time=0, duration=0, playing=False, buffering=True)
        bar.update(time=0, duration=duration, fps=1 / 0.034, buffering=False)
        bar.update(time=0, duration=duration)
    page.reload()
    seek = page.get_by_role("slider", name="Seek Playback")
    expect(seek).to_have_attribute("aria-valuenow", "0")
    expect(seek).to_have_attribute("max", "0.85")
    page.get_by_role("button", name="Next frame Playback").click()
    expect(seek).to_have_attribute("aria-valuenow", "0.034")
    assert not page_errors
