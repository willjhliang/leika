from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

import leika


@pytest.mark.matplotlib
def test_matplotlib_pane_renders_svg_and_rescales_without_a_redraw(
    leika_page: Page, leika_server: leika.Server
) -> None:
    """The figure is relayed as SVG, so the pane scales it in the browser:
    resizing the window changes what is drawn without Python sending a new
    figure."""

    plt = pytest.importorskip("matplotlib.pyplot")
    figure, axes = plt.subplots()
    axes.plot([0, 1, 2], [1, 3, 2])
    axes.set_title("First figure")
    try:
        handle = leika_server.panes.add_matplotlib(figure, pane_id="figure", title="Figure")
        pane = leika_page.locator('[data-viewport-pane="figure"]')
        image = leika_page.locator('[data-viewport-pane-content="figure"] img')
        expect(pane).to_be_visible(timeout=5_000)
        expect(leika_page.locator('[data-viewport-pane-title="figure"]')).to_have_text("Figure")
        expect(image).to_have_count(1)

        # Rendered through an object URL of an SVG blob, never inlined.
        source = image.get_attribute("src")
        assert source is not None and source.startswith("blob:")
        svg_type = image.evaluate("async (el) => (await (await fetch(el.src)).blob()).type")
        assert svg_type == "image/svg+xml"

        before = image.bounding_box()
        assert before is not None
        leika_page.set_viewport_size({"width": 700, "height": 600})
        # The dock reflows through a ResizeObserver, so the pane takes a frame
        # or more to follow the viewport. `to_be_visible` returns at once here
        # -- the image was already visible -- so poll the width itself.
        leika_page.wait_for_function(
            """(width) => {
              const el = document.querySelector('[data-viewport-pane-content="figure"] img');
              return el !== null && el.getBoundingClientRect().width !== width;
            }""",
            arg=before["width"],
            timeout=5_000,
        )
        after = image.bounding_box()
        assert after is not None and after["width"] != before["width"]
        # Same figure: the client rescaled vector art rather than refetching.
        assert image.get_attribute("src") == source

        axes.set_title("Second figure")
        handle.update(figure)
        expect(image).not_to_have_attribute("src", source)

        handle.remove()
        expect(pane).to_have_count(0)
    finally:
        plt.close(figure)
