from __future__ import annotations

import socket
import time
from typing import Tuple

from playwright.sync_api import Locator, Page


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_until(predicate, timeout: float = 2.0) -> None:
    """Poll a server-side predicate until it holds, then assert that it does.

    The browser-side equivalents are Playwright's own `expect` timeouts; this
    is for Python state, which has no locator to wait on.
    """
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def find_gui_row(page: Page, label: str) -> Locator:
    element = page.locator("label", has_text=label).first
    return element.locator("xpath=ancestor::*[@data-leika-gui-row][1]")


def find_gui_input(page: Page, label: str) -> Locator:
    return find_gui_row(page, label).locator("input:not([type='hidden'])").first


def box(page: Page, selector: str) -> dict[str, float]:
    value = page.locator(selector).bounding_box()
    assert value is not None, selector
    return value


# Mouse coordinates, in CSS pixels relative to the viewport.
Point = Tuple[float, float]


def center(locator: Locator) -> Point:
    """Center of a locator's bounding box, as mouse coordinates."""
    bounds = locator.bounding_box()
    assert bounds is not None, "element has no bounding box"
    return (bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2)


def drag(
    page: Page,
    start: Point,
    *waypoints: Point,
    cancel: bool = False,
    steps: int = 6,
) -> None:
    """Press at `start`, move through `waypoints`, and release.

    Every waypoint is interpolated so the gesture crosses the drag threshold and
    the dock's rAF-throttled handlers see intermediate positions, as a real
    pointer would. With `cancel=True` the drag is abandoned with Escape (the
    dock's cancel path) instead of committing at the last waypoint.
    """
    page.mouse.move(*start)
    page.mouse.down()
    try:
        for waypoint in waypoints:
            page.mouse.move(*waypoint, steps=steps)
        page.evaluate("() => new Promise(requestAnimationFrame)")
        if cancel:
            page.keyboard.press("Escape")
    finally:
        # Always lift the button: a stuck press would leak into the next
        # gesture, including when an assertion above fails mid-drag.
        page.mouse.up()
