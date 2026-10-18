from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import random
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from typing import Any

import msgspec.msgpack
import pytest
import zstandard
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Subprotocol

from leika import _messages
from leika._transport import _websocket as websocket_impl
from leika._transport._message_buffer import AsyncMessageBuffer
from leika._transport._typescript import protocol_fingerprint
from leika._transport._websocket import (
    ClientId,
    WebsockClientConnection,
    WebsockServer,
    _ClientHandleState,
    _message_producer,
    _run_connection_tasks,
)


async def _ignore(_: WebsockClientConnection) -> None:
    pass


def _server(**kwargs: Any) -> WebsockServer:
    kwargs.setdefault("on_connect", _ignore)
    kwargs.setdefault("on_disconnect", _ignore)
    return WebsockServer("127.0.0.1", 0, verbose=False, **kwargs)


def _connect(server: WebsockServer, *subprotocols: str) -> ClientConnection:
    """Connect offering Leika's subprotocol, or the given ones ("" offers none)."""
    offered = subprotocols or (f"leika-{protocol_fingerprint()}",)
    return connect(
        f"ws://127.0.0.1:{server._port}",
        subprotocols=[Subprotocol(value) for value in offered if value] or None,
        open_timeout=2,
    )


def _admitted(server: WebsockServer) -> bool:
    """Whether a new client is accepted and kept open."""
    with _connect(server) as websocket:
        try:
            websocket.recv(timeout=0.1)
        except TimeoutError:
            pass
        except ConnectionClosed:
            return False
    return True


def _wait_for(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    """Poll until ``predicate`` holds, evaluating it once per attempt."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached in time"
        time.sleep(0.01)


def _decode_frame(frame: bytes | str) -> list[dict[str, Any]]:
    """Messages of one frame: a little-endian uint64 size, then zstd MessagePack."""
    assert isinstance(frame, bytes)
    size = int.from_bytes(frame[:8], "little")
    payload = zstandard.ZstdDecompressor().decompress(frame[8:], max_output_size=size)
    assert len(payload) == size
    envelope = msgspec.msgpack.decode(payload)
    assert isinstance(envelope["timestampSec"], float)
    return envelope["messages"]


def _close_code(websocket: ClientConnection) -> tuple[int, str]:
    with pytest.raises(ConnectionClosed) as closed:
        websocket.recv(timeout=2)
    assert closed.value.rcvd is not None
    return closed.value.rcvd.code, closed.value.rcvd.reason


async def _block(started: threading.Event, cancelled: threading.Event) -> None:
    started.set()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        cancelled.set()
        raise


class _RecordingSocket:
    """Records sent frames; each ping returns a receipt the test resolves."""

    def __init__(self, *, automatic_receipts: bool = False) -> None:
        self.frames: asyncio.Queue[bytes] = asyncio.Queue()
        self.receipts: asyncio.Queue[asyncio.Future[float]] = asyncio.Queue()
        self.automatic_receipts = automatic_receipts
        self.sent = 0

    async def send(self, frame: bytes) -> None:
        self.sent += 1
        self.frames.put_nowait(frame)

    async def ping(self) -> asyncio.Future[float]:
        receipt = asyncio.get_running_loop().create_future()
        if self.automatic_receipts:
            receipt.set_result(0.0)
        else:
            self.receipts.put_nowait(receipt)
        return receipt


def _produce(
    socket: _RecordingSocket,
    buffer: AsyncMessageBuffer,
    client_id: int,
    state: _ClientHandleState | None = None,
    *,
    delivery_backpressure: bool = False,
) -> asyncio.Task[None]:
    return asyncio.ensure_future(
        _message_producer(
            socket,  # type: ignore[arg-type]
            buffer,
            client_id,
            state or _ClientHandleState(buffer, buffer),
            delivery_backpressure=delivery_backpressure,
        )
    )


async def _next_frame(socket: _RecordingSocket) -> list[dict[str, Any]]:
    return _decode_frame(await asyncio.wait_for(socket.frames.get(), timeout=1))


async def _shut_down(buffer: AsyncMessageBuffer, *tasks: asyncio.Task[None]) -> None:
    buffer.set_done()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


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


def test_handlers_run_in_registration_order_and_failures_do_not_stop_later_ones(
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = _server()
    completion: Future[None] = Future()
    events: list[str] = []

    def awaited(_: ClientId, __: _messages.ClientPingMessage) -> Future[None]:
        events.append("returns future")
        return completion

    async def fail(_: ClientId, __: _messages.ClientPingMessage) -> None:
        events.append("fails")
        raise RuntimeError("user callback failed")

    server.register_handler(_messages.ClientPingMessage, awaited)
    server.register_handler(_messages.ClientPingMessage, fail)
    server.register_handler(_messages.ClientPingMessage, lambda *_: events.append("last"))

    async def scenario() -> None:
        ping = _messages.ClientPingMessage(sent_ms=1.0)
        task = asyncio.ensure_future(server._handle_incoming_message(ClientId(4), ping))
        while not events:
            await asyncio.sleep(0)
        # A handler registered mid-dispatch applies only to later messages.
        server.register_handler(_messages.ClientPingMessage, lambda *_: events.append("late"))
        await asyncio.sleep(0.01)
        assert events == ["returns future"]
        completion.set_result(None)
        await asyncio.wait_for(task, timeout=1)
        assert events == ["returns future", "fails", "last"]

        await server._handle_incoming_message(ClientId(4), ping)
        assert events[3:] == ["returns future", "fails", "last", "late"]

    asyncio.run(scenario())
    assert "RuntimeError: user callback failed" in capsys.readouterr().err


def test_server_then_connection_handlers_finish_each_message_in_wire_order() -> None:
    events: list[str] = []
    finished = threading.Event()

    async def server_handler(_: ClientId, message: _messages.ClientPingMessage) -> None:
        events.append(f"server {message.sent_ms:g}")
        await asyncio.sleep(0.01)
        events.append(f"server done {message.sent_ms:g}")

    async def connection_handler(_: ClientId, message: _messages.ClientPingMessage) -> None:
        events.append(f"connection {message.sent_ms:g}")
        if message.sent_ms == 2:
            finished.set()

    async def on_connect(connection: WebsockClientConnection) -> None:
        connection.register_handler(_messages.ClientPingMessage, connection_handler)

    server = _server(on_connect=on_connect)
    server.register_handler(_messages.ClientPingMessage, server_handler)
    server.start()
    try:
        with _connect(server) as websocket:
            websocket.send(_messages.ClientPingMessage(sent_ms=1.0).encode())
            websocket.send(_messages.ClientPingMessage(sent_ms=2.0).encode())
            assert finished.wait(2)
        assert events == [
            "server 1",
            "server done 1",
            "connection 1",
            "server 2",
            "server done 2",
            "connection 2",
        ]
    finally:
        server.stop()


def test_peer_close_cancels_a_blocked_handler() -> None:
    started, cancelled = threading.Event(), threading.Event()

    async def block(_: ClientId, __: _messages.ClientPingMessage) -> None:
        await _block(started, cancelled)

    server = _server()
    server.register_handler(_messages.ClientPingMessage, block)
    server.start()
    try:
        with _connect(server) as websocket:
            websocket.send(_messages.ClientPingMessage(sent_ms=1.0).encode())
            assert started.wait(2)
        assert cancelled.wait(2)
        _wait_for(lambda: server._client_state_from_id == {})
    finally:
        server.stop()


def test_peer_close_cancels_a_blocked_connect_callback_and_runs_disconnect() -> None:
    started, cancelled = threading.Event(), threading.Event()
    disconnected: list[ClientId] = []

    async def on_connect(_: WebsockClientConnection) -> None:
        await _block(started, cancelled)

    async def on_disconnect(connection: WebsockClientConnection) -> None:
        disconnected.append(connection.client_id)

    server = _server(on_connect=on_connect, on_disconnect=on_disconnect)
    server.start()
    try:
        with _connect(server):
            assert started.wait(2)
        assert cancelled.wait(2)
        _wait_for(lambda: len(disconnected) == 1)
        assert server._client_state_from_id == {}
    finally:
        server.stop()


def test_failed_connect_callback_is_reported_and_the_connection_stays_live(
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def on_connect(_: WebsockClientConnection) -> None:
        raise RuntimeError("connect callback failed")

    server = _server(on_connect=on_connect)
    server.start()
    try:
        with _connect(server) as websocket:
            assert server.queue_message(_messages.RunJavascriptMessage("still live"))
            server.flush()
            assert _decode_frame(websocket.recv(timeout=2)) == [
                {"type": "RunJavascriptMessage", "source": "still live"}
            ]
    finally:
        server.stop()
    assert "RuntimeError: connect callback failed" in capsys.readouterr().err


def test_server_stop_cancels_a_blocked_disconnect_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(websocket_impl, "_SERVER_STOP_TIMEOUT_SECONDS", 2.0)
    started, cancelled = threading.Event(), threading.Event()

    async def on_disconnect(_: WebsockClientConnection) -> None:
        await _block(started, cancelled)

    server = _server(on_disconnect=on_disconnect)
    server.start()
    try:
        with _connect(server):
            pass
        assert started.wait(2)
        server.stop()
        assert cancelled.is_set()
        assert server._server_thread is not None
        assert not server._server_thread.is_alive()
    finally:
        server.stop()


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ("text frame", 1003),
        (b"\xc1", 1007),
        (msgspec.msgpack.encode({"type": "UnknownMessage", "value": "anything"}), 1007),
        (msgspec.msgpack.encode({"type": "ClientPingMessage", "sent_ms": "soon"}), 1007),
    ],
)
def test_malformed_protocol_input_closes_only_its_connection(
    payload: str | bytes,
    expected_code: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = _server()
    server.start()
    try:
        with _connect(server) as healthy, _connect(server) as websocket:
            websocket.send(payload)
            assert _close_code(websocket)[0] == expected_code

            # The listener and every other connection stay healthy.
            assert server.queue_message(_messages.RunJavascriptMessage("after"))
            server.flush()
            assert _decode_frame(healthy.recv(timeout=2))[-1]["source"] == "after"
        assert "Traceback" not in capsys.readouterr().err
    finally:
        server.stop()


def test_oversized_incoming_frame_closes_cleanly_and_server_stays_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A small limit keeps the unread remainder from stalling the server-side
    # close for websockets' ten-second close timeout.
    monkeypatch.setattr(websocket_impl, "_INCOMING_MESSAGE_LIMIT_BYTES", 1024)
    server = _server()
    server.start()
    try:
        with _connect(server) as websocket:
            # The server may close before the whole frame is written.
            with contextlib.suppress(ConnectionClosed):
                websocket.send(b"x" * 1025)
            assert _close_code(websocket)[0] == 1009
        assert _admitted(server)
    finally:
        server.stop()


def test_connection_cap_rejects_extra_clients_and_releases_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(websocket_impl, "_MAX_ACTIVE_CONNECTIONS", 1)
    server = _server()
    server.start()
    try:
        with _connect(server):
            _wait_for(lambda: len(server._client_state_from_id) == 1)
            with _connect(server) as rejected:
                assert _close_code(rejected)[0] == 1013
            assert len(server._client_state_from_id) == 1

        # The slot frees once the first connection's teardown finishes.
        _wait_for(lambda: _admitted(server))
    finally:
        server.stop()


@pytest.mark.parametrize("subprotocol", ["", "leika-000000000000", "leika-v0.4.0+p000000000000"])
def test_protocol_mismatch_is_rejected_with_a_reason_and_releases_its_slot(
    monkeypatch: pytest.MonkeyPatch,
    subprotocol: str,
) -> None:
    monkeypatch.setattr(websocket_impl, "_MAX_ACTIVE_CONNECTIONS", 1)
    server = _server()
    server.start()
    try:
        with _connect(server, subprotocol) as rejected:
            code, reason = _close_code(rejected)
        assert code == 1002
        assert reason.startswith("Protocol mismatch")
        assert server._client_state_from_id == {}
        _wait_for(lambda: _admitted(server))
    finally:
        server.stop()


def test_delivery_scope_filters_real_websocket_transport() -> None:
    connections: dict[ClientId, WebsockClientConnection] = {}

    async def remember(connection: WebsockClientConnection) -> None:
        connections[connection.client_id] = connection

    def subscribe(client_id: ClientId, message: _messages.PageSubscribeMessage) -> None:
        page_id, generation = message.page_id, message.generation
        assert connections[client_id].request_delivery_scope(
            page_id,
            _messages.PageStreamBeginMessage(page_id, generation),
            _messages.PageStreamReadyMessage(page_id, generation),
        )

    server = _server(on_connect=remember)
    server.register_handler(_messages.PageSubscribeMessage, subscribe)
    server.start()
    try:
        assert server.queue_message(_messages.PageCatalogMessage(("alpha", "beta")))
        assert server.queue_message(_messages.ViewportPaneSnapshotMessage("alpha", ("a",)))
        assert server.queue_message(_messages.ViewportPaneSnapshotMessage("beta", ("b",)))

        with _connect(server) as websocket:
            assert _decode_frame(websocket.recv(timeout=2)) == [
                {"type": "PageCatalogMessage", "page_ids": ["alpha", "beta"]}
            ]

            websocket.send(_messages.PageSubscribeMessage("alpha", 1).encode())
            received: list[dict[str, Any]] = []
            while not received or received[-1]["type"] != "PageStreamReadyMessage":
                received.extend(_decode_frame(websocket.recv(timeout=2)))
            assert received == [
                {"type": "PageStreamBeginMessage", "page_id": "alpha", "generation": 1},
                {"type": "ViewportPaneSnapshotMessage", "page_id": "alpha", "pane_ids": ["a"]},
                {"type": "PageStreamReadyMessage", "page_id": "alpha", "generation": 1},
            ]
            assert connections[ClientId(0)].delivery_scope() == "alpha"

            assert server.queue_message(_messages.ViewportPaneSnapshotMessage("beta", ("live",)))
            server.flush()
            with pytest.raises(TimeoutError):
                websocket.recv(timeout=0.2)

            assert server.queue_message(_messages.ViewportPaneSnapshotMessage("alpha", ("live",)))
            server.flush()
            assert _decode_frame(websocket.recv(timeout=2)) == [
                {"type": "ViewportPaneSnapshotMessage", "page_id": "alpha", "pane_ids": ["live"]}
            ]
    finally:
        server.stop()


def test_closed_connection_refuses_state_messages() -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        local = AsyncMessageBuffer(loop, persistent_messages=False)
        retained = AsyncMessageBuffer(loop, persistent_messages=True)
        connection = WebsockClientConnection(ClientId(1), _ClientHandleState(local, retained))
        message = _messages.RunJavascriptMessage("state")
        with connection.atomic():
            assert local.atomic_counter == 1
            connection.queue_messages_or_raise([message])
        assert local.atomic_counter == 0

        local.set_done()
        assert connection.queue_message(message) is False
        with pytest.raises(RuntimeError, match="closed connection"):
            connection.queue_message_or_raise(message)
        with pytest.raises(RuntimeError, match="closed connection"):
            connection.queue_messages_or_raise([message, message])
        retained.set_done()

    asyncio.run(scenario())


def test_frames_reuse_bytes_encoded_once_at_push() -> None:
    encoded: list[str] = []

    @dataclasses.dataclass
    class _Counted(_messages.Message):
        value: str

        def encode(self) -> bytes:
            encoded.append(self.value)
            return super().encode()

    async def scenario() -> None:
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(), persistent_messages=True, window_duration_sec=0
        )
        kept, swapped = _Counted("kept"), _Counted("swapped")
        assert buffer.push_many((kept, swapped))
        assert encoded == ["kept", "swapped"]

        async def prepare(messages: Sequence[_messages.Message]) -> list[_messages.Message]:
            assert list(messages) == [kept, swapped]
            return [kept, _Counted("replacement")]

        hooked_state = _ClientHandleState(buffer, buffer, prepare_outgoing=prepare)
        plain, hooked = _RecordingSocket(), _RecordingSocket()
        producers = [_produce(plain, buffer, 1), _produce(hooked, buffer, 2, hooked_state)]
        try:
            assert await _next_frame(plain) == [
                {"type": "_Counted", "value": "kept"},
                {"type": "_Counted", "value": "swapped"},
            ]
            assert await _next_frame(hooked) == [
                {"type": "_Counted", "value": "kept"},
                {"type": "_Counted", "value": "replacement"},
            ]
            # Both clients' frames used the bytes stored at push; only the
            # hook's replacement was encoded again.
            assert encoded == ["kept", "swapped", "replacement"]
        finally:
            await _shut_down(buffer, *producers)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["off", "server", "rendering"])
def test_delivery_backpressure_coalesces_pending_updates_until_receipt(mode: str) -> None:
    async def scenario() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        state = _ClientHandleState(buffer, buffer, rendering_backpressure=mode == "rendering")
        socket = _RecordingSocket()
        assert buffer.push(_messages.GuiUpdateMessage("slider", {"value": 0}))
        producer = _produce(socket, buffer, 1, state, delivery_backpressure=mode == "server")
        try:
            await _next_frame(socket)
            receipt = None
            if mode != "off":
                receipt = await asyncio.wait_for(socket.receipts.get(), timeout=1)
            for value in range(1, 100):
                assert buffer.push(_messages.GuiUpdateMessage("slider", {"value": value}))
            buffer.flush()
            if receipt is not None:
                # Nothing more enters the socket before the peer's receipt.
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(socket.frames.get(), timeout=0.05)
                assert socket.sent == 1
                receipt.set_result(0.0)
            frame = await _next_frame(socket)
            assert [message["updates"]["value"] for message in frame] == [99]
            if mode == "off":
                assert socket.receipts.empty()
        finally:
            await _shut_down(buffer, producer)

    asyncio.run(scenario())


def test_delivery_backpressure_does_not_block_another_client() -> None:
    async def scenario() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=True)
        slow, fast = _RecordingSocket(), _RecordingSocket(automatic_receipts=True)
        assert buffer.push(_messages.GuiUpdateMessage("slider", {"value": 0}))
        producers = [
            _produce(slow, buffer, 1, delivery_backpressure=True),
            _produce(fast, buffer, 2, delivery_backpressure=True),
        ]
        try:
            await _next_frame(slow)
            await _next_frame(fast)
            receipt = await asyncio.wait_for(slow.receipts.get(), timeout=1)

            assert buffer.push(_messages.GuiUpdateMessage("slider", {"value": 1}))
            buffer.flush()
            assert [message["updates"]["value"] for message in await _next_frame(fast)] == [1]
            assert slow.sent == 1
            assert not receipt.done()
        finally:
            await _shut_down(buffer, *producers)

    asyncio.run(scenario())


def test_delivery_rate_waits_for_bulk_receipt() -> None:
    async def scenario() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        state = _ClientHandleState(buffer, buffer)
        socket = _RecordingSocket()
        # Random bytes, so compression cannot shrink the frame below bulk size.
        payload = random.Random(0).randbytes(32_000)
        assert buffer.push(_messages.FileTransferPart(None, "transfer", 0, payload))
        producer = _produce(socket, buffer, 1, state, delivery_backpressure=True)
        try:
            receipt = await asyncio.wait_for(socket.receipts.get(), timeout=1)
            assert state.delivery_rate is None
            await asyncio.sleep(0.03)
            receipt.set_result(0.0)
            for _ in range(100):
                if state.delivery_rate is not None:
                    break
                await asyncio.sleep(0.001)
            assert state.delivery_rate is not None
            assert 0 < state.delivery_rate < 2_000_000
        finally:
            await _shut_down(buffer, producer)

    asyncio.run(scenario())


def test_delivery_rate_tracks_slowdown_and_recovery_without_control_noise() -> None:
    state = _ClientHandleState(None, None)  # type: ignore[arg-type]
    state.record_delivery(1_000_000, 0.01)
    assert state.delivery_rate == 100_000_000
    state.record_delivery(125_000, 1)
    assert 125_000 < state.delivery_rate < 420_000
    for _ in range(10):
        state.record_delivery(125_000, 1)
    assert 125_000 <= state.delivery_rate < 130_000

    # Tiny control frames and zero-duration samples measure nothing.
    slow = state.delivery_rate
    state.record_delivery(100, 10)
    state.record_delivery(125_000, 0)
    assert state.delivery_rate == slow
    for _ in range(10):
        state.record_delivery(1_000_000, 0.01)
    assert state.delivery_rate > 4_000_000
