from __future__ import annotations

import re

import numpy as np
import pytest
from playwright.sync_api import Page, expect

import leika

from .utils import box


def test_image_panes_tile_resize_persist_and_update(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    row = leika_server.panes.add_row()
    left = row.add_image(np.zeros((24, 32, 3), dtype=np.uint8), pane_id="left", title="Left")
    row.add_image(np.full((24, 32, 3), 255, dtype=np.uint8), pane_id="right", title="Right")
    left_selector = '[data-viewport-pane="left"]'
    right_selector = '[data-viewport-pane="right"]'
    expect(leika_page.locator(left_selector)).to_be_visible(timeout=5_000)
    expect(leika_page.locator(right_selector)).to_be_visible(timeout=5_000)
    assert leika_page.locator('[data-viewport-pane="scene"]').count() == 0

    left_box = box(leika_page, left_selector)
    right_box = box(leika_page, right_selector)
    assert abs(left_box["y"] - right_box["y"]) < 2
    assert abs(left_box["height"] - right_box["height"]) < 2
    assert abs(left_box["x"] + left_box["width"] - right_box["x"]) < 2

    image = leika_page.locator(left_selector).locator("img")
    expect(image).to_have_attribute("src", re.compile(r"^blob:"))
    expect(
        leika_page.locator(
            '[data-viewport-pane-content="left"] > [data-viewport-pane-renderer] > img'
        )
    ).to_have_count(1)
    old_source = image.get_attribute("src")
    image.evaluate("element => { element.dataset.leikaImageIdentity = 'kept'; }")
    left.title = "Updated left"
    left.fit = "fill"
    left.update(np.full((24, 32, 3), 127, dtype=np.uint8))
    expect(leika_page.locator('[data-viewport-pane-title="left"]')).to_have_text("Updated left")
    expect(image).to_have_css("object-fit", "cover")
    expect(image).not_to_have_attribute("src", old_source or "")
    expect(
        leika_page.locator(
            '[data-viewport-pane-content="left"] > [data-viewport-pane-renderer] > img'
        )
    ).to_have_count(1)
    expect(image).to_have_attribute("data-leika-image-identity", "kept")

    divider = leika_page.locator('[data-viewport-divider-direction="row"]').first
    divider_bounds = divider.bounding_box()
    assert divider_bounds is not None
    before = box(leika_page, left_selector)["width"]
    x = divider_bounds["x"] + divider_bounds["width"] / 2
    y = divider_bounds["y"] + divider_bounds["height"] / 2
    leika_page.mouse.move(x, y)
    leika_page.mouse.down()
    leika_page.mouse.move(x + 70, y, steps=8)
    leika_page.mouse.up()
    after = box(leika_page, left_selector)["width"]
    assert after > before + 20

    leika_page.reload()
    expect(leika_page.locator(left_selector)).to_be_visible(timeout=10_000)
    restored = box(leika_page, left_selector)["width"]
    assert abs(restored - after) < 3

    left.visible = False
    expect(leika_page.locator(left_selector)).to_have_count(0)
    left.visible = True
    expect(leika_page.locator(left_selector)).to_be_visible(timeout=5_000)
    left.remove()
    expect(leika_page.locator(left_selector)).to_have_count(0)
    assert page_errors == []


@pytest.mark.parametrize("direction", ["row", "column"])
@pytest.mark.parametrize("viewport", [(960, 700), (1200, 520), (650, 950)])
def test_dividers_snap_to_sixtieths_of_each_workspace_axis(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
    direction: str,
    viewport: tuple[int, int],
) -> None:
    page = leika_page
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    container = (
        leika_server.panes.add_row() if direction == "row" else leika_server.panes.add_column()
    )
    container.add_pane(pane_id="first", title="First")
    container.add_pane(pane_id="second", title="Second")
    first = '[data-viewport-pane="first"]'
    second = '[data-viewport-pane="second"]'
    expect(page.locator(second)).to_be_visible()
    divider = page.locator(f'[data-viewport-divider-direction="{direction}"]')
    expect(divider).to_have_attribute("aria-valuenow", "30")
    workspace = box(page, "[data-viewport-grid-canvas]")
    dimension = "width" if direction == "row" else "height"
    assert abs(box(page, first)[dimension] - box(page, second)[dimension]) <= 1
    assert abs(box(page, first)[dimension] - workspace[dimension] / 2) <= 1

    divider.focus()
    divider.press("ArrowRight" if direction == "row" else "ArrowDown")
    expect(divider).to_have_attribute("aria-valuenow", "31")
    assert abs(box(page, first)[dimension] - workspace[dimension] * 31 / 60) <= 1
    divider.press("Shift+ArrowLeft" if direction == "row" else "Shift+ArrowUp")
    expect(divider).to_have_attribute("aria-valuenow", "27")
    assert abs(box(page, first)[dimension] - workspace[dimension] * 27 / 60) <= 1

    # Hover waits for the divider's CSS transition to settle before measuring
    # the grab point for the subsequent raw mouse gesture.
    divider.hover()
    bounds = divider.bounding_box()
    assert bounds is not None
    x = bounds["x"] + bounds["width"] / 2
    y = bounds["y"] + bounds["height"] / 2
    # Grab off-center: resizing must preserve the pointer's offset from the line.
    if direction == "row":
        x += 4
        target_x, target_y = workspace["x"] + workspace["width"] * 0.75 + 4, y
    else:
        y += 4
        target_x, target_y = x, workspace["y"] + workspace["height"] * 0.75 + 4
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(target_x, target_y, steps=8)
    page.mouse.up()
    expect(divider).to_have_attribute("aria-valuenow", "45")
    assert abs(box(page, first)[dimension] - workspace[dimension] * 0.75) <= 1
    assert page_errors == []


def test_pane_drop_preview_matches_committed_vertical_split(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    page = leika_page
    row = leika_server.panes.add_row()
    row.add_pane(pane_id="first", title="First")
    row.add_pane(pane_id="second", title="Second")
    expect(page.locator('[data-viewport-pane="second"]')).to_be_visible()
    header = box(page, '[data-viewport-pane-header="first"]')
    target = box(page, '[data-viewport-pane="second"]')
    page.mouse.move(header["x"] + header["width"] / 2, header["y"] + header["height"] / 2)
    page.mouse.down()
    page.mouse.move(
        target["x"] + target["width"] / 2,
        target["y"] + target["height"] * 0.9,
        steps=8,
    )
    hint = '[data-viewport-drop-hint="split"]'
    expect(page.locator(hint)).to_be_visible()
    preview = box(page, hint)
    workspace = box(page, "[data-viewport-grid-canvas]")
    assert abs(preview["y"] - workspace["y"] - workspace["height"] / 2) <= 1
    assert abs(preview["height"] - workspace["height"] / 2) <= 1
    page.mouse.up()
    expect(page.locator(hint)).to_have_count(0)
    actual = box(page, '[data-viewport-pane="first"]')
    for key in ["x", "y", "width", "height"]:
        assert abs(actual[key] - preview[key]) <= 1
    assert page_errors == []


def test_pane_header_is_a_square_bar_across_the_pane_top(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The title is a bar spanning the pane's full width, styled like the
    dock: card surface, left-aligned label, and no rounding anywhere -- every
    corner of the bar sits on a pane seam, where a radius would show the
    canvas through a notch.
    """
    row = leika_server.panes.add_row()
    row.add_image(np.zeros((24, 32, 3), dtype=np.uint8), pane_id="left", title="Left")
    expect(leika_page.locator('[data-viewport-pane="left"]')).to_be_visible(timeout=5_000)

    header = leika_page.locator('[data-viewport-pane-header="left"]')
    geometry = header.evaluate(
        """el => {
            const style = getComputedStyle(el);
            const pane = el.closest('[data-viewport-pane]').getBoundingClientRect();
            const self = el.getBoundingClientRect();
            return {
                topLeft: style.borderTopLeftRadius,
                topRight: style.borderTopRightRadius,
                bottomLeft: style.borderBottomLeftRadius,
                bottomRight: style.borderBottomRightRadius,
                spansPaneWidth:
                    Math.abs(self.left - pane.left) < 1 &&
                    Math.abs(self.right - pane.right) < 1 &&
                    Math.abs(self.top - pane.top) < 1,
            };
        }"""
    )
    assert geometry == {
        "topLeft": "0px",
        "topRight": "0px",
        "bottomLeft": "0px",
        "bottomRight": "0px",
        "spansPaneWidth": True,
    }
    assert page_errors == []


@pytest.mark.plotly
def test_plotly_pane_updates_without_remount(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    handle = leika_server.panes.add_plotly(
        go.Figure(go.Scatter(y=[1, 2, 1])), pane_id="plot", title="Plot"
    )
    pane = leika_page.locator('[data-viewport-pane="plot"]')
    expect(pane).to_be_visible(timeout=10_000)
    plot = pane.locator(".js-plotly-plot")
    expect(plot).to_be_visible(timeout=10_000)
    plot.evaluate("element => { element.dataset.leikaIdentity = 'kept'; }")

    handle.update(go.Figure(go.Bar(y=[3, 1, 2])))
    expect(plot).to_have_attribute("data-leika-identity", "kept", timeout=10_000)
    assert page_errors == []
