from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack
from types import SimpleNamespace

import msgspec
import numpy as np
import zstandard
from playwright.sync_api import Page, expect

import leika

from .utils import find_free_port


def test_viser_pane_renders_an_iframe_and_repoints(
    leika_page: Page, leika_server: leika.Server
) -> None:
    """The pane is exercised hermetically by pointing the URL target at the
    Leika server itself; the iframe's src is deterministic and no viser
    installation is needed."""

    with leika_page.expect_request(
        lambda request: request.is_navigation_request() and request.frame.parent_frame is not None
    ) as navigation:
        handle = leika_server.panes.add_viser(
            leika_server.url,
            pane_id="viser",
            title="Scene",
        )
    assert navigation.value.header_value("referer") is None
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
    scene.scene.add_box("/box", color=(200, 80, 20), dimensions=(0.1, 0.1, 0.1))
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


def test_eight_live_scenes_update_from_leika_and_reconnect(page: Page) -> None:
    import viser

    received = []
    sockets = []

    def receive(data):
        # Viser 0.2 sends MessagePack; 1.x sends compressed metadata followed
        # by binary arrays. Observe messages received by the real browser.
        try:
            messages = msgspec.msgpack.decode(data)
        except msgspec.DecodeError:
            size = int.from_bytes(data[:8], "little")
            compressed_size = int.from_bytes(data[8:16], "little")
            metadata = zstandard.ZstdDecompressor().decompress(
                data[16 : 16 + compressed_size], max_output_size=size
            )
            messages = msgspec.msgpack.decode(metadata)["messages"]
        received.extend(messages if isinstance(messages, (list, tuple)) else [messages])

    def on_socket(socket):
        if "/_leika/viser/" in socket.url:
            sockets.append(socket.url)
            socket.on("framereceived", receive)

    def wait_for(predicate):
        deadline = time.monotonic() + 30
        while not predicate() and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        assert predicate()

    page.on("websocket", on_socket)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1600, "height": 1000})
    with ExitStack() as lifetime:
        server = lifetime.enter_context(leika.Server(host="127.0.0.1", port=0, verbose=False))
        scenes = []
        meshes = []
        for index in range(8):
            scene = viser.ViserServer(host="127.0.0.1", port=find_free_port())
            lifetime.callback(scene.stop)
            scenes.append(scene)
            meshes.append(
                scene.scene.add_mesh_simple(
                    f"/skill-{index}",
                    vertices=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32),
                    faces=np.array([[0, 1, 2]], dtype=np.uint32),
                    color=(200, 80, 20),
                )
            )
            server.panes.add_viser(scene, pane_id=f"skill-{index}", title=f"Skill {index}")

        def move(_):
            for index, mesh in enumerate(meshes):
                mesh.position = (index + 1.0, 0.0, 0.0)

        server.gui.add_button("Step all skills").on_click(move)
        page.goto(server.url)
        expect(page.locator("iframe")).to_have_count(8)
        wait_for(lambda: all(scene.get_clients() for scene in scenes))
        wait_for(lambda: len({m.get("name") for m in received if m["type"] == "MeshMessage"}) == 8)
        for index in range(8):
            expect(
                page.frame_locator(f'iframe[title="Skill {index}"]').locator("canvas[data-engine]")
            ).to_be_visible()
        received.clear()
        page.get_by_role("button", name="Step all skills", exact=True).click()

        def updated():
            return all(
                any(
                    m["type"] == "SetPositionMessage"
                    and m["name"] == f"/skill-{index}"
                    and m["position"] == [index + 1.0, 0.0, 0.0]
                    for m in received
                )
                for index in range(8)
            )

        wait_for(updated)
        old_clients = [set(scene.get_clients()) for scene in scenes]
        page.evaluate("window.sceneDocument = document")
        proxy = server._websock_server._viser_proxy

        async def disconnect():
            await asyncio.gather(
                *(
                    connection.close(1012, "test reconnect")
                    for endpoint in proxy._endpoints.values()
                    for connection in tuple(endpoint.connections)
                )
            )

        received.clear()
        asyncio.run_coroutine_threadsafe(disconnect(), proxy._loop).result(timeout=10)
        # Modern Viser retries only while its document has focus. Exercise
        # that public behavior by focusing each embedded document in turn.
        for index, scene in enumerate(scenes):
            page.locator(f'iframe[title="Skill {index}"]').focus()
            wait_for(lambda: bool(set(scene.get_clients()) - old_clients[index]))
        wait_for(
            lambda: all(set(scene.get_clients()) - old for scene, old in zip(scenes, old_clients))
        )
        wait_for(updated)
        assert page.evaluate("window.sceneDocument === document")
        assert len(sockets) >= 16
        assert all(url.startswith(server.url.replace("http:", "ws:")) for url in sockets)
        assert errors == []
