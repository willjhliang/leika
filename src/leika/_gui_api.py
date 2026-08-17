from __future__ import annotations

import builtins
import contextlib
import contextvars
import dataclasses
import inspect
import os
import threading
import time
import warnings
from asyncio import AbstractEventLoop
from collections import deque
from collections.abc import Coroutine, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    Iterable,
    Protocol,
    Sequence,
    TypeVar,
    cast,
    get_args,
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
from ._async_errors import (
    print_async_errors,
    print_async_exception,
)
from ._file_transfer import validate_file_display_name
from ._gui_handles import (
    _GUI_AGGREGATE_COLLECTION_MAX,
    _GUI_AGGREGATE_PAYLOAD_MAX_BYTES,
    _GUI_AGGREGATE_PIXELS_MAX,
    _GUI_AGGREGATE_TEXT_MAX_UTF16_CODE_UNITS,
    _GUI_COMMAND_MAX,
    _GUI_FORM_ACTION_ORDER,
    _GUI_MODAL_MAX,
    _GUI_NOTIFICATION_MAX,
    _GUI_PROGRAMMATIC_CALLBACK_BATCH_MAX,
    _GUI_PROGRAMMATIC_CALLBACK_RETAINED_MAX_BYTES,
    _GUI_TEXT_MAX_UTF16_CODE_UNITS,
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
    _bounded_tuple,
    _cast_vector,
    _checklist_items,
    _colors_to_int_tuple,
    _CommandHandleState,
    _discard_gui_subtree,
    _gui_descendant_tab_uuids,
    _gui_descendant_uuids,
    _gui_resource_cost,
    _gui_text_source,
    _GuiFileButtonHandle,
    _GuiHandle,
    _GuiHandleState,
    _GuiInputHandle,
    _GuiResourceCost,
    _make_uuid,
    _ndarray_snapshot_spec,
    _plotly_json_and_config,
    _private_ndarray_snapshot,
    _retire_gui_handle_without_queue_locked,
    _string_options,
    _tab_subtree_uuids,
    _validate_collection_string,
    _validate_gui_html_content,
    _validate_slider_marks,
    _validate_unicode_string,
    install_container_add_methods,
    not_container_scoped,
)
from ._icons import svg_from_icon
from ._icons_enum import IconName
from ._image_encoding import _validate_image_encoding_options, encode_image_binary
from ._messages import ButtonColor, FileTransferPartAck, GuiBaseProps, GuiSliderMark
from ._notification_handle import (
    NotificationHandle,
    _NotificationHandleState,
    validate_auto_close_seconds,
)
from ._validation import (
    utf16_code_unit_length,
    utf16_code_unit_length_exceeds,
    validate_renderer_string,
)
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

_PreviewWorkKind = Literal["warm", "preview", "reload", "watch"]

_FILE_UPLOAD_MAX_BYTES = 64 * 1024 * 1024
"""Maximum contents retained for one upload-backed ``UploadedFile``."""

_FILE_UPLOAD_PART_BYTES = 512 * 1024
"""Exact upload part size, except for the final part."""

_PROTOCOL_IDENTIFIER_MAX_CHARS = 128
_MIME_TYPE_MAX_CHARS = 255
_PREVIEW_PENDING_PER_SOURCE_MAX = 32


def _freeze_upload_content(content: bytearray) -> bytes:
    """Convert a completed bounded upload builder to its immutable value."""
    return bytes(content)


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


def _validate_button_color(color: object) -> ButtonColor:
    """Reject anything but the two button roles at runtime, where the
    ``Literal`` annotation alone would let ``"blue"`` through and quietly draw
    the default. Shared by ``add_button`` and ``add_upload_button``."""
    if type(color) is not str or color not in ("default", "inverse"):
        raise ValueError(
            f"Button color must be 'default' or 'inverse', not {color!r}. Buttons take"
            " a role rather than a color; the accent itself is a viewer setting."
        )
    return cast(ButtonColor, color)


def _validate_file_content(content: object, filename: str | None, factory: str) -> DownloadContent:
    """Validate and detach a bounded synchronous source before publication."""
    if filename is not None:
        validate_file_display_name(filename)
    if type(content) is bytes:
        normalized: object = content
    elif isinstance(content, Path):
        normalized = Path(os.fspath(content))
    elif callable(content):
        call = getattr(content, "__call__", None)
        if inspect.iscoroutinefunction(content) or inspect.iscoroutinefunction(call):
            raise TypeError(
                "content providers must be synchronous callables; async providers are not supported"
            )
        normalized = content
    else:
        raise TypeError(
            "content= must be bytes, a Path, or a synchronous callable returning one of those"
        )
    if filename is None and type(normalized) is bytes:
        raise ValueError(
            f"filename= is required when the contents are bytes, which carry"
            f" no name of their own. Passed to {factory}."
        )
    return cast(DownloadContent, normalized)


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
    wanted = (
        (initial_value,)
        if isinstance(initial_value, str)
        else _bounded_tuple(initial_value, "initial toggle value")
    )
    unknown = [option for option in wanted if option not in options]
    if len(set(wanted)) != len(wanted):
        raise ValueError("initial_value cannot repeat a toggle option.")
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
    if type(color) is str:
        return (_validate_button_color(color),) * count
    colors = _bounded_tuple(color, f"{noun} colors")
    if len(colors) != count:
        raise ValueError(
            f"color= takes one role per {noun}: {count} for this row, but got"
            f" {len(colors)}. Pass a single role to answer for every button at"
            " once."
        )
    return tuple(_validate_button_color(one) for one in colors)


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
    flags = _bounded_tuple(merge, "merge flags")
    if any(type(flag) is not bool for flag in flags):
        raise TypeError("merge= sequence entries must be bools.")
    if len(flags) != gaps:
        raise ValueError(
            f"merge= takes one flag per gap between buttons: {gaps} for {count}"
            f" button(s), but got {len(flags)}. Pass a single bool to answer for"
            " every gap at once."
        )
    return flags


def _build_slider_marks(
    marks: Iterable[float | tuple[float, str]] | None,
) -> tuple[GuiSliderMark, ...] | None:
    """Normalize and bound public slider marks before message construction."""
    if marks is None:
        return None
    materialized = _bounded_tuple(marks, "slider marks")
    normalized: list[GuiSliderMark] = []
    for item in materialized:
        if isinstance(item, tuple):
            if len(item) != 2:
                raise ValueError("slider mark tuples must contain a value and label")
            raw_value, label = item
            if type(label) is not str:
                raise TypeError("slider mark labels must be strings")
            _validate_collection_string(label, "slider mark labels")
        else:
            raw_value, label = item, None
        value = _validate_number(raw_value, "slider mark value")
        normalized.append(GuiSliderMark(value=float(value), label=label))
    return _validate_slider_marks(tuple(normalized))


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


class _UploadAckRejected(Exception):
    """Internal rollback signal when a final flow-control ACK cannot queue."""


class _FileUploadState(TypedDict):
    client_id: ClientId
    source_component_uuid: str
    filename: str
    part_count: int
    content: bytearray
    next_part_index: int
    total_bytes: int
    transferred_bytes: int
    reserved_bytes: int


class GuiApi(GuiContainer):
    """Interface for working with the 2D GUI in Leika.

    Used by both our global server object, for sharing the same GUI elements
    with all clients, and by individual client handles."""

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
        self._plotly_connection = None if isinstance(owner, Server) else owner._websock_connection
        self._next_order = server._next_gui_order

        self._websock_interface = (
            owner._websock_server if isinstance(owner, Server) else owner._websock_connection
        )
        """Interface for sending and listening to messages."""

        self._terminal = False
        self._live_component_count = 0
        self._resource_from_gui_uuid: dict[str, _GuiResourceCost] = {}
        self._retained_extra_bytes_from_gui_uuid: dict[str, int] = {}
        self._reset_baseline_resource_from_gui_uuid: dict[str, _GuiResourceCost] = {}
        self._resource_total = _GuiResourceCost()
        self._container_depth_from_uuid: dict[str, int] = {"root": 0}
        self._notification_handle_from_uuid: dict[str, NotificationHandle] = {}
        self._notification_text_units_from_uuid: dict[str, int] = {}
        self._notification_text_units = 0
        self._is_server_scope = isinstance(owner, Server)
        self._gui_input_handle_from_uuid: dict[str, _GuiInputHandle[Any]] = {}
        self._container_handle_from_uuid: dict[str, GuiContainerProtocol] = {
            "root": _RootGuiContainer({})
        }
        self._modal_handle_from_uuid: dict[str, GuiModalHandle] = {}
        self._command_handle_from_uuid: dict[str, CommandHandle] = {}
        self._current_file_upload_states: dict[tuple[ClientId, str], _FileUploadState] = {}
        self._retained_file_upload_bytes: dict[str, int] = {}
        # Upload handlers read handle registries and commit values/resources, so
        # this must remain the canonical GUI lock rather than an independent lock.
        self._file_upload_lock = self._lock
        self._preview_work_from_key: dict[tuple[ClientId, str], _PreviewWorkState] = {}
        self._preview_work_lock = threading.RLock()
        self._programmatic_callback_lock = threading.Lock()
        self._programmatic_callback_queue: deque[
            tuple[tuple[Callable[[Any], object], ...], object, int]
        ] = deque()
        self._programmatic_callback_retained_bytes = 0
        self._programmatic_callback_scheduled = False

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
            _messages.FileTransferAbort,
            self._handle_file_transfer_abort,
        )
        self._websock_interface.register_handler(
            _messages.CommandTriggerMessage, self._handle_command_trigger
        )
        self._websock_interface.register_handler(
            _messages.GuiCloseModalMessage, self._handle_gui_close_modal
        )

    def _check_active_locked(self) -> None:
        if self._terminal:
            raise RuntimeError("This client-local GUI is no longer active.")

    def _set_gui_resource_locked(
        self,
        uuid: str,
        cost: _GuiResourceCost,
    ) -> _GuiResourceCost:
        old = self._resource_from_gui_uuid.get(uuid, _GuiResourceCost())
        prospective = self._resource_total - old + cost
        if prospective.collection_items > _GUI_AGGREGATE_COLLECTION_MAX:
            raise RuntimeError(
                f"A GUI scope cannot retain more than "
                f"{_GUI_AGGREGATE_COLLECTION_MAX} collection items."
            )
        if prospective.text_units > _GUI_AGGREGATE_TEXT_MAX_UTF16_CODE_UNITS:
            raise RuntimeError("A GUI scope exceeded its 16 Mi UTF-16 text budget.")
        if prospective.payload_bytes > _GUI_AGGREGATE_PAYLOAD_MAX_BYTES:
            raise RuntimeError("A GUI scope exceeded its 128 MiB retained payload budget.")
        if prospective.decoded_pixels > _GUI_AGGREGATE_PIXELS_MAX:
            raise RuntimeError("A GUI scope exceeded its 64 Mi-pixel decoded raster budget.")
        self._server._replace_gui_resource_cost(
            old,
            cost,
            page_global=self._is_server_scope,
        )
        self._resource_total = prospective
        if cost == _GuiResourceCost():
            self._resource_from_gui_uuid.pop(uuid, None)
        else:
            self._resource_from_gui_uuid[uuid] = cost
        return old

    @contextlib.contextmanager
    def _gui_resource_transaction_locked(
        self,
        uuid: str,
        value: object,
        props: object,
        *,
        decoded_pixels: int | None = None,
        retained_extra_bytes: int | None = None,
    ) -> Any:
        self._check_active_locked()
        if decoded_pixels is None:
            decoded_pixels = self._resource_from_gui_uuid.get(
                uuid, _GuiResourceCost()
            ).decoded_pixels
        if retained_extra_bytes is None:
            retained_extra_bytes = self._retained_extra_bytes_from_gui_uuid.get(uuid, 0)
        cost = _gui_resource_cost(
            value,
            props,
            decoded_pixels=decoded_pixels,
            retained_extra_bytes=retained_extra_bytes,
        )
        cost += self._reset_baseline_resource_from_gui_uuid.get(uuid, _GuiResourceCost())
        old_extra = self._retained_extra_bytes_from_gui_uuid.get(uuid, 0)
        old = self._set_gui_resource_locked(uuid, cost)
        if retained_extra_bytes:
            self._retained_extra_bytes_from_gui_uuid[uuid] = retained_extra_bytes
        else:
            self._retained_extra_bytes_from_gui_uuid.pop(uuid, None)
        try:
            yield
        except BaseException:
            self._set_gui_resource_locked(uuid, old)
            if old_extra:
                self._retained_extra_bytes_from_gui_uuid[uuid] = old_extra
            else:
                self._retained_extra_bytes_from_gui_uuid.pop(uuid, None)
            raise

    def _release_gui_resource_locked(self, uuid: str) -> None:
        self._set_gui_resource_locked(uuid, _GuiResourceCost())
        self._retained_extra_bytes_from_gui_uuid.pop(uuid, None)
        self._reset_baseline_resource_from_gui_uuid.pop(uuid, None)

    def _container_depth_locked(self, container_uuid: str) -> int:
        try:
            return self._container_depth_from_uuid[container_uuid]
        except KeyError as error:
            raise RuntimeError("GUI parent container is no longer active") from error

    @contextlib.contextmanager
    def _notification_resource_transaction_locked(
        self,
        uuid: str,
        props: _messages.NotificationProps,
    ) -> Any:
        old_units = self._notification_text_units_from_uuid.get(uuid, 0)
        new_units = utf16_code_unit_length(props.title) + utf16_code_unit_length(props.body)
        prospective = self._notification_text_units - old_units + new_units
        if prospective > 2 * 1024 * 1024:
            raise RuntimeError("A GUI scope exceeded its 2 Mi UTF-16 notification text budget.")
        with self._gui_resource_transaction_locked(f"notification:{uuid}", None, props):
            self._notification_text_units = prospective
            self._notification_text_units_from_uuid[uuid] = new_units
            try:
                yield
            except BaseException:
                self._notification_text_units = (
                    self._notification_text_units - new_units + old_units
                )
                if old_units:
                    self._notification_text_units_from_uuid[uuid] = old_units
                else:
                    self._notification_text_units_from_uuid.pop(uuid, None)
                raise

    def _release_notification_resource_locked(self, uuid: str) -> None:
        units = self._notification_text_units_from_uuid.pop(uuid, 0)
        self._notification_text_units -= units
        self._release_gui_resource_locked(f"notification:{uuid}")

    def _schedule_programmatic_callbacks(
        self,
        callbacks: tuple[Callable[[Any], object], ...],
        event: object,
    ) -> None:
        """Queue a bounded callback snapshot without changing commit outcome."""
        if not callbacks:
            return
        event_value = getattr(event, "value", None)
        cost = _gui_resource_cost(event_value, None)
        retained_bytes = 256 + cost.text_units * 2 + cost.payload_bytes + cost.collection_items * 64
        with self._programmatic_callback_lock:
            if (
                len(self._programmatic_callback_queue) >= _GUI_PROGRAMMATIC_CALLBACK_BATCH_MAX
                or self._programmatic_callback_retained_bytes + retained_bytes
                > _GUI_PROGRAMMATIC_CALLBACK_RETAINED_MAX_BYTES
            ):
                # State and wire publication already committed before callback
                # dispatch. Report overload without making a successful assignment
                # appear to have rolled back or retaining unbounded snapshots.
                print_async_exception(
                    RuntimeError("The programmatic GUI callback queue exceeded its safety limit.")
                )
                return
            self._programmatic_callback_queue.append((callbacks, event, retained_bytes))
            self._programmatic_callback_retained_bytes += retained_bytes
            if self._programmatic_callback_scheduled:
                return
            self._programmatic_callback_scheduled = True

        def clear_queued_locked() -> None:
            released = sum(item[2] for item in self._programmatic_callback_queue)
            self._programmatic_callback_queue.clear()
            self._programmatic_callback_retained_bytes -= released
            if self._programmatic_callback_retained_bytes < 0:
                raise RuntimeError("programmatic callback accounting underflow")

        def start() -> None:
            task = self._event_loop.create_task(self._drain_programmatic_callbacks())
            task.add_done_callback(print_async_errors)

        try:
            self._event_loop.call_soon_threadsafe(start)
        except Exception as error:
            with self._programmatic_callback_lock:
                clear_queued_locked()
                self._programmatic_callback_scheduled = False
            print_async_exception(error)

    async def _drain_programmatic_callbacks(self) -> None:
        try:
            while True:
                with self._programmatic_callback_lock:
                    if not self._programmatic_callback_queue:
                        self._programmatic_callback_scheduled = False
                        return
                    callbacks, event, retained_bytes = self._programmatic_callback_queue.popleft()
                try:
                    for callback in callbacks:
                        await self._server._await_user_callback(callback, event)
                finally:
                    with self._programmatic_callback_lock:
                        self._programmatic_callback_retained_bytes -= retained_bytes
                        if self._programmatic_callback_retained_bytes < 0:
                            raise RuntimeError("programmatic callback accounting underflow")
        except BaseException:
            with self._programmatic_callback_lock:
                released = sum(item[2] for item in self._programmatic_callback_queue)
                self._programmatic_callback_queue.clear()
                self._programmatic_callback_retained_bytes -= released
                self._programmatic_callback_scheduled = False
            raise

    @property
    def _child_gui_api(self) -> GuiApi:
        return self

    @property
    def _child_container_id(self) -> str:
        return "root"

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
        from ._server import ClientHandle, Server

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

    async def _handle_gui_updates(
        self, client_id: ClientId, message: _messages.GuiUpdateMessage
    ) -> None:
        """Handle one browser value update as a linearized state transition."""
        client = self._resolve_client(client_id)
        if client is None or set(message.updates.keys()) != {"value"}:
            return
        raw_value = message.updates["value"]

        with self._lock:
            handle = self._gui_input_handle_from_uuid.get(message.uuid)
            if handle is None or handle._impl.removed:
                return
            props = handle._impl.props
            if isinstance(props, GuiBaseProps) and (props.disabled or not props.visible):
                return
            handle_state = handle._impl
            try:
                prop_value = handle._coerce_client_value(raw_value)
            except (TypeError, ValueError, OverflowError):
                return

            try:
                has_changed = handle_state.value != prop_value
            except (TypeError, ValueError):
                has_changed = True
            if not handle_state.is_button and not has_changed:
                return

            # Synchronize before publishing local state. A stopped/overloaded
            # destination leaves state unchanged and no callback observes a
            # value peers never received.
            with self._gui_resource_transaction_locked(
                handle_state.uuid, prop_value, handle_state.props
            ):
                if handle_state.sync_cb is not None:
                    handle_state.sync_cb(client_id, {"value": prop_value})
                if has_changed:
                    handle_state.value = prop_value
                handle_state.update_timestamp = time.time()
            event = GuiEvent(client, client_id, handle)
            callbacks = tuple(handle_state.update_cb)
            is_preview = isinstance(handle, GuiPreviewButtonHandle)
            is_file_button = isinstance(handle, _GuiFileButtonHandle)
            if is_file_button and not handle._begin_file_press_locked():
                return

        if is_preview:
            try:
                accepted = self._queue_preview_work(
                    "preview",
                    client_id,
                    client,
                    handle,
                    lambda: handle._send(event),
                )
            except BaseException:
                handle._finish_file_press()
                raise
            if not accepted:
                handle._finish_file_press()
        # User code never runs under the registry/state lock.
        for callback in callbacks:
            await self._server._await_user_callback(callback, event)

    async def _handle_gui_button_hold(
        self, client_id: ClientId, message: _messages.GuiButtonHoldMessage
    ) -> None:
        """Callback for handling button hold messages."""
        client = self._resolve_client(client_id)
        if client is None:
            return
        with self._lock:
            handle = self._gui_input_handle_from_uuid.get(message.uuid)
            if not isinstance(handle, GuiButtonHandle) or handle._impl.removed:
                return
            props = handle._impl.props
            if isinstance(props, GuiBaseProps) and (props.disabled or not props.visible):
                return
            callbacks = cast(
                tuple[Callable[[GuiEvent[Any]], object], ...],
                tuple(handle._hold_cbs_from_freq.get(message.frequency, ())),
            )
            if not callbacks:
                return
            event = GuiEvent(client, client_id, handle)

        for callback in callbacks:
            await self._server._await_user_callback(callback, event)

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
        client = self._resolve_client(client_id)
        if client is None:
            return None
        with self._lock:
            handle = self._gui_input_handle_from_uuid.get(uuid)
            if not isinstance(handle, GuiPreviewButtonHandle) or handle._impl.removed:
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
            state = self._preview_work_from_key.get(key)
            if state is None:
                state = _PreviewWorkState()
                self._preview_work_from_key[key] = state

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
                state.worker = self._thread_executor.submit(
                    self._run_preview_work,
                    key,
                    state,
                )
            except BaseException:
                self._preview_work_from_key.pop(key, None)
                raise
            state.worker.add_done_callback(print_async_errors)
            return True

    def _run_preview_work(
        self,
        key: tuple[ClientId, str],
        state: _PreviewWorkState,
    ) -> None:
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
                # Each operation used to own an executor future, where one
                # failure was reported without preventing later submissions.
                # Preserve that isolation inside the serialized worker.
                print_async_exception(error)
            finally:
                if item.kind == "preview":
                    item.handle._finish_file_press()
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
        discarded_preview_handles: list[GuiPreviewButtonHandle] = []
        with self._preview_work_lock:
            stale = [
                key
                for key in self._preview_work_from_key
                if (client_id is None or key[0] == client_id)
                and (source_component_uuid is None or key[1] == source_component_uuid)
            ]
            for key in stale:
                state = self._preview_work_from_key.pop(key)
                discarded_preview_handles.extend(
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

        # A preview press acquires the file-button lease before it enters this
        # queue. Pending items that are discarded never reach the worker's
        # finally block, so release their leases explicitly. Do this outside
        # the preview lock because release takes the canonical GUI lock.
        for handle in discarded_preview_handles:
            handle._finish_file_press()

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
        props = handle._impl.props
        if isinstance(props, GuiBaseProps) and (props.disabled or not props.visible):
            return
        self._queue_preview_work(
            "warm",
            client_id,
            client,
            handle,
            lambda: handle._warm(client),
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
        event = GuiEvent(client, client_id, handle)
        self._queue_preview_work(
            "reload",
            client_id,
            client,
            handle,
            lambda: handle._reload(event),
        )

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
        version = message.version
        self._queue_preview_work(
            "watch",
            client_id,
            client,
            handle,
            lambda: handle._watch(client, version),
        )

    async def _handle_gui_form_submit(
        self, client_id: ClientId, message: _messages.GuiFormSubmitMessage
    ) -> None:
        """Publish a browser form submit, then run a stable callback snapshot."""
        client = self._resolve_client(client_id)
        if client is None:
            return
        with self._lock:
            handle = self._container_handle_from_uuid.get(message.uuid)
            if not isinstance(handle, GuiFormHandle) or handle._impl.removed:
                return
            # Broadcast before entering user code so every client closes the
            # form even if an async submit callback raises.
            self._websock_interface.queue_message_or_raise(
                _messages.GuiFormSubmitMessage(uuid=message.uuid)
            )
            callbacks = tuple(handle._submit_cb)
            event = GuiEvent(client, client_id, handle)

        for callback in callbacks:
            await self._server._await_user_callback(callback, event)

    def _queue_upload_message(self, client_id: ClientId, message: _messages.Message) -> bool:
        """Send upload flow control only to its originating browser."""
        client = self._resolve_client(client_id)
        return client is not None and client._websock_connection.queue_message(message) is not False

    def _drop_file_upload_locked(self, key: tuple[ClientId, str]) -> _FileUploadState | None:
        """Drop one transfer and release its exact aggregate reservation."""
        state = self._current_file_upload_states.pop(key, None)
        if state is not None:
            self._server._release_file_upload(state["reserved_bytes"])
        return state

    def _queue_upload_abort(self, client_id: ClientId, transfer_uuid: str, reason: str) -> None:
        self._queue_upload_message(
            client_id,
            _messages.FileTransferAbort(
                transfer_uuid=transfer_uuid,
                reason=reason[:160],
            ),
        )

    def _handle_file_transfer_start(
        self, client_id: ClientId, message: _messages.FileTransferStartUpload
    ) -> Coroutine[Any, Any, None] | None:
        transfer_uuid = message.transfer_uuid
        if not _valid_protocol_identifier(transfer_uuid):
            # There is no safe identifier with which to correlate an abort.
            return
        source_component_uuid = message.source_component_uuid
        if not _valid_protocol_identifier(source_component_uuid):
            self._queue_upload_abort(client_id, transfer_uuid, "Invalid upload metadata.")
            return

        metadata_valid = (
            type(message.part_count) is int
            and type(message.size_bytes) is int
            and message.part_count >= 0
            and message.size_bytes >= 0
            and message.part_count
            == (message.size_bytes + _FILE_UPLOAD_PART_BYTES - 1) // _FILE_UPLOAD_PART_BYTES
            and _valid_mime_type(message.mime_type)
        )
        try:
            validate_file_display_name(message.filename)
        except (TypeError, ValueError):
            metadata_valid = False
        if not metadata_valid:
            self._queue_upload_abort(client_id, transfer_uuid, "Invalid upload metadata.")
            return

        key = (client_id, transfer_uuid)
        completion = None
        with self._file_upload_lock:
            handle = self._gui_input_handle_from_uuid.get(source_component_uuid)
            # Incoming messages are dispatched to both global and client-local
            # GUI APIs. Only the API that owns this component may respond.
            if not isinstance(handle, GuiUploadButtonHandle):
                return
            if handle._impl.removed:
                self._queue_upload_abort(client_id, transfer_uuid, "Upload target removed.")
                return
            props = handle._impl.props
            if isinstance(props, GuiBaseProps) and (props.disabled or not props.visible):
                self._queue_upload_abort(client_id, transfer_uuid, "Upload target unavailable.")
                return
            if any(
                state["client_id"] == client_id
                and state["source_component_uuid"] == source_component_uuid
                for state in self._current_file_upload_states.values()
            ):
                self._queue_upload_abort(
                    client_id, transfer_uuid, "An upload is already active for this control."
                )
                return
            if key in self._current_file_upload_states:
                self._queue_upload_abort(client_id, transfer_uuid, "Duplicate upload transfer.")
                return
            if message.size_bytes > _FILE_UPLOAD_MAX_BYTES:
                self._queue_upload_abort(
                    client_id, transfer_uuid, "Upload exceeds the 64 MiB limit."
                )
                return
            if not self._server._reserve_file_upload(message.size_bytes):
                self._queue_upload_abort(
                    client_id, transfer_uuid, "Server upload capacity is full."
                )
                return

            self._current_file_upload_states[key] = {
                "client_id": client_id,
                "source_component_uuid": source_component_uuid,
                "filename": message.filename,
                "part_count": message.part_count,
                "content": bytearray(),
                "next_part_index": 0,
                "total_bytes": message.size_bytes,
                "transferred_bytes": 0,
                "reserved_bytes": message.size_bytes,
            }
            prepared_completion = None
            if message.part_count == 0:
                try:
                    prepared_completion = self._prepare_file_upload_completion_locked(key)
                except MemoryError:
                    self._drop_file_upload_locked(key)
                    self._queue_upload_abort(
                        client_id, transfer_uuid, "Server could not store upload."
                    )
                    return
            completion = self._admit_upload_ack_locked(
                key,
                FileTransferPartAck(
                    source_component_uuid=source_component_uuid,
                    transfer_uuid=transfer_uuid,
                    transferred_bytes=0,
                    total_bytes=message.size_bytes,
                ),
                prepared_completion,
            )

        if completion is not None and completion[3]:
            return self._dispatch_file_upload_completion(completion)
        return None

    def _prepare_file_upload_completion_locked(
        self,
        key: tuple[ClientId, str],
    ) -> (
        tuple[
            GuiUploadButtonHandle,
            UploadedFile,
            tuple[Callable[..., Any], ...],
        ]
        | None
    ):
        """Freeze a completed upload without committing any owner state."""
        state = self._current_file_upload_states.get(key)
        if state is None:
            return None
        handle = self._gui_input_handle_from_uuid.get(state["source_component_uuid"])
        if not isinstance(handle, GuiUploadButtonHandle) or handle._impl.removed:
            self._drop_file_upload_locked(key)
            return None
        content = _freeze_upload_content(state["content"])
        value = UploadedFile(name=state["filename"], content=content)
        return handle, value, tuple(handle._impl.update_cb)

    def _commit_file_upload_completion_locked(
        self,
        key: tuple[ClientId, str],
        prepared: tuple[
            GuiUploadButtonHandle,
            UploadedFile,
            tuple[Callable[..., Any], ...],
        ],
    ) -> tuple[
        ClientId,
        GuiUploadButtonHandle,
        UploadedFile,
        tuple[Callable[..., Any], ...],
    ]:
        """Commit a prepared upload only after its final ACK is admitted."""
        state = self._current_file_upload_states[key]
        handle, value, callbacks = prepared
        source_uuid = state["source_component_uuid"]
        replaced_bytes = self._retained_file_upload_bytes.get(source_uuid, 0)
        self._server._complete_file_upload(state["reserved_bytes"], replaced_bytes)
        self._current_file_upload_states.pop(key)
        self._retained_file_upload_bytes[source_uuid] = len(value.content)
        handle._impl.value = value
        handle._impl.update_timestamp = time.time()
        return state["client_id"], handle, value, callbacks

    def _admit_upload_ack_locked(
        self,
        key: tuple[ClientId, str],
        ack: FileTransferPartAck,
        prepared: tuple[
            GuiUploadButtonHandle,
            UploadedFile,
            tuple[Callable[..., Any], ...],
        ]
        | None,
    ) -> (
        tuple[
            ClientId,
            GuiUploadButtonHandle,
            UploadedFile,
            tuple[Callable[..., Any], ...],
        ]
        | None
    ):
        """Reserve final owner state before ACK, then commit without a gap."""
        if prepared is None:
            if not self._queue_upload_message(key[0], ack):
                self._drop_file_upload_locked(key)
            return None
        handle, value, _ = prepared
        try:
            with self._gui_resource_transaction_locked(
                handle._impl.uuid, value, handle._impl.props
            ):
                if not self._queue_upload_message(key[0], ack):
                    raise _UploadAckRejected
                return self._commit_file_upload_completion_locked(key, prepared)
        except _UploadAckRejected:
            self._drop_file_upload_locked(key)
            return None
        except (ValueError, RuntimeError):
            self._drop_file_upload_locked(key)
            self._queue_upload_abort(key[0], key[1], "Server upload storage capacity is full.")
            return None

    async def _dispatch_file_upload_completion(
        self,
        completion: tuple[
            ClientId,
            GuiUploadButtonHandle,
            UploadedFile,
            tuple[Callable[..., Any], ...],
        ],
    ) -> None:
        """Run completion callbacks without holding the upload-state lock."""
        client_id, handle, value, callbacks = completion
        client = self._resolve_client(client_id)
        if client is None:
            return
        for cb in callbacks:
            await self._server._await_user_callback(cb, GuiEvent(client, client_id, handle, value))

    def _handle_file_transfer_part(
        self, client_id: ClientId, message: _messages.FileTransferPart
    ) -> Coroutine[Any, Any, None] | None:
        transfer_uuid = message.transfer_uuid
        if not _valid_protocol_identifier(transfer_uuid):
            return
        key = (client_id, transfer_uuid)
        completion = None
        with self._file_upload_lock:
            state = self._current_file_upload_states.get(key)
            if state is None:
                return

            content = message.content
            envelope_valid = (
                _valid_protocol_identifier(message.source_component_uuid)
                and type(message.part_index) is int
                and isinstance(content, bytes)
            )
            if not envelope_valid:
                self._drop_file_upload_locked(key)
                self._queue_upload_abort(client_id, transfer_uuid, "Invalid upload part.")
                return
            content = cast(bytes, content)

            handle = self._gui_input_handle_from_uuid.get(state["source_component_uuid"])
            expected_size = min(
                _FILE_UPLOAD_PART_BYTES,
                state["total_bytes"] - state["transferred_bytes"],
            )
            valid_part = (
                message.source_component_uuid == state["source_component_uuid"]
                and isinstance(handle, GuiUploadButtonHandle)
                and not handle._impl.removed
                and message.part_index == state["next_part_index"]
                and len(content) == expected_size
                and expected_size > 0
            )
            transferred_bytes = state["transferred_bytes"] + len(content)
            next_part_index = state["next_part_index"] + 1
            parts_remaining = state["part_count"] - next_part_index
            valid_part = (
                valid_part
                and parts_remaining >= 0
                and (parts_remaining == 0) == (transferred_bytes == state["total_bytes"])
            )
            if not valid_part:
                self._drop_file_upload_locked(key)
                self._queue_upload_abort(client_id, transfer_uuid, "Invalid upload part.")
                return

            try:
                state["content"].extend(content)
            except MemoryError:
                self._drop_file_upload_locked(key)
                self._queue_upload_abort(client_id, transfer_uuid, "Server could not store upload.")
                return
            state["transferred_bytes"] = transferred_bytes
            state["next_part_index"] = next_part_index
            prepared_completion = None
            if parts_remaining == 0:
                try:
                    prepared_completion = self._prepare_file_upload_completion_locked(key)
                except MemoryError:
                    self._drop_file_upload_locked(key)
                    self._queue_upload_abort(
                        client_id, transfer_uuid, "Server could not store upload."
                    )
                    return
            completion = self._admit_upload_ack_locked(
                key,
                FileTransferPartAck(
                    source_component_uuid=state["source_component_uuid"],
                    transfer_uuid=transfer_uuid,
                    transferred_bytes=transferred_bytes,
                    total_bytes=state["total_bytes"],
                ),
                prepared_completion,
            )

        if completion is not None and completion[3]:
            return self._dispatch_file_upload_completion(completion)
        return None

    def _handle_file_transfer_abort(
        self, client_id: ClientId, message: _messages.FileTransferAbort
    ) -> None:
        """Release a browser-cancelled or timed-out upload."""
        if not _valid_protocol_identifier(message.transfer_uuid):
            return
        with self._file_upload_lock:
            self._drop_file_upload_locked((client_id, message.transfer_uuid))

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
                self._drop_file_upload_locked(key)
            if source_component_uuid is not None:
                retained = self._retained_file_upload_bytes.pop(source_component_uuid, 0)
                if retained:
                    self._server._release_retained_file_upload(retained)

    def _retire_scope_without_queue(self) -> None:
        """Terminally retire every owner after disconnect or server shutdown."""
        with self._lock:
            if self._terminal:
                return
            self._terminal = True
            root = self._container_handle_from_uuid.get("root")
            if isinstance(root, _RootGuiContainer):
                _discard_gui_subtree(root, self)
            for modal in tuple(self._modal_handle_from_uuid.values()):
                _discard_gui_subtree(modal)
                modal.closed = True
                modal._create_message = None
            for command in tuple(self._command_handle_from_uuid.values()):
                command._retire_without_queue_locked()
            for notification in tuple(self._notification_handle_from_uuid.values()):
                notification._retire_without_queue()
            self._modal_handle_from_uuid.clear()
            self._command_handle_from_uuid.clear()
            self._notification_handle_from_uuid.clear()
            self._notification_text_units_from_uuid.clear()
            self._notification_text_units = 0
            self._gui_input_handle_from_uuid.clear()
            self._container_handle_from_uuid = {"root": _RootGuiContainer({})}
            self._container_depth_from_uuid = {"root": 0}
            # Defensive release for any record not reachable from a corrupted tree.
            for uuid in tuple(self._resource_from_gui_uuid):
                self._release_gui_resource_locked(uuid)
            self._live_component_count = 0
        with self._programmatic_callback_lock:
            released = sum(item[2] for item in self._programmatic_callback_queue)
            self._programmatic_callback_queue.clear()
            self._programmatic_callback_retained_bytes -= released
            self._programmatic_callback_scheduled = False

    def _discard_client_work(
        self, client_id: ClientId, *, release_retained_uploads: bool = False
    ) -> None:
        """Discard connection-owned work that must not outlive its browser."""
        self._discard_file_uploads(client_id=client_id)
        if release_retained_uploads:
            with self._file_upload_lock:
                for source_uuid, size_bytes in tuple(self._retained_file_upload_bytes.items()):
                    handle = self._gui_input_handle_from_uuid.get(source_uuid)
                    if isinstance(handle, GuiUploadButtonHandle):
                        handle._impl.value = UploadedFile("", b"")
                    self._server._release_retained_file_upload(size_bytes)
                self._retained_file_upload_bytes.clear()
        if release_retained_uploads:
            # The connection-local message buffer is already closed when its
            # disconnect callback runs. Retiring the scope first marks every
            # preview handle terminal, so releasing discarded leases cannot
            # try to publish an enabled state to that closed connection.
            self._retire_scope_without_queue()
        else:
            self._discard_preview_work(client_id=client_id)

    async def _handle_command_trigger(
        self, client_id: ClientId, message: _messages.CommandTriggerMessage
    ) -> None:
        """Handle one command trigger using an immutable callback snapshot."""
        client = self._resolve_client(client_id)
        if client is None:
            return
        with self._lock:
            handle = self._command_handle_from_uuid.get(message.uuid)
            if handle is None or handle._impl.removed or handle._impl.props.disabled:
                return
            callbacks = tuple(handle._impl.trigger_cb)
            event = CommandEvent(client, client_id, handle)

        for callback in callbacks:
            await self._server._await_user_callback(callback, event)

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
            handle = self._modal_handle_from_uuid.get(message.uuid)
            if handle is None:
                return
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
        """Atomically remove every GUI-owned entity in this scope."""
        with self._lock:
            self._check_active_locked()
            root_container = self._container_handle_from_uuid["root"]
            children = tuple(root_container._children.values())
            modals = tuple(self._modal_handle_from_uuid.values())
            commands = tuple(self._command_handle_from_uuid.values())
            notifications = tuple(self._notification_handle_from_uuid.values())
            messages: list[_messages.Message] = []
            for child in children:
                if not isinstance(child, _GuiHandle):
                    raise RuntimeError("root GUI registry contains an invalid owner")
                if isinstance(child, GuiTabGroupHandle):
                    descendants = tuple(
                        uuid for tab in child._tab_handles for uuid in _gui_descendant_uuids(tab)
                    )
                    removed_tabs = tuple(
                        uuid for tab in child._tab_handles for uuid in _tab_subtree_uuids(tab)
                    )
                elif isinstance(child, GuiContainer):
                    descendants = _gui_descendant_uuids(child)
                    removed_tabs = _gui_descendant_tab_uuids(child)
                else:
                    descendants = ()
                    removed_tabs = ()
                messages.append(_messages.GuiRemoveMessage(child.id, descendants, removed_tabs))
            messages.extend(
                _messages.GuiCloseModalMessage(
                    modal.id,
                    _gui_descendant_uuids(modal),
                    _gui_descendant_tab_uuids(modal),
                )
                for modal in modals
            )
            messages.extend(_messages.RemoveCommandMessage(command.id) for command in commands)
            messages.extend(
                _messages.RemoveNotificationMessage(notification.id)
                for notification in notifications
            )
            if messages:
                self._websock_interface.queue_messages_or_raise(messages)

            for child in children:
                _retire_gui_handle_without_queue_locked(cast(_GuiHandle[Any], child))
            root_container._children.clear()
            for modal in modals:
                _discard_gui_subtree(modal)
                modal.closed = True
                modal._create_message = None
                self._container_handle_from_uuid.pop(modal.id, None)
                self._container_depth_from_uuid.pop(modal.id, None)
                self._modal_handle_from_uuid.pop(modal.id, None)
                self._release_gui_resource_locked(f"modal:{modal.id}")
            for command in commands:
                command._retire_without_queue_locked()
            for notification in notifications:
                notification._retire_without_queue()

    def set_panel_label(self, label: str | None) -> None:
        """Compatibility alias for naming the server's default page.

        The panel header now selects pages, so it has no visualization-wide
        label of its own. Calls on ``server.gui`` rename the authoritative
        default page; calls on a client-local GUI send that rename only to the
        owning browser, preserving the historical connection-local behavior.

        Args:
            label: Default-page name. ``None`` and ``""`` become ``"Main"``.
        """
        from ._pages import _normalize_legacy_page_label
        from ._server import Server

        name = _normalize_legacy_page_label(label)
        if isinstance(self._owner, Server):
            self._owner.pages.default.name = name
            return
        with self._lock:
            self._check_active_locked()
            self._websock_interface.queue_message_or_raise(
                _messages.PageUpdateMessage(
                    page_id=str(self._server.pages.default.page_id),
                    name=name,
                )
            )

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

        if type(control_layout) is not str or control_layout not in (
            "floating",
            "left",
            "right",
        ):
            raise ValueError(
                "control_layout must be 'floating', 'left', or 'right'. The"
                " 'collapsible' and 'fixed' sidebar layouts were removed; use"
                " 'left' or 'right' to start the panel docked to that edge."
            )
        if not (type(dark_mode) is bool or (type(dark_mode) is str and dark_mode == "auto")):
            raise ValueError("dark_mode must be True, False, or 'auto'.")

        self._websock_interface.queue_message_or_raise(
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
                ``None`` or ``0`` keeps it up until dismissed, removed, or updated to a positive timeout.
        """
        title = cast(str, validate_renderer_string(title, "notification title"))
        body = cast(str, validate_renderer_string(body, "notification body"))
        if type(loading) is not bool:
            raise TypeError("loading must be a bool")
        if type(with_close_button) is not bool:
            raise TypeError("with_close_button must be a bool")
        auto_close_seconds = validate_auto_close_seconds(auto_close_seconds)
        with self._lock:
            self._check_active_locked()
            if len(self._notification_handle_from_uuid) >= _GUI_NOTIFICATION_MAX:
                raise RuntimeError(
                    f"A GUI scope cannot own more than {_GUI_NOTIFICATION_MAX} notifications."
                )
            notification_uuid = _make_uuid()

            def retire(uuid: str) -> None:
                with self._lock:
                    self._notification_handle_from_uuid.pop(uuid, None)
                    self._release_notification_resource_locked(uuid)

            def notification_resources(
                props: _messages.NotificationProps,
            ) -> ContextManager[object]:
                return self._notification_resource_transaction_locked(notification_uuid, props)

            handle = NotificationHandle(
                _NotificationHandleState(
                    websock_interface=self._websock_interface,
                    event_loop=self._event_loop,
                    uuid=notification_uuid,
                    state_lock=self._lock,
                    on_terminal=retire,
                    resource_transaction=notification_resources,
                    props=_messages.NotificationProps(
                        title=title,
                        body=body,
                        loading=loading,
                        with_close_button=with_close_button,
                        auto_close_seconds=auto_close_seconds,
                    ),
                )
            )
            self._notification_handle_from_uuid[notification_uuid] = handle
            try:
                with self._notification_resource_transaction_locked(
                    notification_uuid, handle._impl.props
                ):
                    handle._show()
            except BaseException:
                self._notification_handle_from_uuid.pop(notification_uuid, None)
                handle._retire_without_queue()
                raise

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
        label = cast(str, validate_renderer_string(label, "command label"))
        description = cast(
            str | None,
            validate_renderer_string(description, "command description", optional=True),
        )
        if callback is not None and not callable(callback):
            raise TypeError("callback must be callable or None")
        if type(disabled) is not bool:
            raise TypeError("disabled must be a bool")
        valid_hotkeys = get_args(_messages.HotkeyKey)
        if hotkey is not None and (type(hotkey) is not str or hotkey not in valid_hotkeys):
            raise ValueError(f"hotkey must be one of {valid_hotkeys!r} or None")
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
        handle_state = _CommandHandleState(
            uuid=command_uuid,
            gui_api=self,
            props=props,
            icon=icon,
        )
        handle = CommandHandle(handle_state)
        if callback is not None:
            # Install the shorthand before publishing: a client can trigger
            # the command as soon as its registration reaches the browser.
            def trigger(_: CommandEvent) -> Any:
                return callback()

            handle_state.trigger_cb.append(trigger)

        # Register in the local map before publishing, so an immediate
        # trigger from the client can be resolved here.
        with self._lock:
            self._check_active_locked()
            if len(self._command_handle_from_uuid) >= _GUI_COMMAND_MAX:
                raise RuntimeError(f"A GUI scope cannot own more than {_GUI_COMMAND_MAX} commands.")
            self._command_handle_from_uuid[command_uuid] = handle
            try:
                with self._gui_resource_transaction_locked(f"command:{command_uuid}", None, props):
                    self._websock_interface.queue_message_or_raise(
                        _messages.RegisterCommandMessage(
                            uuid=command_uuid,
                            props=props,
                        )
                    )
            except BaseException:
                self._command_handle_from_uuid.pop(command_uuid, None)
                raise
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
        order = self._apply_default_order(order)
        props = _messages.GuiFolderProps(
            order=order,
            label=label,
            expand_by_default=expand_by_default,
            visible=visible,
        )
        message = _messages.GuiFolderMessage(
            uuid=folder_container_id,
            container_uuid=self._get_container_uuid(),
            props=props,
        )
        return GuiFolderHandle(
            _GuiHandleState(
                folder_container_id,
                self,
                None,
                props=props,
                parent_container_id=message.container_uuid,
                create_message=message,
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
            handle.actions = self._add_button_group(
                ("Reset", "Submit"),
                label=None,
                color=("default", "inverse"),
                merge=False,
                disabled=False,
                visible=True,
                hint=None,
                order=_GUI_FORM_ACTION_ORDER,
                _is_form_actions=True,
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

        Exactly one direct, editable field goes inside. A sibling row, nested
        container, or second field raises :class:`ValueError` before it is
        published.
        Sending is the button, or Enter in a single-line text input, and both
        fire :meth:`GuiFormHandle.on_submit`.
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
        order = self._apply_default_order(order)
        props = _messages.GuiFormProps(
            order=order,
            label=label,
            visible=visible,
            mini=mini,
        )
        message = _messages.GuiFormMessage(
            uuid=form_container_id,
            container_uuid=self._get_container_uuid(),
            props=props,
        )
        handle = GuiFormHandle(
            _GuiHandleState(
                form_container_id,
                self,
                None,
                props=props,
                parent_container_id=message.container_uuid,
                create_message=message,
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
        title = cast(str, validate_renderer_string(title, "modal title"))
        with self._lock:
            self._check_active_locked()
            if len(self._modal_handle_from_uuid) >= _GUI_MODAL_MAX:
                raise RuntimeError(f"A GUI scope cannot own more than {_GUI_MODAL_MAX} modals.")
        modal_container_id = _make_uuid()
        order = self._apply_default_order(order)
        message = _messages.GuiModalMessage(
            order=order,
            uuid=modal_container_id,
            title=title,
        )
        return GuiModalHandle(
            _gui_api=self,
            _uuid=modal_container_id,
            _create_message=message,
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
        order = self._apply_default_order(order)

        message = _messages.GuiTabGroupMessage(
            uuid=tab_group_id,
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiTabGroupProps(
                order=order,
                _tabs=(),
                visible=visible,
            ),
        )
        return GuiTabGroupHandle(
            _GuiHandleState(
                message.uuid,
                self,
                value=None,
                props=message.props,
                parent_container_id=message.container_uuid,
                create_message=message,
            )
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
            content: Trusted raw HTML to display. The bundled browser accepts
                at most 1,048,576 UTF-16 code units per element.
            order: Optional ordering, smallest values will be displayed first.
            visible: Whether the component is visible.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        content = _validate_gui_html_content(content)
        message = _messages.GuiHtmlMessage(
            uuid=_make_uuid(),
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiHtmlProps(
                order=self._apply_default_order(order),
                content=content,
                visible=visible,
            ),
        )
        handle = GuiHtmlHandle(
            _GuiHandleState(
                message.uuid,
                self,
                None,
                props=message.props,
                parent_container_id=message.container_uuid,
                create_message=message,
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
                order=self._apply_default_order(order),
                visible=visible,
            ),
        )
        handle = GuiDividerHandle(
            _GuiHandleState(
                message.uuid,
                self,
                None,
                props=message.props,
                parent_container_id=message.container_uuid,
                create_message=message,
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
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None")
        if type(visible) is not bool:
            raise TypeError("visible must be a bool")
        if order is not None:
            _validate_number(order, "order")
        _validate_image_encoding_options(format, jpeg_quality)
        if type(image) is not np.ndarray:
            raise TypeError("image must be a base numpy.ndarray")
        image_array = image
        spec = _ndarray_snapshot_spec(image_array)
        if spec[2] > _GUI_AGGREGATE_PAYLOAD_MAX_BYTES:
            raise RuntimeError("Image source exceeds the 128 MiB GUI retained payload budget.")
        container_uuid = self._get_container_uuid()
        resolved_order = self._apply_default_order(order)
        with self._server._reserve_image_preparation(spec[2]):
            image_array = _private_ndarray_snapshot(image_array, spec)
            if format == "jpeg" and image_array.ndim == 3 and image_array.shape[2] == 4:
                warnings.warn(
                    "Encoding an RGBA image as JPEG discards its alpha channel.",
                    stacklevel=2,
                )
            resolved_format, data = encode_image_binary(
                image_array, format, jpeg_quality=jpeg_quality
            )
            message = _messages.GuiImageMessage(
                uuid=_make_uuid(),
                container_uuid=container_uuid,
                props=_messages.GuiImageProps(
                    _data=data,
                    label=label,
                    _format=resolved_format,
                    order=resolved_order,
                    visible=visible,
                ),
            )
            return GuiImageHandle(
                _GuiHandleState(
                    message.uuid,
                    self,
                    None,
                    props=message.props,
                    parent_container_id=message.container_uuid,
                    create_message=message,
                    decoded_pixels=int(image_array.shape[0]) * int(image_array.shape[1]),
                    retained_extra_bytes=int(image_array.nbytes),
                ),
                _image=image_array,
                _jpeg_quality=jpeg_quality,
                _user_format=format,
            )

    def _ensure_plotly_js_sent(self) -> None:
        """Ensure every recipient of this API can render Plotly figures."""
        self._server._ensure_plotly_js_sent(self._plotly_connection)

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
                an independent copy from bounded JSON. The final JSON must fit
                the bundled browser's 16,777,216 UTF-16-code-unit render limit.
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
        if type(visible) is not bool:
            raise TypeError("visible must be a bool")
        if order is not None:
            _validate_number(order, "order")
        with self._server._reserve_renderer_preparation():
            plotly_json, _ = _plotly_json_and_config(figure, config)

        # Plotly must be available before the valid figure creation message.
        self._ensure_plotly_js_sent()

        message = _messages.GuiPlotlyMessage(
            uuid=_make_uuid(),
            container_uuid=self._get_container_uuid(),
            props=_messages.GuiPlotlyProps(
                order=self._apply_default_order(order),
                _plotly_json_str=plotly_json,
                aspect=aspect,
                visible=visible,
            ),
        )
        return GuiPlotlyHandle(
            _GuiHandleState(
                message.uuid,
                self,
                value=None,
                props=message.props,
                parent_container_id=message.container_uuid,
                create_message=message,
            )
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
        if type(color) is not str:
            raise ValueError(
                "color= takes one role per button, and a single button is one button;"
                " pass the role itself rather than a sequence."
            )
        color = _validate_button_color(color)

        # Re-wrap the GUI handle with a button interface.
        uuid = _make_uuid()
        order = self._apply_default_order(order)
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

        color = _validate_button_color(color)

        # Re-wrap the GUI handle with a button interface.
        uuid = _make_uuid()
        order = self._apply_default_order(order)
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

        color = _validate_button_color(color)
        content = cast(
            DownloadContent,
            _validate_file_content(content, filename, "add_download_button()"),
        )

        uuid = _make_uuid()
        order = self._apply_default_order(order)
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

        state = self._create_gui_input(False, message, is_button=True)
        state.retained_extra_bytes = len(cast(bytes, content)) if type(content) is bytes else 0
        handle = GuiDownloadButtonHandle(
            state,
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

        color = _validate_button_color(color)
        content = cast(
            PreviewContent,
            _validate_file_content(content, filename, "add_preview_button()"),
        )
        _validate_nonnegative_integer(max_bytes, "max_bytes")

        uuid = _make_uuid()
        order = self._apply_default_order(order)
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

        state = self._create_gui_input(False, message, is_button=True)
        state.retained_extra_bytes = len(cast(bytes, content)) if type(content) is bytes else 0
        handle = GuiPreviewButtonHandle(
            state,
            _icon=icon,
            _content=content,
            _filename=filename,
            _max_bytes=max_bytes,
        )
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
        _is_form_actions: bool = False,
    ) -> GuiButtonGroupHandle:
        """The many-faced half of :meth:`add_button`."""
        options = _string_options(options, "add_button()")
        value = options[0]
        uuid = _make_uuid()
        order = self._apply_default_order(order)
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
                is_form_actions=_is_form_actions,
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
            if type(color) is not str:
                raise ValueError(
                    "color= takes one role per toggle, and a single toggle is one"
                    " toggle; pass the role itself rather than a sequence."
                )
            color = _validate_button_color(color)
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
            order = self._apply_default_order(order)
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
        order = self._apply_default_order(order)
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
        order = self._apply_default_order(order)
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
        value = _validate_unicode_string(value, "text input value")
        if utf16_code_unit_length_exceeds(value, _GUI_TEXT_MAX_UTF16_CODE_UNITS):
            raise ValueError("Text exceeds the 1 Mi-character browser render limit.")
        if rows is not None:
            if type(rows) is not int or rows < 1:
                raise ValueError(
                    f"rows= is a height in lines and must be a positive integer; got {rows!r}."
                )
        if type(editable) is not bool or type(markdown) is not bool or type(multiline) is not bool:
            raise TypeError("editable, markdown, and multiline must be bools.")
        if markdown and editable:
            raise ValueError("markdown text must be read-only (editable=False).")
        if image_root is not None:
            if not isinstance(image_root, Path):
                raise TypeError("image_root must be a pathlib.Path or None.")
            image_root = Path(os.fspath(image_root))
        source = _gui_text_source(
            value,
            markdown=markdown,
            editable=editable,
            image_root=image_root,
            server=self._server,
        )
        uuid = _make_uuid()
        order = self._apply_default_order(order)
        return GuiTextHandle(
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
                        _source=source,
                    ),
                ),
            ),
            _image_root=image_root,
        )

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
        entries = _bounded_tuple(initial_value, "list")
        for entry in entries:
            if not isinstance(entry, str):
                raise ValueError(
                    "add_list() holds text entries, so initial_value= is a sequence of"
                    f" strings; got {entry!r}. Pass str(...) for anything else."
                )
            _validate_collection_string(entry, "list")
        uuid = _make_uuid()
        order = self._apply_default_order(order)
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
        order = self._apply_default_order(order)
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
            value = cast(IntOrFloat, float(value))

        if step is None:
            # It's ok that `step` is always a float, even if the value is an integer,
            # because things all become `number` types after serialization.
            step = cast(
                IntOrFloat,
                float(
                    np.min(
                        [
                            _compute_step(value),
                            _compute_step(min),
                            _compute_step(max),
                        ]
                    )
                ),
            )
        if step is None:
            raise RuntimeError("number input step computation did not produce a value")

        uuid = _make_uuid()
        order = self._apply_default_order(order)
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
        order = self._apply_default_order(order)

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
        order = self._apply_default_order(order)

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
        else:
            value = next((option for option in options_tuple if option == value), None)
            if value is None:
                raise ValueError(
                    f"Dropdown initial_value is not one of the options {options_tuple!r}."
                )
        uuid = _make_uuid()
        order = self._apply_default_order(order)
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
                order=self._apply_default_order(order),
                animated=animated,
                visible=visible,
            ),
        )
        handle = GuiProgressBarHandle(
            _GuiHandleState(
                message.uuid,
                self,
                value=initial_value,
                props=message.props,
                parent_container_id=message.container_uuid,
                create_message=message,
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
        if max > min:
            step = builtins.min(step, max - min)
        if not (min <= value <= max):
            raise ValueError(f"initial_value {value} is outside [{min}, {max}].")

        # Incoming client edits are cast to the type of the stored value, so an
        # int value with float bounds would truncate every edit. Promote it.
        if type(value) is int and (type(min) is float or type(max) is float or type(step) is float):
            value = cast(IntOrFloat, float(value))

        uuid = _make_uuid()
        order = self._apply_default_order(order)
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
        initial_value = _bounded_tuple(initial_value, "multi-slider values")
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
            initial_value = cast(tuple[IntOrFloat, ...], tuple(float(x) for x in initial_value))

        uuid = _make_uuid()
        order = self._apply_default_order(order)
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
        order = self._apply_default_order(order)
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
        order = self._apply_default_order(order)
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
        is_form_actions: bool = False,
    ) -> _GuiHandleState[T]:
        """Private helper for adding a simple GUI element."""

        if not isinstance(message, _messages.Message):
            raise TypeError("GUI input messages must derive from Message")

        # Construct state first. The concrete handle registers itself and only
        # then publishes this deferred creation message, so an event-loop
        # consumer can never answer an element Python has not registered yet.
        handle_state = _GuiHandleState(
            props=message.props,
            gui_api=self,
            value=value,
            update_timestamp=time.time(),
            parent_container_id=self._get_container_uuid(),
            update_cb=[],
            is_button=is_button,
            is_form_actions=is_form_actions,
            sync_cb=None,
            uuid=message.uuid,
            create_message=message,
        )

        # For broadcasted GUI handles, we should synchronize all clients.
        # This will be a no-op for client handles.
        if not is_button:

            def sync_other_clients(client_id: ClientId, updates: dict[str, Any]) -> None:
                message = _messages.GuiUpdateMessage(handle_state.uuid, updates)
                message.excluded_self_client = client_id
                self._websock_interface.queue_message_or_raise(message)

            handle_state.sync_cb = sync_other_clients

        return handle_state


install_container_add_methods(GuiApi)
