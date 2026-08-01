from __future__ import annotations

from playwright.sync_api import Page, expect

import leika


def test_wandb_pane_renders_an_iframe_and_repoints(
    leika_page: Page, leika_server: leika.Server
) -> None:
    """The pane is exercised hermetically by aiming base_url at the Leika
    server itself; the iframe's src is deterministic even though the target
    path serves nothing."""

    handle = leika_server.panes.add_wandb(
        "acme/demo",
        base_url=leika_server.url,
        pane_id="wandb",
        title="W&B",
    )
    pane = leika_page.locator('[data-viewport-pane="wandb"]')
    expect(pane).to_be_visible(timeout=5_000)
    expect(leika_page.locator('[data-viewport-pane-title="wandb"]')).to_have_text("W&B")

    iframe = leika_page.locator('[data-viewport-pane-content="wandb"] iframe')
    expect(iframe).to_have_count(1)
    expect(iframe).to_have_attribute("src", f"{leika_server.url}/acme/demo/workspace?jupyter=true")

    handle.url = "acme/demo/runs/abc"
    expect(iframe).to_have_attribute("src", f"{leika_server.url}/acme/demo/runs/abc?jupyter=true")

    handle.remove()
    expect(pane).to_have_count(0)
