from __future__ import annotations

import builtins
import contextlib
import contextvars
import dataclasses
import os
import threading
import time
from asyncio import AbstractEventLoop
from collections import deque
from collections.abc import Coroutine, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Sequence,
    TypeVar,
    cast,
    overload,
)

import numpy as np
from typing_extensions import Literal, LiteralString, assert_never

from . import _messages
from ._async_errors import print_async_errors, print_async_exception
from ._file_transfer import PREVIEW_MAX_BYTES, validate_file_display_name
from ._gui_handles import (
    CommandEvent,
    CommandHandle,
    FileContent,
    GuiButtonGroupHandle,
    GuiButtonHandle,
    GuiCheckboxHandle,
    GuiColorHandle,
    GuiDividerHandle,
    GuiDownloadButtonHandle,
    GuiDropdownHandle,
    GuiEvent,
    GuiFolderHandle,
    GuiFormHandle,
    GuiHtmlHandle,
    GuiImageHandle,
    GuiInputHandle,
    GuiListHandle,
    GuiModalHandle,
    GuiMultiSliderHandle,
    GuiNumberHandle,
    GuiPlaybackHandle,
    GuiPlotlyHandle,
    GuiPreviewButtonHandle,
    GuiProgressBarHandle,
    GuiSliderHandle,
    GuiTabGroupHandle,
    GuiTextHandle,
    GuiToggleGroupHandle,
    GuiUploadButtonHandle,
    GuiVectorHandle,
    GuiVideoControlsHandle,
    PlaybackEvent,
    UploadedFile,
    _file_content,
    _GuiFileButtonHandle,
    _GuiHandle,
    _GuiHandleState,
    _make_uuid,
)
from ._icons import svg_from_icon
from ._icons_enum import IconName
from ._image_encoding import _validate_image_encoding_options, prepare_image
from ._messages import ButtonColor, FileTransferPartAck
from ._notification_handle import NotificationHandle
from ._plotly import plotly_config, plotly_json, plotly_theme_templates
from ._validation import validate_finite_number as _validate_number
from ._validation import validate_nonnegative_integer as _validate_nonnegative_integer

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from ._client_handle import ClientHandle
    from ._server import Server
    from ._transport._websocket import ClientId

IntOrFloat = TypeVar("IntOrFloat", int, float)
TString = TypeVar("TString", bound=str)
TLiteralString = TypeVar("TLiteralString", bound=LiteralString)
THandle = TypeVar("THandle", bound=_GuiHandle)

_PreviewWorkKind = Literal["warm", "preview", "reload", "watch"]

_FILE_UPLOAD_MAX_BYTES = 64 * 1024 * 1024
"""Largest file a browser may upload."""

_FILE_UPLOAD_PART_BYTES = 512 * 1024
"""Exact upload part size, except for the final part."""

_PROTOCOL_IDENTIFIER_MAX_CHARS = 128
_MIME_TYPE_MAX_CHARS = 255
_PREVIEW_PENDING_PER_SOURCE_MAX = 32


def _valid_protocol_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= _PROTOCOL_IDENTIFIER_MAX_CHARS
        and all(32 <= ord(character) < 127 for character in value)
    )


def _valid_mime_type(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MIME_TYPE_MAX_CHARS
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


@dataclasses.dataclass(frozen=True)
class _PreviewWorkItem:
    """One preview operation, already scoped to its originating browser."""

    kind: _PreviewWorkKind
    client_id: ClientId
    client: ClientHandle
    handle: GuiPreviewButtonHandle
    run: Callable[[], None]


@dataclasses.dataclass
class _PreviewWorkState:
    """FIFO owned by one ``(client_id, source_uuid)`` pair."""

    pending: deque[_PreviewWorkItem] = dataclasses.field(default_factory=deque)
    active_kind: _PreviewWorkKind | None = None
    worker: Future[Any] | None = None


@dataclasses.dataclass
class _Upload:
    """One browser upload in progress."""

    handle: GuiUploadButtonHandle
    filename: str
    size: int
    content: bytearray = dataclasses.field(default_factory=bytearray)


def _compute_step(x: float | None) -> float:
    """For number inputs: compute an increment size from some number.

    Example inputs/outputs:
        100 => 1
        12 => 1
        12.1 => 0.1
        12.02 => 0.01
        0.004 => 0.001
    """
    return 1.0 if x is None else 10.0 ** (-_compute_precision_digits(x))


def _compute_precision_digits(x: float) -> int:
    """For number inputs: compute digits of precision from some number.

    Example inputs/outputs:
        100 => 0
        12 => 0
        12.1 => 1
        10.2 => 1
        0.007 => 3
    """
    digits = 0
    while x != round(x, ndigits=digits) and digits < 7:
        digits += 1
    return digits


def _infer_vector_step(
    value: Iterable[float],
    min: Iterable[float] | None,
    max: Iterable[float] | None,
) -> float:
    """Pick a default step for a vector input from its value/min/max components."""
    components = [*value, *(min or ()), *(max or ())]
    return float(np.min([_compute_step(float(x)) for x in components]))


class GuiApi:
    """Interface for working with the 2D GUI in Leika.

    Used by both our global server object, for sharing the same GUI elements
    with all clients, and by individual client handles. Containers place the
    elements created inside their ``with`` block into themselves.
    """

    _container_stack: contextvars.ContextVar[tuple[str, ...]]
    """Containers the current execution context is inside, innermost last.

    ``ContextVar`` isolates both worker threads and interleaved asyncio tasks.
    Its immutable tuple keeps copied task contexts isolated.
    """

    def __init__(
        self,
        owner: Server | ClientHandle,  # Who do I belong to?
        thread_executor: ThreadPoolExecutor,
        event_loop: AbstractEventLoop,
    ) -> None:
        from ._server import Server

        self._owner = owner
        """Entity that owns this API."""
        self._lock = threading.RLock()
        """Linearizes registries, handle state, lifecycle, and wire order."""
        self._container_stack = contextvars.ContextVar(
            f"leika_gui_container_stack_{id(self)}",
            default=(),
        )
        self._thread_executor = thread_executor
        self._event_loop = event_loop
        server = owner if isinstance(owner, Server) else owner._server
        self._server = server
        self._next_order = server._next_gui_order

        self._websock_interface = (
            owner._websock_server if isinstance(owner, Server) else owner._websock_connection
        )
        """Interface for sending and listening to messages."""

        self._terminal = False
        self._handles: dict[str, _GuiHandle[Any]] = {}
        """Every live handle in this scope, by UUID."""
        self._root_children: dict[str, _GuiHandle[Any]] = {}
        self._uploads: dict[tuple[ClientId, str], _Upload] = {}
        self._preview_work_from_key: dict[tuple[ClientId, str], _PreviewWorkState] = {}
        self._preview_work_lock = threading.RLock()
        self._callback_queue: deque[tuple[tuple[Callable[[Any], object], ...], object]] = deque()
        self._callback_draining = False

        register = self._websock_interface.register_handler
        register(_messages.GuiUpdateMessage, self._handle_gui_updates)
        register(_messages.GuiPlaybackCommandMessage, self._handle_playback_command)
        register(_messages.GuiRefreshMessage, self._handle_gui_refresh)
        register(_messages.GuiButtonHoldMessage, self._handle_gui_button_hold)
        register(_messages.GuiPreviewOpenMessage, self._handle_gui_preview_open)
        register(_messages.GuiPreviewWarmMessage, self._handle_gui_preview_warm)
        register(_messages.GuiPreviewReloadMessage, self._handle_gui_preview_reload)
        register(_messages.GuiPreviewWatchMessage, self._handle_gui_preview_watch)
        register(_messages.GuiFormSubmitMessage, self._handle_gui_form_submit)
        register(_messages.GuiFormResetMessage, self._handle_gui_form_reset)
        register(_messages.FileTransferStartUpload, self._handle_file_transfer_start)
        register(_messages.FileTransferPart, self._handle_file_transfer_part)
        register(_messages.FileTransferAbort, self._handle_file_transfer_abort)
        register(_messages.CommandTriggerMessage, self._handle_command_trigger)
        register(_messages.GuiCloseModalMessage, self._handle_gui_close_modal)

    def _check_active_locked(self) -> None:
        if self._terminal:
            raise RuntimeError(
                "This GUI is no longer active: its client disconnected or the server stopped."
            )

    def _add(
        self,
        handle_type: type[THandle],
        props: Any,
        value: Any = None,
        *,
        parent: str | None,
        icon: IconName | None = None,
        **attributes: Any,
    ) -> THandle:
        """Validate, register and publish a new handle inside ``parent``."""
        if icon is not None:
            props = dataclasses.replace(props, _icon_html=svg_from_icon(icon))
        with self._lock:
            self._check_active_locked()
            handle = handle_type(_GuiHandleState(_make_uuid(), self, props, value, parent, icon))
            for name, attribute in attributes.items():
                object.__setattr__(handle, name, attribute)
            impl = handle._impl
            impl.props, impl.value = handle._validate(props, value)
            if isinstance(handle, GuiInputHandle) and handle._is_field():
                impl.initial_value = impl.value
            impl.update_timestamp = time.time()
            siblings = None if parent is None else self._children(parent)
            container = self._handles.get(parent) if parent is not None else None
            if isinstance(container, GuiFormHandle):
                container._admit(handle)
            self._websock_interface.queue_message_or_raise(handle._create_message())
            self._handles[impl.uuid] = handle
            if siblings is not None:
                siblings[impl.uuid] = handle
        return handle

    def _add_input(
        self,
        handle_type: type[THandle],
        value: Any,
        *,
        label: str | None,
        hint: str | None,
        disabled: bool,
        visible: bool,
        order: float | None,
        **props: Any,
    ) -> THandle:
        """Add an input whose props start with the fields every input shares."""
        props_type = next(
            base for base in handle_type.__mro__ if "__dataclass_fields__" in vars(base)
        )
        return self._add(
            handle_type,
            props_type(
                order=self._apply_default_order(order),
                label=label,
                hint=hint,
                disabled=disabled,
                visible=visible,
                **props,
            ),
            value,
            parent=self._get_container_uuid(),
        )

    def _children(self, container_uuid: str) -> dict[str, _GuiHandle[Any]]:
        if container_uuid == "root":
            return self._root_children
        container = self._handles.get(container_uuid)
        if container is None:
            raise RuntimeError("GUI parent container has been removed.")
        return container._impl.children

    def _unregister(self, handle: _GuiHandle[Any]) -> None:
        """Forget a retired handle and the work it owns."""
        impl = handle._impl
        self._handles.pop(impl.uuid, None)
        parent = impl.parent_container_id
        if parent == "root":
            self._root_children.pop(impl.uuid, None)
        elif parent in self._handles:
            self._handles[parent]._impl.children.pop(impl.uuid, None)
        if isinstance(handle, GuiUploadButtonHandle):
            self._discard_file_uploads(source_component_uuid=impl.uuid)
        if isinstance(handle, GuiPreviewButtonHandle):
            self._discard_preview_work(source_component_uuid=impl.uuid)

    def _ancestor_form(self, container_uuid: str | None) -> GuiFormHandle | None:
        """The form enclosing a container, through folders, tab groups and tabs."""
        while container_uuid is not None and container_uuid != "root":
            container = self._handles.get(container_uuid)
            if container is None:
                return None
            if isinstance(container, GuiFormHandle):
                return container
            container_uuid = container._impl.parent_container_id
        return None

    def _schedule_callbacks(
        self,
        callbacks: tuple[Callable[[Any], object], ...],
        event: object,
    ) -> None:
        """Run callbacks for a committed programmatic change, in submission order."""
        if not callbacks:
            return
        with self._lock:
            self._callback_queue.append((callbacks, event))
            if self._callback_draining:
                return
            self._callback_draining = True

        def start() -> None:
            self._event_loop.create_task(self._drain_callbacks()).add_done_callback(
                print_async_errors
            )

        try:
            self._event_loop.call_soon_threadsafe(start)
        except Exception as error:
            # State and wire publication already committed; report the loss.
            with self._lock:
                self._callback_queue.clear()
                self._callback_draining = False
            print_async_exception(error)

    async def _drain_callbacks(self) -> None:
        try:
            while True:
                with self._lock:
                    if not self._callback_queue:
                        return
                    callbacks, event = self._callback_queue.popleft()
                await self._run_callbacks(callbacks, event)
        finally:
            with self._lock:
                self._callback_draining = False

    async def _run_callbacks(self, callbacks: Iterable[Callable[..., Any]], event: object) -> None:
        """Run a callback snapshot in order, outside the lock; failures are reported."""
        for callback in callbacks:
            await self._server._await_user_callback(callback, event)

    def _apply_default_order(self, order: float | None) -> float:
        """Return a finite explicit order, or the next owner order."""
        if order is None:
            return self._next_order()
        return float(_validate_number(order, "order"))

    def _resolve_client(self, client_id: ClientId) -> ClientHandle | None:
        """Resolve the ClientHandle for a given client_id. Returns None when
        the client has disconnected between queuing and dispatch -- callers
        should early-return."""
        # Runtime import to break the circular edge with `_server`.
        from ._client_handle import ClientHandle
        from ._server import Server

        with self._server._client_lock:
            connected = self._server._connected_clients.get(client_id)
            if isinstance(self._owner, ClientHandle):
                # A client-local GUI must only accept messages from the exact
                # live connection that owns it. The object can outlive its
                # websocket long enough for an already-queued handler to run.
                return self._owner if connected is self._owner else None
            if isinstance(self._owner, Server):
                return connected
        assert_never(self._owner)

    async def _handle_gui_refresh(
        self, client_id: ClientId, message: _messages.GuiRefreshMessage
    ) -> None:
        if not 1 <= len(message.request_id) <= 128:
            return
        with self._lock:
            if not isinstance(self._handles.get(message.uuid), GuiInputHandle):
                return
        try:
            await self._handle_gui_updates(
                client_id, _messages.GuiUpdateMessage(message.uuid, message.updates)
            )
        finally:
            # A no-op or rejected value must also settle local invalidation.
            # The barrier and snapshot share the broadcast producer's ordering.
            for page in self._server.pages:
                page.panes._ack_refresh(message.uuid, message.request_id, client_id)

    async def _handle_gui_updates(
        self,
        client_id: ClientId,
        message: _messages.GuiUpdateMessage,
        *,
        preview_request: _messages.GuiPreviewOpenMessage | None = None,
    ) -> None:
        """Apply one browser value, echo it to the other browsers, then run callbacks."""
        client = self._resolve_client(client_id)
        if client is None or message.updates.keys() != {"value"}:
            return
        with self._lock:
            handle = self._handles.get(message.uuid)
            if not isinstance(handle, GuiInputHandle) or not handle._accepts_input():
                return
            try:
                change = handle._prepare({"value": handle._client_value(message.updates["value"])})
            except (TypeError, ValueError, OverflowError):
                return
            file_button = isinstance(handle, _GuiFileButtonHandle)
            if change is None or (file_button and handle._impl.props._busy):
                return
            # The source browser already shows its own edit.
            handle._commit(change, exclude_client=client_id)
            if file_button:
                # Busy until the file is out, so one press sends one file.
                handle._update({"_busy": True})
            event = GuiEvent(client, client_id, handle, change.value)
            callbacks = tuple(handle._impl.callbacks)

        if isinstance(handle, GuiDownloadButtonHandle):
            # The file is on its way before whatever else the press does.
            callbacks = (handle._send, *callbacks)
        if isinstance(handle, GuiPreviewButtonHandle):
            preview = handle
            try:
                accepted = self._queue_preview_work(
                    "preview",
                    client_id,
                    client,
                    preview,
                    lambda: preview._send(event, preview_request),
                )
            except BaseException:
                preview._finish_press()
                raise
            if not accepted:
                preview._finish_press()
        # User code never runs under the registry/state lock.
        await self._run_callbacks(callbacks, event)

    async def _handle_playback_command(
        self, client_id: ClientId, message: _messages.GuiPlaybackCommandMessage
    ) -> None:
        client = self._resolve_client(client_id)
        if client is None:
            return
        with self._lock:
            handle = self._handles.get(message.uuid)
            if (
                not isinstance(handle, GuiPlaybackHandle)
                or handle._impl.removed
                or handle.disabled
                or not handle.visible
                or handle.duration == 0
            ):
                return
            try:
                handle._command(message.action, message.value)
            except (TypeError, ValueError, OverflowError):
                return
            event = PlaybackEvent(
                client,
                client_id,
                handle,
                message.action,
                message.value if message.action in ("seek", "step", "speed") else None,
                handle.state,
            )
            callbacks = tuple(handle._impl.callbacks)
        await self._run_callbacks(callbacks, event)

    async def _handle_gui_button_hold(
        self, client_id: ClientId, message: _messages.GuiButtonHoldMessage
    ) -> None:
        """Callback for handling button hold messages."""
        client = self._resolve_client(client_id)
        if client is None:
            return
        with self._lock:
            handle = self._handles.get(message.uuid)
            if not isinstance(handle, GuiButtonHandle) or not handle._accepts_input():
                return
            callbacks = tuple(handle._hold_callbacks.get(message.frequency, ()))
            event = GuiEvent(client, client_id, handle, handle._impl.value)
        await self._run_callbacks(callbacks, event)

    def _preview_button_for(
        self, uuid: str, client_id: ClientId
    ) -> tuple[GuiPreviewButtonHandle, ClientHandle] | None:
        """The button a preview message names, and the client that sent it.

        None for every mismatch -- a stale uuid, another kind of button, a
        button that takes no input now, a client gone between queueing and
        dispatch -- so each preview message can be a quiet return: the browser
        asks on its own account about a file it was already sent, and nobody is
        waiting on an error.
        """
        client = self._resolve_client(client_id)
        if client is None:
            return None
        with self._lock:
            handle = self._handles.get(uuid)
            if not isinstance(handle, GuiPreviewButtonHandle) or not handle._accepts_input():
                return None
            return handle, client

    def _queue_preview_work(
        self,
        kind: _PreviewWorkKind,
        client_id: ClientId,
        client: ClientHandle,
        handle: GuiPreviewButtonHandle,
        run: Callable[[], None],
    ) -> bool:
        """Admit preview work, returning whether it was queued.

        File resolution and transfer happen in the callback pool, but a shared
        pool alone does not preserve submission order. A slow warm or reload
        could otherwise finish after a newer press and replace the browser's
        newer contents. One worker drains one FIFO per ``(client, source)``.

        Warm and watch requests are advisory. At most one is useful while no
        user-requested work is pending; a press or explicit reload supersedes
        any advisory item that has not started. Presses and reloads are never
        coalesced, so two reload clicks still resolve the source twice.
        """
        item = _PreviewWorkItem(kind, client_id, client, handle, run)
        key = (client_id, handle._impl.uuid)

        with self._preview_work_lock:
            state = self._preview_work_from_key.setdefault(key, _PreviewWorkState())
            has_work = state.active_kind is not None or bool(state.pending)
            if kind in ("warm", "watch") and has_work:
                return False
            if kind in ("preview", "reload"):
                state.pending = deque(
                    queued for queued in state.pending if queued.kind not in ("warm", "watch")
                )
            if len(state.pending) >= _PREVIEW_PENDING_PER_SOURCE_MAX:
                return False
            state.pending.append(item)
            if state.worker is not None:
                return True
            try:
                state.worker = self._thread_executor.submit(self._run_preview_work, key, state)
            except BaseException:
                self._preview_work_from_key.pop(key, None)
                raise
            state.worker.add_done_callback(print_async_errors)
            return True

    def _run_preview_work(self, key: tuple[ClientId, str], state: _PreviewWorkState) -> None:
        """Drain one preview FIFO. Called by exactly one pool worker."""
        while True:
            with self._preview_work_lock:
                if self._preview_work_from_key.get(key) is not state:
                    return
                if not state.pending:
                    self._preview_work_from_key.pop(key, None)
                    return
                item = state.pending.popleft()
                state.active_kind = item.kind

            try:
                # A queued item can become stale while an earlier file is being
                # read. Revalidate both halves of its identity immediately
                # before entering user code or touching the connection buffer.
                if (
                    not item.handle._impl.removed
                    and self._resolve_client(item.client_id) is item.client
                ):
                    item.run()
            except BaseException as error:
                # One failure is reported without preventing later work.
                print_async_exception(error)
                if item.kind == "preview":
                    # The click already opened a local loading popup. A
                    # provider/preparation failure has no transfer to abort.
                    with contextlib.suppress(Exception):
                        item.client._websock_connection.queue_message(
                            _messages.GuiPreviewCancelMessage(item.handle._impl.uuid)
                        )
                        item.client.gui.add_notification(
                            "Could not preview file",
                            "The file could not be prepared. Try again after checking its source.",
                        )
            finally:
                if item.kind == "preview":
                    item.handle._finish_press()
                with self._preview_work_lock:
                    if self._preview_work_from_key.get(key) is state:
                        state.active_kind = None

    def _discard_preview_work(
        self,
        *,
        client_id: ClientId | None = None,
        source_component_uuid: str | None = None,
    ) -> None:
        """Drop queued preview work for a disconnected client or removed source."""
        workers: list[Future[Any]] = []
        discarded_presses: list[GuiPreviewButtonHandle] = []
        with self._preview_work_lock:
            stale = [
                key
                for key in self._preview_work_from_key
                if (client_id is None or key[0] == client_id)
                and (source_component_uuid is None or key[1] == source_component_uuid)
            ]
            for key in stale:
                state = self._preview_work_from_key.pop(key)
                discarded_presses.extend(
                    item.handle for item in state.pending if item.kind == "preview"
                )
                state.pending.clear()
                if state.worker is not None:
                    workers.append(state.worker)

        # A worker that has not started can be removed from the executor too.
        # Running Python code cannot be terminated safely; after it returns,
        # the missing state above makes it stop before the next queued item.
        for worker in workers:
            worker.cancel()
        # Discarded presses never reach the worker's release, so release them
        # here, outside the preview lock, since release takes the GUI lock.
        for handle in discarded_presses:
            handle._finish_press()

    async def _handle_gui_preview_open(
        self, client_id: ClientId, message: _messages.GuiPreviewOpenMessage
    ) -> None:
        if self._preview_button_for(message.uuid, client_id) is None:
            return
        # Keep the normal press's busy state, ordering, and on_click callbacks.
        await self._handle_gui_updates(
            client_id,
            _messages.GuiUpdateMessage(message.uuid, {"value": True}),
            preview_request=message,
        )

    async def _handle_gui_preview_warm(
        self, client_id: ClientId, message: _messages.GuiPreviewWarmMessage
    ) -> None:
        """A preview button has scrolled into view; start its press's transfer."""
        found = self._preview_button_for(message.uuid, client_id)
        if found is None:
            return
        handle, client = found
        self._queue_preview_work("warm", client_id, client, handle, lambda: handle._warm(client))

    async def _handle_gui_preview_reload(
        self, client_id: ClientId, message: _messages.GuiPreviewReloadMessage
    ) -> None:
        """A reader has asked an open preview for the file again.

        Off the event loop, like a press: resolving the contents may run the
        caller's function or read a large file.
        """
        found = self._preview_button_for(message.uuid, client_id)
        if found is None:
            return
        handle, client = found
        event = GuiEvent(client, client_id, handle, handle._impl.value)
        self._queue_preview_work("reload", client_id, client, handle, lambda: handle._reload(event))

    async def _handle_gui_preview_watch(
        self, client_id: ClientId, message: _messages.GuiPreviewWatchMessage
    ) -> None:
        """An open preview is asking whether its file has moved on: one `stat`,
        off the event loop, and usually a return."""
        found = self._preview_button_for(message.uuid, client_id)
        if found is None:
            return
        handle, client = found
        version = message.version
        self._queue_preview_work(
            "watch", client_id, client, handle, lambda: handle._watch(client, version)
        )

    def _form_for(
        self, client_id: ClientId, uuid: str
    ) -> tuple[GuiFormHandle, ClientHandle] | None:
        client = self._resolve_client(client_id)
        with self._lock:
            form = self._handles.get(uuid)
            if client is None or not isinstance(form, GuiFormHandle) or form._impl.removed:
                return None
            return form, client

    async def _handle_gui_form_submit(
        self, client_id: ClientId, message: _messages.GuiFormSubmitMessage
    ) -> None:
        """Publish a browser form submit, then run the form's callbacks."""
        found = self._form_for(client_id, message.uuid)
        if found is None:
            return
        form, client = found
        await self._run_callbacks(form._submit(), GuiEvent(client, client_id, form))

    async def _handle_gui_form_reset(
        self, client_id: ClientId, message: _messages.GuiFormResetMessage
    ) -> None:
        found = self._form_for(client_id, message.uuid)
        # Only a visible regular form draws a Reset.
        if found is not None and found[0].visible and not found[0].mini:
            found[0].reset_form()

    def _queue_to_client(self, client_id: ClientId, message: _messages.Message) -> bool:
        """Send upload flow control only to its originating browser."""
        client = self._resolve_client(client_id)
        return client is not None and client._websock_connection.queue_message(message) is not False

    def _abort_upload(self, client_id: ClientId, transfer_uuid: str, reason: str) -> None:
        self._queue_to_client(
            client_id, _messages.FileTransferAbort(transfer_uuid=transfer_uuid, reason=reason)
        )

    def _handle_file_transfer_start(
        self, client_id: ClientId, message: _messages.FileTransferStartUpload
    ) -> Coroutine[Any, Any, None] | None:
        transfer_uuid = message.transfer_uuid
        if not _valid_protocol_identifier(transfer_uuid):
            # There is no safe identifier with which to correlate an abort.
            return None
        with self._lock:
            handle = self._handles.get(message.source_component_uuid)
            # Incoming messages are dispatched to both global and client-local
            # GUI APIs. Only the API that owns this component may respond.
            if not isinstance(handle, GuiUploadButtonHandle):
                return None
            try:
                validate_file_display_name(message.filename)
                metadata_valid = (
                    message.size_bytes >= 0
                    and message.part_count == -(-message.size_bytes // _FILE_UPLOAD_PART_BYTES)
                    and _valid_mime_type(message.mime_type)
                )
            except (TypeError, ValueError):
                metadata_valid = False
            if not metadata_valid:
                reason = "Invalid upload metadata."
            elif message.size_bytes > _FILE_UPLOAD_MAX_BYTES:
                reason = "Upload exceeds the 64 MiB limit."
            elif (client_id, transfer_uuid) in self._uploads or any(
                key[0] == client_id and upload.handle is handle
                for key, upload in self._uploads.items()
            ):
                reason = "An upload is already active for this control."
            else:
                upload = _Upload(handle, message.filename, message.size_bytes)
                self._uploads[(client_id, transfer_uuid)] = upload
                return self._acknowledge_upload(client_id, transfer_uuid, upload)
            self._abort_upload(client_id, transfer_uuid, reason)
            return None

    def _handle_file_transfer_part(
        self, client_id: ClientId, message: _messages.FileTransferPart
    ) -> Coroutine[Any, Any, None] | None:
        key = (client_id, message.transfer_uuid)
        with self._lock:
            upload = self._uploads.get(key)
            if upload is None:
                return None
            received = len(upload.content)
            if not (
                message.source_component_uuid == upload.handle.id
                and message.part_index == received // _FILE_UPLOAD_PART_BYTES
                and isinstance(message.content, bytes)
                and len(message.content) == min(_FILE_UPLOAD_PART_BYTES, upload.size - received) > 0
            ):
                del self._uploads[key]
                self._abort_upload(client_id, message.transfer_uuid, "Invalid upload part.")
                return None
            upload.content.extend(message.content)
            return self._acknowledge_upload(client_id, message.transfer_uuid, upload)

    def _acknowledge_upload(
        self, client_id: ClientId, transfer_uuid: str, upload: _Upload
    ) -> Coroutine[Any, Any, None] | None:
        """Acknowledge an upload's progress, committing its value once complete.

        The upload is the button's next value, so it proceeds only while the
        button accepts input: disabling or hiding it aborts the transfer."""
        if not upload.handle._accepts_input():
            self._uploads.pop((client_id, transfer_uuid), None)
            self._abort_upload(client_id, transfer_uuid, "Upload target unavailable.")
            return None
        done = len(upload.content) == upload.size
        acknowledged = self._queue_to_client(
            client_id,
            FileTransferPartAck(
                source_component_uuid=upload.handle.id,
                transfer_uuid=transfer_uuid,
                transferred_bytes=len(upload.content),
                total_bytes=upload.size,
            ),
        )
        if done or not acknowledged:
            self._uploads.pop((client_id, transfer_uuid), None)
        if not done or not acknowledged:
            return None
        handle = upload.handle
        value = UploadedFile(upload.filename, bytes(upload.content))
        handle._impl.value = value
        handle._impl.update_timestamp = time.time()
        callbacks = tuple(handle._impl.callbacks)
        return self._run_upload_callbacks(client_id, handle, value, callbacks)

    async def _run_upload_callbacks(
        self,
        client_id: ClientId,
        handle: GuiUploadButtonHandle,
        value: UploadedFile,
        callbacks: tuple[Callable[..., Any], ...],
    ) -> None:
        client = self._resolve_client(client_id)
        if client is None:
            return
        event = GuiEvent(client, client_id, handle, value)
        await self._run_callbacks(callbacks, event)

    def _handle_file_transfer_abort(
        self, client_id: ClientId, message: _messages.FileTransferAbort
    ) -> None:
        """Release a browser-cancelled or timed-out upload."""
        with self._lock:
            self._uploads.pop((client_id, message.transfer_uuid), None)

    def _discard_file_uploads(
        self,
        *,
        client_id: ClientId | None = None,
        source_component_uuid: str | None = None,
    ) -> None:
        """Discard incomplete uploads for a disconnected client or removed button."""
        with self._lock:
            for key, upload in tuple(self._uploads.items()):
                if (client_id is None or key[0] == client_id) and (
                    source_component_uuid is None or upload.handle.id == source_component_uuid
                ):
                    del self._uploads[key]

    def _retire_scope(self) -> None:
        """Retire every handle without messages, after disconnect or server shutdown."""
        with self._lock:
            if self._terminal:
                return
            self._terminal = True
            for handle in self._handles.values():
                handle._impl.removed = True
            self._handles.clear()
            self._root_children.clear()
            self._uploads.clear()
            self._callback_queue.clear()
        self._discard_preview_work()

    def _discard_client_work(self, client_id: ClientId) -> None:
        """Discard work owned by a browser that has disconnected."""
        self._discard_file_uploads(client_id=client_id)
        self._discard_preview_work(client_id=client_id)

    async def _handle_command_trigger(
        self, client_id: ClientId, message: _messages.CommandTriggerMessage
    ) -> None:
        """Run a triggered command's callbacks."""
        client = self._resolve_client(client_id)
        if client is None:
            return
        with self._lock:
            handle = self._handles.get(message.uuid)
            if not isinstance(handle, CommandHandle) or handle._impl.removed or handle.disabled:
                return
            callbacks = tuple(handle._impl.callbacks)
        event = CommandEvent(client, client_id, handle)
        await self._run_callbacks(callbacks, event)

    async def _handle_gui_close_modal(
        self, client_id: ClientId, message: _messages.GuiCloseModalMessage
    ) -> None:
        """Callback for a client dismissing a modal.

        Teardown runs here rather than on the client so that the contained GUI
        components are removed exactly once, by the side that owns them. Closing
        broadcasts the same message back, which is what actually takes the modal
        off screen -- for every connected client, not just the one that
        dismissed it.
        """
        del client_id
        # Absent when the server closed the modal first, or when a second client
        # dismissed it in the same instant. Either way it is already gone.
        with self._lock:
            handle = self._handles.get(message.uuid)
            if isinstance(handle, GuiModalHandle) and not handle._impl.removed:
                handle.close()

    def _get_container_uuid(self) -> str:
        """Container that new GUI elements in this execution context belong to."""
        stack = self._container_stack.get()
        return stack[-1] if stack else "root"

    def _push_container_uuid(self, container_uuid: str) -> None:
        """Direct new GUI elements in this context into ``container_uuid``."""
        self._container_stack.set((*self._container_stack.get(), container_uuid))

    def _pop_container_uuid(self) -> None:
        """Undo the matching :meth:`_push_container_uuid`."""
        stack = self._container_stack.get()
        if not stack:
            raise RuntimeError("GUI container stack is empty.")
        self._container_stack.set(stack[:-1])

    def reset(self) -> None:
        """Remove every GUI element, modal, command and notification in this scope."""
        with self._lock:
            self._check_active_locked()
            top = [
                handle
                for handle in self._handles.values()
                if handle._impl.parent_container_id in ("root", None)
            ]
            if top:
                self._websock_interface.queue_messages_or_raise(
                    [handle._removal_message() for handle in top]
                )
            for handle in top:
                handle._retire()

    def configure_theme(
        self,
        *,
        control_layout: Literal["floating", "left", "right"] = "floating",
        theme: Literal["auto", "light", "dark"] | None = None,
    ) -> None:
        """Configures the visual appearance of the Leika front-end.

        Args:
            control_layout: Where the control panel starts. ``"floating"`` puts
                            it in a card over the canvas; ``"left"`` and
                            ``"right"`` start it docked to that edge. This is a
                            starting position, not a constraint: in every mode
                            the viewer can drag the panel out or to an edge, and
                            collapse it by clicking its header. On a phone the
                            controls are a bottom sheet and the value is
                            ignored.
            theme: Selects ``"auto"``, ``"light"``, or ``"dark"`` in the
                   viewer's Theme setting. The default, ``None``, is equivalent
                   to ``"auto"`` and follows each browser's OS preference,
                   including changes during the session. This sets the current
                   selection; viewers can change it afterwards in Settings.
        """

        if type(control_layout) is not str or control_layout not in (
            "floating",
            "left",
            "right",
        ):
            raise ValueError("control_layout must be 'floating', 'left', or 'right'.")
        if theme is not None and (type(theme) is not str or theme not in ("auto", "light", "dark")):
            raise ValueError("theme must be None, 'auto', 'light', or 'dark'.")

        self._websock_interface.queue_message_or_raise(
            _messages.ThemeConfigurationMessage(
                control_layout=control_layout,
                theme="auto" if theme is None else theme,
            ),
        )

    def add_notification(
        self,
        title: str,
        body: str = "",
        *,
        loading: bool = False,
        with_close_button: bool = True,
        auto_close_seconds: float | None = 5.0,
    ) -> NotificationHandle:
        """Show a notification for every client in this GUI API's scope.

        Args:
            title: Title to display on the notification.
            body: Message to display on the notification body.
            loading: Whether the notification shows a loading icon.
            with_close_button: Whether the notification can be manually closed.
            auto_close_seconds: Time before the notification closes on its own;
                ``None`` or ``0`` keeps it up until dismissed, removed, or updated to a positive timeout.
        """
        with self._lock:
            handle = self._add(
                NotificationHandle,
                _messages.NotificationProps(
                    title=title,
                    body=body,
                    loading=loading,
                    with_close_button=with_close_button,
                    auto_close_seconds=auto_close_seconds,
                ),
                parent=None,
            )
            handle._restart_expiry()
        return handle

    def add_command(
        self,
        label: str,
        callback: Callable[[], Any] | None = None,
        *,
        description: str | None = None,
        hotkey: _messages.HotkeyKey | None = None,
        modifier: _messages.KeyModifier | None = None,
        icon: IconName | None = None,
        disabled: bool = False,
    ) -> CommandHandle:
        """Register a command for the command palette.

        Scope follows the owner of this :class:`GuiApi`, matching the
        rest of the GUI API: ``server.gui.add_command(...)`` registers
        the command for every connected client (and any that connect
        later), while ``client.gui.add_command(...)`` registers it only
        for that client.

        (Experimental) The command palette API may change in future
        releases.

        Args:
            label: Label displayed in the command palette.
            callback: Optional shorthand for a single no-argument trigger
                handler. Equivalent to :meth:`CommandHandle.on_trigger`, which
                should be preferred when the handler needs the event.
            description: Optional description displayed below the label.
            hotkey: Optional hotkey key, e.g. ``"K"`` or ``"R"``. ``None``
                disables the hotkey.
            modifier: Modifier-combo to require with the hotkey, as a
                canonically ordered ``"+"``-separated string like
                ``"cmd/ctrl"``, ``"shift"``, or ``"cmd/ctrl+shift"``.
                ``None`` matches "no modifiers held". ``cmd/ctrl``
                matches whenever either Cmd or Ctrl is held. Must be
                ``None`` when ``hotkey`` is ``None``; passing a
                modifier without a hotkey raises ``ValueError``.
            icon: Optional icon to display next to the command label.
            disabled: If True, the command is visible but not triggerable.

        Returns:
            A handle that can be used to attach callbacks via
            :meth:`CommandHandle.on_trigger`, update properties, or remove the
            command.
        """
        if callback is not None and not callable(callback):
            raise TypeError("callback must be callable or None")
        handle = self._add(
            CommandHandle,
            _messages.CommandProps(
                label=label,
                description=description,
                hotkey=hotkey,
                modifier=modifier,
                _icon_html=None,
                disabled=disabled,
            ),
            parent=None,
            icon=icon,
        )
        if callback is not None:
            handle.on_trigger(lambda _: callback())
        return handle

    def add_folder(
        self,
        label: str | None,
        *,
        order: float | None = None,
        expand_by_default: bool = True,
        popup: bool = False,
        visible: bool = True,
    ) -> GuiFolderHandle:
        """Add a folder, and return a handle that can be used to populate it.

        Args:
            label: Label to display on the folder. If ``None``, the folder is
                rendered without a header or collapse control, which is useful for pure
                layout grouping.
            order: Optional ordering, smallest values will be displayed first.
            expand_by_default: Open the folder by default. Set to False to collapse it by
                default. Ignored when ``label`` is ``None`` or ``popup`` is set.
            popup: Draw the folder as one labelled row whose children open in a
                popout, keeping them out of the panel until the viewer opens
                it. Needs a label.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used as a context to populate the folder.
        """
        return self._add(
            GuiFolderHandle,
            _messages.GuiFolderProps(
                order=self._apply_default_order(order),
                label=label,
                expand_by_default=expand_by_default,
                popup=popup,
                visible=visible,
            ),
            parent=self._get_container_uuid(),
        )

    def add_form(
        self,
        *,
        label: str | None = None,
        mini: bool = False,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiFormHandle:
        """Add a form, and return a handle that can be used to populate it.

        See :class:`GuiFormHandle` for usage and semantics.

        Args:
            label: Label shown beside the form's row, opposite the button that
                opens it. If ``None``, that button takes the whole row, the
                same rule a labelless :meth:`add_button` follows. Ignored for a
                mini form.
            mini: Wrap a single field instead: the same commit semantics in the
                space of one row, drawn as the field's own row with a send
                button on the end of it, and no popout or Reset. Exactly one
                direct, editable field goes inside; a sibling row, nested
                container, or second field raises :class:`ValueError` before it
                is published.
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used as a context to populate the form.

        Example::

            with server.gui.add_form(mini=True) as ask:
                query = server.gui.add_text("Search", "")

            @ask.on_submit
            def _(event):
                run_search(query.value)
        """
        # Nested <form> elements are invalid HTML. Modals render in a separate
        # portal, where the walk stops and a fresh <form> is well-formed.
        if self._ancestor_form(self._get_container_uuid()) is not None:
            raise ValueError(
                "Nested forms are not supported: add_form() was called "
                "inside an existing form's context."
            )
        return self._add(
            GuiFormHandle,
            _messages.GuiFormProps(
                order=self._apply_default_order(order), label=label, visible=visible, mini=mini
            ),
            parent=self._get_container_uuid(),
        )

    def add_modal(
        self,
        title: str,
        *,
        order: float | None = None,
    ) -> GuiModalHandle:
        """Show a modal window, which can be useful for popups and messages, then return
        a handle that can be used to populate it.

        Args:
            title: Title to display on the modal.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used as a context to populate the modal.
        """
        return self._add(
            GuiModalHandle,
            None,
            parent=None,
            _order=self._apply_default_order(order),
            _title=title,
        )

    def add_tab_group(
        self,
        *,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiTabGroupHandle:
        """Add a tab group.

        Args:
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used as a context to populate the tab group.
        """
        return self._add(
            GuiTabGroupHandle,
            _messages.GuiTabGroupProps(order=self._apply_default_order(order), visible=visible),
            parent=self._get_container_uuid(),
        )

    def add_html(
        self,
        content: str,
        *,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiHtmlHandle:
        """Add trusted, server-authored raw HTML to the GUI.

        The browser injects this content without sanitizing it. HTML event
        attributes, resource loads, and similar active content can act with the
        page's authority. Never pass untrusted user input unless the caller has
        sanitized it for this exact use.

        Args:
            content: Trusted raw HTML to display.
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add(
            GuiHtmlHandle,
            _messages.GuiHtmlProps(
                order=self._apply_default_order(order), content=content, visible=visible
            ),
            parent=self._get_container_uuid(),
        )

    def add_playback(
        self,
        label: str | None = None,
        *,
        duration: float,
        time: float = 0.0,
        playing: bool = False,
        speed: float = 1.0,
        loop: bool = True,
        fps: float | None = None,
        buffering: bool = False,
        disabled: bool = False,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiPlaybackHandle:
        """Add play/pause, seek, speed, loop and optional frame-step controls
        for a timeline that Python owns.

        Pass ``duration`` in seconds. Python owns the clock and receives
        browser commands through ``handle.on_update``. Publish actual progress
        with ``handle.time = seconds``, or call ``handle.advance(elapsed_seconds)``
        in your render loop. No automatic background work runs. For videos,
        whose clock the browser owns, use :meth:`add_video_controls`.

        ``fps`` enables frame stepping. ``buffering`` indicates that content is
        being prepared without disabling pause or seek. ``duration=0`` disables
        transport until content is ready. All time values are seconds.

        With ``label=None`` the full row includes previous/next frame and time;
        a label selects the compact row. State of Python-controlled playback
        follows the GUI scope: shared on ``server.gui``, private on ``client.gui``.
        """
        return self._add(
            GuiPlaybackHandle,
            _messages.GuiPlaybackProps(
                order=self._apply_default_order(order),
                label=label,
                visible=visible,
                disabled=disabled,
                time=time,
                duration=duration,
                playing=playing,
                speed=speed,
                loop=loop,
                fps=fps,
                buffering=buffering,
            ),
            parent=self._get_container_uuid(),
        )

    def add_video_controls(
        self,
        label: str | None = None,
        *,
        sync_group: str,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiVideoControlsHandle:
        """Add shared video playback controls.

        Without a label, a full-width 32px row contains play/pause, frame
        stepping, seeking, elapsed time, speed and looping. With a label, a
        standard 24px labelled row contains play/pause, seeking, speed and
        looping. Set ``label=None`` to switch back to the full layout.

        Videos join by passing the same ``sync_group`` to ``add_video``.
        Playback belongs to each browser, independently of Python and other
        viewers. Hiding or removing this component does not stop its videos.
        Frame stepping requires an equal, known ``fps`` on all group members.
        Group names follow the same nonempty 1,024 UTF-16-unit limit as pane IDs.
        """
        return self._add(
            GuiVideoControlsHandle,
            _messages.GuiVideoControlsProps(
                order=self._apply_default_order(order),
                label=label,
                sync_group=sync_group,
                visible=visible,
            ),
            parent=self._get_container_uuid(),
        )

    def add_divider(
        self,
        *,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiDividerHandle:
        """Add a horizontal divider line to the GUI.

        Args:
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add(
            GuiDividerHandle,
            _messages.GuiDividerProps(order=self._apply_default_order(order), visible=visible),
            parent=self._get_container_uuid(),
        )

    def add_image(
        self,
        image: np.ndarray,
        *,
        label: str | None = None,
        format: Literal["auto", "png", "jpeg"] = "auto",
        jpeg_quality: int | None = None,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiImageHandle:
        """Add an image element to the GUI.

        Args:
            image: A numpy array representing the image to display.
            label: Label to display on the image element.
            format: Format to transport and display the image using. 'auto' will use PNG for RGBA images and JPEG for RGB.
            jpeg_quality: Quality of the jpeg image (if jpeg format is used).
            order: Order of the element for sorting.
            visible: Whether the image element is visible initially.

        Returns:
            Handle for manipulating the image element.
        """
        _validate_image_encoding_options(format, jpeg_quality)
        snapshot, resolved_format, data = prepare_image(image, format, jpeg_quality)
        return self._add(
            GuiImageHandle,
            _messages.GuiImageProps(
                order=self._apply_default_order(order),
                label=label,
                _data=data,
                _format=resolved_format,
                visible=visible,
            ),
            parent=self._get_container_uuid(),
            _image=snapshot,
            _jpeg_quality=jpeg_quality,
            _user_format=format,
        )

    def add_plotly(
        self,
        figure: go.Figure,
        *,
        config: Mapping[str, Any] | None = None,
        aspect: float = 1.0,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiPlotlyHandle:
        """Add a Plotly figure to the GUI. Requires the `plotly` package to be
        installed.

        Args:
            figure: Plotly figure to snapshot and display. The handle does
                not retain this mutable object; its ``figure`` getter rebuilds
                an independent copy from the serialized JSON. A figure without
                a template, or with Plotly's stock default, follows the
                viewer's light or dark theme.
            config: Plotly config dict merged into the figure JSON. Controls
                display options like ``{"displayModeBar": False}``. Values
                must be JSON-serializable. See
                https://plotly.com/javascript/configuration-options/
            aspect: Width-to-height ratio for the plot in the control panel.
                1.0 creates a square plot, values > 1.0 create wider plots.
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        config = plotly_config(config)
        json_str = plotly_json(figure, config)
        self._server._ensure_plotly_runtime()
        return self._add(
            GuiPlotlyHandle,
            _messages.GuiPlotlyProps(
                order=self._apply_default_order(order),
                _plotly_json_str=json_str,
                _theme_templates=plotly_theme_templates(),
                aspect=aspect,
                visible=visible,
            ),
            parent=self._get_container_uuid(),
            _config=config,
        )

    @overload
    def add_button(
        self,
        text: str,
        *,
        label: str | None = None,
        color: Literal["default", "inverse"] = "default",
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        merge: bool | Sequence[bool] = True,
        icon: IconName | None = None,
        order: float | None = None,
    ) -> GuiButtonHandle: ...

    @overload
    def add_button(
        # A list or a tuple rather than `Sequence[str]`, which `str` satisfies:
        # the two overloads would then overlap on every single button and a
        # type checker could not tell which handle it was getting.
        self,
        text: list[str] | tuple[str, ...],
        *,
        label: str | None = None,
        color: ButtonColor | Sequence[ButtonColor] = "default",
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        merge: bool | Sequence[bool] = True,
        icon: None = None,
        order: float | None = None,
    ) -> GuiButtonGroupHandle: ...

    def add_button(
        self,
        text: str | Sequence[str],
        *,
        label: str | None = None,
        color: ButtonColor | Sequence[ButtonColor] = "default",
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        merge: bool | Sequence[bool] = True,
        icon: IconName | None = None,
        order: float | None = None,
    ) -> GuiButtonHandle | GuiButtonGroupHandle:
        """Add a button, or a group of them, to the GUI.

        One face or several: passing a string gives a single button, whose
        value is set to ``True`` every time it is clicked (set it back to
        ``False`` to detect the next click), and passing a sequence of strings
        gives a row of them, whose value is the option last pressed.

        A row of them is buttons, not a choice between them: nothing stays
        pressed, and pressing the same option twice fires the callback twice.
        Read ``value`` to see which was pressed. They are one method because
        they are one control with one option or many -- same label rule, same
        colorways, same height.

        Args:
            text: Text on the button's face. A sequence gives a group with one
                button per entry, and its value starts on the first.
            label: Optional label for the row. Left unset, the button takes the
                whole width of the panel, which is what a button that says what
                it does needs; given one, the label takes the left column and
                the button sits beside it, like every other labelled control.
            color: Colorway. ``"default"`` outlines, which is what most
                buttons want; ``"inverse"`` fills with the accent instead, for
                the one action a panel is really about. A single role answers
                for every button in a row; a sequence answers one button at a
                time, so ``color=("default", "inverse")`` puts the accent
                behind the second of a pair and not the first.
            merge: Whether neighbouring buttons in a row are joined into one
                block, sharing an edge, or parted by a gap. A single bool
                answers for the whole row; a sequence answers one gap at a
                time, so ``merge=(True, False)`` joins the first two buttons
                and parts the third from them. Ignored for a single button,
                which has no neighbours.
            visible: Whether the button is visible.
            disabled: Whether the button is disabled.
            hint: Optional hint to display on hover.
            icon: Optional icon to display on the button. Single buttons only:
                a group has one face per option and no room to say which of
                them an icon belongs to.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        if not isinstance(text, str):
            if icon is not None:
                raise ValueError(
                    "icon= is for a single button; a group of buttons has one face per"
                    " option and nowhere to say which of them the icon belongs to."
                )
            options = tuple(text)
            return self._add_input(
                GuiButtonGroupHandle,
                options[0] if options else None,
                label=label,
                hint=hint,
                disabled=disabled,
                visible=visible,
                order=order,
                color=color,
                options=options,
                merge=merge,
            )
        if not isinstance(merge, bool) or not isinstance(color, str):
            raise ValueError(
                "color= and merge= take one value for a single button, which has no row"
                " of faces or gaps to give them per option."
            )
        return self._add_button(
            GuiButtonHandle,
            text,
            label=label,
            color=color,
            disabled=disabled,
            visible=visible,
            hint=hint,
            icon=icon,
            order=order,
        )

    def _add_button(
        self,
        handle_type: type[THandle],
        text: str,
        *,
        label: str | None,
        color: ButtonColor,
        disabled: bool,
        visible: bool,
        hint: str | None,
        icon: IconName | None,
        order: float | None,
        prefetch: bool = False,
        **attributes: Any,
    ) -> THandle:
        """A single button, or a file button built on one."""
        return self._add(
            handle_type,
            _messages.GuiButtonProps(
                order=self._apply_default_order(order),
                label=label,
                hint=hint,
                visible=visible,
                disabled=disabled,
                text=text,
                color=color,
                _icon_html=None,
                _hold_callback_freqs=(),
                _prefetch=prefetch,
                _busy=False,
            ),
            False,
            parent=self._get_container_uuid(),
            icon=icon,
            **attributes,
        )

    def add_upload_button(
        self,
        text: str,
        *,
        label: str | None = None,
        color: Literal["default", "inverse"] = "default",
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        icon: IconName | None = None,
        mime_type: str = "*/*",
        order: float | None = None,
    ) -> GuiUploadButtonHandle:
        """Add a button that uploads a file from the browser.

        The handle's ``value`` is the last uploaded :class:`UploadedFile`, and
        ``on_upload`` callbacks run once each upload completes. Files are
        limited to 64 MiB, and disabling or hiding the button aborts an upload
        in progress.

        Args:
            text: Text to display on the button itself.
            label: Optional label for the row; see :meth:`add_button`.
            color: Colorway for the button. ``"default"`` outlines, which is
                what most buttons want; ``"inverse"`` fills with the accent
                instead, for the one action a panel is really about.
            visible: Whether the button is visible.
            disabled: Whether the button is disabled.
            hint: Optional hint to display on hover.
            icon: Optional icon to display on the button.
            mime_type: Optional MIME type to filter the files that can be uploaded.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add(
            GuiUploadButtonHandle,
            _messages.GuiUploadButtonProps(
                order=self._apply_default_order(order),
                label=label,
                hint=hint,
                visible=visible,
                disabled=disabled,
                text=text,
                color=color,
                _icon_html=None,
                mime_type=mime_type,
            ),
            UploadedFile("", b""),
            parent=self._get_container_uuid(),
            icon=icon,
        )

    def add_download_button(
        self,
        text: str,
        content: FileContent,
        *,
        filename: str | None = None,
        label: str | None = None,
        color: Literal["default", "inverse"] = "default",
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        icon: IconName | None = None,
        order: float | None = None,
    ) -> GuiDownloadButtonHandle:
        """Add a button that sends a file to the client that presses it.

        A button wired to :meth:`ClientHandle.send_file_download`, which is the
        wiring worth having done for you: the file goes to the one client that
        pressed rather than to everyone connected, the browser saves it as soon
        as it arrives, and the button stays busy until the transfer is out,
        so a slow export cannot be started twice. Sending a file at a moment
        that is not a click -- when a job finishes, on a timer -- is what the
        underlying method is for, and it can offer the file as a link instead.

        Args:
            text: Text on the button's face.
            content: What to send. Bytes are sent as they are; a
                :class:`~pathlib.Path` is read when the button is pressed and
                streamed a chunk at a time, so the file may change, or outgrow
                memory, after the button is made. A function is called on each
                press with the click event and returns either. Providers must
                be synchronous callables; they run in the callback thread
                pool. Note that a `str` is neither: text has to be encoded,
                and a path has to be a Path.
            filename: Name the file is saved under. Optional only when the
                contents come from a path, whose own name is then used.
            label: Optional label for the row; see :meth:`add_button`.
            color: Colorway for the button. ``"default"`` outlines, which is
                what most buttons want; ``"inverse"`` fills with the accent
                instead, for the one action a panel is really about.
            visible: Whether the button is visible.
            disabled: Whether the button is disabled.
            hint: Optional hint to display on hover.
            icon: Optional icon to display on the button.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add_button(
            GuiDownloadButtonHandle,
            text,
            label=label,
            color=color,
            disabled=disabled,
            visible=visible,
            hint=hint,
            icon=icon,
            order=order,
            _content=_file_content(content, filename, "add_download_button()"),
            _filename=filename,
        )

    def add_preview_button(
        self,
        text: str,
        content: FileContent,
        *,
        filename: str | None = None,
        label: str | None = None,
        color: Literal["default", "inverse"] = "default",
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        icon: IconName | None = None,
        max_bytes: int = PREVIEW_MAX_BYTES,
        order: float | None = None,
    ) -> GuiPreviewButtonHandle:
        """Add a button that opens a file in a dialog on the client that presses it.

        The download button's twin, shown rather than saved. Which viewer the
        dialog reaches for follows from the file's type: text as itself,
        markdown rendered, images, audio and video in players, PDFs in a frame,
        and anything else as a card naming the file and offering to download it
        instead. The type is read off `filename`, so an extension is worth
        having even when the contents are bytes.

        Writing gets a reading dialog: markdown and plain text are set in a
        column about 65 characters wide, at a size meant for paragraphs rather
        than for labels, in a frame as tall as the window allows. Everything
        else opens in a fixed frame, since a picture or a player is fitted into
        one rather than scrolled through. Either way the dialog is the same
        size whatever the file turns out to hold.

        A markdown file with headings to list them is shown with its own
        contents in the margin beside it, where the window is wide enough to
        hold a column of them without narrowing the writing.

        Local Markdown images resolve relative to the document directory,
        including parent-directory paths and symlinks. Absolute local paths
        also work; the directory is a base path, not a filesystem boundary.

        Recent completed Markdown previews are retained in a bounded browser
        cache. Reopening shows the cached document immediately while the server
        rechecks the source and its linked images. Identical prepared contents
        reuse that document without another transfer or parse. A callable is
        still run on every press; the reload button always requests a fresh copy.

        An open preview follows its file. Where `content` is a path, the
        dialog checks about once a second whether what is on disk is still
        what it is showing, and takes the new copy when it is not -- so a
        document being rewritten, or a log being appended to, can be watched
        from the browser without pressing anything. It keeps its place in the
        document while it does. Contents given as bytes cannot change, and
        contents given as a function are not run on a timer: for those, the
        dialog's reload button asks, and a press is what runs your code.

        Args:
            text: Text on the button's face.
            content: What to show, as in :meth:`add_download_button`: bytes, a
                :class:`~pathlib.Path` read when the button is pressed, or a
                synchronous function of the click event returning either.
            filename: Name the file is shown under. Optional only when the
                contents come from a path, whose own name is then used.
            label: Optional label for the row; see :meth:`add_button`.
            color: Colorway for the button. ``"default"`` outlines, which is
                what most buttons want; ``"inverse"`` fills with the accent
                instead, for the one action a panel is really about.
            visible: Whether the button is visible.
            disabled: Whether the button is disabled.
            hint: Optional hint to display on hover.
            icon: Optional icon to display on the button.
            max_bytes: Size past which the file is not sent at all and the
                client is told why; showing a file means holding it whole in
                the browser. Defaults to 64 MiB.
            order: Optional ordering, smallest values will be displayed first.

        Note:
            Markdown is rendered the way :meth:`add_text` renders it: as
            GitHub renders it, with nothing in the document evaluated. A file
            previews the same whether you wrote it or found it.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        _validate_nonnegative_integer(max_bytes, "max_bytes")
        return self._add_button(
            GuiPreviewButtonHandle,
            text,
            label=label,
            color=color,
            disabled=disabled,
            visible=visible,
            hint=hint,
            icon=icon,
            order=order,
            prefetch=True,
            _content=_file_content(content, filename, "add_preview_button()"),
            _filename=filename,
            _max_bytes=max_bytes,
        )

    def add_toggle(
        self,
        text: Sequence[str],
        *,
        initial_value: str | Sequence[str] | None = None,
        label: str | None = None,
        color: ButtonColor | Sequence[ButtonColor] = "default",
        multiple: bool = False,
        required: bool | None = None,
        merge: bool | Sequence[bool] = True,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiToggleGroupHandle:
        """Add a row of toggles to the GUI.

        A toggle is a button that stays pressed: same faces, same colorways,
        same label rule and heights as :meth:`add_button`, but it holds its
        state instead of firing and returning to rest. On, it takes the
        appearance that button has under the pointer at the moment of a click.
        The value is the tuple of options currently on. For one true/false
        value, use :meth:`add_checkbox`.

        Args:
            text: The options, one toggle per entry.
            initial_value: What starts on: one option's text or a sequence of
                them. Left unset, a required row starts on its first option
                and any other row starts empty.
            label: Optional label for the row; see :meth:`add_button`.
            color: Colorway; see :meth:`add_button`.
            multiple: Whether more than one option may be on at once. Off by
                default, which makes the row a choice between its options:
                turning one on turns the others off.
            required: Whether one option must always be on, so the toggle that
                is on cannot be turned off. Left unset, a row behaves like the
                control it resembles: one at a time requires a choice, the way
                a radio group does, and a ``multiple`` row does not, the way
                checkboxes do not.
            merge: Whether neighbouring toggles are joined or parted; see
                :meth:`add_button`.
            disabled: Whether the toggles are disabled.
            visible: Whether the toggles are visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        if isinstance(text, str):
            raise ValueError(
                "add_toggle() takes a sequence of options; for one true/false value,"
                " use add_checkbox()."
            )
        options = tuple(text)
        # A row behaves like the control it resembles unless told otherwise: a
        # choice between options is required the way a radio group is, and a row
        # of independent switches is not, the way checkboxes are not.
        required = (not multiple) if required is None else required
        if initial_value is None:
            initial_value = options[:1] if required else ()
        return self._add_input(
            GuiToggleGroupHandle,
            initial_value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
            color=color,
            options=options,
            multiple=multiple,
            required=required,
            merge=merge,
        )

    def add_checkbox(
        self,
        label: str,
        initial_value: bool,
        *,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiCheckboxHandle:
        """Add a checkbox to the GUI.

        Args:
            label: Label to display on the checkbox.
            initial_value: Initial value of the checkbox.
            disabled: Whether the checkbox is disabled.
            visible: Whether the checkbox is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add_input(
            GuiCheckboxHandle,
            initial_value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
        )

    def add_text(
        self,
        label: str | None,
        initial_value: str,
        *,
        editable: bool = True,
        markdown: bool = False,
        multiline: bool = False,
        rows: int | None = None,
        image_root: Path | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiTextHandle:
        r"""Add text to the GUI, for the viewer to read or to edit.

        Editable, it is a text box and its value is whatever has been typed into
        it. Read-only, it is that value shown rather than asked for: no box to
        click into, a tinted surface to say as much, and markdown drawn as
        markdown if ``markdown`` is set. Prose in a panel is the read-only,
        markdown, unlabelled case::

            server.gui.add_text(None, "## Notes", editable=False, markdown=True)

        Markdown is GitHub's: CommonMark plus GFM's tables, task lists,
        strikethrough and autolinks, and the same subset of inline HTML GitHub
        keeps -- ``<br>`` and ``<sub>`` work, ``<script>`` and event handlers
        are dropped. Nothing in the document is evaluated, so a file renders
        here the way it renders on GitHub and a page cannot be a program.

        Args:
            label: Label to display beside the text, or None for text that fills
                the row on its own.
            initial_value: Initial value of the text.
            editable: Whether the viewer can type in it.
            markdown: Whether the value is drawn as markdown rather than as the
                characters it is made of. Only for text that is not editable: what
                is edited is the source, so an editable field shows it. A document
                is blocks and takes the lines it needs, so ``multiline`` says
                nothing about it.
            multiline: Whether the text runs to several lines, delimited with the \n
                character. One line otherwise, ending in an ellipsis if it does not
                fit. Ignored when ``markdown`` is set.
            rows: Height in lines, or None to leave it to the field. Given, it is the
                height the box keeps, scrolling its own text rather than growing.
                Left out, an editable box is three lines and a read-only one fits
                itself to the text it holds. Ignored unless ``multiline``.
            image_root: Optional base directory for relative Markdown image paths.
                Parent-directory paths, absolute paths, and symlinks follow normal
                filesystem resolution.
            disabled: Whether an editable box is disabled.
            visible: Whether the text is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        if image_root is not None and not isinstance(image_root, Path):
            raise TypeError("image_root must be a pathlib.Path or None.")
        return self._add(
            GuiTextHandle,
            _messages.GuiTextProps(
                order=self._apply_default_order(order),
                label=label,
                hint=hint,
                visible=visible,
                disabled=disabled,
                multiline=multiline,
                rows=rows,
                editable=editable,
                markdown=markdown,
                _source="",
            ),
            initial_value,
            parent=self._get_container_uuid(),
            _image_root=None if image_root is None else Path(os.fspath(image_root)),
        )

    @overload
    def add_list(
        self,
        label: str | None = None,
        initial_value: Sequence[str] = (),
        *,
        mark: None = None,
        frozen: bool = False,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiListHandle[tuple[str, ...]]: ...

    @overload
    def add_list(
        self,
        label: str | None = None,
        initial_value: Sequence[str | tuple[str, bool]] = (),
        *,
        mark: Literal["check", "radio"],
        frozen: bool = False,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiListHandle[tuple[tuple[str, bool], ...]]: ...

    def add_list(
        self,
        label: str | None = None,
        initial_value: Sequence[str | tuple[str, bool]] = (),
        *,
        mark: Literal["check", "radio"] | None = None,
        frozen: bool = False,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiListHandle[Any]:
        """Add an editable list of text rows to the GUI, each optionally marked.

        A stack of text boxes rather than one. A viewer can edit any row, add
        one, remove one, or drag one to another place in the list, and every
        one of those reports the whole tuple, so ``on_update`` sees the list as
        it now reads.

        Without a mark, the value is a tuple of strings. With
        ``mark="check"``, each row carries a box to tick, and with
        ``mark="radio"`` a radio of which at most one is selected; the value is
        then one ``(text, marked)`` pair per row, and a row given as a bare
        string starts unmarked::

            items = server.gui.add_list("Preflight", ["Fuel", ("Doors", True)], mark="check")
            items.marked  # ("Doors",)

        Args:
            label: Optional label for the row. Left unset, the list takes the
                whole width of the panel, which a stack of boxes usually wants;
                given one, the label takes the left column and the rows sit
                beside it, like every other labelled control.
            initial_value: The rows the list starts with: strings, or with a
                mark strings and ``(text, marked)`` pairs. An empty list is a
                list with nothing in it yet, not an error.
            mark: What each row carries: nothing, ``"check"``, or ``"radio"``.
            frozen: Fix the rows' number and order, and with a mark their
                words too, which are then drawn as text so the viewer only
                marks them. Without a mark the entries can still be edited. Use
                ``disabled`` to stop all editing.
            disabled: Whether the list is disabled.
            visible: Whether the list is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add_input(
            GuiListHandle,
            initial_value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
            mark=mark,
            frozen=frozen,
        )

    def add_number(
        self,
        label: str,
        initial_value: IntOrFloat,
        *,
        min: IntOrFloat | None = None,
        max: IntOrFloat | None = None,
        step: IntOrFloat | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiNumberHandle[IntOrFloat]:
        """Add a number input to the GUI, with user-specifiable bound and precision parameters.

        Args:
            label: Label to display on the number input.
            initial_value: Initial value of the number input.
            min: Optional minimum value of the number input.
            max: Optional maximum value of the number input.
            step: Optional step size of the number input. Computed automatically if not
                specified.
            disabled: Whether the number input is disabled.
            visible: Whether the number input is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        value = _validate_number(initial_value, "initial_value")
        # Browser edits are cast to the type of the stored value, so an int
        # value with float bounds would truncate every edit. Promote it.
        if type(value) is int and float in (type(min), type(max), type(step)):
            value = float(value)
        if step is None:
            step = cast(
                IntOrFloat,
                builtins.min(_compute_step(value), _compute_step(min), _compute_step(max)),
            )
        return self._add_input(
            GuiNumberHandle,
            value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
            precision=_compute_precision_digits(step),
            step=step,
            min=min,
            max=max,
        )

    @overload
    def add_vector(
        self,
        label: str,
        initial_value: tuple[float, float],
        *,
        min: tuple[float, float] | None = None,
        max: tuple[float, float] | None = None,
        step: float | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiVectorHandle[tuple[float, float]]: ...

    @overload
    def add_vector(
        self,
        label: str,
        initial_value: tuple[float, float, float],
        *,
        min: tuple[float, float, float] | None = None,
        max: tuple[float, float, float] | None = None,
        step: float | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiVectorHandle[tuple[float, float, float]]: ...

    @overload
    def add_vector(
        self,
        label: str,
        initial_value: np.ndarray,
        *,
        min: tuple[float, ...] | np.ndarray | None = None,
        max: tuple[float, ...] | np.ndarray | None = None,
        step: float | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiVectorHandle[tuple[float, ...]]: ...

    def add_vector(
        self,
        label: str,
        initial_value: tuple[float, ...] | np.ndarray,
        *,
        min: tuple[float, ...] | np.ndarray | None = None,
        max: tuple[float, ...] | np.ndarray | None = None,
        step: float | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiVectorHandle[Any]:
        """Add a vector input of two or three components to the GUI.

        Args:
            label: Label to display on the vector input.
            initial_value: Initial value, whose length (2 or 3) the vector keeps.
            min: Optional minimum value of each component.
            max: Optional maximum value of each component.
            step: Optional step size of the vector input. Computed automatically if not
                specified.
            disabled: Whether the vector input is disabled.
            visible: Whether the vector input is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        if step is None:
            step = _infer_vector_step(initial_value, min, max)
        return self._add_input(
            GuiVectorHandle,
            initial_value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
            min=min,
            max=max,
            step=step,
            precision=_compute_precision_digits(step),
        )

    # See add_dropdown for notes on overloads.
    @overload
    def add_dropdown(
        self,
        label: str,
        options: Sequence[TLiteralString],
        *,
        initial_value: TLiteralString | None = None,
        disabled: bool = False,
        visible: bool = True,
        searchable: bool = False,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiDropdownHandle[TLiteralString]: ...

    @overload
    def add_dropdown(
        self,
        label: str,
        options: Sequence[TString],
        *,
        initial_value: TString | None = None,
        disabled: bool = False,
        visible: bool = True,
        searchable: bool = False,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiDropdownHandle[TString]: ...

    def add_dropdown(
        self,
        label: str,
        options: Sequence[TLiteralString] | Sequence[TString],
        *,
        initial_value: TLiteralString | TString | None = None,
        disabled: bool = False,
        visible: bool = True,
        searchable: bool = False,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiDropdownHandle[Any]:  # Output type is specified in overloads.
        """Add a dropdown to the GUI.

        Args:
            label: Label to display on the dropdown.
            options: Sequence of options to display in the dropdown.
            initial_value: Initial value of the dropdown; the first option when
                left unset.
            disabled: Whether the dropdown is disabled.
            visible: Whether the dropdown is visible.
            searchable: Whether the open dropdown offers a search box to filter
                the options. Off by default, which keeps the selected option
                under the cursor when the list opens; turn it on for lists too
                long to scan by eye.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add_input(
            GuiDropdownHandle,
            initial_value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
            options=options,
            searchable=searchable,
        )

    def add_progress_bar(
        self,
        initial_value: float,
        *,
        visible: bool = True,
        animated: bool = False,
        order: float | None = None,
    ) -> GuiProgressBarHandle:
        """Add a progress bar to the GUI.

        Args:
            initial_value: Initial value of the progress bar, from 0 to 100.
                Assign the handle's ``value`` to move it.
            visible: Whether the progress bar is visible.
            animated: Whether the progress bar is in an animated loading state.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add(
            GuiProgressBarHandle,
            _messages.GuiProgressBarProps(
                order=self._apply_default_order(order),
                value=initial_value,
                animated=animated,
                visible=visible,
            ),
            parent=self._get_container_uuid(),
        )

    def add_slider(
        self,
        label: str,
        initial_value: IntOrFloat,
        *,
        min: IntOrFloat,
        max: IntOrFloat,
        step: IntOrFloat,
        marks: tuple[IntOrFloat | tuple[IntOrFloat, str], ...] | None = None,
        show_value: bool = False,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiSliderHandle[IntOrFloat]:
        """Add a slider to the GUI. Types of the min, max, step, and initial value should match.

        Args:
            label: Label to display on the slider.
            initial_value: Initial value of the slider.
            min: Minimum value of the slider.
            max: Maximum value of the slider.
            step: Step size of the slider.
            marks: tuple of marks to display below the slider. Each mark should
                either be a numerical or a (number, label) tuple, where the
                label is provided as a string.
            show_value: Whether to place an editable number box beside the
                slider. Off by default, which leaves the slider the full width
                of the row; the marks below it still name the range.
            disabled: Whether the slider is disabled.
            visible: Whether the slider is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        value = initial_value
        # Browser edits are cast to the type of the stored value, so an int
        # value with float bounds would truncate every edit. Promote it.
        if type(value) is int and float in (type(min), type(max), type(step)):
            value = float(value)
        return self._add_input(
            GuiSliderHandle,
            value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
            min=min,
            max=max,
            step=step,
            precision=_compute_precision_digits(step),
            show_value=show_value,
            marks=marks,
        )

    def add_multi_slider(
        self,
        label: str,
        initial_value: tuple[IntOrFloat, ...],
        *,
        min: IntOrFloat,
        max: IntOrFloat,
        step: IntOrFloat,
        min_range: IntOrFloat | None = None,
        fixed_endpoints: bool = False,
        marks: tuple[IntOrFloat | tuple[IntOrFloat, str], ...] | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiMultiSliderHandle[IntOrFloat]:
        """Add a multi slider to the GUI. Types of the min, max, step, and initial value should match.

        Args:
            label: Label to display on the slider.
            min: Minimum value of the slider.
            max: Maximum value of the slider.
            step: Step size of the slider.
            initial_value: Initial values of the slider.
            min_range: Optional minimum difference between two values of the slider.
            fixed_endpoints: Whether the endpoints of the slider are fixed.
            marks: tuple of marks to display below the slider. Each mark should
                either be a numerical or a (number, label) tuple, where the
                label is provided as a string.
            disabled: Whether the slider is disabled.
            visible: Whether the slider is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        values = tuple(_validate_number(value, "initial_value entries") for value in initial_value)
        # Browser edits are cast to the type of the stored values; any float
        # argument makes them floats.
        if float in (type(min), type(max), type(step), type(min_range)):
            values = tuple(float(value) for value in values)
        return self._add_input(
            GuiMultiSliderHandle,
            values,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
            min=min,
            max=max,
            step=step,
            min_range=min_range,
            precision=_compute_precision_digits(step),
            fixed_endpoints=fixed_endpoints,
            marks=marks,
        )

    @overload
    def add_color(
        self,
        label: str,
        initial_value: tuple[float, float, float],
        *,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiColorHandle[tuple[int, int, int]]: ...

    @overload
    def add_color(
        self,
        label: str,
        initial_value: tuple[float, float, float, float],
        *,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiColorHandle[tuple[int, int, int, int]]: ...

    def add_color(
        self,
        label: str,
        initial_value: tuple[float, ...],
        *,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiColorHandle[Any]:
        """Add a color picker to the GUI: RGB for three channels, RGBA for four.

        Integer channels are in [0, 255]; float channels in [0, 1] are scaled to
        match (matplotlib convention), so ``1.0`` is white or opaque.

        Args:
            label: Label to display on the color picker.
            initial_value: Initial value, whose channel count the color keeps.
            disabled: Whether the color picker is disabled.
            visible: Whether the color picker is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self._add_input(
            GuiColorHandle,
            initial_value,
            label=label,
            hint=hint,
            disabled=disabled,
            visible=visible,
            order=order,
        )
