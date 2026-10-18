"""Stable pane identity, replaceable renderer ownership, and replay behavior."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from leika import _messages, _panes


def retained(server):
    return tuple(server._websock_server.get_message_buffer().message_from_id.values())


def test_general_pane_replaces_content_and_replay_without_changing_identity(server):
    grid = server.panes.add_grid(columns=2)
    panes = [grid.add_pane(pane_id=f"slot-{i}", title=f"Slot {i}") for i in range(4)]
    pane = panes[0]
    pane.set_image(np.zeros((8, 12, 3), np.uint8))
    old = pane._content
    assert server.panes._resource_total.decoded_pixels == 96
    pane.set_video("/camera.mp4", sync_group="episode", fps=10)
    assert old._impl.removed and old._impl.image.size == 0
    assert server.panes._resource_total.decoded_pixels == 0
    assert server.panes._handle_from_pane_id["slot-0"] is pane
    assert pane.title == "Slot 0"
    pane.clear(loading="Waiting")
    assert pane.loading == "Waiting"
    messages = retained(server)
    declarations = [m for m in messages if isinstance(m, _messages.ViewportPaneMessage)]
    assert [m.pane_id for m in declarations] == [p.pane_id for p in panes]
    assert declarations[1].relative_to == "slot-0"
    assert not any(
        isinstance(m, (_messages.ViewportImageMessage, _messages.ViewportVideoMessage))
        for m in messages
    )
    assert server.panes._aggregate.live_panes == 4
    pane.remove()
    assert not any(getattr(m, "pane_id", None) == pane.pane_id for m in retained(server))


def test_typed_update_restores_video_settings_after_clear(server):
    pane = server.panes.add_video(
        "/a.mp4", sync_group="episode", fps=30, loop=False, autoplay=False
    )
    pane.clear()
    pane.update("/b.mp4", loading=False)
    assert pane.sync_group == "episode" and pane.fps == 30
    assert pane._impl.props._url == "/b.mp4"
    assert not pane._impl.props.loop and not pane._impl.props.autoplay
    pane.set_image(np.zeros((2, 3, 3), np.uint8))
    with pytest.raises(RuntimeError, match="different"):
        pane.update("/c.mp4")
    pane.clear()
    with pytest.raises(RuntimeError, match="different"):
        pane.update("/c.mp4")
    pane.set_video("/d.mp4")
    pane.update("/e.mp4")
    assert pane._impl.props._url == "/e.mp4"


@pytest.mark.parametrize("operation", ["update", "set_image"])
def test_clear_rejects_inflight_image_work(server, monkeypatch, operation):
    pane = server.panes.add_image(np.zeros((2, 3, 3), np.uint8))
    started, release = threading.Event(), threading.Event()
    encode = _panes.encode_image_binary

    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return encode(*args, **kwargs)

    monkeypatch.setattr(_panes, "encode_image_binary", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(getattr(pane, operation), np.ones((2, 3, 3), np.uint8))
        assert started.wait(5)
        try:
            pane.clear()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="removed|changed"):
            result.result(timeout=5)
    assert server.panes._resource_total.decoded_pixels == 0
    assert not any(isinstance(m, _messages.ViewportImageMessage) for m in retained(server))


@pytest.mark.parametrize("clear", [False, True])
def test_failed_replacement_restores_content_resources_and_replay(server, monkeypatch, clear):
    pane = server.panes.add_image(np.zeros((2, 3, 3), np.uint8), title="Original")
    old = pane._content
    cost, messages = server.panes._resource_total, retained(server)

    def reject(*args):
        raise RuntimeError("publication failed")

    monkeypatch.setattr(server.panes._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="publication failed"):
        pane.clear() if clear else pane.set_viser("https://example.com/scene")
    assert pane._content is old and not old._impl.removed
    assert pane.title == "Original"
    assert server.panes._resource_total == cost
    assert server.panes._aggregate.resource_total == cost
    assert server.panes._aggregate.live_viser_panes == 0
    assert retained(server) == messages


def test_replace_at_pane_limit_and_viser_limit(server, monkeypatch):
    monkeypatch.setattr(_panes, "_PANE_MAX", 2)
    monkeypatch.setattr(_panes, "_VISER_PANE_MAX", 1)
    first, second = server.panes.add_pane(), server.panes.add_pane()
    first.set_viser("https://example.com/first")
    first.set_viser("https://example.com/second")
    with pytest.raises(RuntimeError, match="viser panes"):
        second.set_viser("https://example.com/third")
    first.clear()
    second.set_viser("https://example.com/third")
    assert server.panes._aggregate.live_panes == 2
    assert server.panes._aggregate.live_viser_panes == 1
    second.remove()
    assert server.panes._aggregate.live_viser_panes == 0


def test_clear_unregisters_viser_proxy(server):
    from types import SimpleNamespace

    target = SimpleNamespace(get_host=lambda: "127.0.0.1", get_port=lambda: 9876)
    pane = server.panes.add_viser(target, minimize_gui=False)
    old = pane._content
    assert old._impl.proxy_path is not None
    pane.clear()
    assert old._impl.proxy_path is None and old._impl.proxy_address is None
    pane.update(target)
    assert pane.port == 9876
    assert not pane._impl.minimize_gui


def test_replacement_preserves_refresh_bindings_and_latest_metadata(server, monkeypatch):
    control = server.gui.add_checkbox("Selection", initial_value=False)
    pane = server.panes.add_pane(title="Original")
    pane.invalidate_on(control)
    prepare = _panes._prepare_video

    def rename_during_preparation(*args):
        pane.title = "Latest"
        pane.visible = False
        pane.loading = "Preparing"
        return prepare(*args)

    monkeypatch.setattr(_panes, "_prepare_video", rename_during_preparation)
    pane.set_video("/movie.mp4")
    assert (pane.title, pane.visible, pane.loading) == ("Latest", False, "Preparing")
    updates = [m for m in retained(server) if isinstance(m, _messages.ViewportPaneUpdateMessage)]
    assert updates[-1].updates["_refresh_controls"] == (control._impl.uuid,)
    pane.clear(loading=False)
    assert pane.loading is False and pane.title == "Latest"


def test_matplotlib_and_plotly_can_share_one_pane(server):
    class Figure:
        def savefig(self, target, **kwargs):
            target.write(b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"></svg>')

    pane = server.panes.add_pane()
    figure = Figure()
    pane.set_matplotlib(figure)
    assert any(isinstance(m, _messages.ViewportMatplotlibMessage) for m in retained(server))
    old = pane._content
    pane.clear()
    assert old._impl.figure_ref is None
    go = pytest.importorskip("plotly.graph_objects")
    pane.set_plotly(go.Figure(), config={"displayModeBar": False})
    assert any(isinstance(m, _messages.ViewportPlotlyMessage) for m in retained(server))
    pane.clear()
    pane.set_image(np.zeros((2, 3, 3), np.uint8))


def test_cleared_image_keeps_default_quality_after_one_frame_override(server, monkeypatch):
    pane = server.panes.add_image(
        np.zeros((2, 3, 3), np.uint8), format="jpeg", jpeg_quality=70, fit="fill"
    )
    pane.clear()
    qualities = []
    encode = _panes.encode_image_binary

    def record(*args, **kwargs):
        qualities.append(kwargs["jpeg_quality"])
        return encode(*args, **kwargs)

    monkeypatch.setattr(_panes, "encode_image_binary", record)
    pane.update(np.ones((2, 3, 3), np.uint8), jpeg_quality=20)
    pane.update(np.zeros((2, 3, 3), np.uint8))
    assert qualities == [20, 70]
    assert pane.format == "jpeg" and pane.fit == "fill"


def test_cleared_plotly_restores_bounded_config_without_retaining_figure(server):
    go = pytest.importorskip("plotly.graph_objects")
    pane = server.panes.add_plotly(
        go.Figure(data=[go.Scatter(y=[1, 2])]), config={"displayModeBar": False}
    )
    old = pane._content
    pane.clear()
    assert old._impl.props._plotly_json_str == ""
    assert pane._impl.resume_options == {"config": {"displayModeBar": False}}
    pane.update(go.Figure(data=[go.Scatter(y=[3, 4])]))
    _, config = _panes._plotly_payload_from_json(pane._impl.props._plotly_json_str)
    assert config == {"displayModeBar": False}
    assert list(pane.figure.data[0].y) == [3, 4]
