from __future__ import annotations

import asyncio
import dataclasses
import threading
from collections.abc import AsyncGenerator, Callable
from typing import Any

import msgspec.msgpack
import pytest

from leika import _messages
from leika._transport import _message_buffer as buffer_impl
from leika._transport._message_buffer import AsyncMessageBuffer, MessageWindow
from leika._transport._websocket import _ClientHandleState, _message_producer

Windows = AsyncGenerator[MessageWindow, None]
_PANE_PROPS = _messages.ViewportEmptyProps("Pane", True, False)


class _QueuedLoop:
    """Records thread-safe callbacks instead of running them."""

    def __init__(self) -> None:
        self.callbacks: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def call_soon_threadsafe(self, callback: Callable[..., Any], *args: Any) -> None:
        self.callbacks.append((callback, args))


class _ClosedLoop:
    def call_soon_threadsafe(self, callback: Callable[..., Any], *args: Any) -> None:
        raise RuntimeError("loop is closed")


@dataclasses.dataclass
class _Scoped(_messages.Message):
    """A retained message delivered only to subscribers of its scope."""

    scope: str
    value: str

    def delivery_scope(self) -> str:
        return self.scope


def _buffer(persistent: bool = True) -> AsyncMessageBuffer:
    """A buffer whose wakeups are recorded, for tests that never window."""
    return AsyncMessageBuffer(_QueuedLoop(), persistent_messages=persistent)  # type: ignore[arg-type]


def _live_buffer(persistent: bool = True, **kwargs: Any) -> AsyncMessageBuffer:
    return AsyncMessageBuffer(
        asyncio.get_running_loop(), persistent_messages=persistent, window_duration_sec=0, **kwargs
    )


def _retained(buffer: AsyncMessageBuffer) -> list[_messages.Message]:
    return list(buffer.message_from_id.values())


def _streams(page_id: str, generation: int) -> tuple[_messages.Message, _messages.Message]:
    return (
        _messages.PageStreamBeginMessage(page_id, generation),
        _messages.PageStreamReadyMessage(page_id, generation),
    )


def _text(uuid: str, container_uuid: str = "root") -> _messages.GuiTextMessage:
    props = _messages.GuiTextProps(
        order=0.0,
        label=uuid,
        hint=None,
        visible=True,
        disabled=False,
        multiline=False,
        rows=None,
        editable=False,
        markdown=False,
        _source=uuid,
    )
    return _messages.GuiTextMessage(
        uuid=uuid, value=uuid, container_uuid=container_uuid, props=props
    )


async def _receive(
    buffer: AsyncMessageBuffer, windows: Windows, client_id: int, count: int
) -> list[_messages.Message]:
    """Exactly ``count`` messages from consecutive windows, each marked sent."""
    received: list[_messages.Message] = []
    while len(received) < count:
        window = await asyncio.wait_for(windows.__anext__(), timeout=1)
        buffer.mark_messages_sent(client_id, window.last_message_id)
        received.extend(record.message for record in window.messages)
    assert len(received) == count
    return received


async def _pending(windows: Windows) -> asyncio.Future[MessageWindow]:
    """Start waiting for the next window and check that none is ready."""
    pending = asyncio.ensure_future(windows.__anext__())
    done, _ = await asyncio.wait({pending}, timeout=0.05)
    assert not done
    return pending


def test_window_generator_cleans_up_flush_wait() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        next_window = asyncio.ensure_future(buffer.window_generator(0).__anext__())
        await asyncio.sleep(0)

        buffer.set_done()
        with pytest.raises(StopAsyncIteration):
            await next_window

        current = asyncio.current_task()
        assert [task for task in asyncio.all_tasks() if task is not current] == []

    asyncio.run(run())


def test_closed_buffer_discards_queued_messages_and_rejects_new_ones() -> None:
    buffer = _buffer()
    buffer.register_client(1)
    assert buffer.reserve_file_bytes(3)
    assert buffer.push_reserved_file_message(_messages.FileTransferPart(None, "t", 0, b"abc"), 3)
    assert buffer.push(_messages.GuiRemoveMessage("removed"))
    assert len(buffer.message_from_id) == 2

    buffer.set_done()

    # Queued file parts give back the capacity they held.
    assert (buffer._file_bytes, buffer._file_parts) == (0, 0)
    assert buffer.message_from_id == {}
    assert not buffer.push(_messages.ClientPingMessage(sent_ms=1.0))
    assert not buffer.push_many([_messages.ClientPingMessage(sent_ms=2.0)])
    assert not buffer.request_delivery_scope(1, "page", *_streams("page", 1))
    assert not buffer.reserve_file_bytes(1)
    assert buffer.message_from_id == {}


def test_push_and_flush_coalesce_threadsafe_event_pulses() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]

    assert buffer.push(_messages.ClientPingMessage(sent_ms=1.0))
    assert buffer.push_many([_messages.RunJavascriptMessage("second")] * 2)
    for _ in range(1_000):
        buffer.flush()
    assert len(loop.callbacks) == 2

    for callback, args in loop.callbacks:
        callback(*args)
    assert buffer.message_event.is_set()
    assert buffer.flush_event.is_set()

    # Each pulse is scheduled again only after the previous one ran.
    loop.callbacks.clear()
    assert buffer.push(_messages.RunJavascriptMessage("third"))
    buffer.flush()
    buffer.flush()
    assert len(loop.callbacks) == 2


def test_closed_event_loop_raises_before_any_state_changes() -> None:
    buffer = AsyncMessageBuffer(_ClosedLoop(), persistent_messages=True)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="loop is closed"):
        buffer.push(_messages.ClientPingMessage(sent_ms=1.0))
    with pytest.raises(RuntimeError, match="loop is closed"):
        buffer.push_many([_messages.RunJavascriptMessage("a"), _messages.RunJavascriptMessage("b")])
    assert buffer.message_from_id == {}

    # Teardown on a closed loop neither raises nor schedules.
    buffer.atomic_start()
    buffer.set_done()
    buffer.atomic_end()
    assert buffer.atomic_counter == 0


def test_nested_atomic_blocks_and_unmatched_end() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=False)  # type: ignore[arg-type]
    assert not buffer.file_transfer_must_be_deferred()
    buffer.atomic_start()
    buffer.atomic_start()
    assert buffer.push(_messages.RunJavascriptMessage("held"))
    assert buffer.file_transfer_must_be_deferred()
    buffer.atomic_end()
    assert loop.callbacks == []
    buffer.atomic_end()
    assert len(loop.callbacks) == 1
    assert not buffer.file_transfer_must_be_deferred()
    with pytest.raises(RuntimeError, match="without a matching"):
        buffer.atomic_end()


def test_flush_cuts_the_batching_delay() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(), persistent_messages=False, window_duration_sec=60
        )
        first = _messages.RunJavascriptMessage("first")
        second = _messages.RunJavascriptMessage("second")
        windows = buffer.window_generator(1)
        assert buffer.push(first)
        assert await _receive(buffer, windows, 1, 1) == [first]

        # The next window waits out the batching delay unless flushed.
        assert buffer.push(second)
        pending = await _pending(windows)
        buffer.flush()
        window = await asyncio.wait_for(pending, timeout=1)
        assert [record.message for record in window.messages] == [second]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_validation_errors_surface_at_push_and_leave_the_buffer_unchanged() -> None:
    loop = _QueuedLoop()
    buffer = AsyncMessageBuffer(loop, persistent_messages=True)  # type: ignore[arg-type]
    invalid = _messages.RunJavascriptMessage(source=1)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="expected"):
        buffer.push(invalid)
    with pytest.raises(TypeError, match="expected"):
        buffer.push_many([_messages.RunJavascriptMessage("valid"), invalid])
    with pytest.raises(TypeError, match="unsupported protocol value"):
        buffer.push(_messages.GuiUpdateMessage("field", {"value": object()}))

    assert buffer.message_from_id == {}
    assert loop.callbacks == []


def test_each_message_is_encoded_once_and_shared_by_every_client() -> None:
    async def run() -> None:
        buffer = _live_buffer()
        message = _messages.GuiUpdateMessage("slider", {"value": 1})
        assert buffer.push(message)
        message.updates["value"] = 2

        first, second = buffer.window_generator(1), buffer.window_generator(2)
        (record,) = (await asyncio.wait_for(first.__anext__(), timeout=1)).messages
        (shared,) = (await asyncio.wait_for(second.__anext__(), timeout=1)).messages
        assert shared is record
        assert record.message is message
        # The queued bytes are the message as it was pushed.
        assert msgspec.msgpack.decode(record.data) == {
            "type": "GuiUpdateMessage",
            "uuid": "slider",
            "updates": {"value": 1},
        }
        await first.aclose()
        await second.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_coalescing_replaces_only_messages_with_a_shared_redundancy_key() -> None:
    buffer = _buffer()
    value = _messages.GuiUpdateMessage("field", {"value": 1})
    label = _messages.GuiUpdateMessage("field", {"label": "Field"})
    script = _messages.RunJavascriptMessage("same")
    tab = _messages.GuiTabMessage("tab", "tabs", _messages.GuiTabProps("Tab", None))
    child = _text("child", "tab")
    pages = _messages.PageCatalogMessage(("alpha",))
    snapshot_a = _messages.ViewportPaneSnapshotMessage("alpha", ("one",))
    snapshot_b = _messages.ViewportPaneSnapshotMessage("beta", ("one",))
    assert buffer.push_many(
        [
            value,
            label,
            script,
            script,
            tab,
            child,
            _messages.GuiTabUpdateMessage("tab", "tabs", _messages.GuiTabProps("Old", None)),
            _messages.ServerPongMessage(1.0),
            _messages.ThemeConfigurationMessage("floating", "auto"),
            _messages.GuiFormSubmitMessage("form"),
            pages,
            snapshot_a,
            snapshot_b,
        ]
    )
    newest = [
        _messages.GuiTabUpdateMessage("tab", "tabs", _messages.GuiTabProps("New", None)),
        _messages.ServerPongMessage(2.0),
        _messages.ThemeConfigurationMessage("left", "dark"),
        _messages.GuiFormSubmitMessage("form"),
        _messages.PageCatalogMessage(("alpha", "beta")),
        _messages.ViewportPaneSnapshotMessage("alpha", ("two",)),
        _messages.GuiUpdateMessage("field", {"value": 2}),
    ]
    assert buffer.push_many(newest)

    # A replacement takes the newest position; a tab's rename never moves its
    # declaration behind the children it contains.
    retained = _retained(buffer)
    assert retained == [label, script, script, tab, child, snapshot_b, *newest]
    assert retained[-1] is newest[-1]


@pytest.mark.parametrize(
    ("before", "removal", "survivors"),
    [
        pytest.param(
            [
                _messages.GuiFolderMessage(
                    uuid="parent",
                    container_uuid="root",
                    props=_messages.GuiFolderProps(0.0, "Parent", True, True),
                ),
                _text("child", "parent"),
                _messages.GuiUpdateMessage("child", {"value": "updated"}),
                _messages.GuiUpdateMessage("grandchild", {"value": "updated"}),
                _text("sibling"),
            ],
            _messages.GuiRemoveMessage("parent", removed_uuids=("grandchild", "child")),
            [_text("sibling")],
            id="parent",
        ),
        pytest.param(
            [
                _messages.GuiTabMessage("tab", "tabs", _messages.GuiTabProps("Tab", None)),
                _text("child", "tab"),
                _messages.GuiTabUpdateMessage(
                    "tab", "tabs", _messages.GuiTabProps("Renamed", None)
                ),
                _messages.GuiTabMessage("other", "tabs", _messages.GuiTabProps("Other", None)),
            ],
            _messages.GuiRemoveMessage("tab", removed_uuids=("child",)),
            [_messages.GuiTabMessage("other", "tabs", _messages.GuiTabProps("Other", None))],
            id="tab",
        ),
        pytest.param(
            [
                _messages.GuiTabMessage("outer", "group-a", _messages.GuiTabProps("Outer", None)),
                _messages.GuiTabMessage("inner", "group-b", _messages.GuiTabProps("Inner", None)),
                _text("child", "inner"),
            ],
            _messages.GuiRemoveMessage("folder", removed_uuids=("outer", "inner", "child")),
            [],
            id="nested-tabs",
        ),
        pytest.param(
            [
                _messages.GuiModalMessage(0.0, "modal", "Modal"),
                _text("child", "modal"),
                _messages.GuiUpdateMessage("child", {"value": "updated"}),
            ],
            _messages.GuiCloseModalMessage("modal", removed_uuids=("child",)),
            [],
            id="modal",
        ),
        pytest.param(
            [
                _messages.ViewportPaneMessage("page", "pane", "right", "root", (), _PANE_PROPS),
                _messages.ViewportEmptyMessage("page", "pane", "right", "root", (), _PANE_PROPS),
                _messages.ViewportPaneUpdateMessage("page", "pane", {"title": "Renamed"}),
                _messages.ViewportPaneUpdateMessage("other", "pane", {"title": "Kept"}),
            ],
            _messages.ViewportPaneRemoveMessage("page", "pane"),
            [_messages.ViewportPaneUpdateMessage("other", "pane", {"title": "Kept"})],
            id="pane",
        ),
    ],
)
def test_removal_purges_entity_state_and_named_descendants(
    before: list[_messages.Message],
    removal: _messages.Message,
    survivors: list[_messages.Message],
) -> None:
    buffer = _buffer()
    buffer.register_client(1)
    assert buffer.push_many(before)
    assert buffer.push(removal)

    # The connected client still needs the removal itself.
    assert _retained(buffer) == [*survivors, removal]
    (remove_id,) = [key for key, value in buffer.message_from_id.items() if value is removal]
    buffer.mark_messages_sent(1, remove_id)
    assert _retained(buffer) == survivors


def test_recreated_entity_replays_without_its_purged_state() -> None:
    buffer = _buffer()
    buffer.register_client(1)
    group = _messages.GuiTabGroupMessage(
        uuid="tabs",
        container_uuid="root",
        props=_messages.GuiTabGroupProps(order=0.0, visible=True),
    )
    assert buffer.push_many(
        [
            group,
            _messages.GuiTabMessage("tab", "tabs", _messages.GuiTabProps("Old", None)),
            _text("child", "tab"),
            _messages.GuiRemoveMessage("tab", removed_uuids=("child",)),
        ]
    )
    recreated = _messages.GuiTabMessage("tab", "tabs", _messages.GuiTabProps("New", None))
    assert buffer.push(recreated)
    retained = _retained(buffer)
    assert retained[0] is group
    assert retained[-1] is recreated
    assert not any(isinstance(message, _messages.GuiTextMessage) for message in retained)


def test_tombstone_waits_for_every_connected_client_then_is_collected() -> None:
    buffer = _buffer()
    buffer.register_client(1)
    buffer.register_client(2)
    remove = _messages.GuiRemoveMessage("removed")
    assert buffer.push(remove)
    assert _retained(buffer) == [remove]

    buffer.mark_messages_sent(1, 0)
    assert _retained(buffer) == [remove]
    buffer.mark_messages_sent(2, 0)
    assert buffer.message_from_id == {}


def test_tombstones_are_not_retained_when_no_client_needs_them() -> None:
    buffer = _buffer()
    for index in range(100):
        assert buffer.push(_messages.GuiRemoveMessage(f"removed-{index}"))
    assert buffer.message_from_id == {}


def test_failed_send_keeps_tombstone_until_disconnect() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=True)
        buffer.register_client(7)
        remove = _messages.GuiRemoveMessage("removed")
        assert buffer.push(remove)

        class FailingSocket:
            async def send(self, frame: bytes) -> None:
                assert frame
                assert _retained(buffer) == [remove]
                raise RuntimeError("send failed")

        state = _ClientHandleState(buffer, buffer)
        with pytest.raises(RuntimeError, match="send failed"):
            await _message_producer(FailingSocket(), buffer, 7, state)  # type: ignore[arg-type]

        # The producer's exit unregistered the client, which released it.
        assert buffer.message_from_id == {}
        buffer.set_done()

    asyncio.run(run())


def test_skipped_inactive_tombstone_advances_cursor_and_is_collected() -> None:
    async def run() -> None:
        buffer = _live_buffer()
        buffer.register_client(1)
        script = _messages.RunJavascriptMessage("global")
        inactive_remove = _messages.ViewportPaneRemoveMessage("page-b", "removed-pane")
        assert buffer.push_many((script, inactive_remove))

        windows = buffer.window_generator(1)
        window = await asyncio.wait_for(windows.__anext__(), timeout=1)
        assert [record.message for record in window.messages] == [script]
        assert window.last_message_id == 1
        assert inactive_remove in _retained(buffer)

        buffer.mark_messages_sent(1, window.last_message_id)
        assert _retained(buffer) == [script]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_connection_local_buffer_drops_windowed_messages_and_persistent_buffer_replays() -> None:
    async def run() -> None:
        messages = [_messages.RunJavascriptMessage("a"), _messages.RunJavascriptMessage("b")]
        local = _live_buffer(persistent=False)
        assert local.push_many(messages)
        windows = local.window_generator(1)
        assert await _receive(local, windows, 1, 2) == messages
        assert local.message_from_id == {}
        await windows.aclose()
        local.set_done()

        retained = _live_buffer()
        assert retained.push_many(messages)
        early = retained.window_generator(1)
        assert await _receive(retained, early, 1, 2) == messages
        late = retained.window_generator(2)
        assert await _receive(retained, late, 2, 2) == messages
        assert _retained(retained) == messages
        await early.aclose()
        await late.aclose()
        retained.set_done()

    asyncio.run(run())


def test_excluded_client_never_receives_its_own_echo() -> None:
    async def run() -> None:
        buffer = _live_buffer()
        echo = _messages.GuiUpdateMessage("slider", {"value": 1})
        echo.excluded_self_client = 1
        sender, other = buffer.window_generator(1), buffer.window_generator(2)
        assert buffer.push(echo)

        assert await _receive(buffer, other, 2, 1) == [echo]
        pending = await _pending(sender)
        later = _messages.RunJavascriptMessage("later")
        assert buffer.push(later)
        window = await asyncio.wait_for(pending, timeout=1)
        assert [record.message for record in window.messages] == [later]
        await sender.aclose()
        await other.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_unsubscribed_persistent_client_receives_only_global_messages() -> None:
    async def run() -> None:
        buffer = _live_buffer()
        first_global = _messages.ClientPingMessage(sent_ms=1.0)
        second_global = _messages.RunJavascriptMessage("global")
        assert buffer.push_many(
            (first_global, _Scoped("page-a", "a"), second_global, _Scoped("page-b", "b"))
        )

        windows = buffer.window_generator(1)
        assert await _receive(buffer, windows, 1, 2) == [first_global, second_global]

        live_global = _messages.GuiUpdateMessage("component", {"value": "global"})
        assert buffer.push_many(
            (_Scoped("page-a", "live-a"), live_global, _Scoped("page-b", "live-b"))
        )
        assert await _receive(buffer, windows, 1, 1) == [live_global]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_scope_subscription_frames_replay_and_live_delivery() -> None:
    async def run() -> None:
        buffer = _live_buffer(max_window_size=1)
        replayed = _Scoped("page-a", "replayed")
        stale = _messages.ViewportPaneUpdateMessage("page-a", "pane", {"title": "stale"})
        assert buffer.push_many((replayed, stale))
        buffer.register_client(1)
        begin, ready = _streams("page-a", 7)
        assert buffer.request_delivery_scope(1, "page-a", begin, ready)
        windows = buffer.window_generator(1)
        assert await _receive(buffer, windows, 1, 2) == [begin, replayed]

        # A replacement queued mid-replay arrives once, after the ready marker.
        replacement = _messages.ViewportPaneUpdateMessage("page-a", "pane", {"title": "new"})
        assert buffer.push(replacement)
        assert await _receive(buffer, windows, 1, 2) == [ready, replacement]

        selected = _Scoped("page-a", "selected-live")
        live_global = _messages.ClientPingMessage(sent_ms=2.0)
        assert buffer.push_many((_Scoped("page-b", "inactive-live"), selected, live_global))
        assert await _receive(buffer, windows, 1, 2) == [selected, live_global]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_scope_subscriptions_isolate_two_clients() -> None:
    async def run() -> None:
        buffer = _live_buffer()
        retained_a = _Scoped("page-a", "retained-a")
        retained_b = _Scoped("page-b", "retained-b")
        assert buffer.push_many((retained_a, retained_b))

        clients = []
        for client_id, page_id, retained in ((1, "page-a", retained_a), (2, "page-b", retained_b)):
            buffer.register_client(client_id)
            begin, ready = _streams(page_id, 1)
            assert buffer.request_delivery_scope(client_id, page_id, begin, ready)
            assert buffer.delivery_scope_from_client(client_id) == page_id
            windows = buffer.window_generator(client_id)
            assert await _receive(buffer, windows, client_id, 3) == [begin, retained, ready]
            clients.append(windows)

        live_a = _Scoped("page-a", "live-a")
        live_b = _Scoped("page-b", "live-b")
        live_global = _messages.RunJavascriptMessage("shared-live")
        assert buffer.push_many((live_a, live_b, live_global))
        assert await _receive(buffer, clients[0], 1, 2) == [live_a, live_global]
        assert await _receive(buffer, clients[1], 2, 2) == [live_b, live_global]
        for windows in clients:
            await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_rapid_scope_replacement_abandons_old_replay() -> None:
    async def run() -> None:
        buffer = _live_buffer(max_window_size=1)
        retained_a_first = _Scoped("page-a", "retained-a-first")
        retained_a_second = _Scoped("page-a", "retained-a-second")
        retained_b = _Scoped("page-b", "retained-b")
        assert buffer.push_many((retained_a_first, retained_a_second, retained_b))

        buffer.register_client(1)
        begin_a, ready_a = _streams("page-a", 1)
        assert buffer.request_delivery_scope(1, "page-a", begin_a, ready_a)
        windows = buffer.window_generator(1)
        assert await _receive(buffer, windows, 1, 2) == [begin_a, retained_a_first]

        begin_b, ready_b = _streams("page-b", 2)
        assert buffer.request_delivery_scope(1, "page-b", begin_b, ready_b)
        assert await _receive(buffer, windows, 1, 3) == [begin_b, retained_b, ready_b]

        live_b = _Scoped("page-b", "live-b")
        live_global = _messages.ClientPingMessage(sent_ms=3.0)
        assert buffer.push_many((_Scoped("page-a", "live-a"), live_b, live_global))
        assert await _receive(buffer, windows, 1, 2) == [live_b, live_global]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_scope_requests_need_a_connected_client() -> None:
    buffer = _buffer()
    assert not buffer.request_delivery_scope(1, "page-a", *_streams("page-a", 1))
    assert buffer.delivery_scope_from_client(1) is None

    buffer.register_client(1)
    assert buffer.request_delivery_scope(1, "page-a", *_streams("page-a", 1))
    assert buffer.request_delivery_scope(1, "page-b", *_streams("page-b", 2))
    assert buffer.delivery_scope_from_client(1) == "page-b"
    buffer.unregister_client(1)
    assert buffer.delivery_scope_from_client(1) is None

    # Connection-local buffers have no retained scopes.
    local = _buffer(persistent=False)
    local.register_client(1)
    assert not local.request_delivery_scope(1, "page-a", *_streams("page-a", 1))


def test_atomic_block_holds_connection_local_windows() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        queued = _messages.RunJavascriptMessage("queued")
        assert buffer.push(queued)
        buffer.atomic_start()
        windows = buffer.window_generator(1)
        pending = await _pending(windows)
        assert _retained(buffer) == [queued]

        buffer.atomic_end()
        window = await asyncio.wait_for(pending, timeout=1)
        assert [record.message for record in window.messages] == [queued]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_atomic_scope_request_waits_and_drains_global_prefix_first() -> None:
    async def run() -> None:
        buffer = _live_buffer()
        buffer.register_client(1)
        begin, ready = _streams("page-a", 1)

        buffer.atomic_start()
        first_global = _messages.ClientPingMessage(sent_ms=4.0)
        scoped = _Scoped("page-a", "retained")
        second_global = _messages.RunJavascriptMessage("global")
        assert buffer.push_many((first_global, scoped, second_global))
        assert buffer.request_delivery_scope(1, "page-a", begin, ready)

        windows = buffer.window_generator(1)
        pending = await _pending(windows)
        buffer.atomic_end()
        window = await asyncio.wait_for(pending, timeout=1)
        assert [record.message for record in window.messages] == [
            first_global,
            second_global,
            begin,
            scoped,
            ready,
        ]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def _reserve_in_thread(buffer: AsyncMessageBuffer) -> tuple[threading.Thread, list[bool]]:
    """Start a one-byte reservation and check that it blocks."""
    result: list[bool] = []
    thread = threading.Thread(target=lambda: result.append(buffer.reserve_file_bytes(1)))
    thread.start()
    thread.join(timeout=0.05)
    assert thread.is_alive()
    return thread, result


def test_file_reservation_blocks_at_byte_capacity_and_wakes_on_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_FILE_TRANSFER_BUFFER_BYTES", 4)
    buffer = _buffer(persistent=False)
    assert buffer.reserve_file_bytes(4)
    thread, result = _reserve_in_thread(buffer)

    buffer.release_file_bytes(4)
    thread.join(timeout=1)
    assert result == [True]
    assert (buffer._file_bytes, buffer._file_parts) == (1, 1)


def test_file_reservation_blocks_at_part_capacity_and_wakes_on_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(buffer_impl, "_FILE_TRANSFER_BUFFER_PARTS", 2)
    buffer = _buffer(persistent=False)
    assert buffer.reserve_file_bytes(1)
    assert buffer.reserve_file_bytes(1)
    thread, result = _reserve_in_thread(buffer)

    buffer.release_file_bytes(1)
    thread.join(timeout=1)
    assert result == [True]
    assert buffer._file_parts == 2


def test_shutdown_wakes_a_blocked_file_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(buffer_impl, "_FILE_TRANSFER_BUFFER_BYTES", 4)
    buffer = _buffer(persistent=False)
    assert buffer.reserve_file_bytes(4)
    thread, result = _reserve_in_thread(buffer)

    buffer.set_done()
    thread.join(timeout=1)
    assert result == [False]


def test_reserved_windows_preserve_order_and_own_capacity_until_sent() -> None:
    async def run() -> None:
        buffer = _live_buffer(persistent=False)
        first = _messages.FileTransferPart(None, "transfer", 0, b"ab")
        start = _messages.RunJavascriptMessage("between")
        second = _messages.FileTransferPart(None, "transfer", 1, b"cd")
        assert buffer.reserve_file_bytes(2)
        assert buffer.push_reserved_file_message(first, 2)
        assert buffer.push(start)
        assert buffer.reserve_file_bytes(2)
        assert buffer.push_reserved_file_message(second, 2)

        windows = buffer.window_generator(1)
        window = await asyncio.wait_for(windows.__anext__(), timeout=1)
        assert [record.message for record in window.messages] == [first, start, second]
        assert (window.file_bytes, window.file_parts) == (4, 2)
        # Leaving the queue does not free capacity; the completed send does.
        assert buffer.message_from_id == {}
        assert (buffer._file_bytes, buffer._file_parts) == (4, 2)
        buffer.release_file_bytes(window.file_bytes, window.file_parts)
        assert (buffer._file_bytes, buffer._file_parts) == (0, 0)
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


@pytest.mark.parametrize("persistent", [False, True])
def test_windows_split_at_the_message_count_in_order(persistent: bool) -> None:
    async def run() -> None:
        buffer = _live_buffer(persistent, max_window_size=2)
        messages = [_messages.RunJavascriptMessage(str(index)) for index in range(5)]
        assert buffer.push_many(messages)
        windows = buffer.window_generator(1)
        sizes = []
        received: list[_messages.Message] = []
        while len(received) < len(messages):
            window = await asyncio.wait_for(windows.__anext__(), timeout=1)
            buffer.mark_messages_sent(1, window.last_message_id)
            sizes.append(len(window.messages))
            received.extend(record.message for record in window.messages)
        assert sizes == [2, 2, 1]
        assert received == messages
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


def test_windows_stop_before_the_byte_limit_unless_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        small = [_messages.RunJavascriptMessage(value) for value in ("aa", "bb", "cc")]
        large = _messages.RunJavascriptMessage("x" * 1_000)
        monkeypatch.setattr(buffer_impl, "_WINDOW_MAX_BYTES", 2 * len(small[0].encode()))
        buffer = _live_buffer(persistent=False)
        assert buffer.push_many([*small, large])
        windows = buffer.window_generator(1)
        batches = []
        for _ in range(3):
            window = await asyncio.wait_for(windows.__anext__(), timeout=1)
            batches.append([record.message for record in window.messages])
        # A message larger than the limit still goes, alone.
        assert batches == [small[:2], small[2:], [large]]
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())


@pytest.mark.parametrize("persistent", [False, True])
def test_sparse_index_compaction_delivers_each_message_once(persistent: bool) -> None:
    async def run() -> None:
        buffer = _live_buffer(persistent, max_window_size=16)
        for index in range(128):
            assert buffer.push(_messages.GuiUpdateMessage(str(index), {"value": 0}))
        for revision in range(1_000):
            assert buffer.push(_messages.GuiUpdateMessage("0", {"value": revision}))
        # Replaced IDs leave the replay index instead of accumulating.
        assert len(buffer._ids) <= 2 * len(buffer.message_from_id)
        expected = _retained(buffer)
        assert len(expected) == 128

        windows = buffer.window_generator(1)
        assert await _receive(buffer, windows, 1, 128) == expected

        update = _messages.GuiUpdateMessage("0", {"value": "live"})
        assert buffer.push(update)
        window = await asyncio.wait_for(windows.__anext__(), timeout=1)
        assert [record.message for record in window.messages] == [update]
        assert window.last_message_id == buffer._next_id - 1
        await windows.aclose()
        buffer.set_done()

    asyncio.run(run())
