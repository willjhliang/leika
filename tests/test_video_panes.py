from pathlib import Path

import pytest

import leika
from leika import _messages
from leika._panes import _PaneResourceCost


def test_video_replay_update_and_retirement(server: leika.Server, tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"immutable media")
    pane = server.panes.add_video(clip, pane_id="videos")
    buffer = server._websock_server.get_message_buffer()
    creates = [
        m for m in buffer.message_from_id.values() if isinstance(m, _messages.ViewportVideoMessage)
    ]
    assert len(creates) == 1
    assert creates[0].props._url.startswith("/leika-assets/")
    pane.update("/media/other.mp4")
    assert pane._impl.props._url == "/media/other.mp4"
    cost = server.panes._resource_total
    assert cost.text_units == len("Video/media/other.mp4")
    pane.remove()
    assert pane._impl.props._url == ""
    assert server.panes._resource_total == _PaneResourceCost()
    with pytest.raises(RuntimeError, match="removed"):
        pane.update("/other.mp4")


def test_video_publication_failure_rolls_back(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    pane = server.panes.add_video("/a.mp4")
    cost = server.panes._resource_total

    def fail(*args: object) -> None:
        raise RuntimeError("publication rejected")

    monkeypatch.setattr(server._websock_server, "queue_message_or_raise", fail)
    with pytest.raises(RuntimeError, match="publication rejected"):
        pane.update("/b.mp4")
    assert pane._impl.props._url == "/a.mp4"
    assert server.panes._resource_total == cost
    monkeypatch.setattr(server._websock_server, "queue_messages_or_raise", fail)
    with pytest.raises(RuntimeError):
        server.panes.add_video("/c.mp4")
    assert server.panes._resource_total == cost
    assert server.panes._aggregate.live_panes == 1


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "//example.org/a.mp4", "/\\example.org/a", "/a\nb", "local.mp4"]
)
def test_video_rejects_unsafe_or_ambiguous_urls(server: leika.Server, url: str) -> None:
    with pytest.raises(ValueError):
        server.panes.add_video(url)
    assert server.panes._aggregate.live_panes == 0


def test_video_layout_helpers_and_limits(server: leika.Server) -> None:
    row = server.panes.add_row()
    row.add_video("/1.mp4")
    server.panes.add_column().add_video("/2.mp4")
    grid = server.panes.add_grid(columns=2)
    for index in range(4):
        grid.add_video(f"/{index}.mp4")
    with pytest.raises(ValueError, match="16384"):
        server.panes.add_video("/" + "x" * 16384)
    with pytest.raises(TypeError, match="source"):
        server.panes.add_video({"Task": "/a.mp4"})  # type: ignore[arg-type]


def test_video_update_settles_loading_atomically(server: leika.Server) -> None:
    pane = server.panes.add_video("/a.mp4", loading=True)
    pane.update("/b.mp4", loading=False)
    assert pane._impl.props._url == "/b.mp4"
    assert pane.loading is False
    with pytest.raises(TypeError):
        pane.update("/c.mp4", loading=1)  # type: ignore[arg-type]
    assert pane._impl.props._url == "/b.mp4"


def test_shared_video_api_replay_and_group_assignment(server: leika.Server) -> None:
    controls = server.gui.add_video_controls(sync_group="episode")
    assert controls.label is None
    with server.gui.add_folder("Nested") as folder:
        nested = folder.add_video_controls("Other", sync_group="episode")
    for api in (server.panes, server.panes.add_row(), server.panes.add_grid(columns=2)):
        pane = api.add_video("/clip.mp4", sync_group="episode", fps=30)
        assert pane.sync_group == "episode"
        assert pane.fps == 30
        pane.sync_group = None
        pane.fps = 7.5
        assert pane.sync_group is None
        assert pane.fps == 7.5
        pane.remove()
    controls.visible = False
    controls.label = "Timeline"
    assert controls.label == "Timeline"
    controls.label = None
    assert controls.label is None
    nested.sync_group = "other"
    messages = list(server._websock_server.get_message_buffer().message_from_id.values())
    creates = [m for m in messages if isinstance(m, _messages.GuiVideoControlsMessage)]
    assert len(creates) == 2
    assert {m.props.sync_group for m in creates} == {"episode"}  # Updates replay separately.
    folder.remove()
    controls.remove()
    assert controls._impl.removed and nested._impl.removed


@pytest.mark.parametrize("group", ["", "__proto__", "a" * 1025, 3])
def test_video_group_validation_is_transactional(server: leika.Server, group: object) -> None:
    pane = server.panes.add_video("/clip.mp4", sync_group="valid")
    controls = server.gui.add_video_controls("Playback", sync_group="valid")
    for assign in (
        lambda: server.panes.add_video("/clip.mp4", sync_group=group),
        lambda: server.gui.add_video_controls("Playback", sync_group=group),
        lambda: setattr(pane, "sync_group", group),
        lambda: setattr(controls, "sync_group", group),
    ):
        with pytest.raises((ValueError, TypeError)):
            assign()
    assert pane.sync_group == controls.sync_group == "valid"
    assert server.panes._aggregate.live_panes == 1


@pytest.mark.parametrize("fps", [0, -1, float("inf"), float("nan"), True, "30"])
def test_video_fps_rejects_invalid_values(server: leika.Server, fps: object) -> None:
    pane = server.panes.add_video("/clip.mp4", fps=30)
    with pytest.raises(ValueError, match="fps"):
        server.panes.add_video("/clip.mp4", fps=fps)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="fps"):
        pane.fps = fps  # type: ignore[assignment]
    assert pane.fps == 30
    pane.fps = None
    assert pane.fps is None
