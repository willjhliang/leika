from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import msgspec.msgpack
import numpy as np
import pytest
import zstandard
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika.infra._infra as infra_impl
from leika import _messages
from leika.infra import ClientId, WebsockServer, protocol_fingerprint
from leika.infra._async_message_buffer import AsyncMessageBuffer
from leika.infra._infra import (
    _allocate_client_id,
    _message_consumer,
    _message_producer,
    _run_connection_tasks,
)


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


def test_low_level_handler_and_connection_callback_registration_validates_eagerly() -> None:
    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)

    with pytest.raises(TypeError, match="Message subclass"):
        server.register_handler(str, lambda *_: None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="callback must be callable"):
        server.register_handler(_messages.ClientPingMessage, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Message subclass"):
        server.unregister_handler(str)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="callable"):
        server.on_client_connect(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="callable"):
        server.on_client_disconnect(None)  # type: ignore[arg-type]


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
        # A stop concurrent with callback-owned work is signal-first to avoid
        # circular waits with returned external Futures; its finalizer joins.
        _wait_for(lambda: not server._server_thread.is_alive())
        assert "RuntimeError: disconnect callback failed" in capsys.readouterr().err
    finally:
        release.set()
        websocket.close()
        if not stopped:
            server.stop()


class _RecordingProducerSocket:
    def __init__(self) -> None:
        self.sent: list[object] = []
        self.closed: list[tuple[int, str]] = []

    async def send(self, payload: object) -> None:
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:
        self.closed.append((code, reason))


def test_outgoing_metadata_limit_closes_only_the_affected_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(infra_impl, "_OUTGOING_METADATA_LIMIT_BYTES", 64)
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        assert buffer.push(_messages.RunJavascriptMessage("x" * 1_000))
        socket = _RecordingProducerSocket()

        await asyncio.wait_for(_message_producer(socket, buffer, ClientId(1)), timeout=1)
        assert socket.sent == []
        assert socket.closed == [(1009, "Outgoing message batch exceeds the client size limit.")]
        buffer.set_done()

    asyncio.run(scenario())


def test_outgoing_frame_limit_is_checked_before_join_and_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(infra_impl, "_OUTGOING_METADATA_LIMIT_BYTES", 1_024)
        monkeypatch.setattr(infra_impl, "_OUTGOING_FRAME_LIMIT_BYTES", 32)
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        assert buffer.push(_messages.ClientPingMessage(sent_ms=1.0))
        socket = _RecordingProducerSocket()

        await asyncio.wait_for(_message_producer(socket, buffer, ClientId(1)), timeout=1)
        assert socket.sent == []
        assert socket.closed and socket.closed[0][0] == 1009
        buffer.set_done()

    asyncio.run(scenario())


def test_outgoing_binary_buffers_are_sent_as_one_fragmented_message() -> None:
    async def scenario() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)

        @dataclasses.dataclass
        class _BinaryArrayMessage(_messages.Message):
            values: Any

            def redundancy_key(self) -> None:
                return None

        backing = np.frombuffer(bytearray(b"array payload"), dtype=np.uint8)
        assert buffer.push(_BinaryArrayMessage(backing))

        class FragmentSocket(_RecordingProducerSocket):
            async def send(self, payload: object) -> None:
                await super().send(payload)
                buffer.set_done()

        socket = FragmentSocket()
        await asyncio.wait_for(_message_producer(socket, buffer, ClientId(1)), timeout=1)

        assert len(socket.sent) == 1
        fragments = socket.sent[0]
        assert isinstance(fragments, list)
        assert all(isinstance(fragment, (bytes, memoryview)) for fragment in fragments)
        assert isinstance(fragments[-1], memoryview)
        assert isinstance(fragments[-1].obj, np.ndarray)
        assert fragments[-1].obj is not backing
        assert b"".join(fragments).endswith(backing.tobytes())

    asyncio.run(scenario())


def test_metadata_preflight_counts_true_lower_bounds_without_false_positives() -> None:
    assert not infra_impl._metadata_payload_exceeds("é" * 2, 4)
    assert infra_impl._metadata_payload_exceeds("é" * 3, 4)
    # Tiny integers encode in one byte. Charging their maximum nine-byte form
    # would reject a valid compact collection before exact MsgPack encoding.
    assert not infra_impl._metadata_payload_exceeds([0] * 100, 101)


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ("text frame", 1003),
        (b"\xc1", 1007),
        (
            msgspec.msgpack.encode({"type": "UnknownMessage", "value": "anything"}),
            1007,
        ),
        (
            msgspec.msgpack.encode({"type": "ClientPingMessage", "sent_ms": "not-a-number"}),
            1007,
        ),
    ],
)
def test_malformed_protocol_input_closes_only_its_connection(
    payload: str | bytes,
    expected_code: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)
    server.start()
    url = f"ws://127.0.0.1:{server._port}"
    try:
        with connect(
            url,
            subprotocols=[_client_subprotocol()],
            open_timeout=2,
        ) as websocket:
            websocket.send(payload)
            with pytest.raises(ConnectionClosed) as closed:
                websocket.recv(timeout=2)
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == expected_code

        # A malformed peer cannot poison the listener or another connection.
        with connect(
            url,
            subprotocols=[_client_subprotocol()],
            open_timeout=2,
        ) as healthy:
            assert healthy.protocol.close_code is None
        assert "Traceback" not in capsys.readouterr().err
    finally:
        server.stop()


def test_oversized_incoming_frame_closes_cleanly_and_server_stays_healthy() -> None:
    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)
    server.start()
    url = f"ws://127.0.0.1:{server._port}"
    try:
        with connect(
            url,
            subprotocols=[_client_subprotocol()],
            open_timeout=2,
        ) as websocket:
            websocket.send(b"x" * (infra_impl._INCOMING_MESSAGE_LIMIT_BYTES + 1))
            with pytest.raises(ConnectionClosed) as closed:
                websocket.recv(timeout=2)
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 1009

        with connect(
            url,
            subprotocols=[_client_subprotocol()],
            open_timeout=2,
        ) as healthy:
            assert healthy.protocol.close_code is None
    finally:
        server.stop()


def test_low_level_dispatch_awaits_concurrent_future_and_uses_stable_snapshot() -> None:
    server = WebsockServer(host="127.0.0.1", port=0, verbose=False)
    completion: Future[None] = Future()
    first_started = threading.Event()
    events: list[str] = []

    def first(_: ClientId, __: _messages.ClientPingMessage) -> Future[None]:
        events.append("first")
        first_started.set()
        return completion

    def second(_: ClientId, __: _messages.ClientPingMessage) -> None:
        events.append("second")

    server.register_handler(_messages.ClientPingMessage, first)
    server.register_handler(_messages.ClientPingMessage, second)

    async def scenario() -> None:
        task = asyncio.create_task(
            server._handle_incoming_message(ClientId(7), _messages.ClientPingMessage(sent_ms=1.0))
        )
        while not first_started.is_set():
            await asyncio.sleep(0)
        # Registration mutation is lock-safe and affects only later dispatches;
        # this message owns the snapshot captured at its start.
        server.unregister_handler(_messages.ClientPingMessage, second)
        assert events == ["first"]
        completion.set_result(None)
        await task
        assert events == ["first", "second"]

        await server._handle_incoming_message(ClientId(7), _messages.ClientPingMessage(sent_ms=2.0))
        assert events == ["first", "second", "first"]

    asyncio.run(scenario())


def test_active_websocket_connection_limit_rejects_and_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(infra_impl, "_MAX_ACTIVE_CONNECTIONS", 1)
    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)
    server.start()
    url = f"ws://127.0.0.1:{server._port}"
    first = second = third = None
    try:
        first = connect(url, subprotocols=[_client_subprotocol()], open_timeout=2)
        _wait_for(lambda: len(server._client_state_from_id) == 1)
        second = connect(url, subprotocols=[_client_subprotocol()], open_timeout=2)
        with pytest.raises(ConnectionClosed) as closed:
            second.recv(timeout=2)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1013
        assert len(server._client_state_from_id) == 1

        first.close()
        _wait_for(lambda: server._client_state_from_id == {})
        third = connect(url, subprotocols=[_client_subprotocol()], open_timeout=2)
        _wait_for(lambda: len(server._client_state_from_id) == 1)
        assert third.protocol.close_code is None
    finally:
        for websocket in (first, second, third):
            if websocket is not None:
                websocket.close()
        server.stop()


def test_custom_low_level_protocol_roundtrips_without_leika_subprotocol() -> None:
    class _CustomProtocolRoot(infra_impl.Message):
        pass

    @dataclasses.dataclass
    class CustomRequest(_CustomProtocolRoot):
        value: str

        def redundancy_key(self) -> str:
            return "custom-request"

    @dataclasses.dataclass
    class CustomResponse(_CustomProtocolRoot):
        value: str

        def redundancy_key(self) -> str:
            return "custom-response"

    received = threading.Event()
    server = WebsockServer("127.0.0.1", 0, message_class=_CustomProtocolRoot, verbose=False)

    def reply(_: ClientId, message: CustomRequest) -> None:
        assert server.queue_message(CustomResponse(message.value.upper()))
        received.set()

    server.register_handler(CustomRequest, reply)
    server.start()
    try:
        with connect(f"ws://127.0.0.1:{server._port}", open_timeout=2) as websocket:
            assert websocket.subprotocol is None
            websocket.send(msgspec.msgpack.encode(CustomRequest("hello").as_serializable_dict()))
            frame = websocket.recv(timeout=2)
            assert received.wait(2)
            assert isinstance(frame, bytes)
            inner_size = int.from_bytes(frame[:8], "little")
            compressed_size = int.from_bytes(frame[8:16], "little")
            envelope = msgspec.msgpack.decode(
                zstandard.ZstdDecompressor().decompress(
                    frame[16 : 16 + compressed_size], max_output_size=inner_size
                )
            )
            assert envelope["messages"] == [{"value": "HELLO", "type": "CustomResponse"}]
    finally:
        server.stop()


def test_client_id_allocator_wraps_at_javascript_safe_max_without_collision() -> None:
    maximum = infra_impl._CLIENT_ID_MAX
    first, next_candidate = _allocate_client_id(maximum, set())
    assert first == maximum
    assert next_candidate == 0

    active = {ClientId(0), ClientId(1), ClientId(maximum)}
    allocated, next_candidate = _allocate_client_id(maximum, active)
    assert allocated == 2
    assert next_candidate == 3
    assert 0 <= allocated <= maximum


def test_active_connection_slot_releases_after_protocol_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(infra_impl, "_MAX_ACTIVE_CONNECTIONS", 1)
    server = WebsockServer("127.0.0.1", 0, _messages.Message, verbose=False)
    server.start()
    url = f"ws://127.0.0.1:{server._port}"
    try:
        rejected = connect(
            url,
            subprotocols=[Subprotocol("leika-v0.0.0+pwrong")],
            open_timeout=2,
        )
        with pytest.raises(ConnectionClosed) as closed:
            rejected.recv(timeout=2)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1002
        rejected.close()

        healthy = connect(url, subprotocols=[_client_subprotocol()], open_timeout=2)
        try:
            _wait_for(lambda: len(server._client_state_from_id) == 1)
            assert healthy.protocol.close_code is None
        finally:
            healthy.close()
    finally:
        server.stop()


def test_low_level_callback_returned_future_can_stop_without_join_deadlock() -> None:
    server = WebsockServer(host="127.0.0.1", port=0, verbose=False)
    executor = ThreadPoolExecutor(max_workers=1)
    stop_returned = threading.Event()

    def stop_from_external_worker() -> None:
        server.stop()
        stop_returned.set()

    @server.on_client_connect
    def on_connect(_: object) -> Future[None]:
        return executor.submit(stop_from_external_worker)

    server.start()
    websocket = None
    try:
        websocket = connect(f"ws://127.0.0.1:{server._port}", open_timeout=2)
        assert stop_returned.wait(2.0)
        _wait_for(
            lambda: server._server_thread is not None and not server._server_thread.is_alive()
        )
    finally:
        if websocket is not None:
            websocket.close()
        server.stop()
        executor.shutdown(wait=True)


def test_low_level_callback_registries_are_bounded_removable_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(infra_impl, "_CALLBACK_REGISTRATION_MAX", 1)
    server = WebsockServer("127.0.0.1", 0, verbose=False)

    def handler(_: ClientId, __: _messages.Message) -> None:
        pass

    def other_handler(_: ClientId, __: _messages.Message) -> None:
        pass

    server.register_handler(_messages.GuiUpdateMessage, handler)
    with pytest.raises(RuntimeError, match="more than 1 handlers"):
        server.register_handler(_messages.GuiUpdateMessage, other_handler)
    server.unregister_handler(_messages.GuiUpdateMessage, handler)
    server.register_handler(_messages.GuiUpdateMessage, other_handler)

    connect = lambda _: None
    disconnect = lambda _: None
    server.on_client_connect(connect)
    with pytest.raises(RuntimeError, match="more than 1 connect"):
        server.on_client_connect(lambda _: None)
    server.remove_client_connect_callback(connect)
    server.on_client_connect(connect)
    server.on_client_disconnect(disconnect)
    with pytest.raises(RuntimeError, match="more than 1 disconnect"):
        server.on_client_disconnect(lambda _: None)
    server.remove_client_disconnect_callback()
    assert server._client_disconnect_cb == []

    server.stop()
    assert server._incoming_handlers == {}
    assert server._client_connect_cb == []
    assert server._client_disconnect_cb == []
