"""A lost transport must recover without navigating or refreshing the page."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

import leika

from .test_connection_pane import open_connection, row
from .utils import find_gui_input, wait_until

LABEL = "[data-leika-connection-label]"
READY = '[data-viewport-workspace][aria-busy="false"]'


def set_visibility(page: Page, visibility: str) -> None:
    # Headless browsers do not consistently model background tabs. Dispatch
    # the browser event with its corresponding document state explicitly.
    page.evaluate(
        """visibility => {
            Object.defineProperty(document, "visibilityState", {
                configurable: true,
                value: visibility,
            });
            document.dispatchEvent(new Event("visibilitychange"));
        }""",
        visibility,
    )


@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("failure", ["fatal", "error"])
def test_failed_worker_is_replaced_without_reloading(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
    failure: str,
    background: bool,
) -> None:
    slider = leika_server.gui.add_slider("Recovered gain", 0.5, min=0.0, max=1.0, step=0.1)
    control = find_gui_input(leika_page, "Recovered gain")
    expect(control).to_have_value("0.5")
    popover = open_connection(leika_page)
    expect(row(popover, "Latency")).to_contain_text("ms", timeout=10_000)
    if background:
        set_visibility(leika_page, "hidden")
    previous_clients = set(leika_server.clients)
    leika_page.evaluate("() => { window.reconnectPageMarker = 'same document'; }")
    worker = leika_page.workers[0]

    # Exercise both failure channels delivered by a real Web Worker. Delay
    # the fault so evaluate can return before the owner terminates the worker.
    worker.evaluate(
        """failure => {
            setTimeout(() => {
                if (failure === "error") throw new Error("Test worker interruption");
                self.postMessage({type: "fatal", reason: "Test worker interruption"});
            }, 50);
        }""",
        failure,
    )

    expect(leika_page.locator(LABEL)).to_have_text(
        "Inactive" if background else "Connecting...", timeout=5_000
    )
    expect(popover.locator("[data-leika-connection-error]")).to_contain_text(
        "Test worker interruption"
    )
    if background:
        leika_page.wait_for_timeout(1_200)
        assert len(leika_server.clients) == 0
        set_visibility(leika_page, "visible")
    expect(leika_page.locator(LABEL)).to_have_text("Connected", timeout=15_000)
    expect(popover.locator("[data-leika-connection-error]")).to_have_count(0)
    expect(row(popover, "Latency")).to_contain_text("ms", timeout=10_000)
    expect(leika_page.locator(READY)).to_be_visible()
    expect(control).to_have_value("0.5")
    assert leika_page.evaluate("() => window.reconnectPageMarker") == "same document"
    wait_until(
        lambda: len(leika_server.clients) == 1 and not previous_clients & set(leika_server.clients)
    )

    leika_page.keyboard.press("Escape")
    control.fill("0.8")
    control.press("Enter")
    wait_until(lambda: slider.value == 0.8)
    assert page_errors == []


@pytest.mark.parametrize("background", [False, True])
def test_server_restart_reconnects_when_visible_without_window_focus(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str], background: bool
) -> None:
    # A visible page can lack focus while the user is in browser chrome, an
    # embedded pane, or another window. Its retries must still be allowed.
    leika_page.evaluate(
        """() => {
            window.reconnectPageMarker = 'same document';
            Object.defineProperty(document, "hasFocus", {
                configurable: true,
                value: () => false,
            });
        }"""
    )
    set_visibility(leika_page, "hidden" if background else "visible")
    leika_server.stop()
    expect(leika_page.locator(LABEL)).to_have_text(
        "Inactive" if background else "Connecting...", timeout=15_000
    )

    with leika.Server(host="127.0.0.1", port=leika_server.port, verbose=False) as restarted:
        restarted.gui.add_slider("Restarted gain", 0.3, min=0.0, max=1.0, step=0.1)
        if background:
            leika_page.wait_for_timeout(1_200)
            assert len(restarted.clients) == 0
            set_visibility(leika_page, "visible")

        expect(leika_page.locator(LABEL)).to_have_text("Connected", timeout=15_000)
        expect(leika_page.locator(READY)).to_be_visible()
        expect(find_gui_input(leika_page, "Restarted gain")).to_have_value("0.3")
        assert leika_page.evaluate("() => window.reconnectPageMarker") == "same document"
        assert page_errors == []


def test_failed_retry_command_recovers_and_ignores_the_old_worker(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    page.add_init_script(
        """(() => {
            const BrowserWorker = window.Worker;
            window.connectionTestWorkers = [];
            window.Worker = class extends BrowserWorker {
                constructor(...args) {
                    super(...args);
                    window.connectionTestWorkers.push(this);
                }
            };
        })();"""
    )
    slider = leika_server.gui.add_slider("Recovered gain", 0.5, min=0.0, max=1.0, step=0.1)
    page.goto(leika_server.url)
    expect(page.locator(READY)).to_be_visible(timeout=15_000)
    page.evaluate(
        """() => {
            const worker = window.connectionTestWorkers[0];
            window.staleWorkerCallbacks = {
                message: worker.onmessage,
                error: worker.onerror,
                messageerror: worker.onmessageerror,
            };
            worker.postMessage = () => {
                throw new DOMException("Test command failure", "DataCloneError");
            };
            // A close starts a retry immediately; that command fails inside
            // the disconnect handler, before it returns to the browser.
            worker.dispatchEvent(new MessageEvent("message", {data: {
                type: "closed", closeKind: "socket", closeReason: "Test close",
            }}));
        }"""
    )
    expect(page.locator(LABEL)).to_have_text("Connecting...")
    expect(page.locator(LABEL)).to_have_text("Connected", timeout=15_000)
    expect(page.locator(READY)).to_be_visible()
    page.evaluate(
        """() => {
            const stale = window.staleWorkerCallbacks;
            stale.message({data: {type: "fatal", reason: "Stale failure"}});
            stale.message({data: {type: "closed", closeKind: "version_mismatch",
                                  closeReason: "Stale close"}});
            stale.error(new ErrorEvent("error", {message: "Stale error"}));
            stale.messageerror(new MessageEvent("messageerror"));
        }"""
    )
    # Wait past another retry tick to expose duplicate timers or a stale
    # failure accidentally replacing the newly connected worker.
    page.wait_for_timeout(1_200)
    expect(page.locator(LABEL)).to_have_text("Connected")
    assert page.evaluate("() => window.connectionTestWorkers.length") == 2
    control = find_gui_input(page, "Recovered gain")
    control.fill("0.8")
    control.press("Enter")
    wait_until(lambda: slider.value == 0.8)
    assert page_errors == []


@pytest.mark.parametrize("failure", ["socket", "worker"])
@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("grouped", [False, True])
def test_reconnect_preserves_renderers_and_reconciles_content(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
    failure: str,
    background: bool,
    grouped: bool,
) -> None:
    from .test_video_pane import CLIP

    group = "episode" if grouped else None
    if grouped:
        leika_server.gui.add_video_controls("Playback", sync_group=group)
    video_pane = leika_server.panes.add_video(
        CLIP,
        pane_id="video",
        title="Task",
        sync_group=group,
        fps=10,
    )
    removed = leika_server.panes.add_video(CLIP, pane_id="removed", sync_group=group, fps=10)
    scene = leika_server.panes.add_viser(leika_server.url + "/missing-scene", pane_id="scene")
    slider = leika_server.gui.add_slider("Gain", 0.5, min=0.0, max=1.0, step=0.1)
    page.goto(leika_server.url)
    expect(page.locator(READY)).to_be_visible(timeout=15_000)
    video = page.locator('[data-viewport-pane="video"] video')
    expect(video).to_have_count(1)
    page.wait_for_function('document.querySelector("video")?.readyState >= 3')
    video.evaluate("""v => {
        window.keptVideo = v; v.pause(); v.currentTime = .8; v.playbackRate = 1.5;
        window.keptFrame = document.querySelector('iframe');
    }""")
    label = "Playback" if grouped else "Task"
    page.get_by_role("button", name=f"Loop {label}", exact=True).click()
    frame = page.locator("iframe").element_handle().content_frame()
    frame.evaluate("window.reconnectMarker = 'kept'")
    old_clients = set(leika_server.clients)
    worker = page.workers[0]
    # Catch the next real send, then close the real socket. Visibility sync
    # sends even while hidden; transport retries wait until the tab returns.
    if failure == "socket":
        worker.evaluate("""() => {
            const send = WebSocket.prototype.send;
            WebSocket.prototype.send = function(...args) {
                WebSocket.prototype.send = send;
                send.apply(this, args);
                setTimeout(() => this.close(1000, 'Test socket interruption'), 50);
            };
        }""")
    else:
        worker.evaluate("""() => {
            setTimeout(() => self.postMessage({type:'fatal', reason:'Test interruption'}), 50);
        }""")
    set_visibility(page, "hidden")
    expect(page.locator(LABEL)).to_have_text("Inactive", timeout=10_000)
    assert video.evaluate("v => v === window.keptVideo")
    assert page.evaluate("window.keptFrame === document.querySelector('iframe')")
    removed.remove()
    video_pane.title = "Replayed video"
    if not background:
        set_visibility(page, "visible")
    else:
        page.wait_for_timeout(1_200)
        assert not leika_server.clients
        set_visibility(page, "visible")
    expect(page.locator(LABEL)).to_have_text("Connected", timeout=15_000)
    expect(page.locator(READY)).to_be_visible()
    expect(page.locator("video")).to_have_count(1)
    expect(video).to_have_attribute("aria-label", "Replayed video")
    assert video.evaluate("""v => v === window.keptVideo && v.paused &&
        Math.abs(v.currentTime - .8) < .05 && v.playbackRate === 1.5""")
    assert page.evaluate("window.keptFrame === document.querySelector('iframe')")
    assert frame.evaluate("window.reconnectMarker") == "kept"
    label = "Playback" if grouped else "Replayed video"
    expect(page.get_by_role("button", name=f"Loop {label}", exact=True)).to_have_attribute(
        "aria-pressed", "false"
    )
    page.get_by_role("button", name=f"Next frame {label}", exact=True).click()
    page.wait_for_function('Math.abs(document.querySelector("video").currentTime - .9) < .02')
    assert (page.workers[0] == worker) == (failure == "socket")
    wait_until(
        lambda: len(leika_server.clients) == 1 and not old_clients & set(leika_server.clients)
    )
    client = next(iter(leika_server.clients.values()))
    # The preserved host must report dimensions using the new connection.
    wait_until(lambda: client.pane_size(video_pane) is not None)
    control = find_gui_input(page, "Gain")
    control.fill("0.8")
    control.press("Enter")
    wait_until(lambda: slider.value == 0.8)
    scene.update(leika_server.url + "/changed-scene")
    page.wait_for_function("window.keptFrame !== document.querySelector('iframe')")
    assert page_errors == []
