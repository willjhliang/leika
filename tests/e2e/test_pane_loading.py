from __future__ import annotations

import numpy as np
from playwright.sync_api import Page, expect

import leika


def test_pane_loading_overlays_content_without_changing_layout_or_remounting(
    leika_page: Page,
    leika_server: leika.Server,
    page_errors: list[str],
) -> None:
    handle = leika_server.panes.add_image(
        np.zeros((12, 16, 3), dtype=np.uint8),
        pane_id="video",
        title="Video",
        loading=True,
    )
    pane = leika_page.locator('[data-viewport-pane="video"]')
    image = pane.locator("img")
    overlay = pane.locator("[data-viewport-pane-loading]")
    renderer = pane.locator("[data-viewport-pane-renderer]")

    expect(pane).to_be_visible(timeout=5_000)
    expect(pane).to_have_attribute("aria-busy", "true")
    expect(overlay).to_have_attribute("aria-label", "Loading")
    expect(image).to_have_count(1)
    before = pane.bounding_box()
    assert before is not None
    image.evaluate("element => { element.dataset.mountIdentity = 'kept'; }")

    # Renderer libraries can create their own very high z-index descendants.
    # The renderer surface is a lower stacking context, so those descendants
    # cannot escape over the loading surface.
    expect(renderer).to_have_css("z-index", "0")
    renderer.evaluate(
        """element => {
          const content = document.createElement("button");
          content.dataset.highZRendererContent = "";
          Object.assign(content.style, {
            position: "absolute",
            inset: "0",
            zIndex: "2147483647",
          });
          element.append(content);
        }"""
    )
    assert overlay.evaluate(
        """element => {
          const bounds = element.getBoundingClientRect();
          const top = document.elementFromPoint(
            bounds.left + bounds.width / 2,
            bounds.top + bounds.height / 2,
          );
          return top !== null && element.contains(top);
        }"""
    )
    renderer.locator("[data-high-z-renderer-content]").evaluate("element => element.remove()")

    handle.loading = "Indexing ABC · 129k episodes"
    expect(overlay).to_have_text("Indexing ABC · 129k episodes")

    handle.update(np.full((24, 32, 3), 127, dtype=np.uint8), loading=False)
    expect(overlay).to_have_count(0)
    expect(pane).not_to_have_attribute("aria-busy", "true")
    expect(image).to_have_attribute("data-mount-identity", "kept")
    assert pane.bounding_box() == before

    assert page_errors == []
