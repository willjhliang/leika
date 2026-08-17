from __future__ import annotations

import asyncio
import dataclasses
import itertools
import math
import threading
from asyncio.events import AbstractEventLoop
from typing import Any, AsyncGenerator, Dict, List, Sequence

from ._messages import Message

_FILE_TRANSFER_BUFFER_BYTES = 8 * 1024 * 1024
"""Maximum queued file payload per client."""

_FILE_TRANSFER_BUFFER_PARTS = 256
"""Maximum queued and in-flight file-part objects per client."""

_CONNECTION_MESSAGE_BUFFER_MAX = 1024
"""Maximum connection-local messages, independent of payload byte size."""

_CONNECTION_MESSAGE_BUFFER_MAX_METADATA_BYTES = 256 * 1024 * 1024
_CONNECTION_MESSAGE_BUFFER_MAX_RAW_BYTES = 512 * 1024 * 1024
_PERSISTENT_MESSAGE_BUFFER_MAX = 65_536
_PERSISTENT_MESSAGE_BUFFER_MAX_METADATA_BYTES = 256 * 1024 * 1024
_PERSISTENT_MESSAGE_BUFFER_MAX_RAW_BYTES = 512 * 1024 * 1024
"""Aggregate retained-message bounds; replacements are charged by net size."""

_OUTGOING_METADATA_LIMIT_BYTES = 256 * 1024 * 1024
_OUTGOING_FRAME_LIMIT_BYTES = 512 * 1024 * 1024
_OUTGOING_BINARY_BUFFER_LIMIT = 16_384
_OUTGOING_DECODED_NODE_LIMIT = 500_000
"""Whole-batch traversal ceiling enforced by the bundled browser."""

_PREPARATION_OWNER_MAX = 1
_PREPARATION_METADATA_MAX_BYTES = 256 * 1024 * 1024
_PREPARATION_RAW_MAX_BYTES = 512 * 1024 * 1024
_PREPARATION_MESSAGE_OVERHEAD_BYTES = 256
_PREPARATION_METADATA_OWNER_BYTES = _PREPARATION_METADATA_MAX_BYTES
_PREPARATION_RAW_OWNER_BYTES = _PREPARATION_RAW_MAX_BYTES
"""Bound immutable snapshots being copied and measured before queue admission."""

# Conservative encoded envelope overhead. The empty envelope already carries
# its map keys and float timestamp. Replacing its two empty array headers with
# their largest MsgPack headers costs at most eight more bytes; each binary
# length is conservatively charged as a 64-bit integer.
_EMPTY_ENVELOPE_METADATA_BYTES = 55
_ENVELOPE_ARRAY_HEADER_GROWTH_BYTES = 8
_ENCODED_BINARY_LENGTH_MAX_BYTES = 9
_FRAME_HEADER_BYTES = 16


def _metadata_envelope_upper_bound(message_bytes: int, binary_buffers: int) -> int:
    """Conservatively bound the decoded MsgPack envelope size."""
    return (
        _EMPTY_ENVELOPE_METADATA_BYTES
        + _ENVELOPE_ARRAY_HEADER_GROWTH_BYTES
        + message_bytes
        + binary_buffers * _ENCODED_BINARY_LENGTH_MAX_BYTES
    )


def _zstd_compress_bound(size: int) -> int:
    """The public ZSTD_COMPRESSBOUND formula from the zstd API."""
    return size + (size >> 8) + (((128 << 10) - size) >> 11 if size < 128 << 10 else 0)


def _frame_upper_bound(metadata_bytes: int, raw_binary_bytes: int) -> int:
    return _FRAME_HEADER_BYTES + _zstd_compress_bound(metadata_bytes) + raw_binary_bytes


@dataclasses.dataclass(frozen=True)
class _PreparedMessage:
    """Immutable queued record with admission and routing metadata."""

    message: Message
    serialized_size: tuple[int, int, int]
    decoded_nodes: int
    delivery_scope: str | None
    redundancy_key: str | None
    purge_entities: frozenset[tuple[str, object]]


@dataclasses.dataclass(frozen=True)
class _DeliveryScopeRequest:
    """Latest page-like stream requested by one connected client."""

    revision: int
    scope: str
    begin_message: Message
    ready_message: Message


@dataclasses.dataclass(frozen=True)
class MessageWindow:
    """One outgoing batch and the file capacity it owns until sent."""

    messages: Sequence[Message]
    file_bytes_reserved: int = 0
    file_parts_reserved: int = 0
    last_message_id: int = -1


@dataclasses.dataclass
class AsyncMessageBuffer:
    """Async iterable for keeping a persistent buffer of messages.

    Uses heuristics on message names to automatically cull out redundant messages."""

    event_loop: AbstractEventLoop
    persistent_messages: bool
    message_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    flush_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)

    message_counter: int = 0
    message_from_id: Dict[int, Message] = dataclasses.field(default_factory=dict)
    id_from_redundancy_key: Dict[str, int] = dataclasses.field(default_factory=dict)
    _file_bytes_from_id: Dict[int, int] = dataclasses.field(default_factory=dict, init=False)
    _serialized_size_from_id: Dict[int, tuple[int, int, int]] = dataclasses.field(
        default_factory=dict, init=False
    )
    _decoded_nodes_from_id: Dict[int, int] = dataclasses.field(default_factory=dict, init=False)
    _delivery_scope_from_id: Dict[int, str | None] = dataclasses.field(
        default_factory=dict, init=False
    )
    _batch_insert_no_close: bool = dataclasses.field(default=False, init=False)
    _batch_insert_no_schedule: bool = dataclasses.field(default=False, init=False)
    _queued_metadata_bytes: int = dataclasses.field(default=0, init=False)
    _queued_raw_binary_bytes: int = dataclasses.field(default=0, init=False)
    _preparation_owners: int = dataclasses.field(default=0, init=False)
    _preparation_metadata_bytes: int = dataclasses.field(default=0, init=False)
    _preparation_raw_bytes: int = dataclasses.field(default=0, init=False)
    _preparation_local: threading.local = dataclasses.field(
        default_factory=threading.local, init=False, repr=False
    )

    buffer_lock: threading.RLock = dataclasses.field(default_factory=threading.RLock)
    """Lock to prevent race conditions when pushing messages from different threads."""

    max_window_size: int = 128
    window_duration_sec: float = 1.0 / 60.0
    done: bool = False
    atomic_counter: int = 0
    overload_reason: str | None = dataclasses.field(default=None, init=False)

    _file_bytes_reserved: int = dataclasses.field(default=0, init=False)
    _file_parts_reserved: int = dataclasses.field(default=0, init=False)
    _file_bytes_condition: threading.Condition = dataclasses.field(init=False)
    _preparation_condition: threading.Condition = dataclasses.field(init=False)
    _message_signal_scheduled: bool = dataclasses.field(default=False, init=False)
    _flush_signal_scheduled: bool = dataclasses.field(default=False, init=False)
    _sent_message_id_from_client: Dict[int, int] = dataclasses.field(
        default_factory=dict, init=False
    )
    _delivery_scope_revision: int = dataclasses.field(default=0, init=False)
    _delivery_scope_request_from_client: Dict[int, _DeliveryScopeRequest] = dataclasses.field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        if type(self.max_window_size) is not int or self.max_window_size <= 0:
            raise ValueError("max_window_size must be a positive integer")
        if (
            isinstance(self.window_duration_sec, bool)
            or not isinstance(self.window_duration_sec, (int, float))
            or not math.isfinite(self.window_duration_sec)
            or self.window_duration_sec < 0
        ):
            raise ValueError("window_duration_sec must be a finite non-negative number")
        self._file_bytes_condition = threading.Condition(self.buffer_lock)
        self._preparation_condition = threading.Condition(self.buffer_lock)

    def reserve_file_bytes(self, size: int) -> bool:
        """Reserve outgoing file capacity, blocking until it is available.

        Returns ``False`` when shutdown or disconnect makes the reservation
        impossible. Capacity remains reserved through websocket serialization
        and send, not merely until the message is removed from this buffer.
        """
        if not 0 <= size <= _FILE_TRANSFER_BUFFER_BYTES:
            raise ValueError(f"size must be between 0 and {_FILE_TRANSFER_BUFFER_BYTES} bytes")
        with self._file_bytes_condition:
            while not self.done and (
                self._file_bytes_reserved + size > _FILE_TRANSFER_BUFFER_BYTES
                or self._file_parts_reserved >= _FILE_TRANSFER_BUFFER_PARTS
            ):
                self._file_bytes_condition.wait()
            if self.done:
                return False
            self._file_bytes_reserved += size
            self._file_parts_reserved += 1
            return True

    def release_file_bytes(self, size: int, parts: int = 1) -> None:
        """Release successful or failed outgoing file reservations."""
        with self._file_bytes_condition:
            if not 0 <= size <= self._file_bytes_reserved:
                raise RuntimeError("file byte reservation accounting underflow")
            if not 0 <= parts <= self._file_parts_reserved:
                raise RuntimeError("file part reservation accounting underflow")
            self._file_bytes_reserved -= size
            self._file_parts_reserved -= parts
            self._file_bytes_condition.notify_all()

    def file_transfer_must_be_deferred(self) -> bool:
        """Whether a synchronous transfer would block its own message drain."""
        with self.buffer_lock:
            return self.atomic_counter > 0

    def _set_message_event(self) -> None:
        """Pulse the asyncio event from its owning event-loop thread."""
        with self.buffer_lock:
            self._message_signal_scheduled = False
        self.message_event.set()

    def _schedule_message_event_locked(self) -> None:
        """Schedule one coalesced pulse while ``buffer_lock`` is held."""
        if self._message_signal_scheduled:
            return
        self._message_signal_scheduled = True
        try:
            self.event_loop.call_soon_threadsafe(self._set_message_event)
        except RuntimeError:
            self._message_signal_scheduled = False
            raise

    def push(self, message: Message) -> bool:
        """Push an ordinary message, returning whether its connection is open."""
        return self._push(message, file_bytes_reserved=0)

    def push_many(self, messages: Sequence[Message]) -> bool:
        """Atomically validate, snapshot, and queue an ordinary message batch."""
        self._enter_preparation_call()
        try:
            return self._push_many_impl(messages)
        finally:
            self._leave_preparation_call()

    def _push_many_impl(self, messages: Sequence[Message]) -> bool:
        """Prepare and atomically insert an ordinary batch."""
        requested_count = len(messages)
        preparation_limit = (
            _PERSISTENT_MESSAGE_BUFFER_MAX
            if self.persistent_messages
            else _CONNECTION_MESSAGE_BUFFER_MAX
        )
        if requested_count > preparation_limit:
            raise RuntimeError(
                f"message batch exceeds the {preparation_limit}-entry preparation limit"
            )
        requested = tuple(itertools.islice(iter(messages), preparation_limit + 1))
        if len(requested) != requested_count:
            raise RuntimeError("message sequence length changed during admission")
        if not requested:
            return not self.done

        estimates = tuple(self._preparation_estimate(message) for message in requested)
        if sum(estimate[0] for estimate in estimates) > _PREPARATION_METADATA_MAX_BYTES:
            raise RuntimeError("message batch preparation exceeds the metadata safety limit")
        if sum(estimate[1] for estimate in estimates) > _PREPARATION_RAW_MAX_BYTES:
            raise RuntimeError("message batch preparation exceeds the binary safety limit")
        reservation = self._acquire_preparation(len(requested))
        if reservation is None:
            return False
        try:
            batch: list[_PreparedMessage] = []
            cumulative_metadata = 0
            cumulative_raw = 0
            for message, estimate in zip(requested, estimates):
                prepared = self._prepare_message(message, estimate)
                cumulative_metadata += prepared.serialized_size[0]
                cumulative_raw += prepared.serialized_size[1]
                if cumulative_metadata > _PREPARATION_METADATA_MAX_BYTES:
                    raise RuntimeError(
                        "message batch preparation exceeds the metadata safety limit"
                    )
                if cumulative_raw > _PREPARATION_RAW_MAX_BYTES:
                    raise RuntimeError("message batch preparation exceeds the binary safety limit")
                batch.append(prepared)

            with self.buffer_lock:
                if self.done:
                    return False
                state_snapshot = (
                    self.message_counter,
                    self.message_from_id.copy(),
                    self.id_from_redundancy_key.copy(),
                    self._serialized_size_from_id.copy(),
                    self._decoded_nodes_from_id.copy(),
                    self._delivery_scope_from_id.copy(),
                    self._file_bytes_from_id.copy(),
                    self._file_bytes_reserved,
                    self._file_parts_reserved,
                    self._queued_metadata_bytes,
                    self._queued_raw_binary_bytes,
                    self.overload_reason,
                )
                try:
                    self._batch_insert_no_close = True
                    self._batch_insert_no_schedule = True
                    for prepared_message in batch:
                        if not self._insert_prepared_locked(
                            prepared_message,
                            file_bytes_reserved=0,
                        ):
                            self._restore_batch_state_locked(state_snapshot)
                            return False
                    self._batch_insert_no_close = False
                    self._batch_insert_no_schedule = False
                    if self.atomic_counter == 0:
                        self._schedule_message_event_locked()
                except BaseException:
                    self._restore_batch_state_locked(state_snapshot)
                    raise
                return True
        finally:
            self._release_preparation(reservation)

    def _restore_batch_state_locked(self, state: tuple[Any, ...]) -> None:
        """Restore one insertion transaction after a false return or exception."""
        (
            self.message_counter,
            self.message_from_id,
            self.id_from_redundancy_key,
            self._serialized_size_from_id,
            self._decoded_nodes_from_id,
            self._delivery_scope_from_id,
            self._file_bytes_from_id,
            self._file_bytes_reserved,
            self._file_parts_reserved,
            self._queued_metadata_bytes,
            self._queued_raw_binary_bytes,
            self.overload_reason,
        ) = state
        self._batch_insert_no_close = False
        self._batch_insert_no_schedule = False
        self._file_bytes_condition.notify_all()

    def push_reserved_file_message(self, message: Message, size: int) -> bool:
        """Queue a file message whose capacity was reserved by its producer."""
        if self.persistent_messages:
            raise RuntimeError("file reservations require a connection-local buffer")
        if size <= 0:
            raise ValueError("file reservation size must be positive")
        if message.excluded_self_client is not None:
            raise ValueError("reserved file messages cannot exclude their destination")
        return self._push(message, file_bytes_reserved=size)

    def register_client(self, client_id: int) -> None:
        """Include a connected client in persistent-message delivery tracking."""
        if not self.persistent_messages:
            return
        with self.buffer_lock:
            self._sent_message_id_from_client.setdefault(client_id, -1)

    def unregister_client(self, client_id: int) -> None:
        """Stop tracking a disconnected client and prune newly safe tombstones."""
        if not self.persistent_messages:
            return
        with self.buffer_lock:
            self._sent_message_id_from_client.pop(client_id, None)
            self._prune_delivered_tombstones_locked()
            self._delivery_scope_request_from_client.pop(client_id, None)

    def request_delivery_scope(
        self,
        client_id: int,
        scope: str,
        begin_message: Message,
        ready_message: Message,
    ) -> bool:
        """Replace one client's active retained scope without copying payloads."""

        if not self.persistent_messages:
            raise RuntimeError("delivery scopes require a persistent message buffer")
        if type(scope) is not str or not scope:
            raise ValueError("delivery scope must be a non-empty string")

        controls = (begin_message, ready_message)
        self._enter_preparation_call()
        try:
            estimates = tuple(self._preparation_estimate(message) for message in controls)
            if sum(estimate[0] for estimate in estimates) > _PREPARATION_METADATA_MAX_BYTES:
                raise RuntimeError("delivery control preparation exceeds the metadata safety limit")
            if sum(estimate[1] for estimate in estimates) > _PREPARATION_RAW_MAX_BYTES:
                raise RuntimeError("delivery control preparation exceeds the binary safety limit")
            reservation = self._acquire_preparation(len(controls))
            if reservation is None:
                return False
            try:
                prepared_controls = tuple(
                    self._prepare_message(message, estimate)
                    for message, estimate in zip(controls, estimates)
                )
            finally:
                self._release_preparation(reservation)
        finally:
            self._leave_preparation_call()

        if any(control.delivery_scope is not None for control in prepared_controls):
            raise ValueError("delivery stream control messages must be global")
        begin_snapshot, ready_snapshot = (control.message for control in prepared_controls)
        with self.buffer_lock:
            if self.done or client_id not in self._sent_message_id_from_client:
                return False
            if self.atomic_counter == 0:
                self._schedule_message_event_locked()
            self._delivery_scope_revision += 1
            self._delivery_scope_request_from_client[client_id] = _DeliveryScopeRequest(
                revision=self._delivery_scope_revision,
                scope=scope,
                begin_message=begin_snapshot,
                ready_message=ready_snapshot,
            )
            return True

    def delivery_scope_from_client(self, client_id: int) -> str | None:
        """Return the latest retained scope requested by one client."""

        if not self.persistent_messages:
            raise RuntimeError("delivery scopes require a persistent message buffer")
        with self.buffer_lock:
            request = self._delivery_scope_request_from_client.get(client_id)
            return None if request is None else request.scope

    def mark_messages_sent(self, client_id: int, last_message_id: int) -> None:
        """Record a successful persistent send through last_message_id."""
        if not self.persistent_messages:
            return
        with self.buffer_lock:
            previous = self._sent_message_id_from_client.get(client_id)
            if previous is None:
                return
            if last_message_id < previous:
                raise RuntimeError("persistent message delivery cursor moved backwards")
            if last_message_id >= self.message_counter:
                raise RuntimeError("persistent message delivery cursor is out of range")
            self._sent_message_id_from_client[client_id] = last_message_id
            self._prune_delivered_tombstones_locked()

    def _prune_delivered_tombstones_locked(self) -> None:
        """Drop removes no current client still needs, with buffer_lock held.

        A future client needs the surviving state, never the history saying an
        entity no longer exists. Current clients do need that history until a
        websocket send containing it succeeds, so the minimum successful-send
        cursor is the only safe collection boundary.
        """
        if not self.persistent_messages:
            return
        delivered_through = (
            min(self._sent_message_id_from_client.values())
            if self._sent_message_id_from_client
            else self.message_counter - 1
        )
        for message_id, message in tuple(self.message_from_id.items()):
            if message_id > delivered_through or message.lifecycle_phase != "remove":
                continue
            self._remove_message_locked(message_id, release_file_reservation=True)

    def _enter_preparation_call(self) -> None:
        """Reject same-thread reentry before it can wait on its own reservation."""
        active = getattr(self._preparation_local, "buffer_ids", None)
        if active is None:
            active = set()
            self._preparation_local.buffer_ids = active
        identity = id(self)
        if identity in active:
            raise RuntimeError("message preparation cannot re-enter the same buffer")
        active.add(identity)

    def _leave_preparation_call(self) -> None:
        active = getattr(self._preparation_local, "buffer_ids", None)
        if active is None or id(self) not in active:
            raise RuntimeError("message preparation reentrancy accounting underflow")
        active.remove(id(self))

    def _preparation_estimate(self, message: Message) -> tuple[int, int]:
        """Validate one caller-owned graph and conservatively size its copy."""
        if not isinstance(message, Message):
            raise TypeError("message must be a Message instance.")
        nodes, metadata, raw, buffers = message._validated_source_metrics()
        return (
            metadata + nodes * 256 + _PREPARATION_MESSAGE_OVERHEAD_BYTES,
            raw + 7 * buffers,
        )

    def _acquire_preparation(self, message_count: int) -> tuple[int, int] | None:
        """Own worst-case copy capacity, or return None after shutdown.

        Caller-owned fields may mutate after source validation. A per-message
        worst-case reservation, capped by the aggregate envelope, is therefore
        the only safe bound before deepcopy; source-derived estimates are used
        solely to reject an already-oversized batch without copying.
        """
        metadata = _PREPARATION_METADATA_OWNER_BYTES
        raw = _PREPARATION_RAW_OWNER_BYTES
        if message_count <= 0:
            raise ValueError("preparation requires at least one message")
        with self._preparation_condition:
            while not self.done and (
                self._preparation_owners >= _PREPARATION_OWNER_MAX
                or self._preparation_metadata_bytes + metadata > _PREPARATION_METADATA_MAX_BYTES
                or self._preparation_raw_bytes + raw > _PREPARATION_RAW_MAX_BYTES
            ):
                self._preparation_condition.wait()
            if self.done:
                return None
            self._preparation_owners += 1
            self._preparation_metadata_bytes += metadata
            self._preparation_raw_bytes += raw
            return metadata, raw

    def _release_preparation(self, reservation: tuple[int, int]) -> None:
        metadata, raw = reservation
        with self._preparation_condition:
            self._preparation_owners -= 1
            self._preparation_metadata_bytes -= metadata
            self._preparation_raw_bytes -= raw
            if (
                self._preparation_owners < 0
                or self._preparation_metadata_bytes < 0
                or self._preparation_raw_bytes < 0
            ):
                raise RuntimeError("message preparation accounting underflow")
            self._preparation_condition.notify_all()

    def _prepare_message(self, message: Message, estimate: tuple[int, int]) -> _PreparedMessage:
        """Copy and measure a message while its pre-copy reservation is owned."""
        # Identity keys must be materialized before copying. Payload-derived
        # keys are recomputed from the snapshot so an earlier cache cannot be
        # inconsistent with fields the caller changed before admission.
        if message.redundancy_key_is_identity:
            message.redundancy_key()
        snapshot = message._bounded_transport_snapshot(
            metadata_limit=estimate[0],
            raw_limit=estimate[1],
        )
        if not snapshot.redundancy_key_is_identity:
            try:
                object.__delattr__(snapshot, "_cached_redundancy_key")
            except AttributeError:
                pass

        metadata_size, raw_binary_size, binary_buffer_count, decoded_nodes = (
            snapshot.serialized_metrics_upper_bound()
        )
        if metadata_size > estimate[0] or raw_binary_size > estimate[1]:
            raise ValueError("message grew while its immutable snapshot was prepared")
        serialized_size = metadata_size, raw_binary_size, binary_buffer_count
        envelope_size = _metadata_envelope_upper_bound(metadata_size, binary_buffer_count)
        if envelope_size > _OUTGOING_METADATA_LIMIT_BYTES:
            raise ValueError("message metadata exceeds the client size limit")
        if _frame_upper_bound(envelope_size, raw_binary_size) > _OUTGOING_FRAME_LIMIT_BYTES:
            raise ValueError("message frame exceeds the client size limit")
        if binary_buffer_count > _OUTGOING_BINARY_BUFFER_LIMIT:
            raise ValueError("message contains too many binary buffers")
        if 1 + decoded_nodes > _OUTGOING_DECODED_NODE_LIMIT:
            raise ValueError("message decoded structure exceeds the client traversal limit")

        lifecycle_phases = ("create", "remove", "update_dict", "update_simple")
        if (
            snapshot.lifecycle_phase in lifecycle_phases
            and snapshot.entity_type is not None
            and snapshot.entity_id_field is not None
        ):
            entity_id = snapshot.lifecycle_entity_id()
            try:
                hash((snapshot.entity_type, entity_id))
            except TypeError as error:
                raise TypeError("message lifecycle entity identifiers must be hashable") from error

        raw_purge_entities = snapshot.purge_entities()
        if type(raw_purge_entities) is not tuple:
            raise TypeError("purge_entities() must return a tuple of entity pairs")
        purge_entities: set[tuple[str, object]] = set()
        for entity in raw_purge_entities:
            if type(entity) is not tuple or len(entity) != 2 or type(entity[0]) is not str:
                raise TypeError("purge_entities() must return (entity type, identifier) pairs")
            try:
                purge_entities.add(entity)
            except TypeError as error:
                raise TypeError("purged entity identifiers must be hashable") from error

        delivery_scope = snapshot.delivery_scope()
        if delivery_scope is not None and type(delivery_scope) is not str:
            raise TypeError("delivery_scope() must return None or a non-empty string")
        if delivery_scope == "":
            raise ValueError("delivery_scope() must return None or a non-empty string")

        return _PreparedMessage(
            snapshot,
            serialized_size,
            decoded_nodes,
            delivery_scope,
            snapshot.redundancy_key(),
            frozenset(purge_entities),
        )

    def _remove_message_locked(
        self, message_id: int, *, release_file_reservation: bool
    ) -> tuple[Message, int]:
        """Remove one retained message and update every ownership counter."""
        message = self.message_from_id.pop(message_id)
        metadata, raw, _ = self._serialized_size_from_id.pop(message_id)
        self._decoded_nodes_from_id.pop(message_id)
        self._delivery_scope_from_id.pop(message_id)
        self._queued_metadata_bytes -= metadata
        self._queued_raw_binary_bytes -= raw
        if self._queued_metadata_bytes < 0 or self._queued_raw_binary_bytes < 0:
            raise RuntimeError("queued message byte accounting underflow")

        reservation = self._file_bytes_from_id.pop(message_id, 0)
        if reservation and release_file_reservation:
            self._file_bytes_reserved -= reservation
            self._file_parts_reserved -= 1
            self._file_bytes_condition.notify_all()
            reservation = 0

        redundancy_key = message.redundancy_key()
        if (
            redundancy_key is not None
            and self.id_from_redundancy_key.get(redundancy_key) == message_id
        ):
            self.id_from_redundancy_key.pop(redundancy_key)
        return message, reservation

    def _reject_connection_overload_locked(self) -> bool:
        self.overload_reason = "Outgoing message backlog exceeded the safety limit."
        self._set_done_locked()
        try:
            self.event_loop.call_soon_threadsafe(self.message_event.set)
            self.event_loop.call_soon_threadsafe(self.flush_event.set)
        except RuntimeError:
            pass
        return False

    def _insert_prepared_locked(
        self,
        prepared: _PreparedMessage,
        *,
        file_bytes_reserved: int,
    ) -> bool:
        """Insert prepared state while the buffer lock is held."""
        if self.done:
            return False

        message = prepared.message
        redundancy_key = prepared.redundancy_key
        removal_ids: set[int] = set()
        if redundancy_key is not None:
            old_message_id = self.id_from_redundancy_key.get(redundancy_key)
            if old_message_id is not None:
                removal_ids.add(old_message_id)
        if prepared.purge_entities:
            for message_id, queued in self.message_from_id.items():
                if (
                    queued.lifecycle_phase in ("create", "remove", "update_dict", "update_simple")
                    and queued.entity_type is not None
                    and queued.entity_id_field is not None
                    and (
                        queued.entity_type,
                        queued.lifecycle_entity_id(),
                    )
                    in prepared.purge_entities
                ):
                    removal_ids.add(message_id)

        removed_metadata = 0
        removed_raw = 0
        for message_id in removal_ids:
            metadata, raw, _ = self._serialized_size_from_id[message_id]
            removed_metadata += metadata
            removed_raw += raw
        metadata, raw, _ = prepared.serialized_size
        entry_count = len(self.message_from_id) - len(removal_ids) + 1
        metadata_bytes = self._queued_metadata_bytes - removed_metadata + metadata
        raw_bytes = self._queued_raw_binary_bytes - removed_raw + raw

        if self.persistent_messages:
            if (
                entry_count > _PERSISTENT_MESSAGE_BUFFER_MAX
                or metadata_bytes > _PERSISTENT_MESSAGE_BUFFER_MAX_METADATA_BYTES
                or raw_bytes > _PERSISTENT_MESSAGE_BUFFER_MAX_RAW_BYTES
            ):
                raise RuntimeError("persistent message backlog exceeded the safety limit")
        elif (
            entry_count > _CONNECTION_MESSAGE_BUFFER_MAX
            or metadata_bytes > _CONNECTION_MESSAGE_BUFFER_MAX_METADATA_BYTES
            or raw_bytes > _CONNECTION_MESSAGE_BUFFER_MAX_RAW_BYTES
        ):
            if not self._batch_insert_no_close:
                return self._reject_connection_overload_locked()
            return False

        # Schedule before mutation. A closed loop leaves the old coalesced or
        # purged state and every byte counter untouched.
        if not self._batch_insert_no_schedule and self.atomic_counter == 0:
            self._schedule_message_event_locked()

        for message_id in removal_ids:
            self._remove_message_locked(message_id, release_file_reservation=True)

        new_message_id = self.message_counter
        self.message_from_id[new_message_id] = message
        self._serialized_size_from_id[new_message_id] = prepared.serialized_size
        self._decoded_nodes_from_id[new_message_id] = prepared.decoded_nodes
        self._delivery_scope_from_id[new_message_id] = prepared.delivery_scope
        self._queued_metadata_bytes += metadata
        self._queued_raw_binary_bytes += raw
        if file_bytes_reserved:
            self._file_bytes_from_id[new_message_id] = file_bytes_reserved
        self.message_counter += 1
        if redundancy_key is not None:
            self.id_from_redundancy_key[redundancy_key] = new_message_id

        self._prune_delivered_tombstones_locked()
        return True

    def _push(self, message: Message, *, file_bytes_reserved: int) -> bool:
        self._enter_preparation_call()
        try:
            estimate = self._preparation_estimate(message)
            reservation = self._acquire_preparation(1)
            if reservation is None:
                return False
            try:
                prepared = self._prepare_message(message, estimate)
                with self.buffer_lock:
                    return self._insert_prepared_locked(
                        prepared, file_bytes_reserved=file_bytes_reserved
                    )
            finally:
                self._release_preparation(reservation)
        finally:
            self._leave_preparation_call()

    def atomic_start(self) -> None:
        """Start an atomic block. No new messages/windows should be sent."""
        # Locked: `atomic()` is public and may be entered from multiple threads,
        # and `+=`/`-=` are non-atomic read-modify-writes. A lost update would
        # leave the counter stuck != 0 and stall message delivery permanently.
        with self.buffer_lock:
            self.atomic_counter += 1

    def atomic_end(self) -> None:
        """End an atomic block."""
        with self.buffer_lock:
            if self.atomic_counter == 0:
                raise RuntimeError("atomic_end() called without a matching atomic_start()")
            self.atomic_counter -= 1
            if self.atomic_counter == 0 and not self.done:
                self._schedule_message_event_locked()

    def _set_flush_event(self) -> None:
        """Pulse the flush event from its owning loop and release coalescing."""
        with self.buffer_lock:
            self._flush_signal_scheduled = False
        self.flush_event.set()

    def flush(self) -> None:
        """Request immediate windowing, coalescing concurrent pulses."""
        with self.buffer_lock:
            if self.done or self._flush_signal_scheduled:
                return
            self._flush_signal_scheduled = True
            try:
                self.event_loop.call_soon_threadsafe(self._set_flush_event)
            except RuntimeError:
                self._flush_signal_scheduled = False
                raise

    def _set_done_locked(self) -> None:
        """Mark done and release queued reservations with the buffer lock held."""
        self.done = True
        self.message_from_id.clear()
        self.id_from_redundancy_key.clear()
        self._serialized_size_from_id.clear()
        self._decoded_nodes_from_id.clear()
        self._delivery_scope_from_id.clear()
        self._delivery_scope_request_from_client.clear()
        self._queued_metadata_bytes = 0
        self._queued_raw_binary_bytes = 0
        if not self.persistent_messages:
            self._file_bytes_reserved -= sum(self._file_bytes_from_id.values())
            self._file_parts_reserved -= len(self._file_bytes_from_id)
            self._file_bytes_from_id.clear()
        self._file_bytes_condition.notify_all()
        self._preparation_condition.notify_all()

    def set_done(self) -> None:
        """Set the done flag. Kills the generator."""
        with self._file_bytes_condition:
            self._set_done_locked()

        try:
            # Pulse message event to make sure we aren't waiting for a new message.
            self.event_loop.call_soon_threadsafe(self.message_event.set)

            # Pulse flush event to skip any windowing delay.
            self.event_loop.call_soon_threadsafe(self.flush_event.set)
        except RuntimeError:
            # Event loop may already be closed during teardown.
            pass

    async def _persistent_window_generator(
        self, client_id: int
    ) -> AsyncGenerator[MessageWindow, None]:
        """Yield global state plus one replaceable retained delivery scope.

        Begin, replay, Ready, and live payload stay on this one ordered producer.
        """

        self.register_client(client_id)
        last_sent_id = -1
        active_scope: str | None = None
        applied_revision = 0
        replay_request: _DeliveryScopeRequest | None = None
        replay_cutoff = -1
        replay_message_ids: tuple[int, ...] = ()
        replay_index = 0
        replay_phase = "idle"
        flush_wait = self.event_loop.create_task(self.flush_event.wait())
        try:
            while not self.done:
                window: List[Message] = []
                message: Message | None = None
                metadata_total = 0
                raw_total = 0
                binary_buffer_total = 0
                decoded_nodes_total = 1

                def append_candidate(
                    message: Message,
                    serialized_size: tuple[int, int, int],
                    decoded_nodes: int,
                ) -> bool:
                    nonlocal metadata_total
                    nonlocal raw_total
                    nonlocal binary_buffer_total
                    nonlocal decoded_nodes_total
                    metadata, raw, binary_count = serialized_size
                    candidate_metadata = metadata_total + metadata
                    candidate_raw = raw_total + raw
                    candidate_binary_count = binary_buffer_total + binary_count
                    candidate_decoded_nodes = decoded_nodes_total + decoded_nodes
                    candidate_envelope = _metadata_envelope_upper_bound(
                        candidate_metadata, candidate_binary_count
                    )
                    if window and (
                        candidate_envelope > _OUTGOING_METADATA_LIMIT_BYTES
                        or _frame_upper_bound(candidate_envelope, candidate_raw)
                        > _OUTGOING_FRAME_LIMIT_BYTES
                        or candidate_binary_count > _OUTGOING_BINARY_BUFFER_LIMIT
                        or candidate_decoded_nodes > _OUTGOING_DECODED_NODE_LIMIT
                    ):
                        return False
                    window.append(message)
                    metadata_total = candidate_metadata
                    raw_total = candidate_raw
                    binary_buffer_total = candidate_binary_count
                    decoded_nodes_total = candidate_decoded_nodes
                    return True

                with self.buffer_lock:
                    high_water_message_id = self.message_counter - 1
                    atomic_active = self.atomic_counter > 0
                    if not atomic_active:
                        request = self._delivery_scope_request_from_client.get(client_id)
                        current_revision = (
                            replay_request.revision
                            if replay_request is not None
                            else applied_revision
                        )
                        if request is not None and request.revision != current_revision:
                            replay_request = request
                            replay_cutoff = high_water_message_id
                            replay_message_ids = tuple(
                                message_id
                                for message_id, message in self.message_from_id.items()
                                if message_id <= replay_cutoff
                                and message.excluded_self_client != client_id
                                and self._delivery_scope_from_id[message_id] == request.scope
                            )
                            replay_index = 0
                            replay_phase = "drain"

                        if replay_request is not None:
                            if replay_phase == "drain":
                                considered_through = last_sent_id
                                for message_id, message in self.message_from_id.items():
                                    if message_id <= last_sent_id:
                                        continue
                                    if message_id > replay_cutoff:
                                        break
                                    if (
                                        message.excluded_self_client == client_id
                                        or self._delivery_scope_from_id[message_id] is not None
                                    ):
                                        considered_through = message_id
                                        continue
                                    if not append_candidate(
                                        message,
                                        self._serialized_size_from_id[message_id],
                                        self._decoded_nodes_from_id[message_id],
                                    ):
                                        break
                                    considered_through = message_id
                                    if len(window) >= self.max_window_size:
                                        break
                                else:
                                    considered_through = replay_cutoff
                                last_sent_id = considered_through
                                if last_sent_id >= replay_cutoff:
                                    replay_phase = "begin"

                            if not window and replay_phase == "begin":
                                window.append(replay_request.begin_message)
                                replay_phase = "replay"

                            if not window and replay_phase == "replay":
                                while (
                                    replay_index < len(replay_message_ids)
                                    and len(window) < self.max_window_size
                                ):
                                    message_id = replay_message_ids[replay_index]
                                    message = self.message_from_id.get(message_id)
                                    if message is None:
                                        replay_index += 1
                                        continue
                                    if not append_candidate(
                                        message,
                                        self._serialized_size_from_id[message_id],
                                        self._decoded_nodes_from_id[message_id],
                                    ):
                                        break
                                    replay_index += 1
                                if replay_index >= len(replay_message_ids):
                                    replay_phase = "ready"

                            if not window and replay_phase == "ready":
                                window.append(replay_request.ready_message)
                                active_scope = replay_request.scope
                                applied_revision = replay_request.revision
                                replay_request = None
                                replay_message_ids = ()
                                replay_index = 0
                                replay_phase = "idle"
                        else:
                            considered_through = last_sent_id
                            for message_id, message in self.message_from_id.items():
                                if message_id <= last_sent_id:
                                    continue
                                if message_id > high_water_message_id:
                                    break
                                delivery_scope = self._delivery_scope_from_id[message_id]
                                if message.excluded_self_client == client_id or (
                                    delivery_scope is not None and delivery_scope != active_scope
                                ):
                                    considered_through = message_id
                                    continue
                                if not append_candidate(
                                    message,
                                    self._serialized_size_from_id[message_id],
                                    self._decoded_nodes_from_id[message_id],
                                ):
                                    break
                                considered_through = message_id
                                if len(window) >= self.max_window_size:
                                    break
                            else:
                                considered_through = high_water_message_id
                            last_sent_id = considered_through

                should_wait_for_window = not window or (
                    replay_request is None and high_water_message_id == last_sent_id
                )
                if window:
                    yield MessageWindow(tuple(window), last_message_id=last_sent_id)
                    window.clear()
                    message = None
                else:
                    if last_sent_id >= 0:
                        self.mark_messages_sent(client_id, last_sent_id)
                    message = None
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

    async def window_generator(self, client_id: int) -> AsyncGenerator[MessageWindow, None]:
        """Yield bounded message windows until the buffer is done."""
        if self.persistent_messages:
            generator = self._persistent_window_generator(client_id)
            try:
                async for persistent_window in generator:
                    yield persistent_window
                    del persistent_window
            finally:
                await generator.aclose()
            return
        self.register_client(client_id)
        last_sent_id = -1
        flush_wait = self.event_loop.create_task(self.flush_event.wait())
        try:
            while not self.done:
                window: List[Message] = []
                message: Message | None = None
                file_bytes_reserved = 0
                file_parts_reserved = 0
                metadata_total = 0
                raw_total = 0
                binary_buffer_total = 0
                decoded_nodes_total = 1  # Root messages array traversed by the browser.
                with self.buffer_lock:
                    most_recent_message_id = self.message_counter - 1
                    high_water_message_id = most_recent_message_id
                    atomic_active = self.atomic_counter > 0
                    if not atomic_active:
                        # Select, size, and remove under the same lock that
                        # atomic_start() acquires. The first individually valid
                        # message always fits; later messages defer to a window.
                        message_id = last_sent_id + 1
                        while (
                            message_id <= most_recent_message_id
                            and len(window) < self.max_window_size
                        ):
                            message = self.message_from_id.get(message_id)
                            if message is None:
                                last_sent_id = message_id
                                message_id += 1
                                continue
                            if message.excluded_self_client == client_id:
                                self._remove_message_locked(
                                    message_id, release_file_reservation=True
                                )
                                last_sent_id = message_id
                                message_id += 1
                                continue
                            metadata, raw, binary_count = self._serialized_size_from_id[message_id]
                            candidate_metadata = metadata_total + metadata
                            candidate_raw = raw_total + raw
                            candidate_binary_count = binary_buffer_total + binary_count
                            candidate_decoded_nodes = (
                                decoded_nodes_total + self._decoded_nodes_from_id[message_id]
                            )
                            candidate_envelope = _metadata_envelope_upper_bound(
                                candidate_metadata, candidate_binary_count
                            )
                            if window and (
                                candidate_envelope > _OUTGOING_METADATA_LIMIT_BYTES
                                or _frame_upper_bound(candidate_envelope, candidate_raw)
                                > _OUTGOING_FRAME_LIMIT_BYTES
                                or candidate_binary_count > _OUTGOING_BINARY_BUFFER_LIMIT
                                or candidate_decoded_nodes > _OUTGOING_DECODED_NODE_LIMIT
                            ):
                                break
                            _, reservation = self._remove_message_locked(
                                message_id, release_file_reservation=False
                            )
                            if reservation:
                                file_bytes_reserved += reservation
                                file_parts_reserved += 1
                            window.append(message)
                            metadata_total += metadata
                            raw_total += raw
                            binary_buffer_total += binary_count
                            decoded_nodes_total = candidate_decoded_nodes
                            last_sent_id = message_id
                            message_id += 1

                should_wait_for_window = not window or high_water_message_id == last_sent_id
                if window:
                    yield MessageWindow(
                        tuple(window),
                        file_bytes_reserved,
                        file_parts_reserved,
                        last_message_id=last_sent_id,
                    )
                    window.clear()
                    message = None
                else:
                    message = None
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
