from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import Page, expect

import leika


def test_viser_pane_renders_an_iframe_and_repoints(
    leika_page: Page, leika_server: leika.Server
) -> None:
    """The pane is exercised hermetically by pointing the URL target at the
    Leika server itself; the iframe's src is deterministic and no viser
    installation is needed."""

    handle = leika_server.panes.add_viser(
        leika_server.url,
        pane_id="viser",
        title="Scene",
    )
    pane = leika_page.locator('[data-viewport-pane="viser"]')
    expect(pane).to_be_visible(timeout=5_000)
    expect(leika_page.locator('[data-viewport-pane-title="viser"]')).to_have_text("Scene")

    iframe = leika_page.locator('[data-viewport-pane-content="viser"] iframe')
    expect(iframe).to_have_count(1)
    # new URL() normalizes the bare origin with a trailing slash; the e2e
    # theme defaults to light, so no darkMode parameter is appended.
    expect(iframe).to_have_attribute("src", f"{leika_server.url}/")

    handle.update(f"{leika_server.url}/other")
    expect(iframe).to_have_attribute("src", f"{leika_server.url}/other")

    # Port targets: the browser derives the host from the page it loaded
    # Leika from, so only the port comes from the (fake) viser server.
    # Nothing listens on the port; only the derived src is asserted.
    handle.update(SimpleNamespace(get_port=lambda: 9876, get_host=lambda: "0.0.0.0"))
    hostname = urlsplit(leika_server.url).hostname
    expect(iframe).to_have_attribute("src", f"http://{hostname}:9876/")

    handle.remove()
    expect(pane).to_have_count(0)
