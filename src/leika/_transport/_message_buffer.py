"""Ordered outgoing message queues with coalescing, retained replay and windows."""

from __future__ import annotations

import asyncio
import dataclasses
import threading
from bisect import bisect_right
from collections.abc import AsyncGenerator, Iterator, Sequence

from .._messages import Message

_FILE_TRANSFER_BUFFER_BYTES = 8 * 1024 * 1024
"""Maximum queued file payload per client."""

_FILE_TRANSFER_BUFFER_PARTS = 256
"""Maximum queued and in-flight file parts per client."""

_WINDOW_MAX_BYTES = 8 * 1024 * 1024
"""Encoded bytes after which a window takes no further messages."""


@dataclasses.dataclass(frozen=True)
class QueuedMessage:
    """A message's bytes, encoded once at push, with the routing it was queued under."""

    data: bytes
    redundancy_key: str | None
    entity: tuple[str, object] | None
    purge_entities: tuple[tuple[str, object], ...]
    removal: bool
    delivery_scope: str | None
    excluded_client: int | None
    file_bytes: int = 0

    @classmethod
    def prepare(cls, message: Message, file_bytes: int = 0) -> QueuedMessage:
        return cls(
            message.encode(),
            message.redundancy_key(),
            message.lifecycle_entity(),
            message.purge_entities(),
            message.lifecycle_phase == "remove",
            message.delivery_scope(),
            message.excluded_self_client,
            file_bytes,
        )


@dataclasses.dataclass(frozen=True)
class MessageWindow:
    """One outgoing batch and the file capacity it owns until it is sent."""

    messages: tuple[QueuedMessage, ...]
    last_message_id: int
    file_bytes: int = 0
    file_parts: int = 0


@dataclasses.dataclass(frozen=True)
class _ScopeRequest:
    revision: int
    scope: str
    begin: QueuedMessage
    ready: QueuedMessage


@dataclasses.dataclass
class _ScopeReplay:
    """A scope switch in progress: earlier global messages, then begin, the
    scope's retained messages and ready."""

    request: _ScopeRequest
    cutoff: int
    items: list[int | QueuedMessage]
    global_items: int
    index: int = 0


class AsyncMessageBuffer:
    """Thread-safe queue of outgoing messages for one or all clients.

    A newer message replaces a queued one with the same redundancy key, and a
    removal purges its entity's messages. A persistent buffer retains state
    for clients that connect later and tracks each client's delivery; a
    connection-local buffer drops each message once it is in a window.
    """

    def __init__(
        self,
        event_loop: asyncio.AbstractEventLoop,
        persistent_messages: bool,
        *,
        max_window_size: int = 128,
        window_duration_sec: float = 1.0 / 60.0,
    ) -> None:
        self.event_loop = event_loop
        self.persistent_messages = persistent_messages
        self.max_window_size = max_window_size
        self.window_duration_sec = window_duration_sec
        self.message_event = asyncio.Event()
        self.flush_event = asyncio.Event()
        self.done = False
        self.atomic_counter = 0
        self._lock = threading.RLock()
        self._file_condition = threading.Condition(self._lock)
        self._message_signal_scheduled = False
        self._flush_signal_scheduled = False

        self._next_id = 0
        self._queued: dict[int, QueuedMessage] = {}
        self._ids: list[int] = []
        """Sorted replay index, compacted when stale IDs outnumber live ones."""
        self._id_from_key: dict[str, int] = {}
        self._ids_from_entity: dict[tuple[str, object], set[int]] = {}
        self._tombstones: dict[int, None] = {}
        """Retained removals, in ID order, until every connected client has them."""
        self._sent_through: dict[int, int] = {}
        self._scope_revision = 0
        self._scope_requests: dict[int, _ScopeRequest] = {}
        self._file_bytes = 0
        self._file_parts = 0

    def __len__(self) -> int:
        """Number of queued or, when persistent, retained messages."""
        with self._lock:
            return len(self._queued)

    def push(self, message: Message) -> bool:
        """Queue one message, returning whether the buffer is still open."""
        return self._insert((QueuedMessage.prepare(message),))

    def push_many(self, messages: Sequence[Message]) -> bool:
        """Queue related messages together, or none of them on a closed buffer."""
        return self._insert(tuple(QueuedMessage.prepare(message) for message in messages))

    def push_reserved_file_message(self, message: Message, size: int) -> bool:
        """Queue a file part whose capacity its producer already reserved."""
        return self._insert((QueuedMessage.prepare(message, file_bytes=size),))

    def _insert(self, records: tuple[QueuedMessage, ...]) -> bool:
        with self._lock:
            if self.done:
                return False
            if not records:
                return True
            # Schedule first: a closed loop raises before any state changes.
            if self.atomic_counter == 0:
                self._schedule_message_event_locked()
            for record in records:
                removed = set()
                if record.redundancy_key is not None:
                    previous = self._id_from_key.get(record.redundancy_key)
                    if previous is not None:
                        removed.add(previous)
                for entity in record.purge_entities:
                    removed.update(self._ids_from_entity.get(entity, ()))
                for message_id in removed:
                    self._remove_locked(message_id)

                message_id = self._next_id
                self._next_id += 1
                self._queued[message_id] = record
                self._ids.append(message_id)
                if record.redundancy_key is not None:
                    self._id_from_key[record.redundancy_key] = message_id
                if record.entity is not None:
                    self._ids_from_entity.setdefault(record.entity, set()).add(message_id)
                if self.persistent_messages and record.removal:
                    self._tombstones[message_id] = None
            self._prune_tombstones_locked()
            return True

    def _remove_locked(self, message_id: int) -> QueuedMessage:
        record = self._queued.pop(message_id)
        if len(self._ids) > max(128, 2 * len(self._queued)):
            self._ids = list(self._queued)
        if (
            record.redundancy_key is not None
            and self._id_from_key.get(record.redundancy_key) == message_id
        ):
            del self._id_from_key[record.redundancy_key]
        if record.entity is not None:
            entity_ids = self._ids_from_entity[record.entity]
            entity_ids.discard(message_id)
            if not entity_ids:
                del self._ids_from_entity[record.entity]
        self._tombstones.pop(message_id, None)
        return record

    def _prune_tombstones_locked(self) -> None:
        """Drop removals every connected client has been sent.

        A later client needs only the surviving state; a connected client
        needs each removal until a send containing it succeeds.
        """
        if not self._tombstones:
            return
        delivered = min(self._sent_through.values(), default=self._next_id - 1)
        while self._tombstones:
            message_id = next(iter(self._tombstones))
            if message_id > delivered:
                break
            self._remove_locked(message_id)

    def register_client(self, client_id: int) -> None:
        """Track a connected client's delivery of retained removals."""
        if self.persistent_messages:
            with self._lock:
                self._sent_through.setdefault(client_id, -1)

    def unregister_client(self, client_id: int) -> None:
        if self.persistent_messages:
            with self._lock:
                self._sent_through.pop(client_id, None)
                self._scope_requests.pop(client_id, None)
                self._prune_tombstones_locked()

    def mark_messages_sent(self, client_id: int, last_message_id: int) -> None:
        """Record a successful send through ``last_message_id``."""
        if self.persistent_messages:
            with self._lock:
                if client_id in self._sent_through:
                    self._sent_through[client_id] = last_message_id
                    self._prune_tombstones_locked()

    def request_delivery_scope(
        self, client_id: int, scope: str, begin_message: Message, ready_message: Message
    ) -> bool:
        """Switch one client to a retained scope, framed by begin and ready."""
        begin = QueuedMessage.prepare(begin_message)
        ready = QueuedMessage.prepare(ready_message)
        with self._lock:
            if self.done or client_id not in self._sent_through:
                return False
            if self.atomic_counter == 0:
                self._schedule_message_event_locked()
            self._scope_revision += 1
            self._scope_requests[client_id] = _ScopeRequest(
                self._scope_revision, scope, begin, ready
            )
            return True

    def delivery_scope_from_client(self, client_id: int) -> str | None:
        with self._lock:
            request = self._scope_requests.get(client_id)
            return None if request is None else request.scope

    def reserve_file_bytes(self, size: int) -> bool:
        """Reserve outgoing file capacity, blocking until it is available.

        Returns False once the buffer closes. Capacity stays reserved through
        the websocket send, not merely until the part leaves this buffer.
        """
        with self._file_condition:
            while not self.done and (
                self._file_bytes + size > _FILE_TRANSFER_BUFFER_BYTES
                or self._file_parts >= _FILE_TRANSFER_BUFFER_PARTS
            ):
                self._file_condition.wait()
            if self.done:
                return False
            self._file_bytes += size
            self._file_parts += 1
            return True

    def release_file_bytes(self, size: int, parts: int = 1) -> None:
        with self._file_condition:
            self._file_bytes -= size
            self._file_parts -= parts
            self._file_condition.notify_all()

    def file_transfer_must_be_deferred(self) -> bool:
        """Whether a synchronous transfer would wait on its own held delivery."""
        with self._lock:
            return self.atomic_counter > 0

    def atomic_start(self) -> None:
        """Hold windows until the matching ``atomic_end()``."""
        with self._lock:
            self.atomic_counter += 1

    def atomic_end(self) -> None:
        with self._lock:
            if self.atomic_counter == 0:
                raise RuntimeError("atomic_end() called without a matching atomic_start()")
            self.atomic_counter -= 1
            if self.atomic_counter == 0 and not self.done:
                self._schedule_message_event_locked()

    def _set_message_event(self) -> None:
        with self._lock:
            self._message_signal_scheduled = False
        self.message_event.set()

    def _schedule_message_event_locked(self) -> None:
        """Schedule one coalesced wakeup on the owning event loop."""
        if not self._message_signal_scheduled:
            self.event_loop.call_soon_threadsafe(self._set_message_event)
            self._message_signal_scheduled = True

    def _set_flush_event(self) -> None:
        with self._lock:
            self._flush_signal_scheduled = False
        self.flush_event.set()

    def flush(self) -> None:
        """Send pending messages without waiting out the batching delay."""
        with self._lock:
            if self.done or self._flush_signal_scheduled:
                return
            self.event_loop.call_soon_threadsafe(self._set_flush_event)
            self._flush_signal_scheduled = True

    def set_done(self) -> None:
        """Close the buffer, discarding queued messages and ending windows."""
        with self._lock:
            self.done = True
            self._file_bytes -= sum(record.file_bytes for record in self._queued.values())
            self._file_parts -= sum(1 for record in self._queued.values() if record.file_bytes)
            self._queued.clear()
            self._ids.clear()
            self._id_from_key.clear()
            self._ids_from_entity.clear()
            self._tombstones.clear()
            self._scope_requests.clear()
            self._file_condition.notify_all()
        try:
            self.event_loop.call_soon_threadsafe(self.message_event.set)
            self.event_loop.call_soon_threadsafe(self.flush_event.set)
        except RuntimeError:
            # The event loop may already be closed during teardown.
            pass

    def _ids_after_locked(self, cursor: int, through: int) -> Iterator[int]:
        # Removals may compact ``_ids`` during iteration; keep this generation.
        ids = self._ids
        for index in range(bisect_right(ids, cursor), len(ids)):
            if ids[index] > through:
                break
            if ids[index] in self._queued:
                yield ids[index]

    async def window_generator(self, client_id: int) -> AsyncGenerator[MessageWindow, None]:
        """Yield ordered windows for one client until the buffer closes.

        A scope request first drains earlier global messages, then sends its
        begin message, the scope's retained messages and its ready message, all
        on this one ordered stream; live messages of other scopes are skipped.
        """
        self.register_client(client_id)
        cursor = -1
        scope: str | None = None
        applied_revision = 0
        replay: _ScopeReplay | None = None
        flush_wait = self.event_loop.create_task(self.flush_event.wait())
        try:
            while not self.done:
                records: list[QueuedMessage] = []
                size = 0
                file_bytes = 0
                file_parts = 0

                def fits(record: QueuedMessage) -> bool:
                    return not records or (
                        len(records) < self.max_window_size
                        and size + len(record.data) <= _WINDOW_MAX_BYTES
                    )

                with self._lock:
                    high_water = self._next_id - 1
                    if self.atomic_counter == 0:
                        request = self._scope_requests.get(client_id)
                        revision = applied_revision if replay is None else replay.request.revision
                        if request is not None and request.revision != revision:
                            global_ids = [
                                message_id
                                for message_id in self._ids_after_locked(cursor, high_water)
                                if self._queued[message_id].delivery_scope is None
                                and self._queued[message_id].excluded_client != client_id
                            ]
                            scope_ids = [
                                message_id
                                for message_id in self._ids_after_locked(-1, high_water)
                                if self._queued[message_id].delivery_scope == request.scope
                                and self._queued[message_id].excluded_client != client_id
                            ]
                            replay = _ScopeReplay(
                                request,
                                high_water,
                                [*global_ids, request.begin, *scope_ids, request.ready],
                                len(global_ids),
                            )

                        if replay is not None:
                            while replay.index < len(replay.items):
                                item = replay.items[replay.index]
                                record = self._queued.get(item) if isinstance(item, int) else item
                                if record is not None:
                                    if not fits(record):
                                        break
                                    records.append(record)
                                    size += len(record.data)
                                replay.index += 1
                                if isinstance(item, int) and replay.index <= replay.global_items:
                                    cursor = item
                            if replay.index >= replay.global_items:
                                cursor = max(cursor, replay.cutoff)
                            if replay.index == len(replay.items):
                                scope = replay.request.scope
                                applied_revision = replay.request.revision
                                replay = None
                        else:
                            for message_id in self._ids_after_locked(cursor, high_water):
                                record = self._queued[message_id]
                                skipped = record.excluded_client == client_id or (
                                    record.delivery_scope is not None
                                    and record.delivery_scope != scope
                                )
                                if not skipped:
                                    if not fits(record):
                                        break
                                    records.append(record)
                                    size += len(record.data)
                                    if record.file_bytes:
                                        file_bytes += record.file_bytes
                                        file_parts += 1
                                if not self.persistent_messages:
                                    self._remove_locked(message_id)
                                cursor = message_id
                            else:
                                cursor = high_water

                should_wait_for_window = not records or (replay is None and high_water == cursor)
                if records:
                    yield MessageWindow(tuple(records), cursor, file_bytes, file_parts)
                else:
                    if cursor >= 0:
                        self.mark_messages_sent(client_id, cursor)
                    await self.message_event.wait()
                    self.message_event.clear()

                if should_wait_for_window:
                    completed, _ = await asyncio.wait(
                        [flush_wait], timeout=self.window_duration_sec
                    )
                    if flush_wait in completed and not self.done:
                        self.flush_event.clear()
                        flush_wait = self.event_loop.create_task(self.flush_event.wait())
        finally:
            self.unregister_client(client_id)
            flush_wait.cancel()
            try:
                await flush_wait
            except asyncio.CancelledError:
                pass
