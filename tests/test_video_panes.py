from pathlib import Path

import pytest

import leika
from leika import _messages
from leika._panes import _PaneResourceCost


def test_video_gallery_replay_update_and_retirement(server: leika.Server, tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"immutable media")
    pane = server.panes.add_video_gallery({"Task": clip}, pane_id="videos")
    buffer = server._websock_server.get_message_buffer()
    creates = [
        m for m in buffer.message_from_id.values() if isinstance(m, _messages.ViewportVideoMessage)
    ]
    assert len(creates) == 1
    assert creates[0].props._videos[0][1].startswith("/leika-assets/")
    pane.update({"Other": "/media/other.mp4"})
    assert pane._impl.props._videos == (("Other", "/media/other.mp4"),)
    cost = server.panes._resource_total
    assert cost.text_units == len("VideosOther/media/other.mp4")
    pane.remove()
    assert pane._impl.props._videos == ()
    assert server.panes._resource_total == _PaneResourceCost()
    with pytest.raises(RuntimeError, match="removed"):
        pane.update({})


def test_video_publication_failure_rolls_back(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    pane = server.panes.add_video_gallery({"Task": "/a.mp4"})
    cost = server.panes._resource_total

    def fail(*args: object) -> None:
        raise RuntimeError("publication rejected")

    monkeypatch.setattr(server._websock_server, "queue_message_or_raise", fail)
    with pytest.raises(RuntimeError, match="publication rejected"):
        pane.update({"Other": "/b.mp4"})
    assert pane._impl.props._videos == (("Task", "/a.mp4"),)
    assert server.panes._resource_total == cost
    monkeypatch.setattr(server._websock_server, "queue_messages_or_raise", fail)
    with pytest.raises(RuntimeError):
        server.panes.add_video_gallery({"New": "/c.mp4"})
    assert server.panes._resource_total == cost
    assert server.panes._aggregate.live_panes == 1


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "//example.org/a.mp4", "/\\example.org/a", "/a\nb", "local.mp4"]
)
def test_video_rejects_unsafe_or_ambiguous_urls(server: leika.Server, url: str) -> None:
    with pytest.raises(ValueError):
        server.panes.add_video_gallery({"Task": url})
    assert server.panes._aggregate.live_panes == 0


def test_video_layout_helpers_and_limits(server: leika.Server) -> None:
    row = server.panes.add_row()
    row.add_video_gallery({"one": "/1.mp4"})
    server.panes.add_grid(columns=2).add_video_gallery({})
    with pytest.raises(ValueError, match="32"):
        server.panes.add_video_gallery({str(i): f"/{i}.mp4" for i in range(33)})
    with pytest.raises(ValueError, match="columns"):
        server.panes.add_video_gallery({}, columns=0)
