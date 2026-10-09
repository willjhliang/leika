from __future__ import annotations

from types import SimpleNamespace

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

    # Server targets use the same origin. Nothing listens on this fake
    # backend; this assertion checks the native iframe route.
    handle.update(SimpleNamespace(get_port=lambda: 9876, get_host=lambda: "0.0.0.0"))
    expect(iframe).to_have_attribute("src", leika_server.url + handle.url)

    handle.remove()
    expect(pane).to_have_count(0)


def test_password_protects_native_viser_embedding(page: Page) -> None:
    import threading

    import viser

    from .utils import find_free_port

    scene = viser.ViserServer(host="127.0.0.1", port=find_free_port())
    clicked = threading.Event()
    button = scene.gui.add_button("Core proxy check")
    button.on_click(lambda event: clicked.set())
    scene.scene.add_box("/box", dimensions=(0.1, 0.1, 0.1))
    sockets = []
    page.on("websocket", lambda socket: sockets.append(socket.url))
    try:
        with leika.Server(
            host="127.0.0.1", port=0, password="test-password", verbose=False
        ) as server:
            pane = server.panes.add_viser(scene, minimize_gui=False)
            assert page.request.get(server.url + pane.url).status == 401
            page.goto(server.url)
            password = page.locator("input[type=password]")
            password.fill("test-password")
            password.press("Enter")
            frame = page.frame_locator("iframe")
            frame.get_by_role("button", name="Core proxy check", exact=True).click(timeout=30000)
            assert clicked.wait(5)
            assert any(pane.url.rstrip("/") in socket for socket in sockets)
            assert all(socket.startswith(server.url.replace("http:", "ws:")) for socket in sockets)
    finally:
        scene.stop()


def test_hidden_viser_keeps_the_iframe_document(
    leika_page: Page, leika_server: leika.Server
) -> None:
    # A local inert asset gives us a same-origin document to mark without
    # starting another renderer or relying on network services.
    pane = leika_server.panes.add_viser(leika_server.url + "/missing-scene", pane_id="persistent")
    iframe = leika_page.locator("iframe")
    expect(iframe).to_have_count(1)
    frame = leika_page.frames[1]
    frame.wait_for_load_state()
    frame.evaluate("window.sceneMarker = document")
    pane.visible = False
    expect(iframe).not_to_be_visible()
    pane.visible = True
    expect(iframe).to_be_visible()
    assert frame.evaluate("window.sceneMarker === document")
