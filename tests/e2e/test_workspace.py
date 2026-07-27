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
    expect(leika_page.locator('[data-viewport-pane-content="left"] > img')).to_have_count(1)
    old_source = image.get_attribute("src")
    left.title = "Updated left"
    left.fit = "fill"
    left.update(np.full((24, 32, 3), 127, dtype=np.uint8))
    expect(leika_page.locator('[data-viewport-pane-title="left"]')).to_have_text("Updated left")
    expect(image).to_have_css("object-fit", "cover")
    expect(image).not_to_have_attribute("src", old_source or "")

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


def test_pane_header_rounds_only_the_corner_over_the_pane(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The label tucks into the pane's top-left corner, overlapping both edges.

    Three of its corners therefore sit on the seam between panes, where a
    radius would show the canvas through a notch. Only the fourth, which sits
    over the pane's own interior, should be rounded.
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
                roundedBottomRight: parseFloat(style.borderBottomRightRadius) > 0,
                // Negative offsets are what put the other three corners on the
                // seam in the first place.
                overlapsPaneEdges: self.left <= pane.left && self.top <= pane.top,
            };
        }"""
    )
    assert geometry == {
        "topLeft": "0px",
        "topRight": "0px",
        "bottomLeft": "0px",
        "roundedBottomRight": True,
        "overlapsPaneEdges": True,
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
