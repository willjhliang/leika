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


def assert_stable_viewer(dialog: Locator) -> dict:
    """Assert the visual contract shared by every Leika preview surface."""
    state = dialog.evaluate(
        """dialog => {
          const instance = dialog.dataset.dialogInstance;
          const overlay = [...document.querySelectorAll(
            '[data-slot="dialog-overlay"]'
          )].find(element => element.dataset.dialogInstance === instance);
          if (!(overlay instanceof HTMLElement)) {
            const seen = [...document.querySelectorAll(
              '[data-slot="dialog-overlay"]'
            )].map(element => ({
              instance: element.dataset.dialogInstance,
              presentation: element.dataset.dialogPresentation,
            }));
            throw new Error(
              `No paired overlay for dialog ${instance}; saw ${JSON.stringify(seen)}`
            );
          }
          const rect = dialog.getBoundingClientRect();
          const top = document.elementFromPoint(
            rect.left + rect.width / 2,
            rect.top + rect.height / 2,
          );
          const owner = top?.closest('[data-slot="dialog-content"]');
          const popupStyle = getComputedStyle(dialog);
          const overlayStyle = getComputedStyle(overlay);
          return {
            instance,
            popupPresentation: dialog.dataset.dialogPresentation,
            overlayPresentation: overlay.dataset.dialogPresentation,
            popupClasses: [...dialog.classList],
            overlayClasses: [...overlay.classList],
            popupOpacity: popupStyle.opacity,
            popupAnimation: popupStyle.animationName,
            popupAnimations: dialog.getAnimations().length,
            popupBackground: popupStyle.backgroundColor,
            overlayAnimation: overlayStyle.animationName,
            backdropFilter: overlayStyle.backdropFilter,
            ownsCenter: owner?.dataset.dialogInstance === instance,
          };
        }"""
    )

    motion = {
        "duration-100",
        "data-open:animate-in",
        "data-open:fade-in-0",
        "data-open:zoom-in-95",
        "data-closed:animate-out",
        "data-closed:fade-out-0",
        "data-closed:zoom-out-95",
    }
    assert state["instance"], state
    assert state["popupPresentation"] == "viewer", state
    assert state["overlayPresentation"] == "viewer", state
    assert motion.isdisjoint(state["popupClasses"]), state
    assert motion.isdisjoint(state["overlayClasses"]), state
    assert state["popupOpacity"] == "1", state
    assert state["popupAnimation"] == "none", state
    assert state["popupAnimations"] == 0, state
    assert state["overlayAnimation"] == "none", state
    assert state["backdropFilter"] == "none", state
    assert state["popupBackground"] not in {"transparent", "rgba(0, 0, 0, 0)"}, state
    assert state["ownsCenter"], state
    return state


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
