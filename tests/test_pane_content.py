"""Stable pane identity, replaceable renderer ownership, and replay behavior."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest

from leika import _messages, _panes

from .utils import queued_messages


def retained(server):
    return tuple(queued_messages(server._websock_server.get_message_buffer()).values())


def test_general_pane_replaces_content_and_replay_without_changing_identity(server):
    grid = server.panes.add_grid(columns=2)
    panes = [grid.add_pane(pane_id=f"slot-{i}", title=f"Slot {i}") for i in range(4)]
    pane = panes[0]
    pane.set_image(np.zeros((8, 12, 3), np.uint8))
    assert pane._source.shape == (8, 12, 3)
    pane.set_video("/camera.mp4", sync_group="episode", fps=10)
    assert pane._source is None and pane._renderer is _panes.VideoPaneHandle
    assert server.panes._handle_from_pane_id["slot-0"] is pane
    assert pane.title == "Slot 0"
    pane.clear(loading="Waiting")
    assert pane.loading == "Waiting"
    messages = retained(server)
    declarations = [m for m in messages if isinstance(m, _messages.ViewportPaneMessage)]
    assert [m.pane_id for m in declarations] == [p.pane_id for p in panes]
    # The first pane fills the empty workspace; later ones split beside it.
    assert declarations[0].relative_to is None
    assert declarations[1].relative_to == "slot-0"
    assert not any(
        isinstance(m, (_messages.ViewportImageMessage, _messages.ViewportVideoMessage))
        for m in messages
    )
    pane.remove()
    assert not any(getattr(m, "pane_id", None) == pane.pane_id for m in retained(server))


def test_typed_update_restores_video_settings_after_clear(server):
    pane = server.panes.add_video(
        "/a.mp4", sync_group="episode", fps=30, loop=False, autoplay=False
    )
    pane.clear()
    pane.update("/b.mp4", loading=False)
    assert pane.sync_group == "episode" and pane.fps == 30
    assert pane._props._url == "/b.mp4"
    assert not pane._props.loop and not pane._props.autoplay
    pane.set_image(np.zeros((2, 3, 3), np.uint8))
    with pytest.raises(RuntimeError, match="different"):
        pane.update("/c.mp4")
    with pytest.raises(RuntimeError, match="different"):
        _ = pane.sync_group
    pane.clear()
    with pytest.raises(RuntimeError, match="different"):
        pane.update("/c.mp4")
    pane.set_video("/d.mp4")
    pane.update("/e.mp4")
    assert pane._props._url == "/e.mp4"


@pytest.mark.parametrize("operation", ["update", "set_image"])
def test_clear_rejects_inflight_image_work(server, monkeypatch, operation):
    pane = server.panes.add_image(np.zeros((2, 3, 3), np.uint8))
    started, release = threading.Event(), threading.Event()
    prepare = _panes.prepare_image

    def blocked(*args):
        started.set()
        assert release.wait(5)
        return prepare(*args)

    monkeypatch.setattr(_panes, "prepare_image", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(getattr(pane, operation), np.ones((2, 3, 3), np.uint8))
        assert started.wait(5)
        try:
            pane.clear()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="changed"):
            result.result(timeout=5)
    assert pane._source is None
    assert not any(isinstance(m, _messages.ViewportImageMessage) for m in retained(server))


def test_inflight_update_keeps_a_setting_changed_meanwhile(server, monkeypatch):
    pane = server.panes.add_image(np.zeros((2, 3, 3), np.uint8), fit="fit")
    started, release = threading.Event(), threading.Event()
    prepare = _panes.prepare_image

    def blocked(*args):
        started.set()
        assert release.wait(5)
        return prepare(*args)

    monkeypatch.setattr(_panes, "prepare_image", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(pane.update, np.ones((2, 3, 3), np.uint8))
        assert started.wait(5)
        pane.fit = "fill"
        release.set()
        result.result(timeout=5)
    assert pane.fit == "fill" and pane._settings["fit"] == "fill"
    updates = [m for m in retained(server) if isinstance(m, _messages.ViewportPaneUpdateMessage)]
    assert updates[-1].updates["fit"] == "fill"


@pytest.mark.parametrize("clear", [False, True])
def test_failed_replacement_preserves_content_and_replay(server, monkeypatch, clear):
    pane = server.panes.add_image(np.zeros((2, 3, 3), np.uint8), title="Original")
    renderer, source, messages = pane._renderer, pane._source, retained(server)

    def reject(*args):
        raise RuntimeError("publication failed")

    monkeypatch.setattr(server.panes._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="publication failed"):
        pane.clear() if clear else pane.set_viser("https://example.com/scene")
    assert pane._renderer is renderer and pane._source is source
    assert pane.title == "Original"
    assert retained(server) == messages


def test_clear_unregisters_viser_proxy(server):
    target = SimpleNamespace(get_host=lambda: "127.0.0.1", get_port=lambda: 9876)
    pane = server.panes.add_viser(target, minimize_gui=False)
    proxy = server._websock_server._viser_proxy
    route = pane._source.path
    assert route in proxy._endpoints
    pane.update(target)
    assert pane._source.path == route
    pane.clear()
    assert route not in proxy._endpoints
    pane.update(target)
    assert pane.port == 9876
    assert pane._settings == {"minimize_gui": False}
    pane.remove()
    assert proxy._endpoints == {}


def test_replacement_preserves_refresh_bindings_and_latest_metadata(server, monkeypatch):
    control = server.gui.add_checkbox("Selection", initial_value=False)
    pane = server.panes.add_pane(title="Original")
    pane.invalidate_on(control)
    video_url = _panes._video_url

    def rename_during_preparation(*args):
        pane.title = "Latest"
        pane.visible = False
        pane.loading = "Preparing"
        return video_url(*args)

    monkeypatch.setattr(_panes, "_video_url", rename_during_preparation)
    pane.set_video("/movie.mp4")
    assert (pane.title, pane.visible, pane.loading) == ("Latest", False, "Preparing")
    updates = [m for m in retained(server) if isinstance(m, _messages.ViewportPaneUpdateMessage)]
    assert updates[-1].updates["_refresh_controls"] == [control._impl.uuid]
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
    go = pytest.importorskip("plotly.graph_objects")
    pane.set_plotly(go.Figure(data=[go.Scatter(y=[1, 2])]), config={"displayModeBar": False})
    messages = retained(server)
    assert any(isinstance(m, _messages.ViewportPlotlyMessage) for m in messages)
    assert not any(isinstance(m, _messages.ViewportMatplotlibMessage) for m in messages)
    assert pane._source is None


def test_cleared_image_keeps_default_quality_after_one_frame_override(server, monkeypatch):
    pane = server.panes.add_image(
        np.zeros((2, 3, 3), np.uint8), format="jpeg", jpeg_quality=70, fit="fill"
    )
    pane.clear()
    qualities = []
    prepare = _panes.prepare_image

    def record(image, format, jpeg_quality):
        qualities.append(jpeg_quality)
        return prepare(image, format, jpeg_quality)

    monkeypatch.setattr(_panes, "prepare_image", record)
    pane.update(np.ones((2, 3, 3), np.uint8), jpeg_quality=20)
    pane.update(np.zeros((2, 3, 3), np.uint8))
    assert qualities == [20, 70]
    assert pane.format == "jpeg" and pane.fit == "fill"


def test_cleared_plotly_restores_config_without_retaining_figure(server):
    go = pytest.importorskip("plotly.graph_objects")
    pane = server.panes.add_plotly(
        go.Figure(data=[go.Scatter(y=[1, 2])]), config={"displayModeBar": False}
    )
    pane.clear()
    assert pane._props == _messages.ViewportEmptyProps(title="Plotly", visible=True, loading=False)
    pane.update(go.Figure(data=[go.Scatter(y=[3, 4])]))
    assert json.loads(pane._props._plotly_json_str)["config"] == {"displayModeBar": False}
    assert list(pane.figure.data[0].y) == [3, 4]
