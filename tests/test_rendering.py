from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from leika import _messages
from leika._client_handle import ClientHandle
from leika._image_encoding import encode_image_binary
from leika._rendering import render_image, render_message
from leika.infra import ClientId


def source_image(format="jpeg"):
    pixels = np.random.default_rng(3).integers(
        0, 256, (480, 640, 4 if format == "png" else 3), dtype=np.uint8
    )
    return encode_image_binary(pixels, format, 85)[1]


@pytest.mark.parametrize(
    "mode,size",
    [("quality", (160, 120)), ("auto", None), ("auto", (640, 480)), ("auto", (1280, 960))],
)
def test_quality_and_native_auto_preserve_original_bytes(server, mode, size):
    data = source_image()
    assert render_image(data, mode, size, "fit", server) is data


def test_auto_fits_display_without_lowering_jpeg_quality(server):
    data = source_image()
    resized = render_image(data, "auto", (320, 300), "fit", server)
    with Image.open(BytesIO(data)) as original, Image.open(BytesIO(resized)) as decoded:
        assert decoded.size == (320, 240)
        assert decoded.quantization == original.quantization
    assert len(resized) < len(data)
    assert server._image_preparation_bytes == 0


def test_fill_preserves_enough_pixels_for_the_cropped_dimension(server):
    with Image.open(
        BytesIO(render_image(source_image(), "auto", (200, 400), "fill", server))
    ) as image:
        assert image.size == (533, 400)


@pytest.mark.parametrize("format", ["jpeg", "png"])
def test_performance_reduces_payload_without_changing_format_or_alpha(server, format):
    data = source_image(format)
    resized = render_image(data, "performance", (320, 240), "fit", server)
    with Image.open(BytesIO(resized)) as decoded:
        assert decoded.size == (160, 120)
        assert decoded.format == format.upper()
        assert decoded.mode == ("RGBA" if format == "png" else "RGB")
    assert len(resized) < len(data) / 4
    assert render_image(data, "quality", (320, 240), "fit", server) is data


def test_rendering_does_not_mutate_shared_messages_or_selection_receipts(server):
    data = source_image()
    message = _messages.ViewportPaneUpdateMessage(
        "page",
        "pane",
        {
            "_format": "jpeg",
            "_data": data,
            "loading": False,
            "_refresh_revision": 7,
            "_refresh_requests": ("chosen-frame",),
            "fit": "fit",
        },
    )
    performance = render_message(message, "performance", (320, 240), "fit", server)
    quality = render_message(message, "quality", (320, 240), "fit", server)
    assert quality is message and message.updates["_data"] is data
    assert performance.updates == {**message.updates, "_data": performance.updates["_data"]}
    assert len(performance.updates["_data"]) < len(data)
    cleared = _messages.ViewportPaneUpdateMessage(
        "page", "pane", {"_format": "jpeg", "_data": b"", "loading": True}
    )
    assert render_message(cleared, "auto", (320, 240), "fit", server) is cleared


def test_create_messages_and_png_remain_independent(server):
    props = _messages.ViewportImageProps(source_image("png"), "png", "Image", True, False, "fit")
    message = _messages.ViewportImageMessage("page", "pane", "right", "root", (), props)
    resized = render_message(message, "auto", (320, 240), "fit", server)
    assert resized.props._data != props._data
    with Image.open(BytesIO(resized.props._data)) as image:
        assert image.mode == "RGBA" and image.size == (320, 240)


def test_settings_and_size_refresh_use_ordered_content_and_preserve_source(server):
    pane = server.panes.add_image(np.zeros((480, 640, 3), np.uint8), format="jpeg")
    page_id = pane._impl.api._page_id
    connection = SimpleNamespace(
        client_id=ClientId(12),
        _state=SimpleNamespace(),
        register_handler=lambda *_: None,
        get_message_buffer=lambda: server._websock_server._broadcast_buffer,
        delivery_scope=lambda: page_id,
    )
    client = ClientHandle(connection, server)
    server._connected_clients[12] = client
    assert pane.has_viewers
    updates = []
    pane._queue_update = updates.append
    server._handle_rendering_settings(
        ClientId(12), _messages.RenderingSettingsMessage("performance", "fit")
    )
    assert client._rendering == "performance"
    assert connection._state.rendering_backpressure
    assert updates[-1]["_data"] is pane._impl.props._data
    server._handle_pane_viewport(
        ClientId(12), _messages.PaneViewportMessage(page_id, pane.pane_id, 320, 240)
    )
    assert len(updates) == 2
    server._handle_pane_viewport(
        ClientId(12), _messages.PaneViewportMessage(page_id, pane.pane_id, 320, 240)
    )
    assert len(updates) == 2
    server._handle_pane_viewport(
        ClientId(12), _messages.PaneViewportMessage(page_id, pane.pane_id, 0, 0)
    )
    assert not pane.has_viewers
    server._handle_rendering_settings(
        ClientId(12), _messages.RenderingSettingsMessage("invalid", "fit")
    )
    assert client._rendering == "performance"
    server._handle_pane_viewport(
        ClientId(12), _messages.PaneViewportMessage(page_id, pane.pane_id, 320, 240)
    )
    pane.visible = False
    assert not pane.has_viewers


def test_client_preparation_uses_its_own_preferences(server):
    data = source_image()
    message = _messages.ViewportPaneUpdateMessage(
        "page", "pane", {"_data": data, "_format": "jpeg", "fit": "fit"}
    )

    def client(mode):
        conn = SimpleNamespace(
            client_id=ClientId(1),
            register_handler=lambda *_: None,
            get_message_buffer=lambda: server._websock_server._broadcast_buffer,
        )
        value = ClientHandle(conn, server)
        value._rendering = mode
        value._pane_sizes["page", "pane"] = (320, 240)
        return value

    async def prepare():
        return await asyncio.gather(
            client("quality")._prepare_rendering((message,)),
            client("performance")._prepare_rendering((message,)),
        )

    quality, performance = asyncio.run(prepare())
    assert quality[0] is message
    assert len(performance[0].updates["_data"]) < len(data)
