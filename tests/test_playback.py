from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

import leika
from leika import _messages
from leika.infra import ClientId


def test_playback_clock_pause_loop_and_buffering(server: leika.Server) -> None:
    bar = server.gui.add_playback(duration=2, fps=20, loop=False)
    assert bar.advance(1).time == 0
    bar.update(playing=True, speed=2)
    assert bar.advance(0.25).time == 0.5
    bar.buffering = True
    assert bar.advance(10).time == 0.5
    bar.buffering = False
    final = bar.advance(2)
    assert final.time == 2 and not final.playing
    bar.update(playing=True, loop=True)
    assert bar.advance(2.25).time == 0.5
    bar.disabled = True
    assert bar.advance(1).time == 0.5
    with pytest.raises(FrozenInstanceError):
        final.time = 0  # type: ignore[misc]
    with pytest.raises(ValueError):
        bar.advance(-1)


def test_playback_commands_preserve_steps_and_snapshot_events(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    bar = server.gui.add_playback(duration=2, fps=20)
    events: list[leika.PlaybackEvent] = []
    bar.on_update(events.append)

    async def command(action: _messages.PlaybackAction, value: float = 0) -> None:
        await server.gui._handle_playback_command(
            ClientId(1), _messages.GuiPlaybackCommandMessage(bar.id, action, value)
        )

    async def exercise() -> None:
        await command("play")
        for _ in range(5):
            await command("step", 1)
        await command("speed", 2)
        await command("loop")
        await command("seek", 1.026)

    asyncio.run(exercise())
    assert [e.state.time for e in events[1:6]] == [0.05, 0.1, 0.15, 0.2, 0.25]
    assert all(not e.state.playing for e in events[1:6])
    assert bar.time == 1.05 and bar.speed == 2 and not bar.loop
    assert events[0].state.playing and events[0].state.time == 0
    assert events[0].value is None
    assert all(e.value == 1 for e in events[1:6])
    assert events[-1].value == 1.026  # Retain intent before frame quantization.
    bar.time = 0.7
    bar.advance(1)
    assert len(events) == 9  # Publishing progress never feeds back as user input.
    bar.update(time=2, playing=False)
    asyncio.run(command("play"))
    assert bar.time == 0 and bar.playing
    bar.disabled = True
    asyncio.run(command("seek", 1))
    assert bar.time == 0
    bar.disabled = False
    bar.visible = False
    asyncio.run(command("play"))
    assert len(events) == 10
    bar.remove()
    asyncio.run(command("seek", 1))
    assert len(events) == 10


def test_playback_validation_publication_and_removal(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    for kwargs in (
        {"duration": -1},
        {"duration": 2, "time": 3},
        {"duration": 1, "fps": 0},
        {"duration": 1, "speed": float("nan")},
        {"duration": True},
    ):
        with pytest.raises((TypeError, ValueError)):
            server.gui.add_playback(**kwargs)
    assert not server.gui._playback_handle_from_uuid
    with server.gui.add_folder("Playback") as folder:
        bar = folder.add_playback(duration=3, time=2)
    before = bar.state
    with pytest.raises(ValueError):
        bar.duration = 1
    assert bar.state == before
    bar.update(duration=1, time=0)

    def fail(*args: object) -> None:
        raise RuntimeError("publication rejected")

    with monkeypatch.context() as patch:
        patch.setattr(server._websock_server, "queue_message_or_raise", fail)
        with pytest.raises(RuntimeError):
            bar.time = 0.5
        with pytest.raises(RuntimeError):
            server.gui.add_playback(duration=1)
    assert bar.time == 0 and len(server.gui._playback_handle_from_uuid) == 1
    folder.remove()
    assert not server.gui._playback_handle_from_uuid
    with pytest.raises(RuntimeError):
        bar.advance(0.1)


def test_video_playback_adapter_keeps_browser_clock(server: leika.Server) -> None:
    bar = server.gui.add_playback(sync_group="episode")
    assert isinstance(bar, leika.GuiVideoControlsHandle)
    assert bar.sync_group == "episode"
    with pytest.raises(ValueError):
        server.gui.add_playback(sync_group="episode", duration=2)  # type: ignore[call-overload]
    with pytest.raises(ValueError):
        server.gui.add_playback()  # type: ignore[call-overload]
