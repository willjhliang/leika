from __future__ import annotations

import asyncio
import builtins
import dataclasses
import threading
import time
import warnings
from asyncio import AbstractEventLoop
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Protocol,
    Sequence,
    TypeVar,
    cast,
    overload,
)

import numpy as np
from typing_extensions import (
    Literal,
    LiteralString,
    TypedDict,
    assert_never,
)

from . import _messages
from ._gui_handles import (
    PREVIEW_MAX_BYTES,
    CommandEvent,
    CommandHandle,
    DownloadContent,
    GuiButtonGroupHandle,
    GuiButtonHandle,
    GuiCheckboxHandle,
    GuiChecklistHandle,
    GuiContainer,
    GuiContainerProtocol,
    GuiDividerHandle,
    GuiDownloadButtonHandle,
    GuiDropdownHandle,
    GuiEvent,
    GuiFolderHandle,
    GuiFormHandle,
    GuiHtmlHandle,
    GuiImageHandle,
    GuiListHandle,
    GuiModalHandle,
    GuiMultiSliderHandle,
    GuiNumberHandle,
    GuiPlotlyHandle,
    GuiPreviewButtonHandle,
    GuiProgressBarHandle,
    GuiRgbaHandle,
    GuiRgbHandle,
    GuiSliderHandle,
    GuiTabGroupHandle,
    GuiTabHandle,
    GuiTextHandle,
    GuiToggleGroupHandle,
    GuiToggleHandle,
    GuiUploadButtonHandle,
    GuiVector2Handle,
    GuiVector3Handle,
    PreviewContent,
    SupportsRemoveProtocol,
    UploadedFile,
    _cast_vector,
    _checklist_items,
    _colors_to_int_tuple,
    _CommandHandleState,
    _GuiHandleState,
    _GuiInputHandle,
    _make_uuid,
    _plotly_json_with_config,
    _string_options,
    install_container_add_methods,
    not_container_scoped,
)
from ._icons import svg_from_icon
from ._icons_enum import IconName
from ._image_encoding import encode_image_binary
from ._messages import ButtonColor, FileTransferPartAck, GuiBaseProps, GuiSliderMark
from ._notification_handle import NotificationHandle, _NotificationHandleState
from ._threadpool_exceptions import print_threadpool_errors
from ._validation import (
    validate_finite_number as _validate_number,
)
from ._validation import (
    validate_nonnegative_integer as _validate_nonnegative_integer,
)
from ._validation import (
    validate_positive_number as _validate_positive_number,
)

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from ._server import ClientHandle, Server
    from .infra import ClientId

GuiInputPropsType = TypeVar("GuiInputPropsType", bound=GuiBaseProps)
IntOrFloat = TypeVar("IntOrFloat", int, float)
TString = TypeVar("TString", bound=str)
TLiteralString = TypeVar("TLiteralString", bound=LiteralString)
T = TypeVar("T")


def _compute_step(x: float | None) -> float:  # type: ignore
    """For number inputs: compute an increment size from some number.

    Example inputs/outputs:
        100 => 1
        12 => 1
        12.1 => 0.1
        12.02 => 0.01
        0.004 => 0.001
    """
    return 1 if x is None else 10 ** (-_compute_precision_digits(x))


def _validate_button_color(color: str) -> None:
    """Reject anything but the two button roles at runtime, where the
    ``Literal`` annotation alone would let ``"blue"`` through and quietly draw
    the default. Shared by ``add_button`` and ``add_upload_button``."""
    if color not in ("default", "inverse"):
        raise ValueError(
            f"Button color must be 'default' or 'inverse', not {color!r}. Buttons take"
            " a role rather than a color; the accent itself is a viewer setting."
        )


def _validate_file_content(content: object, filename: str | None, factory: str) -> None:
    """Reject the two ways a file button can be asked for at creation.

    What is left -- a function that turns out to return unnamed bytes -- can
    only be caught once it has run, and is raised from the handle.
    """
    if isinstance(content, str):
        raise TypeError(
            "content= must be bytes, a Path, or a function returning one of"
            " those; a str is neither a file's contents (encode it) nor a"
            " path we would guess at (wrap it in Path)."
        )
    if filename is None and isinstance(content, bytes):
        raise ValueError(
            f"filename= is required when the contents are bytes, which carry"
            f" no name of their own. Passed to {factory}."
        )


def _initial_toggles(
    options: tuple[str, ...],
    initial_value: bool | str | Sequence[str] | None,
    *,
    multiple: bool,
    required: bool,
) -> tuple[str, ...]:
    """Which options a row of toggles starts on, as a tuple in every case.

    Accepts the shapes a caller reaches for -- nothing, one option's text, or
    a sequence of them -- and rejects an option that is not in the row, which
    would otherwise start a group in a state the user cannot click their way
    back to. A required row left unset starts on its first option, since it is
    not allowed to be empty and something has to be chosen.
    """
    if initial_value is None:
        return (options[0],) if required else ()
    if isinstance(initial_value, bool):
        raise ValueError(
            "A row of toggles starts on the options named, so initial_value= is"
            f" an option or a sequence of them; got {initial_value!r}."
        )
    wanted = (initial_value,) if isinstance(initial_value, str) else tuple(initial_value)
    unknown = [option for option in wanted if option not in options]
    if len(unknown) > 0:
        raise ValueError(f"initial_value={unknown!r} is not among the options {options!r}.")
    if not multiple and len(wanted) > 1:
        raise ValueError(
            f"initial_value={wanted!r} turns on {len(wanted)} options, but this row"
            " holds one at a time. Pass multiple=True to allow several."
        )
    if required and len(wanted) == 0:
        raise ValueError(
            "A required row cannot start empty: pass the option to start on, or"
            " required=False to let the row hold nothing."
        )
    # Declaration order, not the order they were named: the value reads the
    # same way the row does.
    return tuple(option for option in options if option in wanted)


def _button_colors(
    count: int,
    color: ButtonColor | Sequence[ButtonColor],
    *,
    noun: str = "button",
) -> tuple[ButtonColor, ...]:
    """One colorway per BUTTON, the way ``_merge_flags`` gives one per gap: a
    single role answers for the whole row, a sequence one button at a time
    (a main action with something quieter beside it)."""
    if isinstance(color, str):
        _validate_button_color(color)
        return (color,) * count
    colors = tuple(color)
    if len(colors) != count:
        raise ValueError(
            f"color= takes one role per {noun}: {count} for this row, but got"
            f" {len(colors)}. Pass a single role to answer for every button at"
            " once."
        )
    for one in colors:
        _validate_button_color(one)
    return colors


def _merge_flags(count: int, merge: bool | Sequence[bool]) -> tuple[bool, ...]:
    """One flag per GAP between buttons: True joins the pair, False parts them.

    A single bool answers for every gap at once, which is the common case; a
    sequence answers each in turn, so a row can join some pairs and part
    others. Normalized here rather than in the client so the wire carries one
    shape, and so a mismatched length is a Python error with a Python
    traceback rather than a row that quietly renders wrong.
    """
    gaps = max(0, count - 1)
    if isinstance(merge, bool):
        return (merge,) * gaps
    flags = tuple(bool(flag) for flag in merge)
    if len(flags) != gaps:
        raise ValueError(
            f"merge= takes one flag per gap between buttons: {gaps} for {count}"
            f" button(s), but got {len(flags)}. Pass a single bool to answer for"
            " every gap at once."
        )
    return flags


def _build_slider_marks(
    marks: tuple[float | tuple[float, str], ...] | None,
) -> tuple[GuiSliderMark, ...] | None:
    """Normalize a slider's ``marks`` argument into ``GuiSliderMark`` tuples.
    Shared by add_slider and add_multi_slider so the two can't diverge."""
    if marks is None:
        return None
    return tuple(
        GuiSliderMark(value=float(x[0]), label=x[1])
        if isinstance(x, tuple)
        else GuiSliderMark(value=x, label=None)
        for x in marks
    )


def _infer_vector_step(
    value: tuple[float, ...],
    min: tuple[float, ...] | None,
    max: tuple[float, ...] | None,
    step: float | None,
) -> float:
    """Pick a default step for a vector input from its value/min/max components
    when the caller didn't pass one. Shared by add_vector2 and add_vector3 so
    the inference can't drift between the two."""
    if step is not None:
        return step
    possible_steps: list[float] = []
    possible_steps.extend([_compute_step(x) for x in value])
    if min is not None:
        possible_steps.extend([_compute_step(x) for x in min])
    if max is not None:
        possible_steps.extend([_compute_step(x) for x in max])
    return float(np.min(possible_steps))


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


@dataclasses.dataclass
class _RootGuiContainer:
    _children: dict[str, SupportsRemoveProtocol]


_global_order_counter = 0


def _apply_default_order(order: float | None) -> float:
    """Apply default ordering logic for GUI elements.

    If `order` is set to a float, this function is a no-op and returns it back.
    Otherwise, we increment and return the value of a global counter.
    """
    if order is not None:
        return order

    global _global_order_counter
    _global_order_counter += 1
    return _global_order_counter


class _FileUploadState(TypedDict):
    client_id: ClientId
    source_component_uuid: str
    filename: str
    part_count: int
    parts: dict[int, bytes]
    total_bytes: int
    transferred_bytes: int


class GuiApi(GuiContainer):
    """Interface for working with the 2D GUI in Leika.

    Used by both our global server object, for sharing the same GUI elements
    with all clients, and by individual client handles."""

    _container_stack_from_thread_id: dict[int, list[str]]
    """Containers each thread is currently inside, innermost last; new GUI
    elements go into the innermost one. A stack rather than a single ID so that
    nested ``with`` blocks -- including a container entered twice -- unwind to
    exactly where they started.

    Keyed by thread so concurrent builders do not see each other's target, and
    per-instance (NOT a shared class attribute) so a thread inside a ``with
    some_gui.add_folder()`` block cannot leak that target into a *different*
    GuiApi instance (e.g. server.gui vs a client.gui) and raise KeyError on the
    foreign uuid."""

    def __init__(
        self,
        owner: Server | ClientHandle,  # Who do I belong to?
        thread_executor: ThreadPoolExecutor,
        event_loop: AbstractEventLoop,
    ) -> None:
        from ._server import Server

        self._owner = owner
        """Entity that owns this API."""
        self._container_stack_from_thread_id = {}
        self._thread_executor = thread_executor
        self._event_loop = event_loop

        self._websock_interface = (
            owner._websock_server if isinstance(owner, Server) else owner._websock_connection
        )
        """Interface for sending and listening to messages."""

        self._gui_input_handle_from_uuid: dict[str, _GuiInputHandle[Any]] = {}
        self._container_handle_from_uuid: dict[str, GuiContainerProtocol] = {
            "root": _RootGuiContainer({})
        }
        self._modal_handle_from_uuid: dict[str, GuiModalHandle] = {}
        self._command_handle_from_uuid: dict[str, CommandHandle] = {}
        self._current_file_upload_states: dict[tuple[ClientId, str], _FileUploadState] = {}
        self._file_upload_lock = threading.RLock()

        # Set to True when plotly.min.js has been sent to client. The lock
        # keeps concurrent first adds from queueing the ~3MB payload twice.
        self._setup_plotly_js: bool = False
        self._setup_plotly_js_lock = threading.Lock()

        self._websock_interface.register_handler(
            _messages.GuiUpdateMessage, self._handle_gui_updates
        )
        self._websock_interface.register_handler(
            _messages.GuiButtonHoldMessage, self._handle_gui_button_hold
        )
        self._websock_interface.register_handler(
            _messages.GuiPreviewWarmMessage, self._handle_gui_preview_warm
        )
        self._websock_interface.register_handler(
            _messages.GuiPreviewReloadMessage, self._handle_gui_preview_reload
        )
        self._websock_interface.register_handler(
            _messages.GuiPreviewWatchMessage, self._handle_gui_preview_watch
        )
        self._websock_interface.register_handler(
            _messages.GuiFormSubmitMessage, self._handle_gui_form_submit
        )
        self._websock_interface.register_handler(
            _messages.FileTransferStartUpload, self._handle_file_transfer_start
        )
        self._websock_interface.register_handler(
            _messages.FileTransferPart,
            self._handle_file_transfer_part,
        )
        self._websock_interface.register_handler(
            _messages.CommandTriggerMessage, self._handle_command_trigger
        )
        self._websock_interface.register_handler(
            _messages.GuiCloseModalMessage, self._handle_gui_close_modal
        )

    @property
    def _child_gui_api(self) -> GuiApi:
        return self

    @property
    def _child_container_id(self) -> str:
        return "root"

    def _resolve_client(self, client_id: ClientId) -> ClientHandle | None:
        """Resolve the ClientHandle for a given client_id. Returns None when
        the client has disconnected between queuing and dispatch -- callers
        should early-return."""
        # Runtime import to break the circular edge with `_server`.
        from ._server import ClientHandle, Server

        if isinstance(self._owner, ClientHandle):
            return self._owner
        if isinstance(self._owner, Server):
            return self._owner._connected_clients.get(client_id, None)
        assert_never(self._owner)

    async def _handle_gui_updates(
        self, client_id: ClientId, message: _messages.GuiUpdateMessage
    ) -> None:
        """Callback for handling GUI messages."""
        handle = self._gui_input_handle_from_uuid.get(message.uuid, None)
        if handle is None or handle._impl.removed:
            return
        handle_state = handle._impl

        # `value` is the one property a client is allowed to write. Anything
        # else in the message is client-controlled data with no business on
        # `_GuiHandleState`, whose other attributes include the callbacks.
        if set(message.updates.keys()) != {"value"}:
            return
        prop_value = message.updates["value"]

        # Cast to the shape the handle holds, which is the handle's own to know.
        try:
            prop_value = handle._coerce_client_value(prop_value)
        except (TypeError, ValueError, OverflowError):
            return

        has_changed = handle_state.value != prop_value
        if has_changed:
            handle_state.value = prop_value
        updates_cast = {"value": prop_value}

        # Only call update when value has actually changed.
        if not handle_state.is_button and not has_changed:
            return

        # GUI element has been updated!
        handle_state.update_timestamp = time.time()
        client = self._resolve_client(client_id)
        if client is None:
            return
        for cb in tuple(handle_state.update_cb):
            if asyncio.iscoroutinefunction(cb):
                await cb(GuiEvent(client, client_id, handle))
            else:
                self._thread_executor.submit(
                    cb, GuiEvent(client, client_id, handle)
                ).add_done_callback(print_threadpool_errors)

        if handle_state.sync_cb is not None:
            handle_state.sync_cb(client_id, updates_cast)

    async def _handle_gui_button_hold(
        self, client_id: ClientId, message: _messages.GuiButtonHoldMessage
    ) -> None:
        """Callback for handling button hold messages."""
        handle = self._gui_input_handle_from_uuid.get(message.uuid, None)
        if handle is None or handle._impl.removed:
            return

        # Ensure this is a button handle with hold callbacks.
        if not isinstance(handle, GuiButtonHandle):
            return

        # Get callbacks registered for this frequency.
        callbacks = handle._hold_cbs_from_freq.get(message.frequency, [])
        if not callbacks:
            return

        client = self._resolve_client(client_id)
        if client is None:
            return

        # Call all callbacks for this frequency.
        for cb in tuple(callbacks):
            if asyncio.iscoroutinefunction(cb):
                await cb(GuiEvent(client, client_id, handle))
            else:
                self._thread_executor.submit(
                    cb, GuiEvent(client, client_id, handle)
                ).add_done_callback(print_threadpool_errors)

    def _preview_button_for(
        self, uuid: str, client_id: ClientId
    ) -> tuple[GuiPreviewButtonHandle, ClientHandle] | None:
        """The button a preview message names, and the client that sent it.

        None for every mismatch there is -- a stale uuid, a button that is not
        a preview button, a client gone between queueing and dispatch -- so
        that each of these messages can be a quiet return. All three are the
        browser asking on its own account about a file it was already sent;
        none of them is a press that a caller is waiting on, so there is
        nobody an error would reach.
        """
        handle = self._gui_input_handle_from_uuid.get(uuid, None)
        if handle is None or handle._impl.removed:
            return None
        if not isinstance(handle, GuiPreviewButtonHandle):
            return None
        client = self._resolve_client(client_id)
        if client is None:
            return None
        return handle, client

    async def _handle_gui_preview_warm(
        self, client_id: ClientId, message: _messages.GuiPreviewWarmMessage
    ) -> None:
        """A preview button has scrolled into view; start its press's transfer.

        Advisory: the press, if one comes, is unaffected either way -- it
        always sends fresh.
        """
        found = self._preview_button_for(message.uuid, client_id)
        if found is None:
            return
        handle, client = found
        self._thread_executor.submit(handle._warm, client).add_done_callback(
            print_threadpool_errors
        )

    async def _handle_gui_preview_reload(
        self, client_id: ClientId, message: _messages.GuiPreviewReloadMessage
    ) -> None:
        """A reader has asked an open preview for the file again.

        Off the thread pool like a press, and for the same reason: resolving
        the contents may run the caller's function, or read a large file off
        disk, and neither belongs on the event loop.
        """
        found = self._preview_button_for(message.uuid, client_id)
        if found is None:
            return
        handle, client = found
        self._thread_executor.submit(
            handle._reload, GuiEvent(client, client_id, handle)
        ).add_done_callback(print_threadpool_errors)

    async def _handle_gui_preview_watch(
        self, client_id: ClientId, message: _messages.GuiPreviewWatchMessage
    ) -> None:
        """An open preview is asking whether its file has moved on.

        Arrives on a timer for as long as a dialog is open, so the work it
        does when the answer is no has to be nothing much: one `stat`, off the
        event loop, and a return.
        """
        found = self._preview_button_for(message.uuid, client_id)
        if found is None:
            return
        handle, client = found
        self._thread_executor.submit(handle._watch, client, message.version).add_done_callback(
            print_threadpool_errors
        )

    async def _handle_gui_form_submit(
        self, client_id: ClientId, message: _messages.GuiFormSubmitMessage
    ) -> None:
        """Callback for client-initiated form submits.

        Fires the form's on_submit callbacks and broadcasts the submit back so
        every client closes the form's popout -- including the one that sent
        it, which waits to be told rather than closing on its own, so that all
        the ways of submitting end the same way.
        """
        handle = self._container_handle_from_uuid.get(message.uuid, None)
        if not isinstance(handle, GuiFormHandle):
            return

        client = self._resolve_client(client_id)
        if client is None:
            return

        for cb in tuple(handle._submit_cb):
            if asyncio.iscoroutinefunction(cb):
                await cb(GuiEvent(client, client_id, handle))
            else:
                self._thread_executor.submit(
                    cb, GuiEvent(client, client_id, handle)
                ).add_done_callback(print_threadpool_errors)

        # Broadcast so the clients showing this form close it.
        self._websock_interface.queue_message(_messages.GuiFormSubmitMessage(uuid=message.uuid))

    def _handle_file_transfer_start(
        self, client_id: ClientId, message: _messages.FileTransferStartUpload
    ) -> None:
        if (
            not message.transfer_uuid
            or message.part_count < 0
            or message.size_bytes < 0
            or (message.part_count == 0) != (message.size_bytes == 0)
            or (message.size_bytes > 0 and message.part_count > message.size_bytes)
        ):
            return

        key = (client_id, message.transfer_uuid)
        completion = None
        with self._file_upload_lock:
            handle = self._gui_input_handle_from_uuid.get(message.source_component_uuid)
            if not isinstance(handle, GuiUploadButtonHandle) or handle._impl.removed:
                return
            if key in self._current_file_upload_states:
                return
            self._current_file_upload_states[key] = {
                "client_id": client_id,
                "source_component_uuid": message.source_component_uuid,
                "filename": message.filename,
                "part_count": message.part_count,
                "parts": {},
                "total_bytes": message.size_bytes,
                "transferred_bytes": 0,
            }

            # Empty uploads have no part message to drive completion.
            if message.part_count == 0:
                self._websock_interface.queue_message(
                    FileTransferPartAck(
                        source_component_uuid=message.source_component_uuid,
                        transfer_uuid=message.transfer_uuid,
                        transferred_bytes=0,
                        total_bytes=0,
                    )
                )
                completion = self._complete_file_upload_locked(key)

        if completion is not None:
            self._dispatch_file_upload_completion(completion)

    def _complete_file_upload_locked(
        self,
        key: tuple[ClientId, str],
    ) -> (
        tuple[
            ClientId,
            GuiUploadButtonHandle,
            tuple[Callable[..., Any], ...],
        ]
        | None
    ):
        """Consume a completed upload while ``_file_upload_lock`` is held."""
        state = self._current_file_upload_states.pop(key, None)
        if state is None:
            return None

        handle = self._gui_input_handle_from_uuid.get(state["source_component_uuid"])
        if not isinstance(handle, GuiUploadButtonHandle) or handle._impl.removed:
            return None
        handle_state = handle._impl

        value = UploadedFile(
            name=state["filename"],
            content=b"".join(state["parts"][i] for i in range(state["part_count"])),
        )

        # Update state.
        handle_state.value = value
        handle_state.update_timestamp = time.time()
        return state["client_id"], handle, tuple(handle_state.update_cb)

    def _dispatch_file_upload_completion(
        self,
        completion: tuple[
            ClientId,
            GuiUploadButtonHandle,
            tuple[Callable[..., Any], ...],
        ],
    ) -> None:
        """Run completion callbacks without holding the upload-state lock."""
        client_id, handle, callbacks = completion
        client = self._resolve_client(client_id)
        if client is None:
            return
        for cb in callbacks:
            if asyncio.iscoroutinefunction(cb):
                self._event_loop.create_task(cb(GuiEvent(client, client_id, handle)))
            else:
                self._thread_executor.submit(
                    cb, GuiEvent(client, client_id, handle)
                ).add_done_callback(print_threadpool_errors)

    def _handle_file_transfer_part(
        self, client_id: ClientId, message: _messages.FileTransferPart
    ) -> None:
        key = (client_id, message.transfer_uuid)
        completion = None
        with self._file_upload_lock:
            state = self._current_file_upload_states.get(key)
            if state is None:
                return
            if message.source_component_uuid != state["source_component_uuid"]:
                return
            handle = self._gui_input_handle_from_uuid.get(state["source_component_uuid"])
            if not isinstance(handle, GuiUploadButtonHandle) or handle._impl.removed:
                self._current_file_upload_states.pop(key, None)
                return
            if not 0 <= message.part_index < state["part_count"]:
                return
            if message.part_index in state["parts"]:
                return
            transferred_bytes = state["transferred_bytes"] + len(message.content)
            if transferred_bytes > state["total_bytes"]:
                self._current_file_upload_states.pop(key, None)
                return

            state["parts"][message.part_index] = message.content
            state["transferred_bytes"] = transferred_bytes
            total_bytes = state["total_bytes"]
            self._websock_interface.queue_message(
                FileTransferPartAck(
                    source_component_uuid=state["source_component_uuid"],
                    transfer_uuid=message.transfer_uuid,
                    transferred_bytes=transferred_bytes,
                    total_bytes=total_bytes,
                )
            )

            if len(state["parts"]) < state["part_count"]:
                return
            if transferred_bytes != total_bytes:
                self._current_file_upload_states.pop(key, None)
                return
            completion = self._complete_file_upload_locked(key)

        if completion is not None:
            self._dispatch_file_upload_completion(completion)

    def _discard_file_uploads(
        self,
        *,
        client_id: ClientId | None = None,
        source_component_uuid: str | None = None,
    ) -> None:
        """Discard incomplete uploads for a disconnected client or removed button."""
        with self._file_upload_lock:
            stale = [
                key
                for key, state in self._current_file_upload_states.items()
                if (client_id is None or state["client_id"] == client_id)
                and (
                    source_component_uuid is None
                    or state["source_component_uuid"] == source_component_uuid
                )
            ]
            for key in stale:
                self._current_file_upload_states.pop(key, None)

    async def _handle_command_trigger(
        self, client_id: ClientId, message: _messages.CommandTriggerMessage
    ) -> None:
        """Callback for handling command trigger messages from the command palette."""
        handle = self._command_handle_from_uuid.get(message.uuid, None)
        if handle is None or handle._impl.removed:
            return
        handle_state = handle._impl
        if handle_state.props.disabled:
            return

        client = self._resolve_client(client_id)
        if client is None:
            return

        for cb in tuple(handle_state.trigger_cb):
            if asyncio.iscoroutinefunction(cb):
                await cb(CommandEvent(client, client_id, handle))
            else:
                self._thread_executor.submit(
                    cb, CommandEvent(client, client_id, handle)
                ).add_done_callback(print_threadpool_errors)

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
        handle = self._modal_handle_from_uuid.get(message.uuid, None)
        if handle is None:
            return
        handle.close()

    def _get_container_uuid(self) -> str:
        """Container that new GUI elements on this thread belong to."""
        stack = self._container_stack_from_thread_id.get(threading.get_ident())
        return stack[-1] if stack else "root"

    def _push_container_uuid(self, container_uuid: str) -> None:
        """Direct new GUI elements on this thread into ``container_uuid``."""
        self._container_stack_from_thread_id.setdefault(threading.get_ident(), []).append(
            container_uuid
        )

    def _pop_container_uuid(self) -> None:
        """Undo the matching :meth:`_push_container_uuid`.

        The thread's entry is dropped once it is empty, so a pool thread that
        finishes a build leaves nothing behind."""
        thread_id = threading.get_ident()
        stack = self._container_stack_from_thread_id[thread_id]
        stack.pop()
        if not stack:
            del self._container_stack_from_thread_id[thread_id]

    def reset(self) -> None:
        """Reset the GUI."""
        root_container = self._container_handle_from_uuid["root"]
        while root_container._children:
            next(iter(root_container._children.values())).remove()
        while self._modal_handle_from_uuid:
            next(iter(self._modal_handle_from_uuid.values())).close()
        while self._command_handle_from_uuid:
            next(iter(self._command_handle_from_uuid.values())).remove()

    def set_panel_label(self, label: str | None) -> None:
        """Set the main label that appears in the GUI panel.

        Args:
            label: The new label.
        """
        self._websock_interface.queue_message(_messages.SetGuiPanelLabelMessage(label))

    def configure_theme(
        self,
        *,
        control_layout: Literal["floating", "left", "right"] = "floating",
        dark_mode: bool | Literal["auto"] = "auto",
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
            dark_mode: ``True`` or ``False`` to pin the scheme for every client.
                       The default, ``"auto"``, follows each browser's own
                       ``prefers-color-scheme`` and tracks it if the viewer
                       changes their OS setting mid-session.
        """

        if control_layout not in ("floating", "left", "right"):
            raise ValueError(
                "control_layout must be 'floating', 'left', or 'right'. The"
                " 'collapsible' and 'fixed' sidebar layouts were removed; use"
                " 'left' or 'right' to start the panel docked to that edge."
            )
        if dark_mode != "auto" and type(dark_mode) is not bool:
            raise ValueError("dark_mode must be True, False, or 'auto'.")

        self._websock_interface.queue_message(
            _messages.ThemeConfigurationMessage(
                control_layout=control_layout,
                dark_mode=dark_mode,
            ),
        )

    @not_container_scoped
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
                ``None`` keeps it up until it is closed or removed.
        """
        if auto_close_seconds is not None:
            _validate_number(auto_close_seconds, "auto_close_seconds")
            if auto_close_seconds < 0:
                raise ValueError("auto_close_seconds must be non-negative or None.")
        handle = NotificationHandle(
            _NotificationHandleState(
                websock_interface=self._websock_interface,
                uuid=_make_uuid(),
                props=_messages.NotificationProps(
                    title=title,
                    body=body,
                    loading=loading,
                    with_close_button=with_close_button,
                    auto_close_seconds=auto_close_seconds,
                ),
            )
        )
        handle._show()

        if auto_close_seconds is not None:
            # Auto-close happens in each client, so nothing server-side would
            # ever retire the notification: without this, every auto-closed
            # toast is replayed to each newly connecting client, forever. The
            # tombstone replaces the show message in the broadcast buffer; the
            # handle is left usable, so this is not a `remove()`.
            def _expire() -> None:
                if not handle._impl.removed:
                    self._websock_interface.queue_message(
                        _messages.RemoveNotificationMessage(handle._impl.uuid)
                    )

            self._event_loop.call_soon_threadsafe(
                self._event_loop.call_later, auto_close_seconds, _expire
            )
        return handle

    @not_container_scoped
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
        if hotkey is None and modifier is not None:
            raise ValueError("add_command(modifier=...) requires hotkey= to also be set.")
        # Validate + canonicalize the modifier string. Raises on bad input.
        normalized_modifier = _messages._normalize_key_modifier(modifier)
        command_uuid = _make_uuid()
        props = _messages.CommandProps(
            label=label,
            description=description,
            hotkey=hotkey,
            modifier=normalized_modifier,
            disabled=disabled,
            _icon_html=None if icon is None else svg_from_icon(icon),
        )
        # Register in the local map before publishing, so an immediate
        # trigger from the client can be resolved here.
        handle_state = _CommandHandleState(
            uuid=command_uuid,
            gui_api=self,
            props=props,
            icon=icon,
        )
        handle = CommandHandle(handle_state)
        self._command_handle_from_uuid[command_uuid] = handle
        self._websock_interface.queue_message(
            _messages.RegisterCommandMessage(
                uuid=command_uuid,
                props=props,
            )
        )
        if callback is not None:
            # The shorthand callback takes no arguments; adapt it to the
            # event-taking signature that on_trigger expects.
            if asyncio.iscoroutinefunction(callback):

                async def trigger_async(_: CommandEvent) -> None:
                    await callback()

                handle.on_trigger(trigger_async)
            else:

                def trigger_sync(_: CommandEvent) -> None:
                    callback()

                handle.on_trigger(trigger_sync)
        return handle

    def add_folder(
        self,
        label: str | None,
        *,
        order: float | None = None,
        expand_by_default: bool = True,
        visible: bool = True,
    ) -> GuiFolderHandle:
        """Add a folder, and return a handle that can be used to populate it.

        Args:
            label: Label to display on the folder. If ``None``, the folder is
                rendered without a header or collapse control, which is useful for pure
                layout grouping.
            order: Optional ordering, smallest values will be displayed first.
            expand_by_default: Open the folder by default. Set to False to collapse it by
                default. Ignored when ``label`` is ``None``.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used as a context to populate the folder.
        """
        folder_container_id = _make_uuid()
        order = _apply_default_order(order)
        props = _messages.GuiFolderProps(
            order=order,
            label=label,
            expand_by_default=expand_by_default,
            visible=visible,
        )
        self._websock_interface.queue_message(
            _messages.GuiFolderMessage(
                uuid=folder_container_id,
                container_uuid=self._get_container_uuid(),
                props=props,
            )
        )
        return GuiFolderHandle(
            _GuiHandleState(
                folder_container_id,
                self,
                None,
                props=props,
                parent_container_id=self._get_container_uuid(),
            )
        )

    def add_form(
        self,
        *,
        label: str | None = None,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiFormHandle:
        """Add a form, and return a handle that can be used to populate it.

        See :class:`GuiFormHandle` for usage and semantics.

        Args:
            label: Label shown beside the form's row, opposite the button that
                opens it. If ``None``, that button takes the whole row, the
                same rule a labelless :meth:`add_button` follows.
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used as a context to populate the form.
        """
        handle = self._create_form(label=label, order=order, visible=visible, mini=False)
        # Reset parted from Submit -- they are opposite moves, and joining
        # them would invite the wrong one -- with the accent behind Submit alone.
        with handle:
            handle.actions = self.add_button(
                ("Reset", "Submit"), color=("default", "inverse"), merge=False
            )

        def _act(event: GuiEvent[GuiButtonGroupHandle]) -> None:
            if event.target.value == "Reset":
                handle.reset_form()
            else:
                handle.submit_form()

        handle.actions.on_click(_act)
        return handle

    def add_mini_form(
        self,
        *,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiFormHandle:
        """Add a form around a single field, and return a handle to populate it.

        The same commit semantics as :meth:`add_form` in the space of one row:
        no popout and no row of its own, just the field's own row with a send
        button on the end of it. One field is not worth a door.

        Exactly one field goes inside -- a second raises :class:`ValueError`
        when the form's context closes. Sending is the button, or Enter in a
        single-line text input, and both fire :meth:`GuiFormHandle.on_submit`.
        There is no Reset: with one field, undoing is retyping.

        Args:
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used as a context to populate the form.

        Example::

            with server.gui.add_mini_form() as ask:
                query = server.gui.add_text("Search", "")

            @ask.on_submit
            def _(event):
                run_search(query.value)
        """
        return self._create_form(label=None, order=order, visible=visible, mini=True)

    def _create_form(
        self,
        *,
        label: str | None,
        order: float | None,
        visible: bool,
        mini: bool,
    ) -> GuiFormHandle:
        """The container both form flavors are built on."""
        # Nested forms would produce invalid HTML on the client (nested
        # <form> elements are not allowed and the browser flattens
        # them). Walk through folders, tabs, and tab groups -- they
        # share a DOM context with their ancestors. Stop at modals,
        # which render into a separate React portal where a fresh
        # <form> is well-formed.
        container = self._get_container_uuid()
        while container != "root":
            parent = self._container_handle_from_uuid.get(container)
            if isinstance(parent, GuiFormHandle):
                raise ValueError(
                    "Nested forms are not supported: add_form() was called "
                    "inside an existing form's context."
                )
            if isinstance(parent, GuiModalHandle):
                break
            if isinstance(parent, GuiTabHandle):
                container = parent._parent._impl.parent_container_id
            elif isinstance(parent, (GuiFolderHandle, GuiTabGroupHandle)):
                container = parent._impl.parent_container_id
            else:
                break

        form_container_id = _make_uuid()
        order = _apply_default_order(order)
        props = _messages.GuiFormProps(
            order=order,
            label=label,
            visible=visible,
            mini=mini,
        )
        self._websock_interface.queue_message(
            _messages.GuiFormMessage(
                uuid=form_container_id,
                container_uuid=self._get_container_uuid(),
                props=props,
            )
        )
        handle = GuiFormHandle(
            _GuiHandleState(
                form_container_id,
                self,
                None,
                props=props,
                parent_container_id=self._get_container_uuid(),
            )
        )
        return handle

    @not_container_scoped
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
        modal_container_id = _make_uuid()
        order = _apply_default_order(order)
        self._websock_interface.queue_message(
            _messages.GuiModalMessage(
                order=order,
                uuid=modal_container_id,
                title=title,
            )
        )
        return GuiModalHandle(
            _gui_api=self,
            _uuid=modal_container_id,
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
        tab_group_id = _make_uuid()
        order = _apply_default_order(order)

        message = _messages.GuiTabGroupMessage(
            uuid=tab_group_id,
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiTabGroupProps(
                order=order,
                _tabs=(),
                visible=visible,
            ),
        )
        self._websock_interface.queue_message(message)
        return GuiTabGroupHandle(
            _GuiHandleState(
                message.uuid,
                self,
                value=None,
                props=message.props,
                parent_container_id=message.container_uuid,
            )
        )

    def add_html(
        self,
        content: str,
        *,
        order: float | None = None,
        visible: bool = True,
    ) -> GuiHtmlHandle:
        """Add HTML to the GUI.

        Args:
            content: HTML content to display.
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        message = _messages.GuiHtmlMessage(
            uuid=_make_uuid(),
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiHtmlProps(
                order=_apply_default_order(order),
                content=content,
                visible=visible,
            ),
        )
        self._websock_interface.queue_message(message)

        handle = GuiHtmlHandle(
            _GuiHandleState(
                message.uuid,
                self,
                None,
                props=message.props,
                parent_container_id=message.container_uuid,
            ),
        )
        return handle

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
        message = _messages.GuiDividerMessage(
            uuid=_make_uuid(),
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiDividerProps(
                order=_apply_default_order(order),
                visible=visible,
            ),
        )
        self._websock_interface.queue_message(message)

        handle = GuiDividerHandle(
            _GuiHandleState(
                message.uuid,
                self,
                None,
                props=message.props,
                parent_container_id=message.container_uuid,
            ),
        )
        return handle

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
        image_array = np.asarray(image)
        if format == "jpeg" and image_array.ndim == 3 and image_array.shape[2] == 4:
            warnings.warn(
                "Encoding an RGBA image as JPEG discards its alpha channel.",
                stacklevel=2,
            )
        resolved_format, data = encode_image_binary(image_array, format, jpeg_quality=jpeg_quality)
        message = _messages.GuiImageMessage(
            uuid=_make_uuid(),
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiImageProps(
                _data=data,
                label=label,
                _format=resolved_format,
                order=_apply_default_order(order),
                visible=visible,
            ),
        )
        self._websock_interface.queue_message(message)

        return GuiImageHandle(
            _GuiHandleState(
                message.uuid,
                self,
                None,
                props=message.props,
                parent_container_id=message.container_uuid,
            ),
            _image=image_array,
            _jpeg_quality=jpeg_quality,
            _user_format=format,
        )

    def _ensure_plotly_js_sent(self) -> None:
        """Send plotly.min.js to clients, once. Plotly figures cannot be
        rendered client-side until this arrives."""
        with self._setup_plotly_js_lock:
            if self._setup_plotly_js:
                return

            # Check if plotly is installed.
            try:
                import plotly
            except ImportError:
                raise ImportError(
                    "You must have the `plotly` package installed to use the Plotly GUI element."
                )

            # Check that plotly.min.js exists.
            plotly_file = plotly.__file__
            if plotly_file is None:
                raise ImportError("Could not locate the installed `plotly` package.")
            plotly_path = Path(plotly_file).parent / "package_data" / "plotly.min.js"
            assert plotly_path.exists(), f"Could not find plotly.min.js at {plotly_path}."

            # Send it over!
            plotly_js = plotly_path.read_text(encoding="utf-8")
            self._websock_interface.queue_message(_messages.RunJavascriptMessage(source=plotly_js))

            # Update the flag so we don't send it again.
            self._setup_plotly_js = True

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
            figure: Plotly figure to display.
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

        _validate_positive_number(aspect, "aspect")

        # Plotly must be available before the figure creation message.
        self._ensure_plotly_js_sent()

        # After plotly.min.js has been sent, we can send the plotly figure.
        message = _messages.GuiPlotlyMessage(
            uuid=_make_uuid(),
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiPlotlyProps(
                order=_apply_default_order(order),
                _plotly_json_str=_plotly_json_with_config(figure, config),
                aspect=aspect,
                visible=visible,
            ),
        )
        self._websock_interface.queue_message(message)

        return GuiPlotlyHandle(
            _GuiHandleState(
                message.uuid,
                self,
                value=None,
                props=message.props,
                parent_container_id=message.container_uuid,
            ),
            _figure=figure,
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
            return self._add_button_group(
                text,
                label=label,
                color=color,
                merge=merge,
                disabled=disabled,
                visible=visible,
                hint=hint,
                order=order,
            )

        if not isinstance(merge, bool):
            raise ValueError(
                "merge= is about the gaps between buttons in a row; a single button has none."
            )
        if not isinstance(color, str):
            raise ValueError(
                "color= takes one role per button, and a single button is one button;"
                " pass the role itself rather than a sequence."
            )
        _validate_button_color(color)

        # Re-wrap the GUI handle with a button interface.
        uuid = _make_uuid()
        order = _apply_default_order(order)
        props = _messages.GuiButtonProps(
            order=order,
            label=label,
            text=text,
            hint=hint,
            color=color,
            _icon_html=None if icon is None else svg_from_icon(icon),
            _hold_callback_freqs=(),
            _prefetch=False,
            disabled=disabled,
            visible=visible,
        )
        message = _messages.GuiButtonMessage(
            value=False,
            uuid=uuid,
            container_uuid=self._get_container_uuid(),
            props=props,
        )

        return GuiButtonHandle(self._create_gui_input(False, message, is_button=True), _icon=icon)

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
        """Add a button to the GUI. The value of this input is set to `True` every time
        it is clicked; to detect clicks, we can manually set it back to `False`.

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

        _validate_button_color(color)

        # Re-wrap the GUI handle with a button interface.
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiUploadButtonHandle(
            self._create_gui_input(
                value=UploadedFile("", b""),
                message=_messages.GuiUploadButtonMessage(
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiUploadButtonProps(
                        disabled=disabled,
                        visible=visible,
                        order=order,
                        label=label,
                        text=text,
                        hint=hint,
                        color=color,
                        mime_type=mime_type,
                        _icon_html=None if icon is None else svg_from_icon(icon),
                    ),
                ),
                is_button=True,
            ),
            _icon=icon,
        )

    def add_download_button(
        self,
        text: str,
        content: DownloadContent,
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
        as it arrives, and the button stays disabled until the transfer is out,
        so a slow export cannot be started twice. Sending a file at a moment
        that is not a click -- when a job finishes, on a timer -- is what the
        underlying method is for, and it can offer the file as a link instead.

        Args:
            text: Text on the button's face.
            content: What to send. Bytes are sent as they are; a
                :class:`~pathlib.Path` is read when the button is pressed and
                streamed a chunk at a time, so the file may change, or outgrow
                memory, after the button is made. A function is called on each
                press with the click event and returns either -- run in a
                thread pool if defined with ``def``, on the event loop if
                defined with ``async def``. Note that a `str` is neither: text
                has to be encoded, and a path has to be a Path.
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

        _validate_button_color(color)
        _validate_file_content(content, filename, "add_download_button()")

        uuid = _make_uuid()
        order = _apply_default_order(order)
        props = _messages.GuiButtonProps(
            order=order,
            label=label,
            text=text,
            hint=hint,
            color=color,
            _icon_html=None if icon is None else svg_from_icon(icon),
            _hold_callback_freqs=(),
            _prefetch=False,
            disabled=disabled,
            visible=visible,
        )
        message = _messages.GuiButtonMessage(
            value=False,
            uuid=uuid,
            container_uuid=self._get_container_uuid(),
            props=props,
        )

        handle = GuiDownloadButtonHandle(
            self._create_gui_input(False, message, is_button=True),
            _icon=icon,
            _content=content,
            _filename=filename,
        )
        # Registered ahead of any `on_click` the caller adds, so the file is on
        # its way before whatever else the press was meant to do.
        handle._impl.update_cb.append(handle._send)
        return handle

    def add_preview_button(
        self,
        text: str,
        content: PreviewContent,
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
                function of the click event returning either.
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

        _validate_button_color(color)
        _validate_file_content(content, filename, "add_preview_button()")
        _validate_nonnegative_integer(max_bytes, "max_bytes")

        uuid = _make_uuid()
        order = _apply_default_order(order)
        message = _messages.GuiButtonMessage(
            value=False,
            uuid=uuid,
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiButtonProps(
                order=order,
                label=label,
                text=text,
                hint=hint,
                color=color,
                _icon_html=None if icon is None else svg_from_icon(icon),
                _hold_callback_freqs=(),
                _prefetch=True,
                disabled=disabled,
                visible=visible,
            ),
        )

        handle = GuiPreviewButtonHandle(
            self._create_gui_input(False, message, is_button=True),
            _icon=icon,
            _content=content,
            _filename=filename,
            _max_bytes=max_bytes,
        )
        handle._impl.update_cb.append(handle._send)
        return handle

    def _add_button_group(
        self,
        options: Sequence[str],
        *,
        label: str | None,
        color: ButtonColor | Sequence[ButtonColor],
        merge: bool | Sequence[bool],
        disabled: bool,
        visible: bool,
        hint: str | None,
        order: float | None,
    ) -> GuiButtonGroupHandle:
        """The many-faced half of :meth:`add_button`."""
        options = _string_options(options, "add_button()")
        value = options[0]
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiButtonGroupHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiButtonGroupMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiButtonGroupProps(
                        order=order,
                        label=label,
                        hint=hint,
                        color=_button_colors(len(options), color),
                        options=options,
                        _merge=_merge_flags(len(options), merge),
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
                is_button=True,
            ),
        )

    @overload
    def add_toggle(
        self,
        text: str,
        *,
        initial_value: bool = False,
        label: str | None = None,
        color: Literal["default", "inverse"] = "default",
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        icon: IconName | None = None,
        order: float | None = None,
    ) -> GuiToggleHandle: ...

    @overload
    def add_toggle(
        self,
        text: list[str] | tuple[str, ...],
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
        icon: None = None,
        order: float | None = None,
    ) -> GuiToggleGroupHandle: ...

    def add_toggle(
        self,
        text: str | list[str] | tuple[str, ...],
        *,
        initial_value: bool | str | Sequence[str] | None = None,
        label: str | None = None,
        color: ButtonColor | Sequence[ButtonColor] = "default",
        multiple: bool = False,
        required: bool | None = None,
        merge: bool | Sequence[bool] = True,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        icon: IconName | None = None,
        order: float | None = None,
    ) -> GuiToggleHandle | GuiToggleGroupHandle:
        """Add a toggle, or a row of them, to the GUI.

        A toggle is a button that stays pressed: same faces, same colorways,
        same label rule and heights as :meth:`add_button`, but it holds its
        state instead of firing and returning to rest. On, it takes the
        appearance that button has under the pointer at the moment of a click.

        Passing a string gives one toggle, whose value is whether it is on.
        Passing a sequence gives a row of them, whose value is the tuple of
        options currently on -- a tuple in both modes, so reading a group does
        not depend on how it was configured.

        Args:
            text: Text on the toggle's face. A sequence gives a row with one
                toggle per entry.
            initial_value: What starts on: a bool for a single toggle, and for
                a row either one option's text or a sequence of them. Left
                unset, everything starts off.
            label: Optional label for the row; see :meth:`add_button`.
            color: Colorway; see :meth:`add_button`.
            multiple: Whether more than one option in a row may be on at once.
                Off by default, which makes the row a choice between its
                options: turning one on turns the others off.
            required: Whether one option must always be on, so the toggle that
                is on cannot be turned off. Left unset, a row behaves like the
                control it resembles: one at a time requires a choice, the way
                a radio group does, and a ``multiple`` row does not, the way
                checkboxes do not. A required row given no ``initial_value``
                starts on its first option.
            merge: Whether neighbouring toggles are joined or parted; see
                :meth:`add_button`.
            disabled: Whether the toggle is disabled.
            visible: Whether the toggle is visible.
            hint: Optional hint to display on hover.
            icon: Optional icon to display on the toggle. Single toggles only,
                for the reason :meth:`add_button` gives.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """

        if isinstance(text, str):
            if not isinstance(merge, bool):
                raise ValueError(
                    "merge= is about the gaps between toggles in a row; a single toggle has none."
                )
            if not isinstance(color, str):
                raise ValueError(
                    "color= takes one role per toggle, and a single toggle is one"
                    " toggle; pass the role itself rather than a sequence."
                )
            _validate_button_color(color)
            if multiple or required is not None:
                raise ValueError(
                    "multiple= and required= are about how many options in a ROW may be"
                    " on; a single toggle is simply on or off."
                )
            if initial_value is not None and not isinstance(initial_value, bool):
                raise ValueError(
                    "A single toggle is on or off, so initial_value= is a bool;"
                    f" got {initial_value!r}."
                )
            uuid = _make_uuid()
            order = _apply_default_order(order)
            return GuiToggleHandle(
                self._create_gui_input(
                    initial_value is True,
                    message=_messages.GuiToggleMessage(
                        value=initial_value is True,
                        uuid=uuid,
                        container_uuid=self._get_container_uuid(),
                        props=_messages.GuiToggleProps(
                            order=order,
                            label=label,
                            text=text,
                            hint=hint,
                            color=color,
                            disabled=disabled,
                            visible=visible,
                            _icon_html=None if icon is None else svg_from_icon(icon),
                        ),
                    ),
                )
            )

        if icon is not None:
            raise ValueError(
                "icon= is for a single toggle; a row has one face per option and"
                " nowhere to say which of them the icon belongs to."
            )
        if type(multiple) is not bool:
            raise ValueError("multiple must be a bool.")
        if required is not None and type(required) is not bool:
            raise ValueError("required must be a bool or None.")
        options = _string_options(text, "add_toggle()")
        # A row behaves like the control it resembles unless told otherwise: a
        # choice between options is required the way a radio group is, and a row
        # of independent switches is not, the way checkboxes are not.
        required = (not multiple) if required is None else required
        value = _initial_toggles(options, initial_value, multiple=multiple, required=required)
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiToggleGroupHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiToggleGroupMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiToggleGroupProps(
                        order=order,
                        label=label,
                        hint=hint,
                        color=_button_colors(len(options), color, noun="toggle"),
                        options=options,
                        multiple=multiple,
                        required=required,
                        _merge=_merge_flags(len(options), merge),
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
            )
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
        value = initial_value
        if not isinstance(value, bool):
            raise ValueError(f"initial_value must be a bool, not {type(value).__name__}.")
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiCheckboxHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiCheckboxMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiCheckboxProps(
                        order=order,
                        label=label,
                        hint=hint,
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
            )
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
            image_root: Optional root directory to resolve relative image paths in
                markdown against.
            disabled: Whether an editable box is disabled.
            visible: Whether the text is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        value = initial_value
        if not isinstance(value, str):
            raise ValueError(f"initial_value must be a string, not {type(value).__name__}.")
        if rows is not None:
            if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
                raise ValueError(
                    f"rows= is a height in lines and must be a positive integer; got {rows!r}."
                )
        uuid = _make_uuid()
        order = _apply_default_order(order)
        handle = GuiTextHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiTextMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiTextProps(
                        order=order,
                        label=label,
                        hint=hint,
                        disabled=disabled,
                        visible=visible,
                        editable=editable,
                        markdown=markdown,
                        multiline=multiline,
                        rows=rows,
                        _source=value,
                    ),
                ),
            ),
            _image_root=image_root,
        )
        # Resolving the image paths needs the root, so it cannot be done above:
        # the handle is what holds it. Nothing is sent twice -- the create
        # message is still queued, and this updates it before it goes out.
        handle._refresh_source()
        return handle

    def add_list(
        self,
        label: str | None = None,
        initial_value: Sequence[str] = (),
        *,
        frozen: bool = False,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiListHandle:
        """Add an editable list of text entries to the GUI.

        A stack of text boxes rather than one: the value is a tuple of strings,
        and a viewer can edit any of them, add an entry, remove one, or drag
        one to another place in the list. Every one of those reports the whole
        tuple, so ``on_update`` sees the list as it now reads.

        Args:
            initial_value: The entries the list starts with. An empty list is
                a list with nothing in it yet, not an error.
            label: Optional label for the row. Left unset, the list takes the
                whole width of the panel, which a stack of boxes usually wants;
                given one, the label takes the left column and the entries sit
                beside it, like every other labelled control.
            frozen: Fix the list's length and order. The entries can still be
                edited; what goes is adding, removing, and reordering, along
                with the controls that do them. Use ``disabled`` to stop the
                editing too.
            disabled: Whether the list is disabled.
            visible: Whether the list is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        if isinstance(initial_value, str):
            raise ValueError("add_list() initial_value must be a sequence, not one string.")
        entries = tuple(initial_value)
        for entry in entries:
            if not isinstance(entry, str):
                raise ValueError(
                    "add_list() holds text entries, so initial_value= is a sequence of"
                    f" strings; got {entry!r}. Pass str(...) for anything else."
                )
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiListHandle(
            self._create_gui_input(
                entries,
                message=_messages.GuiListMessage(
                    value=entries,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiListProps(
                        order=order,
                        label=label,
                        hint=hint,
                        disabled=disabled,
                        visible=visible,
                        frozen=frozen,
                    ),
                ),
            )
        )

    def add_checklist(
        self,
        label: str | None = None,
        initial_value: Sequence[str | tuple[str, bool]] = (),
        *,
        frozen: bool = False,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiChecklistHandle:
        """Add a checklist to the GUI: entries with a box each to tick.

        A list whose rows carry an answer. The value is one ``(text, checked)``
        pair per item, in the order they are shown, so it reads back the way it
        is written::

            for text, checked in items.value:
                ...

        An item given as a bare string is one nobody has ticked yet, which
        saves a ``False`` per line and is what makes ``items.value +=
        ("Lights",)`` work::

            items = server.gui.add_checklist("Preflight",
                                             ["Fuel", ("Doors", True)])
            items.checked  # ("Doors",)

        Everything a viewer can do -- ticking a box, typing in an entry, adding
        one, removing one, dragging one somewhere else -- reports the whole
        tuple, and a row's tick travels with the words it is against.

        Args:
            label: Optional label for the row. Left unset, the checklist takes
                the whole width of the panel, which a stack of rows usually
                wants; given one, the label takes the left column and the items
                sit beside it, like every other labelled control.
            initial_value: The items the checklist starts with, each a string or
                a ``(text, checked)`` pair. An empty checklist is one with
                nothing on it yet, not an error.
            frozen: Fix the items: their words, their number, and their order.
                Frozen, a row is the words rather than a box to type them in,
                and all the viewer does is tick -- which is the checklist that
                is a checklist rather than a list to write. Stronger than a
                list's ``frozen``, which leaves the typing alone: here the
                answer being asked for is the ticks. Use ``disabled`` to stop
                those too.
            disabled: Whether the checklist is disabled.
            visible: Whether the checklist is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        items = _checklist_items(initial_value)
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiChecklistHandle(
            self._create_gui_input(
                items,
                message=_messages.GuiChecklistMessage(
                    value=items,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiChecklistProps(
                        order=order,
                        label=label,
                        hint=hint,
                        disabled=disabled,
                        visible=visible,
                        frozen=frozen,
                    ),
                ),
            )
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
        value: IntOrFloat = initial_value
        _validate_number(value, "initial_value")
        if min is not None:
            _validate_number(min, "min")
        if max is not None:
            _validate_number(max, "max")
        if step is not None:
            _validate_positive_number(step, "step")
        if min is not None and max is not None and min > max:
            raise ValueError(f"max= must be at least min=; got {min} > {max}.")
        if min is not None and value < min:
            raise ValueError(f"initial_value {value} is below min={min}.")
        if max is not None and value > max:
            raise ValueError(f"initial_value {value} is above max={max}.")

        # Incoming client edits are cast to the type of the stored value, so an
        # int value with float bounds would truncate every edit. Promote it.
        if type(value) is int and (type(min) is float or type(max) is float or type(step) is float):
            value = float(value)  # type: ignore

        if step is None:
            # It's ok that `step` is always a float, even if the value is an integer,
            # because things all become `number` types after serialization.
            step = float(
                np.min(
                    [
                        _compute_step(value),
                        _compute_step(min),
                        _compute_step(max),
                    ]
                )
            )  # type: ignore[assignment]
        assert step is not None  # Narrowing for the type checker.

        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiNumberHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiNumberMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiNumberProps(
                        order=order,
                        label=label,
                        hint=hint,
                        min=min,
                        max=max,
                        precision=_compute_precision_digits(step),
                        step=step,
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
                is_button=False,
            )
        )

    def add_vector2(
        self,
        label: str,
        initial_value: tuple[float, float] | np.ndarray,
        *,
        min: tuple[float, float] | np.ndarray | None = None,
        max: tuple[float, float] | np.ndarray | None = None,
        step: float | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiVector2Handle:
        """Add a length-2 vector input to the GUI.

        Args:
            label: Label to display on the vector input.
            initial_value: Initial value of the vector input.
            min: Optional minimum value of the vector input.
            max: Optional maximum value of the vector input.
            step: Optional step size of the vector input. Computed automatically if not
            disabled: Whether the vector input is disabled.
            visible: Whether the vector input is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        value = initial_value
        value = _cast_vector(value, 2)
        min = _cast_vector(min, 2) if min is not None else None
        max = _cast_vector(max, 2) if max is not None else None
        if step is not None:
            _validate_positive_number(step, "step")
        if min is not None and max is not None and any(lo > hi for lo, hi in zip(min, max)):
            raise ValueError("Each vector min component must be at most its max component.")
        if min is not None and any(component < lo for component, lo in zip(value, min)):
            raise ValueError("initial_value has a component below min.")
        if max is not None and any(component > hi for component, hi in zip(value, max)):
            raise ValueError("initial_value has a component above max.")
        uuid = _make_uuid()
        order = _apply_default_order(order)

        step = _infer_vector_step(value, min, max, step)

        return GuiVector2Handle(
            self._create_gui_input(
                value,
                message=_messages.GuiVector2Message(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiVector2Props(
                        order=order,
                        label=label,
                        hint=hint,
                        min=min,
                        max=max,
                        step=step,
                        precision=_compute_precision_digits(step),
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
            )
        )

    def add_vector3(
        self,
        label: str,
        initial_value: tuple[float, float, float] | np.ndarray,
        *,
        min: tuple[float, float, float] | np.ndarray | None = None,
        max: tuple[float, float, float] | np.ndarray | None = None,
        step: float | None = None,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiVector3Handle:
        """Add a length-3 vector input to the GUI.

        Args:
            label: Label to display on the vector input.
            initial_value: Initial value of the vector input.
            min: Optional minimum value of the vector input.
            max: Optional maximum value of the vector input.
            step: Optional step size of the vector input. Computed automatically if not
            disabled: Whether the vector input is disabled.
            visible: Whether the vector input is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        value = initial_value
        value = _cast_vector(value, 3)
        min = _cast_vector(min, 3) if min is not None else None
        max = _cast_vector(max, 3) if max is not None else None
        if step is not None:
            _validate_positive_number(step, "step")
        if min is not None and max is not None and any(lo > hi for lo, hi in zip(min, max)):
            raise ValueError("Each vector min component must be at most its max component.")
        if min is not None and any(component < lo for component, lo in zip(value, min)):
            raise ValueError("initial_value has a component below min.")
        if max is not None and any(component > hi for component, hi in zip(value, max)):
            raise ValueError("initial_value has a component above max.")
        uuid = _make_uuid()
        order = _apply_default_order(order)

        step = _infer_vector_step(value, min, max, step)

        return GuiVector3Handle(
            self._create_gui_input(
                value,
                message=_messages.GuiVector3Message(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiVector3Props(
                        order=order,
                        label=label,
                        hint=hint,
                        min=min,
                        max=max,
                        step=step,
                        precision=_compute_precision_digits(step),
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
            )
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
            initial_value: Initial value of the dropdown.
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
        # Materialize once so a one-shot iterable isn't consumed by the checks
        # below and again by the message construction.
        options_tuple = cast(
            "tuple[TLiteralString, ...] | tuple[TString, ...]",
            _string_options(options, "add_dropdown()"),
        )
        value = initial_value
        if value is None:
            value = options_tuple[0]
        elif value not in options_tuple:
            raise ValueError(
                f"Dropdown initial_value {value!r} is not one of the options {options_tuple!r}."
            )
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiDropdownHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiDropdownMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiDropdownProps(
                        order=order,
                        label=label,
                        hint=hint,
                        options=options_tuple,
                        disabled=disabled,
                        visible=visible,
                        searchable=searchable,
                    ),
                ),
            ),
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
            visible: Whether the progress bar is visible.
            animated: Whether the progress bar is in an animated loading state.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        _validate_number(initial_value, "initial_value")
        if not 0 <= initial_value <= 100:
            raise ValueError(
                f"initial_value= is a percentage, so it lives in [0, 100]; got {initial_value}."
            )
        message = _messages.GuiProgressBarMessage(
            value=initial_value,
            uuid=_make_uuid(),
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiProgressBarProps(
                order=_apply_default_order(order),
                animated=animated,
                visible=visible,
            ),
        )
        self._websock_interface.queue_message(message)
        handle = GuiProgressBarHandle(
            _GuiHandleState(
                message.uuid,
                self,
                value=initial_value,
                props=message.props,
                parent_container_id=message.container_uuid,
            ),
        )
        return handle

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
        value: IntOrFloat = initial_value
        _validate_number(value, "initial_value")
        _validate_number(min, "min")
        _validate_number(max, "max")
        _validate_positive_number(step, "step")
        if max < min:
            raise ValueError(f"max= must be at least min=; got {min} > {max}.")
        step = builtins.min(step, max - min)
        if not (min <= value <= max):
            raise ValueError(f"initial_value {value} is outside [{min}, {max}].")

        # Incoming client edits are cast to the type of the stored value, so an
        # int value with float bounds would truncate every edit. Promote it.
        if type(value) is int and (type(min) is float or type(max) is float or type(step) is float):
            value = float(value)  # type: ignore

        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiSliderHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiSliderMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiSliderProps(
                        order=order,
                        label=label,
                        hint=hint,
                        min=min,
                        max=max,
                        step=step,
                        precision=_compute_precision_digits(step),
                        show_value=show_value,
                        visible=visible,
                        disabled=disabled,
                        _marks=_build_slider_marks(marks),
                    ),
                ),
                is_button=False,
            )
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
        _validate_number(min, "min")
        _validate_number(max, "max")
        _validate_positive_number(step, "step")
        if max < min:
            raise ValueError(f"max= must be at least min=; got {min} > {max}.")
        initial_value = tuple(initial_value)
        if not initial_value:
            raise ValueError("initial_value must contain at least one slider value.")
        for value in initial_value:
            _validate_number(value, "initial_value entries")
        if any(left > right for left, right in zip(initial_value, initial_value[1:])):
            raise ValueError("initial_value entries must be in ascending order.")
        if min_range is not None:
            _validate_number(min_range, "min_range")
            if min_range < 0:
                raise ValueError("min_range must be non-negative.")
            if any(
                right - left < min_range for left, right in zip(initial_value, initial_value[1:])
            ):
                raise ValueError("initial_value entries are closer than min_range.")
        step = builtins.min(step, max - min)
        if not all(min <= x <= max for x in initial_value):
            raise ValueError(f"initial_value {initial_value} has entries outside [{min}, {max}].")

        # GUI callbacks cast incoming values to match the type of the initial value. If
        # any of the arguments are floats, we should always use a float value.
        #
        # This should also match what the IntOrFloat TypeVar resolves to.
        if (
            type(min) is float
            or type(max) is float
            or type(step) is float
            or type(min_range) is float
        ):
            initial_value = tuple(float(x) for x in initial_value)  # type: ignore

        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiMultiSliderHandle(
            self._create_gui_input(
                value=initial_value,
                message=_messages.GuiMultiSliderMessage(
                    value=initial_value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiMultiSliderProps(
                        order=order,
                        label=label,
                        hint=hint,
                        min=min,
                        min_range=min_range,
                        max=max,
                        step=step,
                        visible=visible,
                        disabled=disabled,
                        fixed_endpoints=fixed_endpoints,
                        precision=_compute_precision_digits(step),
                        _marks=_build_slider_marks(marks),
                    ),
                ),
                is_button=False,
            )
        )

    def add_rgb(
        self,
        label: str,
        initial_value: tuple[int, int, int],
        *,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiRgbHandle:
        """Add an RGB picker to the GUI.

        Integer channels are in [0, 255]; float channels in [0, 1] are scaled to
        match (matplotlib convention), so ``1.0`` is white.

        Args:
            label: Label to display on the RGB picker.
            initial_value: Initial value of the RGB picker.
            disabled: Whether the RGB picker is disabled.
            visible: Whether the RGB picker is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """

        value = cast("tuple[int, int, int]", _colors_to_int_tuple(initial_value, 3))
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiRgbHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiRgbMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiRgbProps(
                        order=order,
                        label=label,
                        hint=hint,
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
            )
        )

    def add_rgba(
        self,
        label: str,
        initial_value: tuple[int, int, int, int],
        *,
        disabled: bool = False,
        visible: bool = True,
        hint: str | None = None,
        order: float | None = None,
    ) -> GuiRgbaHandle:
        """Add an RGBA picker to the GUI.

        Integer channels are in [0, 255]; float channels in [0, 1] are scaled to
        match (matplotlib convention), so ``1.0`` is white/opaque.

        Args:
            label: Label to display on the RGBA picker.
            initial_value: Initial value of the RGBA picker.
            disabled: Whether the RGBA picker is disabled.
            visible: Whether the RGBA picker is visible.
            hint: Optional hint to display on hover.
            order: Optional ordering, smallest values will be displayed first.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        value = cast("tuple[int, int, int, int]", _colors_to_int_tuple(initial_value, 4))
        uuid = _make_uuid()
        order = _apply_default_order(order)
        return GuiRgbaHandle(
            self._create_gui_input(
                value,
                message=_messages.GuiRgbaMessage(
                    value=value,
                    uuid=uuid,
                    container_uuid=self._get_container_uuid(),
                    props=_messages.GuiRgbaProps(
                        order=order,
                        label=label,
                        hint=hint,
                        disabled=disabled,
                        visible=visible,
                    ),
                ),
            )
        )

    class _GuiMessage(Protocol[GuiInputPropsType]):
        uuid: str
        props: GuiInputPropsType

    def _create_gui_input(
        self,
        value: T,
        message: _GuiMessage,
        is_button: bool = False,
    ) -> _GuiHandleState[T]:
        """Private helper for adding a simple GUI element."""

        # Send add GUI input message.
        assert isinstance(message, _messages.Message)
        self._websock_interface.queue_message(message)

        # Construct handle.
        handle_state = _GuiHandleState(
            props=message.props,
            gui_api=self,
            value=value,
            update_timestamp=time.time(),
            parent_container_id=self._get_container_uuid(),
            update_cb=[],
            is_button=is_button,
            sync_cb=None,
            uuid=message.uuid,
        )

        # For broadcasted GUI handles, we should synchronize all clients.
        # This will be a no-op for client handles.
        if not is_button:

            def sync_other_clients(client_id: ClientId, updates: dict[str, Any]) -> None:
                message = _messages.GuiUpdateMessage(handle_state.uuid, updates)
                message.excluded_self_client = client_id
                self._websock_interface.queue_message(message)

            handle_state.sync_cb = sync_other_clients

        return handle_state


install_container_add_methods(GuiApi)
