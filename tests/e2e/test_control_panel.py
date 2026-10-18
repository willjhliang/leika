"""Pointer-driven coverage of the desktop control panel.

The panel floats, docks to the left or right edge, resizes its width, and
collapses to its header. Its arrangement is remembered per server and
workspace, and `configure_theme(control_layout=...)` only sets where it starts.
These read real DOM geometry, so they run against the real app.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Locator, Page, expect

import leika

from .utils import Point, center, drag

# Conftest's viewport, and the panel's own width (ControlPanel/controlWidth.ts).
VIEWPORT_W = 960.0
VIEWPORT_H = 700.0
CONTROL_WIDTH_PX = 320.0
MIN_CONTROL_WIDTH_PX = 220.0
# Clear of both edge zones.
CANVAS: Point = (480.0, 360.0)
LEFT_EDGE: Point = (16.0, 300.0)
RIGHT_EDGE: Point = (VIEWPORT_W - 16.0, 300.0)


def open_app(page: Page, server: leika.Server, layout: str = "floating") -> Page:
    """A workspace with a slider and a two-tab group, its panel starting at `layout`."""
    server.gui.configure_theme(control_layout=layout, theme="dark")  # type: ignore[arg-type]
    server.gui.add_slider("Value", min=0.0, max=1.0, step=0.01, initial_value=0.5)
    tabs = server.gui.add_tab_group()
    with tabs.add_tab("Alpha"):
        server.gui.add_text(None, "Alpha body", editable=False, markdown=True)
    with tabs.add_tab("Beta"):
        server.gui.add_text(None, "Beta body", editable=False, markdown=True)
    page.goto(server.url)
    page.wait_for_selector('[data-viewport-workspace][aria-busy="false"]', timeout=15_000)
    expect(page.get_by_text("Alpha body", exact=True)).to_be_visible(timeout=5_000)
    expect(panel(page)).to_have_attribute("data-leika-placement", layout)
    return page


def panel(page: Page) -> Locator:
    return page.get_by_test_id("control-panel")


def handle(page: Page) -> Locator:
    return page.get_by_test_id("control-panel-handle")


def bounds(locator: Locator) -> dict[str, float]:
    value = locator.bounding_box()
    assert value is not None
    return value


def workspace(page: Page) -> dict[str, float]:
    return bounds(page.locator("[data-viewport-workspace]"))


def click_handle(page: Page) -> None:
    """One click on the header, clear of the previous click's double-click window."""
    page.wait_for_timeout(450)
    handle(page).click(position={"x": 120, "y": 20})


def test_the_header_drags_the_panel_to_float_or_dock_on_either_edge(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server)
    floating = bounds(panel(page))
    assert floating["x"] + floating["width"] == pytest.approx(VIEWPORT_W - 15.0, abs=0.5)
    assert floating["y"] == pytest.approx(15.0, abs=0.5)
    assert workspace(page)["width"] == pytest.approx(VIEWPORT_W, abs=0.5)

    drag(page, center(handle(page)), CANVAS, LEFT_EDGE)
    expect(panel(page)).to_have_attribute("data-leika-placement", "left")
    docked = bounds(panel(page))
    assert (docked["x"], docked["y"]) == (0.0, 0.0)
    assert docked["height"] == pytest.approx(VIEWPORT_H, abs=0.5)
    assert workspace(page)["x"] == pytest.approx(CONTROL_WIDTH_PX, abs=0.5)
    expect(panel(page)).to_have_css("border-radius", "0px")

    # Out onto the canvas it floats again, under the cursor that carried it.
    drag(page, center(handle(page)), (500.0, 250.0), (620.0, 260.0))
    expect(panel(page)).to_have_attribute("data-leika-placement", "floating")
    moved = bounds(panel(page))
    assert moved["x"] < 620.0 < moved["x"] + moved["width"]
    assert workspace(page)["x"] == pytest.approx(0.0, abs=0.5)

    drag(page, center(handle(page)), CANVAS, RIGHT_EDGE)
    expect(panel(page)).to_have_attribute("data-leika-placement", "right")
    canvas = workspace(page)
    assert canvas["x"] == pytest.approx(0.0, abs=0.5)
    assert canvas["width"] == pytest.approx(VIEWPORT_W - CONTROL_WIDTH_PX, abs=0.5)
    assert page_errors == []


def test_escape_abandons_a_drag(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server, "left")
    drag(page, center(handle(page)), CANVAS, RIGHT_EDGE, cancel=True)
    expect(panel(page)).to_have_attribute("data-leika-placement", "left")
    assert workspace(page)["x"] == pytest.approx(CONTROL_WIDTH_PX, abs=0.5)
    assert page_errors == []


def test_the_side_edges_resize_the_width(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server)
    before = bounds(panel(page))
    grip = center(page.get_by_test_id("control-panel-resize-left"))
    drag(page, grip, (grip[0] - 60.0, grip[1]))
    after = bounds(panel(page))
    assert after["width"] == pytest.approx(before["width"] + 60.0, abs=1.0)
    # The right edge holds still.
    assert after["x"] + after["width"] == pytest.approx(before["x"] + before["width"], abs=1.0)

    # Docked left, the inner edge resizes, the canvas follows, and the minimum holds.
    drag(page, center(handle(page)), CANVAS, LEFT_EDGE)
    expect(panel(page)).to_have_attribute("data-leika-placement", "left")
    expect(page.get_by_test_id("control-panel-resize-left")).to_have_count(0)
    grip = center(page.get_by_test_id("control-panel-resize-right"))
    drag(page, grip, (grip[0] + 40.0, grip[1]))
    assert bounds(panel(page))["width"] == pytest.approx(after["width"] + 40.0, abs=1.0)
    assert workspace(page)["x"] == pytest.approx(bounds(panel(page))["width"], abs=0.5)
    grip = center(page.get_by_test_id("control-panel-resize-right"))
    drag(page, grip, (grip[0] - 400.0, grip[1]))
    assert bounds(panel(page))["width"] == pytest.approx(MIN_CONTROL_WIDTH_PX, abs=1.0)
    assert page_errors == []


def test_a_header_click_collapses_and_a_double_click_sends_it_home(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server)
    home = bounds(panel(page))
    body = page.locator("[data-leika-generated-gui]")

    click_handle(page)
    expect(panel(page)).to_have_attribute("data-leika-collapsed", "true")
    expect(body).to_be_hidden()
    assert bounds(panel(page))["height"] < home["height"]
    click_handle(page)
    expect(panel(page)).not_to_have_attribute("data-leika-collapsed", "true")
    expect(body).to_be_visible()

    drag(page, center(handle(page)), CANVAS, (320.0, 400.0))
    assert bounds(panel(page))["x"] != pytest.approx(home["x"], abs=1.0)
    page.wait_for_timeout(450)
    handle(page).dblclick(position={"x": 120, "y": 20})
    restored = bounds(panel(page))
    assert (restored["x"], restored["y"]) == pytest.approx((home["x"], home["y"]), abs=0.5)
    expect(body).to_be_visible()
    assert page_errors == []


def test_a_collapsed_docked_panel_gives_the_canvas_back(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server, "left")
    click_handle(page)
    expect(panel(page)).to_have_attribute("data-leika-collapsed", "true")
    bar = bounds(panel(page))
    assert (bar["x"], bar["y"]) == (0.0, 0.0)
    assert bar["height"] < 80.0
    assert workspace(page)["x"] == pytest.approx(0.0, abs=0.5)

    click_handle(page)
    expect(panel(page)).not_to_have_attribute("data-leika-collapsed", "true")
    assert workspace(page)["x"] == pytest.approx(CONTROL_WIDTH_PX, abs=0.5)
    assert page_errors == []


def test_the_arrangement_survives_a_reload(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server)
    drag(page, center(handle(page)), CANVAS, LEFT_EDGE)
    grip = center(page.get_by_test_id("control-panel-resize-right"))
    drag(page, grip, (grip[0] + 60.0, grip[1]))
    width = bounds(panel(page))["width"]
    click_handle(page)
    expect(panel(page)).to_have_attribute("data-leika-collapsed", "true")

    page.reload()
    expect(panel(page)).to_have_attribute("data-leika-placement", "left", timeout=5_000)
    expect(panel(page)).to_have_attribute("data-leika-collapsed", "true")
    click_handle(page)
    expect(panel(page)).not_to_have_attribute("data-leika-collapsed", "true")
    assert bounds(panel(page))["width"] == pytest.approx(width, abs=1.0)
    assert page_errors == []


@pytest.mark.parametrize("side", ["left", "right"])
def test_the_theme_sets_where_the_panel_starts(
    side: str, leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server, side)
    docked = bounds(panel(page))
    assert docked["width"] == pytest.approx(CONTROL_WIDTH_PX, abs=0.5)
    assert docked["x"] == pytest.approx(0.0 if side == "left" else VIEWPORT_W - CONTROL_WIDTH_PX)
    assert workspace(page)["width"] == pytest.approx(VIEWPORT_W - CONTROL_WIDTH_PX, abs=0.5)
    assert page_errors == []


def test_a_theme_change_moves_the_panel_until_the_viewer_moves_it(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server)
    leika_server.gui.configure_theme(control_layout="left", theme="dark")
    expect(panel(page)).to_have_attribute("data-leika-placement", "left", timeout=5_000)

    # Once the viewer has placed it, the viewer's arrangement wins.
    drag(page, center(handle(page)), CANVAS)
    expect(panel(page)).to_have_attribute("data-leika-placement", "floating")
    leika_server.gui.configure_theme(control_layout="right", theme="dark")
    page.wait_for_timeout(400)
    expect(panel(page)).to_have_attribute("data-leika-placement", "floating")
    assert page_errors == []


def test_settings_and_connection_open_from_a_collapsed_header(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server, "right")
    click_handle(page)
    expect(panel(page)).to_have_attribute("data-leika-collapsed", "true")
    for trigger, popover in (
        ("[data-leika-settings-trigger]", "[data-leika-settings-popover]"),
        ("[data-leika-connection-trigger]", "[data-leika-connection-popover]"),
    ):
        panel(page).locator(trigger).click()
        expect(page.locator(popover)).to_be_visible(timeout=5_000)
        # The press was the button's, not the header's.
        expect(panel(page)).to_have_attribute("data-leika-collapsed", "true")
        page.keyboard.press("Escape")
        expect(page.locator(popover)).to_have_count(0, timeout=5_000)
    assert page_errors == []


def test_gui_tabs_switch_in_place(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    open_app(page, leika_server)
    beta = panel(page).get_by_role("tab", name="Beta", exact=True)
    before = bounds(panel(page))
    # A drag on a tab is not a panel gesture: nothing moves or tears out.
    drag(page, center(beta), (center(beta)[0], center(beta)[1] + 90.0))
    assert bounds(panel(page)) == pytest.approx(before, abs=0.5)
    expect(panel(page).get_by_role("tab")).to_have_count(2)

    beta.click()
    expect(page.get_by_text("Beta body", exact=True)).to_be_visible()
    expect(page.get_by_text("Alpha body", exact=True)).to_be_hidden()
    assert page_errors == []


def test_one_collapsed_state_and_one_workspace_across_layouts(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    """The phone's sheet folds with the desktop panel, and neither moving the
    panel nor switching to the phone layout remounts the workspace."""
    open_app(page, leika_server)
    page.locator("[data-viewport-workspace]").evaluate("el => { window.__workspace = el; }")
    same_workspace = (
        "() => window.__workspace === document.querySelector('[data-viewport-workspace]')"
    )

    drag(page, center(handle(page)), CANVAS, LEFT_EDGE)
    expect(panel(page)).to_have_attribute("data-leika-placement", "left")
    click_handle(page)
    expect(panel(page)).to_have_attribute("data-leika-collapsed", "true")

    page.set_viewport_size({"width": 420, "height": 700})
    sheet = page.locator("[data-leika-bottom-panel-handle]")
    expect(sheet).to_have_attribute("aria-expanded", "false", timeout=5_000)
    sheet.click()
    expect(sheet).to_have_attribute("aria-expanded", "true")

    page.set_viewport_size({"width": int(VIEWPORT_W), "height": int(VIEWPORT_H)})
    expect(panel(page)).not_to_have_attribute("data-leika-collapsed", "true", timeout=5_000)
    assert page.evaluate(same_workspace)
    assert page_errors == []
