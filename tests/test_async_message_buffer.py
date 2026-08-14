from __future__ import annotations

import asyncio
import dataclasses
import threading
from typing import Any, Callable

import numpy as np
import pytest

from leika import _messages
from leika.infra import _async_message_buffer as buffer_impl
from leika.infra._async_message_buffer import AsyncMessageBuffer
from leika.infra._infra import _message_producer


def test_window_generator_cleans_up_flush_wait() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        generator = buffer.window_generator(client_id=0)
        next_window = asyncio.create_task(generator.__anext__())
        await asyncio.sleep(0)

        buffer.set_done()
        try:
            await next_window
        except StopAsyncIteration:
            pass

        current = asyncio.current_task()
        assert [task for task in asyncio.all_tasks() if task is not current] == []

    asyncio.run(run())


def test_closed_buffer_discards_queued_messages_and_rejects_new_ones() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(),
            persistent_messages=False,
        )
        assert buffer.push(_messages.ClientPingMessage(sent_ms=0.0)) is True
        assert len(buffer.message_from_id) == 1

        buffer.set_done()

        assert buffer.push(_messages.ClientPingMessage(sent_ms=1.0)) is False
        assert buffer.message_from_id == {}
        assert buffer.id_from_redundancy_key == {}

    asyncio.run(run())


class _QueuedLoop:
    def __init__(self) -> None:
        self.callbacks: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def call_soon_threadsafe(self, callback: Callable[..., Any], *args: Any) -> None:
        self.callbacks.append((callback, args))


@dataclasses.dataclass
class _ArrayMessage(_messages.Message):
    values: np.ndarray
    key: str = "array"

    def redundancy_key(self) -> str:
        return self.key


@dataclasses.dataclass
class _UnhashableEntityMessage(
    _messages.Message,
    entity=_messages.EntityLifecycle("gui", "create", "uuid"),
):
    uuid: list[str]


@dataclasses.dataclass
class _UnhashablePurgeMessage(
    _messages.Message,
    entity=_messages.EntityLifecycle("gui", "remove", "uuid"),
):
    uuid: str

    def purge_entities(self) -> tuple[tuple[str, object], ...]:
        return (("gui", ["not", "hashable"]),)


class _ClosedLoop:
    def call_soon_threadsafe(self, callback: Callable[..., Any], *args: Any) -> None:
        del callback, args
        raise RuntimeError("loop is closed")


@pytest.mark.parametrize("max_window_size", [0, -1, True, 1.5])
def test_window_size_must_be_a_positive_integer(max_window_size: Any) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        AsyncMessageBuffer(
            _QueuedLoop(),  # type: ignore[arg-type]
            persistent_messages=False,
            max_window_size=max_window_size,
        )


@pytest.mark.parametrize("duration", [-1, float("inf"), float("nan"), True, "fast"])
def test_window_duration_must_be_finite_and_nonnegative(duration: Any) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        AsyncMessageBuffer(
            _QueuedLoop(),  # type: ignore[arg-type]
            persistent_messages=False,
            window_duration_sec=duration,
        )


def test_push_coalesces_threadsafe_event_pulses() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]

    assert buffer.push(_messages.ClientPingMessage(sent_ms=1.0))
    assert buffer.push(_messages.RunJavascriptMessage("second"))
    assert len(loop.callbacks) == 1

    callback, args = loop.callbacks.pop()
    callback(*args)
    assert buffer.message_event.is_set()

    assert buffer.push(_messages.RunJavascriptMessage("third"))
    assert len(loop.callbacks) == 1


def test_push_is_transactional_when_event_loop_is_closed() -> None:
    buffer = AsyncMessageBuffer(_ClosedLoop(), persistent_messages=False)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="loop is closed"):
        buffer.push(_messages.ClientPingMessage(sent_ms=1.0))

    assert buffer.message_from_id == {}
    assert buffer.id_from_redundancy_key == {}
    assert buffer.message_counter == 0


def test_reserved_push_is_transactional_when_event_loop_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_FILE_TRANSFER_BUFFER_BYTES", 4)
    buffer = AsyncMessageBuffer(_ClosedLoop(), persistent_messages=False)  # type: ignore[arg-type]
    assert buffer.reserve_file_bytes(4)

    message = _messages.FileTransferPart(None, "transfer", 0, b"data")
    with pytest.raises(RuntimeError, match="loop is closed"):
        buffer.push_reserved_file_message(message, 4)
    buffer.release_file_bytes(4)

    assert buffer.message_from_id == {}
    assert buffer._file_bytes_from_id == {}
    assert buffer._file_bytes_reserved == 0
    assert buffer._file_parts_reserved == 0


def test_nested_atomic_blocks_and_unmatched_end() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    buffer.atomic_start()
    buffer.atomic_start()
    assert buffer.atomic_counter == 2
    buffer.atomic_end()
    assert buffer.atomic_counter == 1
    assert loop.callbacks == []
    buffer.atomic_end()
    assert buffer.atomic_counter == 0
    assert len(loop.callbacks) == 1
    with pytest.raises(RuntimeError, match="without a matching"):
        buffer.atomic_end()


def test_file_reservation_blocks_at_capacity_and_wakes_on_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_FILE_TRANSFER_BUFFER_BYTES", 4)
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    assert buffer.reserve_file_bytes(4)
    completed = threading.Event()
    result: list[bool] = []

    def reserve() -> None:
        result.append(buffer.reserve_file_bytes(1))
        completed.set()

    thread = threading.Thread(target=reserve)
    thread.start()
    assert not completed.wait(0.05)
    buffer.release_file_bytes(4)
    assert completed.wait(1)
    assert result == [True]
    buffer.release_file_bytes(1)
    buffer.set_done()
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_shutdown_wakes_a_blocked_file_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buffer_impl, "_FILE_TRANSFER_BUFFER_BYTES", 4)
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    assert buffer.reserve_file_bytes(4)
    completed = threading.Event()
    result: list[bool] = []

    def reserve() -> None:
        result.append(buffer.reserve_file_bytes(1))
        completed.set()

    thread = threading.Thread(target=reserve)
    thread.start()
    assert not completed.wait(0.05)
    buffer.set_done()
    assert completed.wait(1)
    assert result == [False]
    buffer.release_file_bytes(4)
    thread.join(timeout=1)


def test_reserved_windows_preserve_order_and_own_capacity_until_send() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(),
            persistent_messages=False,
            window_duration_sec=0,
        )
        first = _messages.FileTransferPart(None, "transfer", 0, b"ab")
        second = _messages.FileTransferPart(None, "transfer", 1, b"cd")
        assert buffer.reserve_file_bytes(2)
        assert buffer.push_reserved_file_message(first, 2)
        assert buffer.reserve_file_bytes(2)
        assert buffer.push_reserved_file_message(second, 2)

        generator = buffer.window_generator(1)
        window = await generator.__anext__()
        assert window.messages == (first, second)
        assert window.file_bytes_reserved == 4
        assert window.file_parts_reserved == 2
        assert buffer._file_bytes_reserved == 4
        buffer.release_file_bytes(window.file_bytes_reserved, window.file_parts_reserved)
        assert buffer._file_bytes_reserved == 0
        assert buffer._file_parts_reserved == 0
        await generator.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_reserved_message_cannot_exclude_its_destination() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    message = _messages.FileTransferPart(None, "transfer", 0, b"x")
    message.excluded_self_client = 4
    assert buffer.reserve_file_bytes(1)
    with pytest.raises(ValueError, match="cannot exclude"):
        buffer.push_reserved_file_message(message, 1)
    buffer.release_file_bytes(1)


def test_tombstone_waits_for_every_connected_client_then_is_collected() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]
    buffer.register_client(1)
    buffer.register_client(2)
    remove = _messages.GuiRemoveMessage("removed")
    assert buffer.push(remove)
    assert list(buffer.message_from_id.values()) == [remove]

    buffer.mark_messages_sent(1, 0)
    assert list(buffer.message_from_id.values()) == [remove]
    buffer.mark_messages_sent(2, 0)
    assert buffer.message_from_id == {}
    assert buffer.id_from_redundancy_key == {}


def test_tombstones_are_not_retained_when_no_client_needs_them() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]

    for index in range(1_000):
        assert buffer.push(_messages.GuiRemoveMessage(f"removed-{index}"))

    assert buffer.message_from_id == {}
    assert buffer.id_from_redundancy_key == {}


def test_failed_persistent_send_keeps_tombstone_until_disconnect() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=True)
        buffer.register_client(7)
        remove = _messages.GuiRemoveMessage("removed")
        assert buffer.push(remove)

        class FailingSocket:
            async def send(self, payload: object) -> None:
                assert payload
                assert list(buffer.message_from_id.values()) == [remove]
                raise RuntimeError("send failed")

        with pytest.raises(RuntimeError, match="send failed"):
            await _message_producer(FailingSocket(), buffer, 7)  # type: ignore[arg-type]

        assert buffer._sent_message_id_from_client == {}
        assert buffer.message_from_id == {}
        buffer.set_done()

    asyncio.run(run())


def test_sparse_persistent_history_jumps_to_retained_ids() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(),
            persistent_messages=True,
            max_window_size=2,
            window_duration_sec=0,
        )
        buffer.register_client(9)
        first = _messages.RunJavascriptMessage("first")
        second = _messages.RunJavascriptMessage("second")
        buffer.message_counter = 10_000_001
        buffer.message_from_id = {9_999_998: first, 10_000_000: second}
        buffer._serialized_size_from_id = {
            message_id: message.serialized_size_upper_bound()
            for message_id, message in buffer.message_from_id.items()
        }
        buffer._queued_metadata_bytes = sum(
            size[0] for size in buffer._serialized_size_from_id.values()
        )
        buffer._queued_raw_binary_bytes = sum(
            size[1] for size in buffer._serialized_size_from_id.values()
        )

        generator = buffer.window_generator(9)
        window = await asyncio.wait_for(generator.__anext__(), timeout=0.1)
        assert window.messages == (first, second)
        assert window.last_message_id == 10_000_000
        buffer.mark_messages_sent(9, window.last_message_id)
        await generator.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_file_part_tokens_bound_tiny_chunks_and_wake_on_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_FILE_TRANSFER_BUFFER_PARTS", 2)
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    assert buffer.reserve_file_bytes(1)
    assert buffer.reserve_file_bytes(1)
    completed = threading.Event()
    result: list[bool] = []

    def reserve() -> None:
        result.append(buffer.reserve_file_bytes(1))
        completed.set()

    thread = threading.Thread(target=reserve)
    thread.start()
    assert not completed.wait(0.05)
    assert buffer._file_parts_reserved == 2
    buffer.release_file_bytes(1)
    assert completed.wait(1)
    assert result == [True]
    assert buffer._file_parts_reserved == 2
    buffer.release_file_bytes(2, 2)
    buffer.set_done()
    thread.join(timeout=1)


def test_flush_coalesces_threadsafe_event_pulses() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    for _ in range(10_000):
        buffer.flush()
    assert len(loop.callbacks) == 1

    callback, args = loop.callbacks.pop()
    callback(*args)
    assert buffer.flush_event.is_set()
    buffer.flush()
    assert len(loop.callbacks) == 1


def test_connection_message_overload_is_terminal_instead_of_silent_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_CONNECTION_MESSAGE_BUFFER_MAX", 2)
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    assert buffer.push(_messages.RunJavascriptMessage("one"))
    assert buffer.push(_messages.GuiRemoveMessage("one"))
    assert not buffer.push(_messages.ClientPingMessage(sent_ms=1.0))

    assert buffer.done
    assert buffer.overload_reason is not None
    assert buffer.message_from_id == {}
    assert not buffer.push(_messages.GuiRemoveMessage("one"))


def test_connection_metadata_backlog_has_an_exact_terminal_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = tuple(_messages.RunJavascriptMessage(value) for value in ("one", "two", "three"))
    exact_two = sum(message.serialized_size_upper_bound()[0] for message in messages[:2])
    monkeypatch.setattr(buffer_impl, "_CONNECTION_MESSAGE_BUFFER_MAX_METADATA_BYTES", exact_two)
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=False)  # type: ignore[arg-type]

    assert buffer.push(messages[0])
    assert buffer.push(messages[1])
    assert buffer._queued_metadata_bytes == exact_two
    assert not buffer.push(messages[2])
    assert buffer.done
    assert buffer._queued_metadata_bytes == 0
    assert buffer._queued_raw_binary_bytes == 0


def test_connection_raw_backlog_is_bounded_and_released_on_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        first = _ArrayMessage(np.zeros(5, dtype="u1"), "first")
        second = _ArrayMessage(np.zeros(5, dtype="u1"), "second")
        raw_size = first.serialized_size_upper_bound()[1]
        monkeypatch.setattr(buffer_impl, "_CONNECTION_MESSAGE_BUFFER_MAX_RAW_BYTES", raw_size)
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(), persistent_messages=False, window_duration_sec=0
        )
        assert buffer.push(first)
        assert buffer._queued_raw_binary_bytes == raw_size
        window = await buffer.window_generator(1).__anext__()
        assert window.messages[0].key == "first"  # type: ignore[attr-defined]
        assert buffer._queued_raw_binary_bytes == 0
        assert buffer.push(second)
        buffer.set_done()

    asyncio.run(run())


def test_persistent_entry_and_byte_caps_reject_without_losing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = tuple(_messages.RunJavascriptMessage(value) for value in ("one", "two", "three"))
    exact_two = sum(message.serialized_size_upper_bound()[0] for message in messages[:2])
    monkeypatch.setattr(buffer_impl, "_PERSISTENT_MESSAGE_BUFFER_MAX", 2)
    monkeypatch.setattr(buffer_impl, "_PERSISTENT_MESSAGE_BUFFER_MAX_METADATA_BYTES", exact_two)
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    assert buffer.push(messages[0])
    assert buffer.push(messages[1])
    with pytest.raises(RuntimeError, match="persistent message backlog"):
        buffer.push(messages[2])
    assert not buffer.done
    assert tuple(message.source for message in buffer.message_from_id.values()) == (
        "one",
        "two",
    )
    assert buffer._queued_metadata_bytes == exact_two


def test_replacement_purge_and_tombstone_gc_update_byte_accounting() -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    buffer.register_client(7)
    assert buffer.push(_messages.GuiUpdateMessage("field", {"value": "x" * 100}))
    assert buffer.push(_messages.GuiUpdateMessage("field", {"value": "short"}))
    (stored_id,) = buffer.message_from_id
    assert buffer._queued_metadata_bytes == buffer._serialized_size_from_id[stored_id][0]

    assert buffer.push(_messages.GuiRemoveMessage("field"))
    assert len(buffer.message_from_id) == 1
    (remove_id,) = buffer.message_from_id
    assert isinstance(buffer.message_from_id[remove_id], _messages.GuiRemoveMessage)
    assert buffer._queued_metadata_bytes == buffer._serialized_size_from_id[remove_id][0]
    buffer.mark_messages_sent(7, remove_id)
    assert buffer.message_from_id == {}
    assert buffer._queued_metadata_bytes == 0
    assert buffer._queued_raw_binary_bytes == 0


def test_protocol_strings_are_validated_before_any_buffer_mutation() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]
    message = _messages.GuiUpdateMessage("component", {"nested": ["valid", {"bad": "\ud800"}]})

    with pytest.raises(ValueError, match="surrogate"):
        buffer.push(message)

    assert buffer.message_counter == 0
    assert buffer.message_from_id == {}
    assert buffer.id_from_redundancy_key == {}
    assert loop.callbacks == []


def test_invalid_object_array_is_rejected_before_deepcopy_hooks_run() -> None:
    class MustNotCopy:
        def __deepcopy__(self, memo: object) -> object:
            del memo
            raise AssertionError("object array was copied before validation")

    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Python objects"):
        buffer.push(_ArrayMessage(np.array([MustNotCopy()], dtype=object)))
    assert buffer.message_from_id == {}


def test_individually_oversized_persistent_message_is_never_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_OUTGOING_METADATA_LIMIT_BYTES", 16)
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="metadata exceeds"):
        buffer.push(_messages.RunJavascriptMessage("x" * 128))

    assert buffer.message_counter == 0
    assert buffer.message_from_id == {}
    assert loop.callbacks == []


def test_single_message_decoded_node_limit_is_enforced_before_windowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _messages.GuiUpdateMessage("component", {"value": ["one", "two", "three"]})
    decoded_nodes = message.serialized_metrics_upper_bound()[3]

    monkeypatch.setattr(buffer_impl, "_OUTGOING_DECODED_NODE_LIMIT", 1 + decoded_nodes)
    exact = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    assert exact.push(message)

    monkeypatch.setattr(buffer_impl, "_OUTGOING_DECODED_NODE_LIMIT", decoded_nodes)
    oversized = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="client traversal limit"):
        oversized.push(message)
    assert oversized.message_from_id == {}
    assert oversized.id_from_redundancy_key == {}
    assert oversized.message_counter == 0


def test_large_valid_persistent_state_is_split_into_deliverable_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr(buffer_impl, "_OUTGOING_METADATA_LIMIT_BYTES", 150)
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(),
            persistent_messages=True,
            max_window_size=128,
            window_duration_sec=0,
        )
        messages = [_messages.RunJavascriptMessage(f"{index:02d}" + "x" * 18) for index in range(4)]
        for message in messages:
            assert buffer.push(message)

        generator = buffer.window_generator(3)
        delivered: list[_messages.Message] = []
        windows = 0
        while len(delivered) < len(messages):
            window = await generator.__anext__()
            windows += 1
            delivered.extend(window.messages)
            buffer.mark_messages_sent(3, window.last_message_id)
        assert windows > 1
        assert delivered == messages
        await generator.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_atomic_block_prevents_nonpersistent_window_extraction() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        assert buffer.push(_messages.RunJavascriptMessage("queued"))
        buffer.atomic_start()
        generator = buffer.window_generator(1)
        pending = asyncio.create_task(generator.__anext__())
        await asyncio.sleep(0)
        assert not pending.done()
        assert len(buffer.message_from_id) == 1
        buffer.atomic_end()
        window = await asyncio.wait_for(pending, 1)
        assert [message.source for message in window.messages] == ["queued"]
        await generator.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_push_snapshots_nested_mutable_protocol_state_and_cached_size() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]
    props = _messages.GuiTextProps(
        order=0.0,
        label="before",
        hint=None,
        disabled=False,
        visible=True,
        editable=False,
        markdown=False,
        multiline=False,
        rows=None,
        _source="before",
    )
    message = _messages.GuiTextMessage(
        value="before",
        uuid="component",
        container_uuid="root",
        props=props,
    )
    assert buffer.push(message)
    stored = buffer.message_from_id[0]
    cached_size = buffer._serialized_size_from_id[0]

    props.label = "after" * 100_000
    props._source = "after" * 100_000

    assert isinstance(stored, _messages.GuiTextMessage)
    assert stored.props.label == "before"
    assert stored.props._source == "before"
    assert buffer._serialized_size_from_id[0] == cached_size
    assert stored.serialized_size_upper_bound() == cached_size


def test_single_message_admission_includes_envelope_and_zstd_overhead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _messages.RunJavascriptMessage("x")
    metadata, raw, binary_count = message.serialized_size_upper_bound()
    envelope = buffer_impl._metadata_envelope_upper_bound(metadata, binary_count)
    monkeypatch.setattr(buffer_impl, "_OUTGOING_METADATA_LIMIT_BYTES", envelope - 1)

    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="metadata exceeds"):
        buffer.push(message)
    assert buffer.message_from_id == {}
    assert raw == 0


def test_push_many_rolls_back_if_a_later_insertion_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    original = buffer._insert_prepared_locked
    calls = 0

    def fail_second(prepared: object, *, file_bytes_reserved: int) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second insertion failed")
        return original(prepared, file_bytes_reserved=file_bytes_reserved)  # type: ignore[arg-type]

    monkeypatch.setattr(buffer, "_insert_prepared_locked", fail_second)
    with pytest.raises(RuntimeError, match="second insertion failed"):
        buffer.push_many(
            (
                _messages.RunJavascriptMessage("first"),
                _messages.RunJavascriptMessage("second"),
            )
        )

    assert buffer.message_counter == 0
    assert buffer.message_from_id == {}
    assert buffer.id_from_redundancy_key == {}
    assert buffer._serialized_size_from_id == {}
    assert buffer._queued_metadata_bytes == 0
    assert buffer._queued_raw_binary_bytes == 0


def test_snapshot_recomputes_payload_derived_redundancy_key() -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    message = _messages.GuiUpdateMessage("before", {"value": 1})
    assert message.redundancy_key() == "gui:before:update:value"

    message.uuid = "after"
    message.updates = {"visible": True}
    assert buffer.push(message)

    stored = buffer.message_from_id[0]
    assert isinstance(stored, _messages.GuiUpdateMessage)
    assert stored.redundancy_key() == "gui:after:update:visible"
    assert buffer.id_from_redundancy_key == {"gui:after:update:visible": 0}


def test_unsupported_dynamic_value_is_rejected_before_deepcopy_hook() -> None:
    class MustNotCopy:
        def __deepcopy__(self, memo: object) -> object:
            del memo
            raise AssertionError("unsupported object reached deepcopy")

    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="unsupported outbound protocol value"):
        buffer.push(_messages.GuiUpdateMessage("component", {"value": MustNotCopy()}))
    assert buffer.message_from_id == {}
    assert loop.callbacks == []


def test_oversized_ndarray_is_rejected_before_deepcopy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from leika.infra import _messages as infra_messages

    monkeypatch.setattr(infra_messages, "_OUTBOUND_PREFLIGHT_RAW_BYTES_LIMIT", 3)
    value = np.zeros(4, dtype=np.uint8)

    def forbidden_snapshot(*_: object, **__: object) -> object:
        raise AssertionError("oversized ndarray reached structural snapshot")

    monkeypatch.setattr(
        _messages.Message,
        "_bounded_transport_snapshot",
        forbidden_snapshot,
    )
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="binary data exceeds"):
        buffer.push(_ArrayMessage(value))
    assert buffer.message_from_id == {}


def test_push_many_false_overload_rolls_back_without_closing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_CONNECTION_MESSAGE_BUFFER_MAX", 2)
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    existing = _messages.RunJavascriptMessage("existing")
    assert buffer.push(existing)
    loop.callbacks.clear()
    before = (
        buffer.message_counter,
        buffer.message_from_id.copy(),
        buffer.id_from_redundancy_key.copy(),
        buffer._serialized_size_from_id.copy(),
        buffer._decoded_nodes_from_id.copy(),
        buffer._queued_metadata_bytes,
        buffer._queued_raw_binary_bytes,
    )

    # The batch length itself is valid. Its first insertion reaches the cap and
    # the second returns False, exercising transaction rollback rather than the
    # earlier hostile-sequence preparation guard.
    assert not buffer.push_many(
        (
            _messages.RunJavascriptMessage("first"),
            _messages.RunJavascriptMessage("second"),
        )
    )
    assert not buffer.done
    assert buffer.overload_reason is None
    assert (
        buffer.message_counter,
        buffer.message_from_id,
        buffer.id_from_redundancy_key,
        buffer._serialized_size_from_id,
        buffer._decoded_nodes_from_id,
        buffer._queued_metadata_bytes,
        buffer._queued_raw_binary_bytes,
    ) == before
    assert tuple(buffer.message_from_id.values()) == (existing,)
    assert loop.callbacks == []


def test_atomic_end_after_shutdown_never_schedules_on_closed_loop() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    buffer.atomic_start()
    buffer.set_done()
    buffer.event_loop = _ClosedLoop()  # type: ignore[assignment]
    buffer.atomic_end()
    assert buffer.atomic_counter == 0


def test_outgoing_windows_split_at_the_browser_decoded_node_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        messages = tuple(
            _messages.GuiUpdateMessage(f"component-{index}", {"value": [1, 2, 3]})
            for index in range(3)
        )
        one_message_nodes = messages[0].serialized_metrics_upper_bound()[3]
        monkeypatch.setattr(
            buffer_impl,
            "_OUTGOING_DECODED_NODE_LIMIT",
            1 + one_message_nodes,
        )
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(),
            persistent_messages=False,
            max_window_size=128,
            window_duration_sec=0,
        )
        assert buffer.push_many(messages)
        generator = buffer.window_generator(1)
        windows = [await generator.__anext__() for _ in range(3)]
        assert [len(window.messages) for window in windows] == [1, 1, 1]
        await generator.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_parent_removal_purges_every_named_descendant_from_replay() -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    buffer.register_client(7)
    props = _messages.GuiTextProps(
        order=0.0,
        label="child",
        hint=None,
        disabled=False,
        visible=True,
        editable=False,
        markdown=False,
        multiline=False,
        rows=None,
        _source="child",
    )
    assert buffer.push(
        _messages.GuiTextMessage(
            value="child",
            uuid="child",
            container_uuid="parent",
            props=props,
        )
    )
    assert buffer.push(_messages.GuiUpdateMessage("child", {"value": "updated"}))
    assert buffer.push(_messages.GuiUpdateMessage("grandchild", {"value": "updated"}))
    assert buffer.push(
        _messages.GuiRemoveMessage(
            "parent",
            removed_uuids=("grandchild", "child"),
        )
    )

    assert len(buffer.message_from_id) == 1
    (stored,) = buffer.message_from_id.values()
    assert isinstance(stored, _messages.GuiRemoveMessage)
    assert stored.removed_uuids == ("grandchild", "child")


def _tab_group_props(*tabs: _messages.GuiTab) -> _messages.GuiTabGroupProps:
    return _messages.GuiTabGroupProps(_tabs=tabs, order=0.0, visible=True)


def _tab_child_message(uuid: str, container_uuid: str) -> _messages.GuiTextMessage:
    return _messages.GuiTextMessage(
        value=uuid,
        uuid=uuid,
        container_uuid=container_uuid,
        props=_messages.GuiTextProps(
            order=0.0,
            label=uuid,
            hint=None,
            disabled=False,
            visible=True,
            editable=False,
            markdown=False,
            multiline=False,
            rows=None,
            _source=uuid,
        ),
    )


def test_tab_lifecycle_is_prefix_safe_for_slow_and_inflight_clients() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(),
            persistent_messages=True,
            max_window_size=1,
            window_duration_sec=0,
        )
        group = _messages.GuiTabGroupMessage("tabs", "root", _tab_group_props())
        tab_a = _messages.GuiTabMessage("tab-a", "tabs", "Alpha", None)
        tab_b = _messages.GuiTabMessage("tab-b", "tabs", "Beta", None)
        assert buffer.push(group)
        assert buffer.push(tab_a)
        assert buffer.push(_tab_child_message("child-a", "tab-a"))

        client = buffer.window_generator(1)
        group_window = await asyncio.wait_for(client.__anext__(), 0.5)
        tab_a_window = await asyncio.wait_for(client.__anext__(), 0.5)
        assert isinstance(group_window.messages[0], _messages.GuiTabGroupMessage)
        assert group_window.messages[0].props._tabs == ()
        assert tab_a_window.messages == (tab_a,)

        # Metadata updates can move after children because the structural tab
        # declaration remains retained before every child and already owns the
        # container. A yielded older update remains immutable.
        update_a = _messages.GuiTabUpdateMessage("tab-a", "tabs", "Alpha", "old")
        assert buffer.push(update_a)
        child_a_window = await asyncio.wait_for(client.__anext__(), 0.5)
        assert isinstance(child_a_window.messages[0], _messages.GuiTextMessage)
        old_window = await asyncio.wait_for(client.__anext__(), 0.5)
        assert old_window.messages == (update_a,)
        update_a_new = _messages.GuiTabUpdateMessage("tab-a", "tabs", "Alpha", "new")
        assert buffer.push(update_a_new)
        assert old_window.messages == (update_a,)

        assert buffer.push(tab_b)
        assert buffer.push(_tab_child_message("child-b", "tab-b"))
        tail = [(await asyncio.wait_for(client.__anext__(), 0.5)).messages[0] for _ in range(3)]
        assert [type(message) for message in tail] == [
            _messages.GuiTabUpdateMessage,
            _messages.GuiTabMessage,
            _messages.GuiTextMessage,
        ]

        fresh = buffer.window_generator(2)
        replay = [(await asyncio.wait_for(fresh.__anext__(), 0.5)).messages[0] for _ in range(6)]
        assert [type(message) for message in replay] == [
            _messages.GuiTabGroupMessage,
            _messages.GuiTabMessage,
            _messages.GuiTextMessage,
            _messages.GuiTabUpdateMessage,
            _messages.GuiTabMessage,
            _messages.GuiTextMessage,
        ]
        assert replay[0].props._tabs == ()  # type: ignore[union-attr]
        assert replay[1].uuid == "tab-a"  # type: ignore[union-attr]
        assert replay[5].container_uuid == "tab-b"  # type: ignore[union-attr]

        await client.aclose()
        await fresh.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_tab_remove_purges_declaration_update_and_descendants_before_recreate() -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    buffer.register_client(1)
    assert buffer.push(_messages.GuiTabGroupMessage("tabs", "root", _tab_group_props()))
    declaration = _messages.GuiTabMessage("tab-a", "tabs", "Alpha", None)
    assert buffer.push(declaration)
    assert buffer.push(_tab_child_message("child-a", "tab-a"))
    assert buffer.push(_messages.GuiTabUpdateMessage("tab-a", "tabs", "Renamed", "icon"))
    assert buffer.push(
        _messages.GuiRemoveMessage(
            "tab-a",
            removed_uuids=("child-a",),
        )
    )
    assert all(
        not (
            getattr(message, "uuid", None) in {"tab-a", "child-a"}
            and message.lifecycle_phase != "remove"
        )
        for message in buffer.message_from_id.values()
    )

    recreated = _messages.GuiTabMessage("tab-a", "tabs", "New", None)
    assert buffer.push(recreated)
    recreate_id = buffer.id_from_redundancy_key[recreated.redundancy_key()]  # type: ignore[index]
    assert recreate_id > 0
    assert buffer.message_from_id[recreate_id] == recreated


def test_nested_tab_tombstones_purge_lifecycle_without_expanding_component_list() -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    buffer.register_client(1)
    assert buffer.push(_messages.GuiTabMessage("outer", "group-a", "Outer", None))
    assert buffer.push(_messages.GuiTabMessage("inner", "group-b", "Inner", None))
    assert buffer.push(_tab_child_message("child", "inner"))
    remove = _messages.GuiRemoveMessage(
        "folder",
        removed_uuids=("child",),
        removed_tab_uuids=("inner", "outer"),
    )
    assert buffer.push(remove)
    assert tuple(buffer.message_from_id.values()) == (remove,)
    assert remove.purge_entities() == (
        ("gui", "folder"),
        ("gui", "child"),
        ("gui", "inner"),
        ("gui", "outer"),
    )


def test_large_subtree_purge_scans_each_retained_entry_once() -> None:
    class CountingDict(dict[int, _messages.Message]):
        items_calls = 0
        item_visits = 0

        def items(self) -> Any:
            self.items_calls += 1
            entries = super().items()

            def count() -> Any:
                for entry in entries:
                    self.item_visits += 1
                    yield entry

            return count()

    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    buffer.register_client(1)
    tab_count = 1_024
    for index in range(tab_count):
        assert buffer.push(_messages.GuiTabMessage(f"tab-{index}", "tabs", f"Tab {index}", None))

    retained = CountingDict(buffer.message_from_id)
    buffer.message_from_id = retained
    remove = _messages.GuiRemoveMessage(
        "folder",
        removed_tab_uuids=tuple(f"tab-{index}" for index in range(tab_count)),
    )
    assert buffer.push(remove)

    # One purge scan visits the old backlog; tombstone GC then examines only
    # the surviving removal. The number of scans is independent of the 1,025
    # distinct purge keys in the message.
    assert retained.items_calls == 2
    assert retained.item_visits == tab_count + 1
    assert tuple(buffer.message_from_id.values()) == (remove,)
    (remove_id,) = buffer.message_from_id
    assert buffer.id_from_redundancy_key == {remove.redundancy_key(): remove_id}
    assert buffer._queued_metadata_bytes == buffer._serialized_size_from_id[remove_id][0]
    assert buffer._queued_raw_binary_bytes == buffer._serialized_size_from_id[remove_id][1]
    assert set(buffer._decoded_nodes_from_id) == {remove_id}


def test_unhashable_lifecycle_identifier_is_rejected_before_insertion() -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="lifecycle entity identifiers must be hashable"):
        buffer.push(_UnhashableEntityMessage(["not", "hashable"]))
    assert not buffer.done
    assert buffer.message_from_id == {}
    assert buffer.id_from_redundancy_key == {}
    assert buffer._queued_metadata_bytes == 0
    assert buffer._queued_raw_binary_bytes == 0


def test_unhashable_purge_identifier_is_rejected_before_insertion() -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="purged entity identifiers must be hashable"):
        buffer.push(_UnhashablePurgeMessage("owner"))
    assert not buffer.done
    assert buffer.message_from_id == {}
    assert buffer.id_from_redundancy_key == {}
    assert buffer._queued_metadata_bytes == 0
    assert buffer._queued_raw_binary_bytes == 0


def test_push_many_rejects_huge_sequence_before_iteration() -> None:
    class HugeSequence:
        touched = False

        def __len__(self) -> int:
            return buffer_impl._CONNECTION_MESSAGE_BUFFER_MAX + 2

        def __getitem__(self, index: int) -> _messages.Message:
            self.touched = True
            raise AssertionError(index)

    messages = HugeSequence()
    buffer = AsyncMessageBuffer(asyncio.new_event_loop(), persistent_messages=False)
    try:
        with pytest.raises(RuntimeError, match="preparation limit"):
            buffer.push_many(messages)  # type: ignore[arg-type]
        assert not messages.touched
        assert not buffer.done
        assert buffer.message_from_id == {}
    finally:
        buffer.event_loop.close()


@pytest.mark.parametrize("reported_length", [0, 1])
def test_push_many_rejects_a_sequence_that_yields_more_than_reported(
    reported_length: int,
) -> None:
    class LyingSequence:
        yielded = 0

        def __len__(self) -> int:
            return reported_length

        def __iter__(self) -> Any:
            while True:
                self.yielded += 1
                yield _messages.RunJavascriptMessage(str(self.yielded))

    messages = LyingSequence()
    buffer = AsyncMessageBuffer(asyncio.new_event_loop(), persistent_messages=False)
    try:
        with pytest.raises(RuntimeError, match="length changed"):
            buffer.push_many(messages)  # type: ignore[arg-type]
        assert messages.yielded <= buffer_impl._CONNECTION_MESSAGE_BUFFER_MAX + 2
        assert buffer.message_from_id == {}
        assert not buffer.done
    finally:
        buffer.event_loop.close()


def test_push_many_rejects_a_sequence_that_yields_fewer_than_reported() -> None:
    class ShortSequence:
        def __len__(self) -> int:
            return 2

        def __iter__(self) -> Any:
            yield _messages.RunJavascriptMessage("only")

    buffer = AsyncMessageBuffer(asyncio.new_event_loop(), persistent_messages=False)
    try:
        with pytest.raises(RuntimeError, match="length changed"):
            buffer.push_many(ShortSequence())  # type: ignore[arg-type]
        assert buffer.message_from_id == {}
        assert not buffer.done
    finally:
        buffer.event_loop.close()


def test_duplicate_runtime_script_sources_coalesce_by_content() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]
    assert buffer.push(_messages.RunJavascriptMessage("runtime"))
    assert buffer.push(_messages.RunJavascriptMessage("runtime"))
    assert len(buffer.message_from_id) == 1


def test_preparation_reservation_serializes_bounded_deepcopy_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_PREPARATION_OWNER_MAX", 1)
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=False)  # type: ignore[arg-type]
    original = buffer._prepare_message
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    call_lock = threading.Lock()

    def blocked(message: _messages.Message, estimate: tuple[int, int]):
        nonlocal calls
        with call_lock:
            calls += 1
            current = calls
        if current == 1:
            entered.set()
            assert release.wait(2.0)
        return original(message, estimate)

    monkeypatch.setattr(buffer, "_prepare_message", blocked)
    results: list[bool] = []
    threads = [
        threading.Thread(
            target=lambda index=index: results.append(
                buffer.push(_messages.ClientPingMessage(sent_ms=float(index)))
            )
        )
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    assert entered.wait(2.0)
    threading.Event().wait(0.05)
    with call_lock:
        assert calls == 1
    release.set()
    for thread in threads:
        thread.join(2.0)
    assert results == [True, True]
    assert buffer._preparation_owners == 0
    assert buffer._preparation_metadata_bytes == 0
    assert buffer._preparation_raw_bytes == 0


def test_batch_preparation_rejects_cumulative_cost_before_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=False)  # type: ignore[arg-type]
    messages = (
        _messages.RunJavascriptMessage("first"),
        _messages.RunJavascriptMessage("second"),
    )
    one_metadata = buffer._preparation_estimate(messages[0])[0]
    monkeypatch.setattr(buffer_impl, "_PREPARATION_METADATA_MAX_BYTES", one_metadata)

    def forbidden(*_: object, **__: object) -> object:
        raise AssertionError("snapshot ran before cumulative preparation admission")

    monkeypatch.setattr(
        _messages.Message,
        "_bounded_transport_snapshot",
        forbidden,
    )
    with pytest.raises(RuntimeError, match="preparation exceeds"):
        buffer.push_many(messages)
    assert buffer.message_from_id == {}
    assert buffer._preparation_owners == 0


def test_preparation_failure_and_shutdown_release_or_wake_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=False)  # type: ignore[arg-type]
    original = _messages.Message._bounded_transport_snapshot
    monkeypatch.setattr(
        _messages.Message,
        "_bounded_transport_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(MemoryError("copy failed")),
    )
    with pytest.raises(MemoryError, match="copy failed"):
        buffer.push(_messages.ClientPingMessage(sent_ms=1.0))
    assert buffer._preparation_owners == 0
    assert buffer._preparation_metadata_bytes == 0
    assert buffer._preparation_raw_bytes == 0

    monkeypatch.setattr(_messages.Message, "_bounded_transport_snapshot", original)
    assert buffer.push(_messages.ClientPingMessage(sent_ms=2.0))
    assert buffer._preparation_owners == 0

    with buffer._preparation_condition:
        buffer._preparation_owners = buffer_impl._PREPARATION_OWNER_MAX
    result: list[bool] = []
    waiter = threading.Thread(
        target=lambda: result.append(buffer.push(_messages.ClientPingMessage(sent_ms=3.0)))
    )
    waiter.start()
    threading.Event().wait(0.05)
    assert waiter.is_alive()
    buffer.set_done()
    waiter.join(2.0)
    assert result == [False]
    # The synthetic occupied slots aren't real reservations; restore them so
    # the invariant assertion describes only the waiter under test.
    with buffer._preparation_condition:
        buffer._preparation_owners = 0


def test_message_preparation_reentrancy_fails_without_deadlock_and_recovers() -> None:
    target: list[AsyncMessageBuffer] = []

    # Private helper leaves are not registered as wire types (though private
    # structural roots are still traversed when they own public descendants).
    # This buffer-only hook must not mutate the bundled high-level protocol.
    @dataclasses.dataclass
    class _ReentrantMessage(_messages.Message):
        value: int

        def redundancy_key(self) -> str:
            target[0].push(_messages.ClientPingMessage(sent_ms=99.0))
            return "reentrant"

    buffer = AsyncMessageBuffer(_QueuedLoop(), persistent_messages=False)  # type: ignore[arg-type]
    target.append(buffer)
    with pytest.raises(RuntimeError, match="cannot re-enter"):
        buffer.push(_ReentrantMessage(1))
    assert buffer._preparation_owners == 0
    assert buffer.push(_messages.ClientPingMessage(sent_ms=1.0))
