"""Actual browser selection barriers while old frames cross a slow TCP link."""

from __future__ import annotations

import json
import select
import socket
import socketserver
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

import numpy as np
from playwright.sync_api import expect


@contextmanager
def slow_proxy(port):
    slow = threading.Event()
    stop = threading.Event()

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            with socket.create_connection(("127.0.0.1", port)) as remote:
                try:
                    while not stop.is_set():
                        readable, _, _ = select.select((self.request, remote), (), (), 0.1)
                        for source in readable:
                            data = source.recv(2048)
                            if not data:
                                return
                            destination = remote if source is self.request else self.request
                            if source is remote and slow.is_set():
                                if stop.wait(len(data) / 125_000):
                                    return
                            destination.sendall(data)
                except (ConnectionError, OSError):
                    pass

    class Proxy(socketserver.ThreadingTCPServer):
        daemon_threads = True

    with Proxy(("127.0.0.1", 0), Handler) as proxy:
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{proxy.server_address[1]}", slow
        finally:
            stop.set()
            proxy.shutdown()
            thread.join(2)


def test_local_clear_drops_inflight_frames_rapid_changes_and_reconnect(
    page,
    leika_server,
    page_errors,
):
    server = leika_server
    image = np.random.default_rng(7).integers(0, 255, (600, 900, 3), dtype=np.uint8)
    pane = server.panes.add_image(image, pane_id="video", format="jpeg", jpeg_quality=85)
    choose = server.gui.add_button("Choose dataset")
    scrub = server.gui.add_slider("Frame", initial_value=0, min=0, max=10, step=1)
    pane.invalidate_on(choose, scrub)
    entered, release = threading.Event(), threading.Event()
    completed = []

    @choose.on_click
    def select_dataset(event):
        entered.set()
        assert release.wait(10)
        pane.update(np.full((12, 16, 3), 50, np.uint8), loading=False)
        completed.append("dataset")

    @scrub.on_update
    def select_frame(event):
        pane.update(np.full((12, 16, 3), 180, np.uint8), loading=False)
        completed.append("frame")

    port = urlsplit(server.url).port
    with slow_proxy(port) as (url, slow):
        page.goto(url)
        region = page.locator('[data-viewport-pane="video"]')
        expect(region.locator("img")).to_be_visible(timeout=15_000)
        # Measure DOM removal, not just arrival of a server-side blank.
        page.evaluate("""() => {
          const region = document.querySelector('[data-viewport-pane="video"]');
          window.refreshTimes = {};
          document.addEventListener('click', () => { window.refreshTimes.click = performance.now(); }, {once:true, capture:true});
          new MutationObserver(() => {
            if (!region.querySelector('img') && window.refreshTimes.clear === undefined)
              window.refreshTimes.clear = performance.now();
          }).observe(region, {childList:true, subtree:true});
        }""")
        slow.set()
        pane.update(image[::-1].copy())  # old image is now on the slow path
        server.flush()
        try:
            page.get_by_role("button", name="Choose dataset", exact=True).click()
            expect(region.locator("img")).to_have_count(0, timeout=250)
            expect(region).to_have_attribute("aria-busy", "true")
            assert entered.wait(3)
            # A second edit arrives while the first callback is still running.
            slider = page.get_by_role("slider", name="Frame", exact=True)
            slider.focus()
            slider.press("ArrowRight")
            pane.update(image)  # still old data, including after the local clear
            page.wait_for_timeout(1200)
            expect(region.locator("img")).to_have_count(0)
            times = page.evaluate("window.refreshTimes")
            elapsed = times["clear"] - times["click"]
            assert elapsed < 150, times
            print(json.dumps({"link_mbps": 1, "click_to_clear_ms": elapsed}))
        finally:
            release.set()
        expect(region.locator("img")).to_be_visible(timeout=15_000)
        expect(region).not_to_have_attribute("aria-busy", "true")
        assert completed == ["dataset", "frame"]
        pixel = region.locator("img").evaluate("""img => {
          const canvas = document.createElement('canvas'); canvas.width=1; canvas.height=1;
          const ctx=canvas.getContext('2d'); ctx.drawImage(img,0,0,1,1);
          return ctx.getImageData(0,0,1,1).data[0];
        }""")
        assert abs(pixel - 180) < 3
        # A fresh connection receives the settled snapshot and control bindings.
        slow.clear()
        page.reload()
        expect(region.locator("img")).to_be_visible(timeout=15_000)
        page.get_by_role("slider", name="Frame", exact=True).press("ArrowRight")
        expect(region.locator("img")).to_be_visible(timeout=10_000)
        assert page_errors == []
