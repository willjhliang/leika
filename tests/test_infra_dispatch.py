from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any

import msgspec.msgpack
import pytest
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
from leika import _messages
from leika.infra import ClientId, WebsockServer, protocol_fingerprint
from leika.infra._infra import _message_consumer, _run_connection_tasks


def _client_subprotocol() -> Subprotocol:
    return Subprotocol(f"leika-v{leika.__version__}+p{protocol_fingerprint(_messages.Message)}")


def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


class _DecodedMessage:
    @classmethod
    def deserialize(cls, raw: bytes) -> str:
        return raw.decode()


class _ScriptedSocket:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames
        self.recv_count = 0

    async def recv(self) -> bytes:
        self.recv_count += 1
        if not self.frames:
            raise StopAsyncIteration
        return self.frames.pop(0)


def test_message_consumer_awaits_handlers_in_wire_order() -> None:
    async def scenario() -> None:
        socket = _ScriptedSocket([b"first", b"second"])
        seen: list[str] = []

        async def handle(message: str) -> None:
            seen.append("start " + message)
            await asyncio.sleep(0)
            seen.append("end " + message)

        with pytest.raises(StopAsyncIteration):
            await _message_consumer(
                socket,  # type: ignore[arg-type]
                handle,  # type: ignore[arg-type]
                _DecodedMessage,  # type: ignore[arg-type]
            )
        assert seen == ["start first", "end first", "start second", "end second"]

    asyncio.run(scenario())


def test_message_consumer_propagates_handler_failure_before_reading_more() -> None:
    failure = RuntimeError("handler failed")

    async def scenario() -> None:
        socket = _ScriptedSocket([b"first", b"second"])

        async def handle(_: Any) -> None:
            raise failure

        with pytest.raises(RuntimeError, match="handler failed") as captured:
            await _message_consumer(
                socket,  # type: ignore[arg-type]
                handle,
                _DecodedMessage,  # type: ignore[arg-type]
            )
        assert captured.value is failure
        assert socket.recv_count == 1

    asyncio.run(scenario())


def test_connection_task_failure_cancels_and_awaits_siblings() -> None:
    failure = RuntimeError("consumer failed")

    async def scenario() -> None:
        sibling_started = asyncio.Event()
        sibling_finished = asyncio.Event()

        async def fail() -> None:
            await sibling_started.wait()
            raise failure

        async def wait_forever() -> None:
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_finished.set()

        with pytest.raises(RuntimeError, match="consumer failed") as captured:
            await _run_connection_tasks(fail(), wait_forever())
        assert captured.value is failure
        assert sibling_finished.is_set()

    asyncio.run(scenario())


def test_registered_handler_failure_is_reported_without_aborting_dispatch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = WebsockServer(host="127.0.0.1", port=0, verbose=False)
    events: list[str] = []

    async def fail(_: ClientId, __: _messages.ClientPingMessage) -> None:
        events.append("failure started")
        await asyncio.sleep(0)
        events.append("failure reported")
        raise RuntimeError("user callback failed")

    async def continue_dispatch(_: ClientId, __: _messages.ClientPingMessage) -> None:
        events.append("later handler ran")

    server.register_handler(_messages.ClientPingMessage, fail)
    server.register_handler(_messages.ClientPingMessage, continue_dispatch)
    asyncio.run(
        server._handle_incoming_message(ClientId(4), _messages.ClientPingMessage(sent_ms=1.0))
    )

    assert events == [
        "failure started",
        "failure reported",
        "later handler ran",
    ]
    captured = capsys.readouterr()
    assert "Task failed with exception" in captured.err
    assert "RuntimeError: user callback failed" in captured.err


def test_peer_close_cancels_a_blocked_ordered_handler() -> None:
    started = threading.Event()
    cancelled = threading.Event()
    release = threading.Event()

    async def block(_: ClientId, __: _messages.ClientPingMessage) -> None:
        started.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)
    server.register_handler(_messages.ClientPingMessage, block)
    server.start()
    websocket = None
    try:
        websocket = connect(
            f"ws://127.0.0.1:{server._port}",
            subprotocols=[_client_subprotocol()],
            open_timeout=2,
        )
        message = _messages.ClientPingMessage(sent_ms=1.0)
        websocket.send(msgspec.msgpack.encode(message.as_serializable_dict()))
        assert started.wait(2.0)

        websocket.close()
        assert cancelled.wait(2.0)
        _wait_for(lambda: server._client_state_from_id == {})
    finally:
        release.set()
        if websocket is not None:
            websocket.close()
        server.stop()


def test_peer_close_cancels_connect_callbacks_and_runs_teardown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    started = threading.Event()
    cancelled = threading.Event()
    disconnected = threading.Event()
    release = threading.Event()

    async def fail(_: Any) -> None:
        raise RuntimeError("connect callback failed")

    async def block(_: Any) -> None:
        started.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)
    server.on_client_connect(fail)
    server.on_client_connect(block)
    server.on_client_disconnect(lambda _: disconnected.set())
    server.start()
    websocket = None
    try:
        websocket = connect(
            f"ws://127.0.0.1:{server._port}",
            subprotocols=[_client_subprotocol()],
            open_timeout=2,
        )
        assert started.wait(2.0)

        websocket.close()
        assert cancelled.wait(2.0)
        assert disconnected.wait(2.0)
        _wait_for(lambda: server._client_state_from_id == {})
        assert "RuntimeError: connect callback failed" in capsys.readouterr().err
    finally:
        release.set()
        if websocket is not None:
            websocket.close()
        server.stop()


def test_server_stop_cancels_blocked_disconnect_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    started = threading.Event()
    cancelled = threading.Event()
    release = threading.Event()

    async def fail(_: Any) -> None:
        raise RuntimeError("disconnect callback failed")

    async def block(_: Any) -> None:
        started.set()
        try:
            while not release.is_set():
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr("leika.infra._infra._SERVER_STOP_TIMEOUT_SECONDS", 1.0)
    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)
    server.on_client_disconnect(fail)
    server.on_client_disconnect(block)
    server.start()
    websocket = connect(
        f"ws://127.0.0.1:{server._port}",
        subprotocols=[_client_subprotocol()],
        open_timeout=2,
    )
    stopped = False
    try:
        websocket.close()
        assert started.wait(2.0)
        _wait_for(lambda: server._client_state_from_id == {})

        server.stop()
        stopped = True
        assert cancelled.wait(2.0)
        assert server._server_thread is not None
        assert not server._server_thread.is_alive()
        assert "RuntimeError: disconnect callback failed" in capsys.readouterr().err
    finally:
        release.set()
        websocket.close()
        if not stopped:
            server.stop()
