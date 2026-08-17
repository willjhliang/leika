from __future__ import annotations

import asyncio
import base64
import contextlib
import copy
import dataclasses
import datetime
import decimal
import functools
import inspect
import itertools
import json
import math
import os
import re
import time
import uuid
import warnings
from collections.abc import Coroutine, Mapping, Sequence
from numbers import Real
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    Generic,
    Iterable,
    Iterator,
    Literal,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)
from urllib.parse import unquote, urlsplit

import numpy as np
from typing_extensions import Protocol, Self, override

from ._assignable_props_api import AssignablePropsBase
from ._async_errors import (
    callback_result_is_awaitable,
    print_async_errors,
    print_async_exception,
)
from ._file_transfer import (
    open_regular_file,
    validate_file_display_name,
    validate_unchanged_file_snapshot,
)
from ._icons import svg_from_icon
from ._icons_enum import IconName
from ._image_encoding import _validate_image_encoding_options, encode_image_binary
from ._messages import (
    ButtonColor,
    CommandProps,
    CommandUpdateMessage,
    FileDisposition,
    GuiBaseProps,
    GuiButtonGroupProps,
    GuiButtonProps,
    GuiCheckboxProps,
    GuiChecklistProps,
    GuiCloseModalMessage,
    GuiDividerProps,
    GuiDropdownProps,
    GuiFolderProps,
    GuiFormProps,
    GuiFormSubmitMessage,
    GuiHtmlProps,
    GuiImageProps,
    GuiListProps,
    GuiMultiSliderProps,
    GuiNumberProps,
    GuiPlotlyProps,
    GuiProgressBarProps,
    GuiRemoveMessage,
    GuiRgbaProps,
    GuiRgbProps,
    GuiSliderMark,
    GuiSliderProps,
    GuiTab,
    GuiTabGroupProps,
    GuiTabMessage,
    GuiTabUpdateMessage,
    GuiTextProps,
    GuiToggleGroupProps,
    GuiToggleProps,
    GuiUpdateMessage,
    GuiUploadButtonProps,
    GuiVector2Props,
    GuiVector3Props,
    RemoveCommandMessage,
    _normalize_key_modifier,
)
from ._validation import utf16_code_unit_length, utf16_code_unit_length_exceeds
from ._validation import validate_finite_number as _finite_number
from ._validation import validate_positive_number as _positive_number
from ._validation import validate_renderer_string as _validate_renderer_string
from ._validation import validate_unicode_string as _validate_unicode_string
from .infra import ClientId, Message
from .infra._image_headers import safe_image_info
from .infra._infra import HttpAsset

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from ._gui_api import GuiApi
    from ._server import ClientHandle, Server


T = TypeVar("T")
TGuiHandle = TypeVar("TGuiHandle", bound="_GuiHandle")
NoneOrCoroutine = TypeVar("NoneOrCoroutine", None, Coroutine)

_GUI_COMPONENT_MAX = 4096
_GUI_COLLECTION_MAX = 4096
_GUI_AGGREGATE_COLLECTION_MAX = 16 * 1024
_GUI_AGGREGATE_TEXT_MAX_UTF16_CODE_UNITS = 16 * 1024 * 1024
_GUI_AGGREGATE_PAYLOAD_MAX_BYTES = 128 * 1024 * 1024
_GUI_AGGREGATE_PIXELS_MAX = 64 * 1024 * 1024
_GUI_CONTAINER_DEPTH_MAX = 64
_GUI_COLLECTION_ITEM_MAX_UTF16_CODE_UNITS = 16 * 1024
_GUI_TEXT_MAX_UTF16_CODE_UNITS = 1024 * 1024
_GUI_COMMAND_MAX = 1024
_GUI_MODAL_MAX = 32
_GUI_NOTIFICATION_MAX = 128
_GUI_CALLBACK_MAX = 256
_GUI_PROGRAMMATIC_CALLBACK_BATCH_MAX = 1024
_GUI_PROGRAMMATIC_CALLBACK_RETAINED_MAX_BYTES = 128 * 1024 * 1024
_GUI_FORM_ACTION_ORDER = float.fromhex("0x1.fffffffffffffp+1023")


@dataclasses.dataclass(frozen=True)
class _GuiResourceCost:
    collection_items: int = 0
    text_units: int = 0
    payload_bytes: int = 0
    decoded_pixels: int = 0

    def __add__(self, other: "_GuiResourceCost") -> "_GuiResourceCost":
        return _GuiResourceCost(
            self.collection_items + other.collection_items,
            self.text_units + other.text_units,
            self.payload_bytes + other.payload_bytes,
            self.decoded_pixels + other.decoded_pixels,
        )

    def __sub__(self, other: "_GuiResourceCost") -> "_GuiResourceCost":
        return _GuiResourceCost(
            self.collection_items - other.collection_items,
            self.text_units - other.text_units,
            self.payload_bytes - other.payload_bytes,
            self.decoded_pixels - other.decoded_pixels,
        )


def _gui_resource_cost(
    value: object,
    props: object,
    *,
    decoded_pixels: int = 0,
    retained_extra_bytes: int = 0,
) -> _GuiResourceCost:
    """Measure a bounded retained value/props graph with browser-parity rules."""
    collection_items = 0
    text_units = 0
    payload_bytes = retained_extra_bytes
    nodes = 0
    active: set[int] = set()
    stack: list[tuple[object, int, bool]] = [(value, 0, False), (props, 0, False)]
    while stack:
        item, depth, exiting = stack.pop()
        if exiting:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > 100_000:
            raise ValueError("GUI retained state contains too many values")
        if depth > _GUI_CONTAINER_DEPTH_MAX:
            raise ValueError("GUI retained state is nested too deeply")
        if item is None or isinstance(item, (bool, Real)):
            continue
        if isinstance(item, str):
            item = _validate_unicode_string(item, "GUI string")
            text_units += utf16_code_unit_length(item)
            payload_bytes += len(item.encode("utf-8"))
            continue
        if isinstance(item, bytes):
            payload_bytes += len(item)
            continue
        if isinstance(item, np.ndarray):
            payload_bytes += int(item.nbytes)
            continue

        composite = (dataclasses.is_dataclass(item) and not isinstance(item, type)) or isinstance(
            item, (Mapping, tuple, list)
        )
        if not composite:
            raise TypeError(f"unsupported retained GUI value: {type(item).__name__}")
        identity = id(item)
        if identity in active:
            raise ValueError("GUI retained state cannot contain cycles")
        active.add(identity)
        stack.append((item, depth, True))
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            children = tuple(getattr(item, field.name) for field in dataclasses.fields(item))
        elif isinstance(item, Mapping):
            children = (*item.keys(), *item.values())
        else:
            children = tuple(cast(Iterable[object], item))
            collection_items += len(children)
        stack.extend((child, depth + 1, False) for child in reversed(children))
    return _GuiResourceCost(
        collection_items,
        text_units,
        payload_bytes,
        decoded_pixels,
    )


def _bounded_tuple(
    values: Iterable[Any],
    control: str,
    *,
    limit: int | None = None,
) -> tuple[Any, ...]:
    """Materialize at most ``limit + 1`` items from an untrusted iterable."""
    if limit is None:
        limit = _GUI_COLLECTION_MAX
    if isinstance(values, Sequence) and len(values) > limit:
        raise ValueError(f"{control} cannot contain more than {limit} items.")
    materialized = tuple(itertools.islice(iter(values), limit + 1))
    if len(materialized) > limit:
        raise ValueError(f"{control} cannot contain more than {limit} items.")
    return materialized


def _validate_collection_size(values: Sequence[object], control: str) -> None:
    if len(values) > _GUI_COLLECTION_MAX:
        raise ValueError(f"{control} cannot contain more than {_GUI_COLLECTION_MAX} items.")


def _validate_collection_string(value: object, control: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{control} entries must be strings; got {value!r}.")
    value = _validate_unicode_string(value, f"{control} entry")
    if utf16_code_unit_length_exceeds(value, _GUI_COLLECTION_ITEM_MAX_UTF16_CODE_UNITS):
        raise ValueError(
            f"{control} entries cannot exceed "
            f"{_GUI_COLLECTION_ITEM_MAX_UTF16_CODE_UNITS} UTF-16 code units."
        )
    return value


def _validate_slider_marks(
    marks: object,
) -> tuple[GuiSliderMark, ...] | None:
    """Bound and validate the exact retained slider-mark wire records."""
    if marks is None:
        return None
    if isinstance(marks, (str, bytes)):
        raise TypeError("slider marks must be an iterable of GuiSliderMark objects")
    try:
        materialized = _bounded_tuple(cast(Iterable[Any], marks), "slider marks")
    except TypeError as error:
        raise TypeError("slider marks must be an iterable of GuiSliderMark objects") from error
    for mark in materialized:
        if type(mark) is not GuiSliderMark:
            raise TypeError("slider marks must contain exact GuiSliderMark objects")
        _finite_number(mark.value, "slider mark value")
        if mark.label is not None:
            _validate_collection_string(mark.label, "slider mark labels")
    return cast(tuple[GuiSliderMark, ...], materialized)


def _make_uuid() -> str:
    """Return a unique ID for referencing GUI elements."""
    return str(uuid.uuid4())


def _string_options(options: Iterable[Any], control: str) -> tuple[str, ...]:
    """Validate labels used as both display text and stable values."""
    if isinstance(options, str):
        raise ValueError(f"{control} options must be a sequence, not one string.")
    values = _bounded_tuple(options, f"{control} options")
    if not values:
        raise ValueError(f"{control} requires at least one option.")
    _validate_collection_size(values, f"{control} options")
    for value in values:
        _validate_collection_string(value, f"{control} options")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"{control} options must be unique; repeated {sorted(duplicates)!r}.")
    return values


def _ndarray_snapshot_spec(value: np.ndarray) -> tuple[tuple[int, ...], np.dtype[Any], int]:
    """Capture the only shape and storage size an admitted copy may allocate."""
    if type(value) is not np.ndarray:
        raise TypeError("image must be a base numpy.ndarray")
    shape = tuple(int(size) for size in value.shape)
    dtype = value.dtype
    nbytes = math.prod(shape) * int(dtype.itemsize)
    return shape, dtype, nbytes


def _private_ndarray_snapshot(
    value: np.ndarray,
    spec: tuple[tuple[int, ...], np.dtype[Any], int],
) -> np.ndarray:
    """Copy into fixed charged storage without trusting a later shape read.

    Callers must not mutate or resize their source while an API call is in
    progress. A buffer export blocks ordinary accidental resize; NumPy's
    explicit ``resize(refcheck=False)`` escape hatch remains outside this
    public contract, while the fixed destination still bounds Leika's own
    allocation.
    """
    shape, dtype, nbytes = spec
    if math.prod(shape) * int(dtype.itemsize) != nbytes:
        raise RuntimeError("invalid ndarray snapshot specification")
    exported = memoryview(value)
    try:
        snapshot = np.empty(shape, dtype=dtype, order="C")
        np.copyto(snapshot, value, casting="no")
    finally:
        exported.release()
    if value.shape != shape or value.dtype != dtype:
        raise ValueError("image changed shape or dtype while it was snapshotted")
    return snapshot


@overload
def _cast_vector(vector: tuple | np.ndarray, length: Literal[2]) -> tuple[float, float]: ...


@overload
def _cast_vector(vector: tuple | np.ndarray, length: Literal[3]) -> tuple[float, float, float]: ...


def _cast_vector(vector: tuple | np.ndarray, length: int) -> tuple[float, ...]:
    """Normalize a fixed-length vector without coercing strings or booleans."""
    if type(vector) is np.ndarray:
        shape = vector.shape
        components = tuple(vector) if shape == (length,) else ()
    elif isinstance(vector, np.ndarray):
        raise TypeError("Vector values must use a base numpy.ndarray, not a subclass.")
    elif isinstance(vector, (tuple, list)):
        shape = (len(vector),)
        components = tuple(vector)
    else:
        shape = ()
        components = ()
    if shape != (length,):
        raise ValueError(f"Expected vector of shape {(length,)}, got {shape}.")

    values: list[float] = []
    for component in components:
        if isinstance(component, (bool, np.bool_)) or not isinstance(component, Real):
            raise ValueError("Vector components must be real numbers.")
        try:
            normalized = float(component)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Vector components must be finite real numbers.") from error
        if not math.isfinite(normalized):
            raise ValueError("Vector components must be finite.")
        values.append(normalized)
    return tuple(values)


TLockedMethod = TypeVar("TLockedMethod", bound=Callable[..., Any])


def _locked_gui_handle_method(method: TLockedMethod) -> TLockedMethod:
    """Linearize one custom handle mutation with removal and wire order."""

    @functools.wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._impl.gui_api._lock:
            if self._impl.removed:
                raise RuntimeError(f"Cannot update a removed {type(self).__name__}.")
            return method(self, *args, **kwargs)

    return cast("TLockedMethod", wrapped)


def _schedule_callback_result(
    event_loop: asyncio.AbstractEventLoop, server: Server, result: object
) -> None:
    """Schedule any Future/Awaitable callback result on its owning loop."""
    if not callback_result_is_awaitable(result):
        return
    coroutine = server._await_user_callback_result(result)
    try:
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is event_loop:
            future = event_loop.create_task(coroutine)
        else:
            future = asyncio.run_coroutine_threadsafe(coroutine, event_loop)
    except Exception as error:
        # Scheduling did not take ownership. Close both the wrapper and a raw
        # coroutine returned by the callback so shutdown cannot leak either as
        # an un-awaited object; concurrent/custom awaitables have no such
        # universally safe cancellation operation.
        coroutine.close()
        if inspect.iscoroutine(result):
            result.close()
        print_async_exception(error)
        return
    future.add_done_callback(print_async_errors)


def _invoke_programmatic_callbacks(
    callbacks: Iterable[Callable[[Any], object]],
    event: object,
    *,
    gui_api: GuiApi,
) -> None:
    """Queue a stable callback batch in programmatic assignment order."""
    gui_api._schedule_programmatic_callbacks(tuple(callbacks), event)


class GuiContainerProtocol(Protocol):
    _children: dict[str, SupportsRemoveProtocol]


class SupportsRemoveProtocol(Protocol):
    def remove(self) -> None: ...


class GuiPropsProtocol(Protocol):
    order: float


class GuiContainer:
    """Common interface for objects that can contain GUI components.

    Containers support both context-manager creation and direct child calls,
    for example ``folder.add_slider(...)``. Direct calls only change the
    target container for the duration of the call, so both styles can be
    mixed safely.
    """

    @property
    def _child_gui_api(self) -> GuiApi:
        raise NotImplementedError

    @property
    def _child_container_id(self) -> str:
        raise NotImplementedError

    def _check_container_active(self) -> None:
        """Raise if this container can no longer accept children."""

    @property
    def id(self) -> str:
        """Stable identifier for this container."""

        return self._child_container_id

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}.")

    def __enter__(self) -> Self:
        self._check_container_active()
        self._child_gui_api._push_container_uuid(self._child_container_id)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        del exc_value, traceback
        self._child_gui_api._pop_container_uuid()
        if exc_type is None:
            return
        # A context that failed while constructing UI must not leave its
        # partially published subtree alive. Preserve the caller's original
        # exception even if shutdown prevents the best-effort retirement.
        try:
            if isinstance(self, GuiModalHandle):
                self.close()
            else:
                remove = getattr(self, "remove", None)
                if callable(remove):
                    remove()
        except BaseException as cleanup_error:
            print_async_exception(cleanup_error)

    def _add_child(self, method: str, *args: Any, **kwargs: Any) -> Any:
        # Direct child calls only borrow the container target; unlike an
        # explicitly entered construction context, a failing child operation
        # must not retire an already-live container and its existing subtree.
        self._check_container_active()
        gui_api = self._child_gui_api
        gui_api._push_container_uuid(self._child_container_id)
        try:
            return getattr(gui_api, method)(*args, **kwargs)
        finally:
            gui_api._pop_container_uuid()


_GUI_HTML_MAX_UTF16_CODE_UNITS = 1 * 1024 * 1024
"""Bundled browser DOM-source limit for one HTML GUI element."""


def _validate_gui_html_content(content: object) -> str:
    if type(content) is not str:
        raise TypeError("HTML content must be a string.")
    if utf16_code_unit_length_exceeds(content, _GUI_HTML_MAX_UTF16_CODE_UNITS):
        raise ValueError("HTML content exceeds the 1 Mi-character browser render limit.")
    return content


_CONTAINER_SCOPED_ATTR = "_leika_container_scoped"

TCallable = TypeVar("TCallable", bound=Callable[..., Any])


def not_container_scoped(method: TCallable) -> TCallable:
    """Mark a ``GuiApi.add_*`` that does not create a child of the current
    container, and so is not mirrored onto :class:`GuiContainer`.

    Notifications and commands are addressed to the client, not placed in the
    GUI tree, so ``folder.add_notification(...)`` would promise a containment
    that does not exist."""

    setattr(method, _CONTAINER_SCOPED_ATTR, False)
    return method


def _container_add_method(method: str) -> Callable[..., Any]:
    """Build the ``GuiContainer`` forwarder for one ``GuiApi.add_*``.

    A factory rather than a closure written inline, so ``method`` is captured
    per call instead of leaking into the forwarder's own signature as a
    keyword a caller could pass."""

    def add(self: GuiContainer, *args: Any, **kwargs: Any) -> Any:
        return self._add_child(method, *args, **kwargs)

    add.__name__ = method
    add.__qualname__ = f"GuiContainer.{method}"
    add.__doc__ = f"Add a child via :meth:`GuiApi.{method}`."
    return add


def install_container_add_methods(gui_api_type: type) -> None:
    """Mirror ``GuiApi``'s container-scoped ``add_*`` onto
    :class:`GuiContainer`.

    Derived from ``GuiApi`` rather than listed by hand, so a newly added
    element is reachable as ``folder.add_thing(...)`` the moment it exists on
    the API; the exceptions opt out at their definition with
    :func:`not_container_scoped`. Called from ``_gui_api`` once ``GuiApi`` is
    defined, since this module is imported on the way there and cannot name it
    at import time.
    """

    for method in dir(gui_api_type):
        if not method.startswith("add_") or hasattr(GuiContainer, method):
            continue
        if not getattr(getattr(gui_api_type, method), _CONTAINER_SCOPED_ATTR, True):
            continue
        setattr(GuiContainer, method, _container_add_method(method))


@dataclasses.dataclass
class _GuiHandleState(Generic[T]):
    """Internal API for GUI elements."""

    uuid: str
    gui_api: GuiApi
    value: T
    props: GuiPropsProtocol
    parent_container_id: str
    """Container that this GUI input was placed into."""

    update_timestamp: float = 0.0
    update_cb: list[Callable[[GuiEvent], None | Coroutine]] = dataclasses.field(
        default_factory=list
    )
    """Registered functions to call when this input is updated."""

    is_button: bool = False
    """Indicates a button element, which requires special handling."""
    is_form_actions: bool = False
    """Internal Reset/Submit row allowed to own the reserved terminal order."""

    sync_cb: Callable[[ClientId, dict[str, Any]], None] | None = None
    """Callback for synchronizing inputs across clients."""

    removed: bool = False
    disabled_generation: int = 0
    create_message: Message | None = None
    """Creation publication deferred until the concrete handle is registered."""
    decoded_pixels: int = 0
    """Decoded raster pixels retained by this component, if any."""
    retained_extra_bytes: int = 0
    """Owned bytes outside value/props, such as a source ndarray copy."""
    owning_form_uuid: str | None = None
    initial_value: object = None

    @property
    def state_lock(self) -> ContextManager[object]:
        return self.gui_api._lock


_GUI_NUMERIC_PRECISION_MAX = 100
_GUI_MIME_TYPE_MAX_CHARS = 255


def _ancestor_form_locked(handle: Any) -> GuiFormHandle | None:
    """Find the enclosing form through folders, tab groups, and tabs."""
    gui_api = handle._impl.gui_api
    container_uuid = handle._impl.parent_container_id
    visited: set[str] = set()
    while container_uuid != "root":
        if container_uuid in visited:
            raise RuntimeError("GUI container ancestry contains a cycle")
        visited.add(container_uuid)
        container = gui_api._container_handle_from_uuid.get(container_uuid)
        if isinstance(container, GuiFormHandle):
            return container
        if isinstance(container, GuiTabHandle):
            container_uuid = container._parent._impl.parent_container_id
        elif isinstance(container, _GuiHandle):
            container_uuid = container._impl.parent_container_id
        else:
            break
    return None


def _validate_gui_props_candidate(handle: Any, props: Any) -> None:
    """Enforce constructor invariants for one prospective live-props state."""
    specialized_strings = {"content", "_source", "_plotly_json_str"}
    for field in dataclasses.fields(props):
        item = getattr(props, field.name)
        if field.name not in specialized_strings and isinstance(item, str):
            _validate_renderer_string(item, field.name)
        elif field.name not in specialized_strings and isinstance(item, tuple):
            for element in item:
                if isinstance(element, str):
                    _validate_collection_string(element, field.name)

    order = getattr(props, "order", None)
    if handle._impl.is_form_actions:
        if order != _GUI_FORM_ACTION_ORDER:
            raise ValueError("A form's Reset/Submit actions must keep their terminal order.")
        if getattr(props, "options", None) != ("Reset", "Submit"):
            raise ValueError("A form's actions must remain exactly Reset and Submit.")
    if order is not None:
        _finite_number(order, "order")
        if (
            order == _GUI_FORM_ACTION_ORDER
            and not handle._impl.is_form_actions
            and _ancestor_form_locked(handle) is not None
        ):
            raise ValueError(
                "sys.float_info.max is reserved for a form's Reset/Submit actions; "
                "choose a smaller child order"
            )

    if isinstance(props, GuiPlotlyProps):
        _positive_number(props.aspect, "aspect")

    if isinstance(props, GuiUploadButtonProps):
        if (
            type(props.mime_type) is not str
            or len(props.mime_type) > _GUI_MIME_TYPE_MAX_CHARS
            or any(ord(character) < 32 or ord(character) == 127 for character in props.mime_type)
        ):
            raise ValueError("mime_type must be a control-free string of at most 255 characters.")

    if isinstance(
        props,
        (GuiNumberProps, GuiSliderProps, GuiMultiSliderProps, GuiVector2Props, GuiVector3Props),
    ):
        if not 0 <= props.precision <= _GUI_NUMERIC_PRECISION_MAX:
            raise ValueError(f"precision must be within [0, {_GUI_NUMERIC_PRECISION_MAX}].")
        _positive_number(props.step, "step")

    value = handle._impl.value
    if isinstance(props, GuiNumberProps):
        if props.min is not None and props.max is not None and props.min > props.max:
            raise ValueError("min must be at most max.")
        if props.min is not None and value < props.min:
            raise ValueError("current value is below min.")
        if props.max is not None and value > props.max:
            raise ValueError("current value is above max.")

    if isinstance(props, (GuiSliderProps, GuiMultiSliderProps)):
        _validate_slider_marks(props._marks)
        if props.min > props.max:
            raise ValueError("slider min must be at most max.")
        if props.max > props.min and props.step > props.max - props.min:
            raise ValueError("step must not exceed the slider range.")

    if isinstance(props, GuiSliderProps) and not props.min <= value <= props.max:
        raise ValueError("current value must remain within the slider range.")

    if isinstance(props, GuiMultiSliderProps):
        values = tuple(value)
        if any(not props.min <= item <= props.max for item in values):
            raise ValueError("current values must remain within the slider range.")
        if any(left > right for left, right in zip(values, values[1:])):
            raise ValueError("current slider values must remain ordered.")
        if props.min_range is not None:
            if props.min_range < 0:
                raise ValueError("min_range must be non-negative.")
            if any(right - left < props.min_range for left, right in zip(values, values[1:])):
                raise ValueError("current values are closer than min_range.")

    if isinstance(props, (GuiVector2Props, GuiVector3Props)):
        if (
            props.min is not None
            and props.max is not None
            and any(lo > hi for lo, hi in zip(props.min, props.max))
        ):
            raise ValueError("Each vector min component must be at most max.")
        if props.min is not None and any(item < lo for item, lo in zip(value, props.min)):
            raise ValueError("current value has a component below min.")
        if props.max is not None and any(item > hi for item, hi in zip(value, props.max)):
            raise ValueError("current value has a component above max.")

    if isinstance(props, GuiTextProps):
        if props.rows is not None and props.rows < 1:
            raise ValueError("rows must be a positive integer or None.")
        if props.markdown and props.editable:
            raise ValueError("markdown text must be read-only (editable=False).")

    if isinstance(props, GuiToggleGroupProps):
        _validate_collection_size(props.options, "toggle options")
        if not props.options or len(set(props.options)) != len(props.options):
            raise ValueError("toggle options must be non-empty and unique.")
        if len(props.color) != len(props.options):
            raise ValueError("toggle colors must match the option count.")
        if len(props._merge) != max(0, len(props.options) - 1):
            raise ValueError("toggle merge flags must match the option gaps.")
        selected = tuple(value)
        if len(set(selected)) != len(selected) or any(
            option not in props.options for option in selected
        ):
            raise ValueError("current toggle value must name unique options.")
        if not props.multiple and len(selected) > 1:
            raise ValueError("multiple=False permits at most one selected option.")
        if props.required and not selected:
            raise ValueError("required=True needs one selected option.")

    if isinstance(props, GuiButtonGroupProps):
        _validate_collection_size(props.options, "button options")
        if not props.options or len(set(props.options)) != len(props.options):
            raise ValueError("button options must be non-empty and unique.")
        if len(props.color) != len(props.options):
            raise ValueError("button colors must match the option count.")
        if len(props._merge) != max(0, len(props.options) - 1):
            raise ValueError("button merge flags must match the option gaps.")
        if value not in props.options:
            raise ValueError("current button value must remain in options.")


# Not exported: some GUI handles do not inherit from `_GuiHandle` -- notably
# `GuiModalHandle` and `GuiTabHandle`, which are containers rather than
# elements. Exporting it would invite isinstance checks that those fail.
class _GuiHandle(Generic[T], AssignablePropsBase[_GuiHandleState]):
    def __init__(self, impl: _GuiHandleState[T]) -> None:
        super().__init__(impl=impl)
        gui_api = self._impl.gui_api
        with gui_api._lock:
            gui_api._check_active_locked()
            parent = gui_api._container_handle_from_uuid.get(self._impl.parent_container_id)
            if parent is None:
                raise RuntimeError("GUI parent container is no longer active")
            parent_depth = gui_api._container_depth_locked(self._impl.parent_container_id)
            component_depth = parent_depth + 1
            if component_depth > _GUI_CONTAINER_DEPTH_MAX:
                raise RuntimeError(
                    f"GUI component graph depth cannot exceed {_GUI_CONTAINER_DEPTH_MAX}."
                )
            _validate_gui_props_candidate(self, self._impl.props)
            if gui_api._live_component_count >= _GUI_COMPONENT_MAX:
                raise RuntimeError(
                    f"A GUI cannot contain more than {_GUI_COMPONENT_MAX} live components."
                )

            input_registry = gui_api._gui_input_handle_from_uuid
            is_input = isinstance(self, _GuiInputHandle)
            is_editable_field = (
                is_input
                and not self._impl.is_button
                and getattr(self._impl.props, "editable", True)
            )
            ancestor_form = _ancestor_form_locked(self)
            if ancestor_form is not None:
                form_props = cast(GuiFormProps, ancestor_form._impl.props)
                if form_props.mini and (
                    not is_editable_field
                    or self._impl.parent_container_id != ancestor_form._impl.uuid
                    or bool(ancestor_form._children)
                ):
                    raise ValueError(
                        "A mini form holds a single field (exactly one direct editable field); "
                        "use add_form() for additional rows or containers."
                    )

            owning_form: GuiFormHandle | None = None
            initial_value: object = None
            baseline_cost = _GuiResourceCost()
            if is_editable_field:
                owning_form = ancestor_form
                if owning_form is not None:
                    initial_value = copy.deepcopy(self._impl.value)
                    baseline_cost = _gui_resource_cost(initial_value, None)

            resource_cost = _gui_resource_cost(
                self._impl.value,
                self._impl.props,
                decoded_pixels=self._impl.decoded_pixels,
                retained_extra_bytes=self._impl.retained_extra_bytes,
            )
            if owning_form is not None:
                resource_cost += baseline_cost
            old_resource = gui_api._set_gui_resource_locked(self._impl.uuid, resource_cost)
            old_baseline = gui_api._reset_baseline_resource_from_gui_uuid.get(self._impl.uuid)
            old_extra = gui_api._retained_extra_bytes_from_gui_uuid.get(self._impl.uuid)
            registered = False
            try:
                if owning_form is not None:
                    self._impl.owning_form_uuid = owning_form._impl.uuid
                    self._impl.initial_value = initial_value
                    gui_api._reset_baseline_resource_from_gui_uuid[self._impl.uuid] = baseline_cost
                if self._impl.retained_extra_bytes:
                    gui_api._retained_extra_bytes_from_gui_uuid[self._impl.uuid] = (
                        self._impl.retained_extra_bytes
                    )
                gui_api._live_component_count += 1
                registered = True
                parent._children[self._impl.uuid] = self
                if isinstance(self, (GuiContainer, GuiTabGroupHandle)):
                    gui_api._container_depth_from_uuid[self._impl.uuid] = component_depth
                if is_input:
                    input_registry[self._impl.uuid] = self
                if owning_form is not None:
                    owning_form._initial_field_uuids.add(self._impl.uuid)
                create_message = self._impl.create_message
                if create_message is not None:
                    gui_api._websock_interface.queue_message_or_raise(create_message)
                    self._impl.create_message = None
            except BaseException:
                parent._children.pop(self._impl.uuid, None)
                gui_api._container_depth_from_uuid.pop(self._impl.uuid, None)
                if registered:
                    gui_api._live_component_count -= 1
                gui_api._set_gui_resource_locked(self._impl.uuid, old_resource)
                if old_baseline is None:
                    gui_api._reset_baseline_resource_from_gui_uuid.pop(self._impl.uuid, None)
                else:
                    gui_api._reset_baseline_resource_from_gui_uuid[self._impl.uuid] = old_baseline
                if old_extra is None:
                    gui_api._retained_extra_bytes_from_gui_uuid.pop(self._impl.uuid, None)
                else:
                    gui_api._retained_extra_bytes_from_gui_uuid[self._impl.uuid] = old_extra
                if is_input:
                    input_registry.pop(self._impl.uuid, None)
                if owning_form is not None:
                    owning_form._initial_field_uuids.discard(self._impl.uuid)
                self._impl.owning_form_uuid = None
                self._impl.initial_value = None
                raise

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_impl" and hasattr(self, "_impl") and name in self._prop_hints:
            prop = getattr(type(self), name, None)
            if not (isinstance(prop, property) and prop.fset is not None):
                self.update(**{name: value})
                return
        super().__setattr__(name, value)

    @property
    def id(self) -> str:
        """Stable identifier for this GUI component."""
        return self._impl.uuid

    @override
    def _queue_update(self, name: str, value: Any) -> None:
        self._impl.gui_api._websock_interface.queue_message_or_raise(
            GuiUpdateMessage(self._impl.uuid, {name: value})
        )

    @override
    def _prop_assignment_transaction(self, name: str) -> ContextManager[object]:
        del name
        return self._impl.gui_api._gui_resource_transaction_locked(
            self._impl.uuid,
            self._impl.value,
            self._impl.props,
        )

    def _publish_internal_props_locked(self, **updates: Any) -> None:
        """Publish trusted derived props from a handle-owned state transition."""
        if not updates or not set(updates).issubset(_DERIVED_PROTOCOL_PROP_NAMES):
            raise RuntimeError("internal prop publication received an unsupported field")
        gui_api = self._impl.gui_api
        gui_api._check_active_locked()
        if self._impl.removed:
            raise RuntimeError(f"Cannot update a removed {type(self).__name__}.")
        candidate = dataclasses.replace(cast(Any, self._impl.props), **updates)
        _validate_gui_props_candidate(self, candidate)
        with gui_api._gui_resource_transaction_locked(self._impl.uuid, self._impl.value, candidate):
            gui_api._websock_interface.queue_message_or_raise(
                GuiUpdateMessage(self._impl.uuid, updates)
            )
            self._impl.props = candidate

    def update(self, **props: Any) -> None:
        """Atomically update one or more synchronized properties.

        Custom properties such as ``value``, ``icon``, and ``color`` own
        derived state and callbacks; update those one at a time. Plain protocol
        properties are validated as one candidate state and published in one
        message before local commit.
        """
        _reject_derived_protocol_props(props)
        if "_marks" in props and isinstance(
            self._impl.props, (GuiSliderProps, GuiMultiSliderProps)
        ):
            props = dict(props)
            props["_marks"] = _validate_slider_marks(props["_marks"])

        custom: list[str] = []
        for name in props:
            prop = getattr(type(self), name, None)
            has_setter = isinstance(prop, property) and prop.fset is not None
            if name not in self._prop_hints and not has_setter:
                raise TypeError(f"{type(self).__name__}.update() got an unknown property {name!r}.")
            if has_setter:
                custom.append(name)
        if custom:
            if len(props) != 1:
                raise TypeError(
                    "custom derived properties must be updated separately from other properties"
                )
            name = custom[0]
            setattr(self, name, props[name])
            return

        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError(f"Cannot update a removed {type(self).__name__}.")
            normalized = {
                name: self._cast_value_recursive(self._prop_hints[name], value)
                for name, value in props.items()
            }
            if not normalized:
                return
            candidate = dataclasses.replace(cast(Any, self._impl.props), **normalized)
            _validate_gui_props_candidate(self, candidate)
            with gui_api._gui_resource_transaction_locked(
                self._impl.uuid, self._impl.value, candidate
            ):
                gui_api._websock_interface.queue_message_or_raise(
                    GuiUpdateMessage(self._impl.uuid, normalized)
                )
                self._impl.props = candidate
            if "disabled" in normalized:
                self._impl.disabled_generation += 1

    def remove(self) -> None:
        """Permanently remove this GUI element from the visualizer."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            self._remove_impl()

    def _remove_impl(self) -> None:
        """Remove after any handle-specific synchronization is held."""

        # Warn if already removed.
        if self._impl.removed:
            warnings.warn(
                f"Attempted to remove an already removed {self.__class__.__name__}.",
                stacklevel=3,
            )
            return
        gui_api = self._impl.gui_api
        gui_api._websock_interface.queue_message_or_raise(GuiRemoveMessage(self._impl.uuid))
        _retire_gui_handle_without_queue_locked(self)


class _GuiInputHandle(
    _GuiHandle[T],
    Generic[T],
    GuiBaseProps,
):
    @property
    def value(self) -> T:
        """Value of the GUI input. Synchronized automatically when assigned.

        :meta private:
        """
        # Private for Sphinx, which cannot resolve the TypeVar readably; the
        # docs declare these attributes manually instead.
        if self._impl.removed:
            raise RuntimeError(f"Cannot read value from a removed {type(self).__name__}.")
        return self._impl.value

    def _coerce_assigned_value(self, value: T | np.ndarray) -> T | np.ndarray:
        """Validate an assigned scalar; specialized inputs normalize further."""
        current = self._impl.value
        if isinstance(current, bool) and type(value) is not bool:
            raise TypeError("boolean input value must be a bool")
        if isinstance(current, str) and type(value) is not str:
            raise TypeError("text input value must be a string")
        return value

    @contextlib.contextmanager
    def _value_assignment_transaction(self, value: T | np.ndarray) -> Iterator[None]:
        """Reserve handle-specific state around queueing and local assignment."""
        del value
        yield

    def _coerce_client_value(self, value: Any) -> Any:
        """Validate and normalize a value received from the browser."""
        current = self._impl.value
        if isinstance(current, bool):
            if type(value) is not bool:
                raise TypeError("client boolean value must be a bool")
            return value
        if isinstance(current, str):
            if not isinstance(value, str):
                raise TypeError("client text value must be a string")
            return value
        if not isinstance(current, tuple):
            if not isinstance(value, type(current)):
                raise TypeError(
                    f"client value must be a {type(current).__name__}, got {type(value).__name__}"
                )
            return value
        if len(current) == 0:
            return tuple(value)
        # Tuple contents are assumed homogeneous.
        typ = type(current[0])
        return tuple(typ(new) for new in value)

    def _normalize_assigned_value_locked(self, value: Any) -> T:
        """Return the exact validated stored value without mutating state."""
        value = self._coerce_assigned_value(value)
        if type(value) is np.ndarray:
            if value.ndim > 1:
                raise ValueError(
                    f"Input value array should be at most 1D; got shape {value.shape}."
                )
            elems = value.tolist()
            current = self._impl.value
            if isinstance(current, tuple) and len(current) == len(elems):
                value = tuple(
                    type(component)(element) for component, element in zip(current, elems)
                )
            else:
                value = tuple(elems)
        elif isinstance(value, np.ndarray):
            raise TypeError("Input values must use a base numpy.ndarray, not a subclass.")
        current_type = type(self._impl.value)
        if not isinstance(value, current_type):
            value = current_type(value)
        return cast(T, value)

    @value.setter
    def value(self, value: T | np.ndarray) -> None:
        self._assign_value(value)

    def _assign_value(self, value: T | np.ndarray) -> None:
        """Normalize and transactionally publish one programmatic value."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError(f"Cannot assign to 'value' on a removed {type(self).__name__}.")
            value = self._normalize_assigned_value_locked(value)

            if not self._impl.is_button:
                try:
                    if self._impl.value == value:
                        return
                except (TypeError, ValueError):
                    pass

            old_value = self._impl.value
            old_timestamp = self._impl.update_timestamp
            with self._value_assignment_transaction(value):
                try:
                    with gui_api._gui_resource_transaction_locked(
                        self._impl.uuid, value, self._impl.props
                    ):
                        if not self._impl.is_button:
                            gui_api._websock_interface.queue_message_or_raise(
                                GuiUpdateMessage(self._impl.uuid, {"value": value})
                            )
                        self._impl.value = cast(T, value)
                        self._impl.update_timestamp = time.time()
                except BaseException:
                    self._impl.value = old_value
                    self._impl.update_timestamp = old_timestamp
                    raise

            event = GuiEvent(client_id=None, client=None, target=self)
            callbacks = tuple(self._impl.update_cb)

        # User code never runs under the registry/state lock.
        _invoke_programmatic_callbacks(
            callbacks,
            event,
            gui_api=gui_api,
        )

    @property
    def update_timestamp(self) -> float:
        """Read-only timestamp when this input was last updated."""
        if self._impl.removed:
            raise RuntimeError(f"Cannot read timestamp from a removed {type(self).__name__}.")
        return self._impl.update_timestamp


StringType = TypeVar("StringType", bound=str)


# GuiInputHandle[T] is used for all inputs except for buttons.
#
# We inherit from _GuiInputHandle to special-case buttons because the usage semantics
# are slightly different: we have `on_click()` instead of `on_update()`.
class GuiInputHandle(_GuiInputHandle[T], Generic[T]):
    """A handle is created for each GUI element that is added in `Leika`.
    Handles can be used to read and write state.

    When a GUI element is added via :attr:`Server.gui`, state is
    synchronized between all connected clients. When a GUI element is added via
    :attr:`ClientHandle.gui`, state is local to a specific client.
    """

    def on_update(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a GUI input is updated.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        if not callable(func):
            raise TypeError("callback must be callable")
        with self._impl.gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot register a callback on a removed handle.")
            if len(self._impl.update_cb) >= _GUI_CALLBACK_MAX:
                raise RuntimeError(
                    f"A GUI handle cannot own more than {_GUI_CALLBACK_MAX} callbacks."
                )
            _append_gui_callback_locked(self._impl.update_cb, func, "GUI handle")
        return func

    def remove_update_callback(self, callback: Literal["all"] | Callable = "all") -> None:
        """Remove update callbacks from the GUI input.

        Args:
            callback: Either "all" to remove all callbacks, or a specific callback function to remove.
        """
        with self._impl.gui_api._lock:
            if callback == "all":
                self._impl.update_cb.clear()
            else:
                self._impl.update_cb = [cb for cb in self._impl.update_cb if cb != callback]


class GuiToggleHandle(GuiInputHandle[bool], GuiToggleProps):
    """Handle for a toggle: a button that stays pressed.

    .. attribute:: value
       :type: bool

       Whether the toggle is on. Synchronized automatically when assigned.
    """


def _row_props(handle: Any) -> Union[GuiButtonGroupProps, GuiToggleGroupProps]:
    props = handle._impl.props
    if not isinstance(props, (GuiButtonGroupProps, GuiToggleGroupProps)):
        raise RuntimeError("button-row handle has incompatible properties")
    return props


def _row_colors(handle: Any) -> Tuple[ButtonColor, ...]:
    """The colorways a row of buttons or toggles is currently wearing."""
    if handle._impl.removed:
        raise RuntimeError(f"Cannot read color from a removed {type(handle).__name__}.")
    return _row_props(handle).color


def _set_row_colors(handle: Any, color: ButtonColor | Sequence[ButtonColor]) -> None:
    """Recolor a row, by one role for all of it or one role per element.

    A property rather than a plain prop because the wire carries one role per
    element and the caller may mean either -- which is the same latitude
    ``add_button`` gives, kept for the live prop so that recoloring a row later
    is not a different API from declaring it.
    """
    # Runtime import to break the circular edge with `_gui_api`.
    from ._gui_api import _button_colors

    props = _row_props(handle)
    noun = "toggle" if isinstance(props, GuiToggleGroupProps) else "button"
    colors = _button_colors(len(props.options), color, noun=noun)
    if colors == props.color:
        return
    old_colors = props.color
    props.color = colors
    try:
        handle._queue_update("color", colors)
    except BaseException:
        props.color = old_colors
        raise


class GuiToggleGroupHandle(GuiInputHandle[Tuple[str, ...]], GuiToggleGroupProps):
    """Handle for a row of toggles.

    .. attribute:: value
       :type: tuple[str, ...]

       The options currently on, in the order they were declared. A tuple in
       both modes, so reading a group does not depend on how it was
       configured: with ``multiple=False`` it simply never holds more than one.
       Assigning turns exactly those options on and the rest off.
    """

    @property
    def color(self) -> Tuple[ButtonColor, ...]:
        """One colorway per toggle, as a tuple however it was assigned.

        Assigning a single role sets the whole row; assigning a sequence sets
        one toggle at a time, and must be as long as ``options``."""
        return _row_colors(self)

    @color.setter
    @_locked_gui_handle_method
    def color(self, color: ButtonColor | Sequence[ButtonColor]) -> None:  # type: ignore[override]
        _set_row_colors(self, color)

    def _normalize_value(self, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            raise ValueError("A toggle group value must be a sequence of option names.")
        wanted = _bounded_tuple(value, "toggle value")
        for option in wanted:
            _validate_collection_string(option, "toggle value")
        unknown = [option for option in wanted if option not in self.options]
        if unknown:
            raise ValueError(f"Unknown toggle option(s): {unknown!r}.")
        if len(set(wanted)) != len(wanted):
            raise ValueError("A toggle group value cannot repeat an option.")
        if not self.multiple and len(wanted) > 1:
            raise ValueError("This toggle group allows only one active option.")
        if self.required and not wanted:
            raise ValueError("This toggle group requires one active option.")
        return tuple(option for option in self.options if option in wanted)

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        return self._normalize_value(value)

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise TypeError("client toggle-group value must be an array")
        return self._normalize_value(value)


class GuiListHandle(GuiInputHandle[Tuple[str, ...]], GuiListProps):
    """Handle for an editable list of text entries.

    .. attribute:: value
       :type: tuple[str, ...]

       The entries, in the order they are shown. Editing an entry, adding one,
       removing one, or dragging one somewhere else all report the whole tuple.
       Assigning one sets the list to exactly those entries, which is how
       Python adds, removes, and reorders: ``handle.value += ("next",)``.
    """

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        if isinstance(value, str):
            raise ValueError("A list value must be a sequence of strings, not one string.")
        entries = _bounded_tuple(value, "list")
        for entry in entries:
            _validate_collection_string(entry, "list")
        return entries

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise TypeError("client list value must be an array")
        return self._coerce_assigned_value(value)


def _checklist_items(value: Iterable[Any]) -> Tuple[Tuple[str, bool], ...]:
    """The ``(text, checked)`` pairs a checklist holds, from what was given.

    A bare string is an item nobody has ticked yet, which is what a checklist
    usually starts as: ``["Fuel", ("Doors", True)]`` says what it means without
    a ``False`` per line, and it is what lets ``handle.value += ("Lights",)``
    read the way it does on a list.
    """
    if isinstance(value, str):
        raise ValueError("A checklist value must be a sequence of items, not one string.")
    materialized = _bounded_tuple(value, "checklist")
    items: list[Tuple[str, bool]] = []
    for item in materialized:
        if isinstance(item, str):
            _validate_collection_string(item, "checklist")
            items.append((item, False))
            continue
        try:
            text, checked = item
        except (TypeError, ValueError):
            raise ValueError(
                "A checklist holds (text, checked) pairs, so its items are strings or"
                f" two-item pairs; got {item!r}."
            ) from None
        if not isinstance(text, str):
            raise ValueError(f"A checklist item's text is a string; got {text!r}.")
        _validate_collection_string(text, "checklist")
        if type(checked) is not bool:
            raise ValueError(f"A checklist item's checked state is a bool; got {checked!r}.")
        items.append((text, checked))
    return tuple(items)


class GuiChecklistHandle(GuiInputHandle[Tuple[Tuple[str, bool], ...]], GuiChecklistProps):
    """Handle for a checklist: entries with a box each to tick.

    .. attribute:: value
       :type: tuple[tuple[str, bool], ...]

       One ``(text, checked)`` pair per item, in the order they are shown, so
       ``for text, checked in handle.value`` reads the list as it stands.
       Ticking a box reports it, and so does every one of the things a list can
       do to its entries -- editing one, adding one, removing one, dragging one
       somewhere else -- since a row's tick travels with the words it is
       against. Assigning sets the checklist to exactly those items, and a bare
       string among them is an item nobody has ticked: ``handle.value +=
       ("Lights",)``.
    """

    @property
    def value(self) -> Tuple[Tuple[str, bool], ...]:
        """The items, as pairs.

        :meta private:
        """
        # Read as pairs, written with the same latitude the constructor gives:
        # what comes back is always normalized, so `handle.value += ("Lights",)`
        # is an expression a type checker can follow rather than one that only
        # happens to work.
        if self._impl.removed:
            raise RuntimeError("Cannot read value from a removed GuiChecklistHandle.")
        return self._impl.value

    @value.setter
    def value(self, value: Sequence[str | Tuple[str, bool]] | np.ndarray) -> None:
        # `np.ndarray` only because the base setter takes one everywhere; a
        # checklist has no use for one, and it goes through the same normalizer.
        _GuiInputHandle.value.fset(self, value)  # type: ignore[attr-defined]

    @property
    def checked(self) -> Tuple[str, ...]:
        """The text of the ticked items, in the order they are shown.

        The question a checklist is usually asked, without the comprehension
        over the pairs. Read-only: what an item says and whether it is ticked
        are one thing, and ``value`` is where both are set.
        """
        return tuple(text for text, checked in self.value if checked)

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        return _checklist_items(value)

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise TypeError("client checklist value must be an array of pairs")
        rows = _bounded_tuple(value, "client checklist")
        for row in rows:
            if (
                not isinstance(row, (list, tuple))
                or len(row) != 2
                or not isinstance(row[0], str)
                or type(row[1]) is not bool
            ):
                raise TypeError("client checklist rows must be [str, bool]")
        return tuple((row[0], row[1]) for row in rows)


class GuiCheckboxHandle(GuiInputHandle[bool], GuiCheckboxProps):
    """Handle for checkbox inputs.

    .. attribute:: value
       :type: bool

       Value of the input. Synchronized automatically when assigned.
    """


_GUI_MARKDOWN_MAX_SOURCE_BYTES = 1 * 1024 * 1024
"""Bundled browser Markdown source limit after local-asset rewriting."""


def _gui_text_source(
    value: str,
    *,
    markdown: bool,
    editable: bool,
    image_root: Path | None,
    server: Server,
) -> str:
    """Build only the source the browser will actually render as Markdown."""
    if not markdown or editable:
        return value
    try:
        raw_size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ValueError("Markdown source must contain valid Unicode.") from error
    if raw_size > _GUI_MARKDOWN_MAX_SOURCE_BYTES:
        raise ValueError("Markdown source exceeds the 1 MiB browser render limit.")
    source = value
    if image_root is not None:
        source = _link_markdown_assets(
            value,
            image_root,
            lambda path, metadata: server._register_http_image(path, _expected_metadata=metadata),
        )
    if len(source.encode("utf-8")) > _GUI_MARKDOWN_MAX_SOURCE_BYTES:
        raise ValueError("Markdown source exceeds the 1 MiB browser render limit.")
    return source


class GuiTextHandle(GuiInputHandle[str], GuiTextProps):
    """Handle for text, editable or read-only.

    .. attribute:: value
       :type: str

       The text itself, whether it is being edited or only read. Synchronized
       automatically when assigned.
    """

    def __init__(self, _impl: _GuiHandleState, _image_root: Path | None = None):
        object.__setattr__(self, "_image_root", _image_root)
        super().__init__(impl=_impl)

    @property
    def value(self) -> str:
        return _GuiInputHandle.value.fget(self)  # type: ignore[attr-defined]

    @value.setter
    def value(self, value: str | np.ndarray) -> None:
        gui_api = self._impl.gui_api
        value = _validate_unicode_string(value, "text input value")
        if utf16_code_unit_length_exceeds(value, _GUI_TEXT_MAX_UTF16_CODE_UNITS):
            raise ValueError("Text exceeds the 1 Mi-character browser render limit.")
        while True:
            with gui_api._lock:
                if self._impl.removed:
                    raise RuntimeError("Cannot assign to 'value' on a removed GuiTextHandle.")
                props = cast(GuiTextProps, self._impl.props)
                mode = (props.markdown, props.editable)
                if self._impl.value == value:
                    return
            source = _gui_text_source(
                value,
                markdown=mode[0],
                editable=mode[1],
                image_root=self._image_root,
                server=gui_api._server,
            )
            with gui_api._lock:
                props = cast(GuiTextProps, self._impl.props)
                if self._impl.removed:
                    raise RuntimeError("Cannot assign to 'value' on a removed GuiTextHandle.")
                if mode != (props.markdown, props.editable):
                    continue
                candidate_props = dataclasses.replace(props, _source=source)
                with gui_api._gui_resource_transaction_locked(
                    self._impl.uuid, value, candidate_props
                ):
                    gui_api._websock_interface.queue_message_or_raise(
                        GuiUpdateMessage(
                            self._impl.uuid,
                            {"value": value, "_source": source},
                        )
                    )
                    self._impl.value = value
                    props._source = source
                self._impl.update_timestamp = time.time()
                event = GuiEvent(client_id=None, client=None, target=self)
                callbacks = tuple(self._impl.update_cb)
                break

        _invoke_programmatic_callbacks(
            callbacks,
            event,
            gui_api=gui_api,
        )

    @override
    def update(self, **updates: Any) -> None:
        if "_source" in updates:
            raise AttributeError('derived protocol properties are internal state: "_source"')
        custom = [
            name
            for name in updates
            if isinstance(getattr(type(self), name, None), property)
            and getattr(type(self), name).fset is not None
        ]
        if custom:
            return super().update(**updates)
        gui_api = self._impl.gui_api
        while True:
            with gui_api._lock:
                if self._impl.removed:
                    raise RuntimeError("Cannot update a removed GuiTextHandle.")
                for name in updates:
                    if name not in self._prop_hints:
                        raise TypeError(f"GuiTextHandle.update() got an unknown property {name!r}.")
                normalized = {
                    name: self._cast_value_recursive(self._prop_hints[name], value)
                    for name, value in updates.items()
                }
                if not normalized:
                    return
                before = dataclasses.replace(cast(GuiTextProps, self._impl.props))
                candidate = dataclasses.replace(before, **normalized)
                _validate_gui_props_candidate(self, candidate)
                value = self._impl.value
            source = _gui_text_source(
                value,
                markdown=candidate.markdown,
                editable=candidate.editable,
                image_root=self._image_root,
                server=gui_api._server,
            )
            candidate._source = source
            wire_updates = dict(normalized)
            if source != before._source:
                wire_updates["_source"] = source
            with gui_api._lock:
                if self._impl.removed:
                    raise RuntimeError("Cannot update a removed GuiTextHandle.")
                if self._impl.props != before or self._impl.value != value:
                    continue
                with gui_api._gui_resource_transaction_locked(self._impl.uuid, value, candidate):
                    gui_api._websock_interface.queue_message_or_raise(
                        GuiUpdateMessage(self._impl.uuid, wire_updates)
                    )
                    self._impl.props = candidate
                return


IntOrFloat = TypeVar("IntOrFloat", int, float)


class GuiNumberHandle(GuiInputHandle[IntOrFloat], Generic[IntOrFloat], GuiNumberProps):
    """Handle for number inputs.

    .. attribute:: value
       :type: IntOrFloat

       Value of the input. Synchronized automatically when assigned.
    """

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        value = _finite_number(value)
        if self.min is not None and value < self.min:
            raise ValueError(f"value must be at least {self.min}.")
        if self.max is not None and value > self.max:
            raise ValueError(f"value must be at most {self.max}.")
        return value

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        value = _finite_number(value)
        return self._coerce_assigned_value(type(self._impl.value)(value))


class GuiSliderHandle(GuiInputHandle[IntOrFloat], Generic[IntOrFloat], GuiSliderProps):
    """Handle for slider inputs.

    .. attribute:: value
       :type: IntOrFloat

       Value of the input. Synchronized automatically when assigned.
    """

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        value = _finite_number(value)
        if not self.min <= value <= self.max:
            raise ValueError(f"value must be within [{self.min}, {self.max}].")
        return value

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        value = _finite_number(value)
        return self._coerce_assigned_value(type(self._impl.value)(value))


class GuiMultiSliderHandle(
    GuiInputHandle[Tuple[IntOrFloat, ...]], Generic[IntOrFloat], GuiMultiSliderProps
):
    """Handle for multi-slider inputs.

    .. attribute:: value
       :type: tuple[IntOrFloat, ...]

       Value of the input. Synchronized automatically when assigned.
    """

    def _normalize_value(self, value: Any) -> tuple[int | float, ...]:
        if isinstance(value, (str, bytes)):
            raise ValueError("value must be a sequence of numbers.")
        materialized = _bounded_tuple(value, "multi-slider values")
        values = tuple(_finite_number(item) for item in materialized)
        if not values:
            raise ValueError("value must contain at least one slider value.")
        if any(not self.min <= item <= self.max for item in values):
            raise ValueError(f"value entries must be within [{self.min}, {self.max}].")
        if any(left > right for left, right in zip(values, values[1:])):
            raise ValueError("value entries must be in ascending order.")
        if self.min_range is not None and any(
            right - left < self.min_range for left, right in zip(values, values[1:])
        ):
            raise ValueError("value entries are closer than min_range.")
        item_type = type(self._impl.value[0]) if self._impl.value else float
        return tuple(item_type(item) for item in values)

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        return self._normalize_value(value)

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        if type(value) not in (list, tuple):
            raise TypeError("client multi-slider value must be an array")
        return self._normalize_value(value)


def _colors_to_int_tuple(value: Any, channels: int) -> tuple[int, ...]:
    """Coerce one bounded RGB/RGBA iterable to uint8 channel values.

    Integer channels are absolute [0, 255]; floats use [0, 1] and are scaled.
    Shape and length admission precede any element conversion or copying.
    """
    if type(value) is np.ndarray:
        if value.ndim != 1:
            raise ValueError(f"Expected a 1D color, got shape {value.shape}.")
        if value.shape[0] != channels:
            raise ValueError(f"Expected {channels} color channels, got {value.shape[0]}.")
        components = tuple(value)
    elif isinstance(value, np.ndarray):
        raise TypeError("Color values must use a base numpy.ndarray, not a subclass.")
    else:
        if isinstance(value, (str, bytes)):
            raise TypeError("Color values must be an iterable of numeric channels.")
        if isinstance(value, Sequence) and len(value) != channels:
            raise ValueError(f"Expected {channels} color channels, got {len(value)}.")
        try:
            components = tuple(itertools.islice(iter(value), channels + 1))
        except TypeError as error:
            raise TypeError("Color values must be an iterable of numeric channels.") from error
        if len(components) != channels:
            raise ValueError(f"Expected {channels} color channels, got {len(components)}.")
    normalized: list[int] = []
    for channel in components:
        if isinstance(channel, (bool, np.bool_)) or not isinstance(
            channel, (int, float, np.integer, np.floating)
        ):
            raise TypeError("Color channels must be integers or floats.")
        if isinstance(channel, (float, np.floating)):
            if not math.isfinite(float(channel)):
                raise ValueError("Color channels must be finite.")
            channel = channel * 255
        normalized.append(max(0, min(255, int(channel))))
    return tuple(normalized)


class GuiRgbHandle(GuiInputHandle[Tuple[int, int, int]], GuiRgbProps):
    """Handle for RGB color inputs.

    .. attribute:: value
       :type: tuple[int, int, int]

       Value of the input. Synchronized automatically when assigned.
    """

    @override
    def _coerce_assigned_value(
        self, value: Tuple[int, int, int] | np.ndarray
    ) -> Tuple[int, int, int]:
        # Float channels are [0, 1] (scaled to [0, 255]); int channels absolute.
        return cast(Tuple[int, int, int], _colors_to_int_tuple(value, 3))

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


class GuiRgbaHandle(GuiInputHandle[Tuple[int, int, int, int]], GuiRgbaProps):
    """Handle for RGBA color inputs.

    .. attribute:: value
       :type: tuple[int, int, int, int]

       Value of the input. Synchronized automatically when assigned.
    """

    @override
    def _coerce_assigned_value(
        self, value: Tuple[int, int, int, int] | np.ndarray
    ) -> Tuple[int, int, int, int]:
        # Float channels are [0, 1] (scaled to [0, 255]); int channels absolute.
        return cast(Tuple[int, int, int, int], _colors_to_int_tuple(value, 4))

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


class GuiVector2Handle(GuiInputHandle[Tuple[float, float]], GuiVector2Props):
    """Handle for 2D vector inputs.

    .. attribute:: value
       :type: tuple[float, float]

       Value of the input. Synchronized automatically when assigned.
    """

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        value = _cast_vector(value, 2)
        if self.min is not None and any(item < lo for item, lo in zip(value, self.min)):
            raise ValueError("value has a component below min.")
        if self.max is not None and any(item > hi for item, hi in zip(value, self.max)):
            raise ValueError("value has a component above max.")
        return value

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


class GuiVector3Handle(GuiInputHandle[Tuple[float, float, float]], GuiVector3Props):
    """Handle for 3D vector inputs.

    .. attribute:: value
       :type: tuple[float, float, float]

       Value of the input. Synchronized automatically when assigned.
    """

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        value = _cast_vector(value, 3)
        if self.min is not None and any(item < lo for item, lo in zip(value, self.min)):
            raise ValueError("value has a component below min.")
        if self.max is not None and any(item > hi for item, hi in zip(value, self.max)):
            raise ValueError("value has a component above max.")
        return value

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


_GUI_EVENT_VALUE_UNSET = object()


@dataclasses.dataclass(frozen=True)
class GuiEvent(Generic[TGuiHandle]):
    """Information associated with a GUI event, such as an update or click.

    Passed as input to callback functions. ``value`` is an event-time snapshot,
    not a live read from ``target``; overlapping clients therefore cannot change
    what an earlier async callback observes after it awaits.
    """

    client: ClientHandle | None
    """Client that triggered this event."""
    client_id: int | None
    """ID of client that triggered this event."""
    target: TGuiHandle
    """GUI element that was affected."""
    value: Any = dataclasses.field(default=_GUI_EVENT_VALUE_UNSET, repr=False)
    """Value at event creation, or None when the handle has no value."""

    def __post_init__(self) -> None:
        if self.value is _GUI_EVENT_VALUE_UNSET:
            value = copy.deepcopy(getattr(self.target, "value", None))
            if isinstance(value, np.ndarray):
                value.flags.writeable = False
            object.__setattr__(self, "value", value)


_GUI_BUTTON_MAX_HOLD_FREQUENCIES = 64
"""Maximum distinct browser timers installed for one held button."""

_DERIVED_PROTOCOL_PROP_NAMES = frozenset(
    {
        "_data",
        "_format",
        "_hold_callback_freqs",
        "_icon_html",
        "_plotly_json_str",
        "_prefetch",
        "_source",
        "_tabs",
    }
)
"""Wire-only fields whose public mutation would desynchronize owned state."""


def _reject_derived_protocol_props(updates: Mapping[str, object]) -> None:
    forbidden = sorted(_DERIVED_PROTOCOL_PROP_NAMES.intersection(updates))
    if forbidden:
        names = ", ".join(repr(name) for name in forbidden)
        raise AttributeError(f"derived protocol properties are internal state: {names}")


def _append_gui_callback_locked(
    callbacks: list[Callable[..., Any]],
    callback: Callable[..., Any],
    noun: str,
) -> None:
    if len(callbacks) >= _GUI_CALLBACK_MAX:
        raise RuntimeError(f"A {noun} cannot own more than {_GUI_CALLBACK_MAX} callbacks.")
    callbacks.append(callback)


class GuiButtonHandle(_GuiInputHandle[bool], GuiButtonProps):
    """Handle for a button input in our visualizer.

    .. attribute:: value
       :type: bool

       Value of the button. Set to `True` when the button is pressed. Can be manually set back to `False`.
    """

    def __init__(self, _impl: _GuiHandleState[bool], _icon: IconName | None):
        object.__setattr__(self, "_icon", _icon)
        # Ready before the creation message can reach the event loop.
        object.__setattr__(self, "_hold_cbs_from_freq", {})
        super().__init__(impl=_impl)

    @property
    def icon(self) -> IconName | None:
        """Icon to display on the button. When set to None, no icon is displayed."""
        if self._impl.removed:
            raise RuntimeError(f"Cannot read icon from a removed {type(self).__name__}.")
        return self._icon

    @icon.setter
    @_locked_gui_handle_method
    def icon(self, icon: IconName | None) -> None:
        icon_html = None if icon is None else svg_from_icon(icon)
        self._publish_internal_props_locked(_icon_html=icon_html)
        self._icon = icon

    def on_click(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a button is pressed.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        if not callable(func):
            raise TypeError("callback must be callable")
        with self._impl.gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot register a callback on a removed handle.")
            _append_gui_callback_locked(self._impl.update_cb, func, "GUI handle")
        return func

    # Type alias for button hold callbacks.
    _HoldCallback = Callable[["GuiEvent[GuiButtonHandle]"], "None | Coroutine"]

    @overload
    def on_hold(
        self,
        func: None = None,
        callback_hz: float = 10.0,
    ) -> Callable[[_HoldCallback], _HoldCallback]: ...

    @overload
    def on_hold(
        self,
        func: _HoldCallback,
        callback_hz: float = 10.0,
    ) -> _HoldCallback: ...

    def on_hold(
        self,
        func: _HoldCallback | None = None,
        callback_hz: float = 10.0,
    ) -> Callable[[_HoldCallback], _HoldCallback] | _HoldCallback:
        """Attach a function to call repeatedly while a button is held down.

        The callback will be triggered immediately when the button is pressed,
        and then repeatedly at the specified frequency until released.

        Can be used as a decorator with or without arguments:
            @button.on_hold
            def callback(event): ...

            @button.on_hold(callback_hz=30.0)
            def callback(event): ...

        Or called directly:
            button.on_hold(callback)
            button.on_hold(callback, callback_hz=30.0)

        Args:
            func: The callback function to attach. If None, returns a decorator.
            callback_hz: The frequency in Hz at which to call the callback while
                the button is held. Defaults to 10.0 Hz.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """

        if isinstance(callback_hz, bool) or not isinstance(callback_hz, (int, float)):
            raise ValueError("callback_hz must be a positive, finite number.")
        callback_hz = float(callback_hz)
        if not math.isfinite(callback_hz) or not 0.0 < callback_hz <= 60.0:
            raise ValueError("callback_hz must be a positive, finite number no greater than 60 Hz.")

        def register_callback(
            f: GuiButtonHandle._HoldCallback,
        ) -> GuiButtonHandle._HoldCallback:
            if not callable(f):
                raise TypeError("callback must be callable")
            with self._impl.gui_api._lock:
                if self._impl.removed:
                    raise RuntimeError("Cannot register a callback on a removed handle.")
                if (
                    callback_hz not in self._hold_cbs_from_freq
                    and len(self._hold_cbs_from_freq) >= _GUI_BUTTON_MAX_HOLD_FREQUENCIES
                ):
                    raise ValueError(
                        "a button supports at most 64 distinct hold callback frequencies"
                    )
                if (
                    sum(len(items) for items in self._hold_cbs_from_freq.values())
                    >= _GUI_CALLBACK_MAX
                ):
                    raise RuntimeError(
                        f"A button cannot own more than {_GUI_CALLBACK_MAX} hold callbacks."
                    )
                callbacks = self._hold_cbs_from_freq.setdefault(callback_hz, [])
                callbacks.append(f)
                try:
                    # Update the prop to notify client of new frequency.
                    self._publish_internal_props_locked(
                        _hold_callback_freqs=tuple(self._hold_cbs_from_freq.keys())
                    )
                except BaseException:
                    callbacks.pop()
                    if not callbacks:
                        self._hold_cbs_from_freq.pop(callback_hz, None)
                    raise
            return f

        if func is not None:
            return register_callback(func)
        return register_callback

    def remove_hold_callback(
        self,
        callback: Literal["all"] | _HoldCallback = "all",
        *,
        callback_hz: float | None = None,
    ) -> None:
        """Remove hold callbacks, optionally only at one registered frequency."""
        with self._impl.gui_api._lock:
            if callback_hz is not None:
                frequencies = (float(callback_hz),)
            else:
                frequencies = tuple(self._hold_cbs_from_freq)
            old = {frequency: list(items) for frequency, items in self._hold_cbs_from_freq.items()}
            for frequency in frequencies:
                callbacks = self._hold_cbs_from_freq.get(frequency)
                if callbacks is None:
                    continue
                if callback == "all":
                    self._hold_cbs_from_freq.pop(frequency, None)
                else:
                    remaining = [item for item in callbacks if item != callback]
                    if remaining:
                        self._hold_cbs_from_freq[frequency] = remaining
                    else:
                        self._hold_cbs_from_freq.pop(frequency, None)
            try:
                self._publish_internal_props_locked(
                    _hold_callback_freqs=tuple(self._hold_cbs_from_freq)
                )
            except BaseException:
                self._hold_cbs_from_freq = old
                raise


@dataclasses.dataclass(frozen=True)
class UploadedFile:
    """Result of a file upload."""

    name: str
    """Name of the file."""
    content: bytes
    """Contents of the file."""


class GuiUploadButtonHandle(_GuiInputHandle[UploadedFile], GuiUploadButtonProps):
    """Handle for an upload file button in our visualizer.

    The `.value` attribute will be updated with the contents of uploaded files.

    .. attribute:: value
       :type: UploadedFile

       Value of the input. Contains information about the uploaded file.
    """

    def __init__(self, _impl: _GuiHandleState[UploadedFile], _icon: IconName | None):
        object.__setattr__(self, "_icon", _icon)
        super().__init__(impl=_impl)

    @property
    def value(self) -> UploadedFile:
        """An independent snapshot of the last uploaded file."""
        if self._impl.removed:
            raise RuntimeError("Cannot read value from a removed GuiUploadButtonHandle.")
        value = self._impl.value
        return UploadedFile(value.name, value.content)

    @value.setter
    def value(self, value: UploadedFile | np.ndarray) -> None:
        self._assign_value(value)

    def _coerce_assigned_value(self, value: UploadedFile | np.ndarray) -> UploadedFile:
        if not isinstance(value, UploadedFile):
            raise TypeError("upload button value must be an UploadedFile")
        name = validate_file_display_name(value.name)
        if type(value.content) is not bytes:
            raise TypeError("UploadedFile.content must be bytes")
        return UploadedFile(name, value.content)

    @contextlib.contextmanager
    def _value_assignment_transaction(self, value: UploadedFile | np.ndarray) -> Iterator[None]:
        if not isinstance(value, UploadedFile):
            raise TypeError("upload button value must be an UploadedFile")
        gui_api = self._impl.gui_api
        new_bytes = len(value.content)
        with gui_api._file_upload_lock:
            old_bytes = gui_api._retained_file_upload_bytes.get(self._impl.uuid, 0)
            gui_api._server._replace_retained_file_upload(old_bytes, new_bytes)
            try:
                yield
            except BaseException:
                # Reverse the exact reservation before exposing the failure.
                gui_api._server._replace_retained_file_upload(new_bytes, old_bytes)
                raise
            else:
                gui_api._retained_file_upload_bytes[self._impl.uuid] = new_bytes

    @property
    def icon(self) -> IconName | None:
        """Icon to display on the upload button. When set to None, no icon is displayed."""
        if self._impl.removed:
            raise RuntimeError(f"Cannot read icon from a removed {type(self).__name__}.")
        return self._icon

    @icon.setter
    @_locked_gui_handle_method
    def icon(self, icon: IconName | None) -> None:
        icon_html = None if icon is None else svg_from_icon(icon)
        self._publish_internal_props_locked(_icon_html=icon_html)
        self._icon = icon

    def on_upload(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a file is uploaded.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        if not callable(func):
            raise TypeError("callback must be callable")
        with self._impl.gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot register a callback on a removed handle.")
            _append_gui_callback_locked(self._impl.update_cb, func, "GUI handle")
        return func


PREVIEW_MAX_BYTES = 64 * 1024 * 1024
"""Transport ceiling for one preview. The browser still applies lower
renderer-specific limits (1 MiB Markdown and 16 MiB plain text) and retains
the complete transported file while its dialog is open."""


def _read_preview_markdown(path: Path, max_bytes: int) -> bytes | None:
    """Read stable regular Markdown, or leave an oversized file to the sender."""
    with open_regular_file(path) as file:
        before = os.fstat(file.fileno())
        size = before.st_size
        if size > max_bytes:
            return None
        payload = file.read(max_bytes + 1)
        after = os.fstat(file.fileno())
    if len(payload) > max_bytes:
        return None
    validate_unchanged_file_snapshot(path, before, after)
    if len(payload) != size:
        raise OSError(f"{path} changed size while it was being read")
    return payload


FileContent = Union[bytes, Path, Callable[["GuiEvent[Any]"], Union[bytes, Path]]]
"""What a file button sends: the bytes themselves, a path to read them from, or
a synchronous function called at click time returning either."""

DownloadContent = FileContent
"""What a download button sends. See :data:`FileContent`."""

PreviewContent = FileContent
"""What a preview button shows. See :data:`FileContent`."""


class _GuiFileButtonHandle(GuiButtonHandle):
    """A button that hands one file to the client that pressed it.

    Subclasses say what becomes of the file; everything before that -- what to
    send, what to call it, and not sending it twice at once -- is the same
    whether the browser saves it or shows it.
    """

    #: Named in the errors this raises, so each subclass points at the method
    #: the caller actually used.
    _factory = "add_download_button()"
    #: Completes "A <verb> of bytes has no name...".
    _noun = "download"

    def __init__(
        self,
        _impl: _GuiHandleState[bool],
        _icon: IconName | None,
        _content: FileContent,
        _filename: str | None,
    ):
        object.__setattr__(self, "_content", _content)
        object.__setattr__(self, "_filename", _filename)
        object.__setattr__(self, "_file_busy", False)
        object.__setattr__(self, "_busy_disabled_generation", -1)
        super().__init__(_impl=_impl, _icon=_icon)

    @property
    def content(self) -> FileContent:
        """What the button sends: bytes, a path to read at click time, or a
        synchronous function of the click event returning one of those."""
        if self._impl.removed:
            raise RuntimeError("Cannot read content from a removed file button.")
        return self._content

    @content.setter
    @_locked_gui_handle_method
    def content(self, content: FileContent) -> None:
        from ._gui_api import _validate_file_content

        content = cast(
            FileContent,
            _validate_file_content(content, self._filename, self._factory),
        )
        retained_bytes = len(cast(bytes, content)) if type(content) is bytes else 0
        with self._impl.gui_api._gui_resource_transaction_locked(
            self._impl.uuid,
            self._impl.value,
            self._impl.props,
            retained_extra_bytes=retained_bytes,
        ):
            self._content = content
            self._impl.retained_extra_bytes = retained_bytes

    @property
    def filename(self) -> str | None:
        """Name the file is sent under, or None to take it from the path that
        the contents were read from."""
        if self._impl.removed:
            raise RuntimeError("Cannot read filename from a removed file button.")
        return self._filename

    @filename.setter
    @_locked_gui_handle_method
    def filename(self, filename: str | None) -> None:
        from ._gui_api import _validate_file_content

        if filename is not None:
            filename = validate_file_display_name(filename)
        _validate_file_content(self._content, filename, self._factory)
        self._filename = filename

    def _resolve(self, event: GuiEvent[Any]) -> Tuple[str, bytes | Path]:
        """The name and contents to send for one press."""
        content = self._content(event) if callable(self._content) else self._content
        if callback_result_is_awaitable(content):
            close = getattr(content, "close", None)
            cancel = getattr(content, "cancel", None)
            if callable(close):
                close()
            elif callable(cancel):
                cancel()
            raise TypeError(
                "content providers must return bytes or a Path directly; async "
                "providers are not supported"
            )
        if type(content) is not bytes and not isinstance(content, Path):
            raise TypeError("content providers must return bytes or a Path")
        if isinstance(content, Path):
            content = Path(os.fspath(content))
        if self._filename is not None:
            return self._filename, content
        if isinstance(content, Path):
            return content.name, content
        # Bytes name nothing, so there is nothing to fall back to. Raised here
        # rather than at creation because a callable's return type is only
        # known once it has run.
        raise ValueError(
            f"A {self._noun} of bytes has no name to save under; pass filename="
            f" to {self._factory}, or return a Path to take the name from."
        )

    def _deliver(self, client: ClientHandle, filename: str, content: bytes | Path) -> None:
        """Hand the resolved file to the client that pressed."""
        raise NotImplementedError

    def _begin_file_press_locked(self) -> bool:
        """Reserve this file producer globally and publish its busy state."""
        if self._file_busy or self._impl.removed:
            return False
        props = cast(GuiButtonProps, self._impl.props)
        if props.disabled or not props.visible:
            return False
        gui_api = self._impl.gui_api
        gui_api._websock_interface.queue_message_or_raise(
            GuiUpdateMessage(self._impl.uuid, {"disabled": True})
        )
        self._file_busy = True
        self._busy_disabled_generation = self._impl.disabled_generation
        self._impl.props = dataclasses.replace(props, disabled=True)
        return True

    def _finish_file_press(self) -> None:
        """Release one producer without overwriting a caller's later disable."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if not self._file_busy:
                return
            self._file_busy = False
            if self._impl.removed:
                return
            if self._impl.disabled_generation != self._busy_disabled_generation:
                return
            props = cast(GuiButtonProps, self._impl.props)
            gui_api._websock_interface.queue_message_or_raise(
                GuiUpdateMessage(self._impl.uuid, {"disabled": False})
            )
            self._impl.props = dataclasses.replace(props, disabled=False)

    def _send(self, event: GuiEvent[Any]) -> None:
        """Send the one globally admitted file to whoever pressed."""
        if event.client is None:
            return
        with self._impl.gui_api._lock:
            if not self._file_busy and not self._begin_file_press_locked():
                return
        try:
            filename, content = self._resolve(event)
            self._deliver(event.client, filename, content)
        finally:
            self._finish_file_press()


class GuiDownloadButtonHandle(_GuiFileButtonHandle):
    """Handle for a download button in our visualizer.

    A button that sends a file to the client that pressed it. The press is an
    ordinary one -- the handle is a :class:`GuiButtonHandle`, and `on_click`
    still works -- so what this adds is the sending: the file goes to the one
    client that asked for it rather than to every connected browser, the
    browser saves it on arrival, and the button holds itself disabled while the
    contents are produced, so a slow export cannot be started twice over.

    .. attribute:: value
       :type: bool

       Value of the button. Set to `True` when the button is pressed. Can be manually set back to `False`.
    """

    _factory = "add_download_button()"
    _noun = "download"

    @override
    def _deliver(self, client: ClientHandle, filename: str, content: bytes | Path) -> None:
        # A press is already the ask, so the file saves rather than arriving as
        # a link to press again. Offering the link is for the sends nobody
        # asked for -- `send_file_download` at a moment that is not a click.
        client.send_file_download(filename, content, save_immediately=True)


class GuiPreviewButtonHandle(_GuiFileButtonHandle):
    """Handle for a preview button in our visualizer.

    The download button's twin, shown rather than saved: the file goes to the
    client that pressed and opens there in a dialog, in whichever viewer its
    type calls for.

    .. attribute:: value
       :type: bool

       Value of the button. Set to `True` when the button is pressed. Can be manually set back to `False`.
    """

    _factory = "add_preview_button()"
    _noun = "preview"

    def __init__(
        self,
        _impl: _GuiHandleState[bool],
        _icon: IconName | None,
        _content: FileContent,
        _filename: str | None,
        _max_bytes: int,
    ):
        object.__setattr__(self, "_max_bytes", _max_bytes)
        super().__init__(_impl=_impl, _icon=_icon, _content=_content, _filename=_filename)

    def _prepared(self, client: ClientHandle, filename: str, content: bytes | Path) -> bytes | Path:
        """The contents as the browser should receive them.

        A path-backed document knows where its relative images live. The
        browser receives the document as an isolated blob, with no filesystem
        base URL it could resolve them against -- but the images do not
        belong *inside* the document either: inlined as base64 they multiply
        the transfer, and nothing shows until the whole of it has arrived.
        Each image is registered with the server instead and the document
        keeps only its URL, so the text arrives on its own -- kilobytes,
        shown at once -- and the browser fills the figures in as they load,
        the way it loads any page. Bytes have no corresponding directory and
        are left exactly as the caller supplied them.
        """
        if isinstance(content, Path) and Path(filename).suffix.lower() in (
            ".md",
            ".markdown",
        ):
            payload = _read_preview_markdown(
                content, min(self._max_bytes, _GUI_MARKDOWN_MAX_SOURCE_BYTES)
            )
            if payload is None:
                return content
            source = payload.decode("utf-8", errors="replace")
            linked = _link_markdown_assets(
                source,
                content.parent,
                lambda path, metadata: client._server._register_http_image(
                    path, _expected_metadata=metadata
                ),
            ).encode("utf-8")
            return linked if len(linked) <= _GUI_MARKDOWN_MAX_SOURCE_BYTES else content
        return content

    def _watched_path(self) -> Path | None:
        """The file this button reads, if it reads one that could change.

        Only the contents given as a path outright. A function's answer is
        whatever running it returns, and running it is what a watch is trying
        to avoid; bytes handed over once are not a file at all, and cannot
        change behind the reader.
        """
        content = self._content
        return content if isinstance(content, Path) else None

    def _version(self) -> str | None:
        """What the watched file is right now, as a stamp to compare against.

        Modification time and size together: the pair a build, an editor's
        save and an append all move, without reading a byte of the file to
        find out. ``None`` for a source that cannot be watched, and for one
        that has gone missing -- a preview of a file being rewritten in place
        should not blink out and back, so nothing is said until there is a
        file to say it about again.
        """
        path = self._watched_path()
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    def _show(
        self,
        client: ClientHandle,
        filename: str,
        content: bytes | Path,
        disposition: FileDisposition,
    ) -> None:
        """Send one file to one client's dialog, opening it or refilling it.

        The version is read *before* the contents rather than after, so a file
        written to while this is sending is left looking newer than what went
        out, and the next watch sends it again. The other way round the two
        would agree about a file the reader never got.
        """
        version = self._version()
        content = self._prepared(client, filename, content)
        client._send_preview(
            filename,
            content,
            max_bytes=self._max_bytes,
            disposition=disposition,
            source_uuid=self._impl.uuid,
            source_version=version,
        )

    @override
    def _deliver(self, client: ClientHandle, filename: str, content: bytes | Path) -> None:
        self._show(client, filename, content, "preview")

    def _reload(self, event: GuiEvent[Any]) -> None:
        """Send the file again, because the reader asked (``GuiPreviewReloadMessage``).

        The press's own path: the contents are resolved exactly as a press
        resolves them, function and all. Pressing reload is asking what the
        file says now, and for contents that are computed, running the
        computation is the only way to answer.

        It lands in the dialog that is already open rather than opening one.
        """
        if event.client is None:
            return
        filename, content = self._resolve(event)
        self._show(event.client, filename, content, "reload")

    def _watch(self, client: ClientHandle, version: str | None) -> None:
        """Send the file again if it is no longer what the reader is holding
        (``GuiPreviewWatchMessage``).

        Advisory like ``_warm``, and quiet like it: an unwatchable source, a
        file that has not moved, one that has grown past the limit -- each is
        a return, because there is nothing here a reader asked for and so
        nobody to tell.
        """
        current = self._version()
        if current is None or current == version:
            return
        path = self._watched_path()
        if path is None:
            return
        filename = self._filename if self._filename is not None else path.name
        try:
            # Checked here as well as in the send, because the send says so
            # in a notification: a file that has grown past the limit while
            # being watched would raise one every tick, and the reader never
            # asked this question in the first place. A press still answers
            # it, once, in the words a press deserves.
            if path.stat().st_size > self._max_bytes:
                return
            self._show(client, filename, path, "reload")
        except OSError:
            # Read out from under us between the stat and the send. The file
            # is still moving; the next watch will find it.
            return

    def _warm(self, client: ClientHandle) -> None:
        """Begin the press's transfer before the press (``GuiPreviewWarmMessage``).

        Sent with disposition ``warm``, which the browser holds ready rather
        than shows. Everything about it is advisory, so every reason not to
        send is a quiet return: warming shows nobody anything, so there is
        nobody to tell.

        Only static contents warm. A callable is the caller's code, run --
        with whatever cost or side effects the caller gave it -- on a *press*;
        a button merely scrolling past is not that, so it is left alone.
        """
        content = self._content
        # Byte-backed content has no stable source revision. A live content=
        # assignment could otherwise leave a stale warmed Blob addressable by
        # the same (source UUID, None) identity until the fresh send completes.
        if callable(content) or isinstance(content, bytes):
            return
        filename = self._filename
        if filename is None:
            filename = content.name if isinstance(content, Path) else None
        if filename is None:
            return
        try:
            version = self._version()
            prepared = self._prepared(client, filename, content)
            client._send_file(
                filename,
                prepared,
                1024 * 1024,
                "warm",
                source_uuid=self._impl.uuid,
                source_version=version,
                max_bytes=self._max_bytes,
            )
        except (OSError, ValueError):
            # An unreadable file warms nothing; the press, if it comes, will
            # say so through the channels a press has.
            return


class GuiButtonGroupHandle(_GuiInputHandle[str], GuiButtonGroupProps):
    """Handle for a button group input in our visualizer.

    .. attribute:: value
       :type: str

       Value of the input. Represents the currently selected button in the group.
    """

    def on_click(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a button in the group is clicked.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        if not callable(func):
            raise TypeError("callback must be callable")
        with self._impl.gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot register a callback on a removed handle.")
            _append_gui_callback_locked(self._impl.update_cb, func, "GUI handle")
        return func

    @property
    def color(self) -> Tuple[ButtonColor, ...]:
        """One colorway per button, as a tuple however it was assigned.

        Assigning a single role sets the whole row; assigning a sequence sets
        one button at a time, and must be as long as ``options``."""
        return _row_colors(self)

    @color.setter
    @_locked_gui_handle_method
    def color(self, color: ButtonColor | Sequence[ButtonColor]) -> None:  # type: ignore[override]
        _set_row_colors(self, color)

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        canonical = next((option for option in self.options if option == value), None)
        if canonical is None:
            raise ValueError(f"Button value must be one of {self.options!r}; got {value!r}.")
        return canonical

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


class GuiDropdownHandle(GuiInputHandle[StringType], Generic[StringType], GuiDropdownProps):
    """Handle for a dropdown-style GUI input in our visualizer.

    .. attribute:: value
       :type: StringType

       Value of the input. Represents the currently selected option in the dropdown.
    """

    @property
    def options(self) -> tuple[StringType, ...]:
        """Options for our dropdown. Synchronized automatically when assigned.

        For projects that care about typing: the static type of `options` should be
        consistent with the `StringType` associated with a handle. Literal types will be
        inferred where possible when handles are instantiated; for the most flexibility,
        we can declare handles as `GuiDropdownHandle[str]`.
        """
        if self._impl.removed:
            raise RuntimeError("Cannot read options from a removed GuiDropdownHandle.")
        props = self._impl.props
        if not isinstance(props, GuiDropdownProps):
            raise RuntimeError("dropdown handle has incompatible properties")
        return cast("tuple[StringType, ...]", props.options)

    @options.setter
    def options(self, options: Iterable[StringType]) -> None:  # type: ignore[override]
        normalized = cast("tuple[StringType, ...]", _string_options(options, "Dropdown"))
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed GuiDropdownHandle.")
            props = self._impl.props
            if not isinstance(props, GuiDropdownProps):
                raise RuntimeError("dropdown handle has incompatible properties")
            if normalized == props.options:
                return
            old_value = self._impl.value
            new_value = old_value if old_value in normalized else normalized[0]
            updates: dict[str, Any] = {"options": normalized}
            if new_value != old_value:
                updates["value"] = new_value
            candidate_props = dataclasses.replace(props, options=normalized)
            with gui_api._gui_resource_transaction_locked(
                self._impl.uuid, new_value, candidate_props
            ):
                gui_api._websock_interface.queue_message_or_raise(
                    GuiUpdateMessage(self._impl.uuid, updates)
                )
                props.options = normalized
            if new_value == old_value:
                return
            self._impl.value = new_value
            self._impl.update_timestamp = time.time()
            event = GuiEvent(client_id=None, client=None, target=self)
            callbacks = tuple(self._impl.update_cb)

        _invoke_programmatic_callbacks(
            callbacks,
            event,
            gui_api=gui_api,
        )

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        canonical = next((option for option in self.options if option == value), None)
        if canonical is None:
            raise ValueError(f"Dropdown value must be one of {self.options!r}; got {value!r}.")
        return canonical

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


def _scrub_dataclass_payload(value: object) -> None:
    """Drop charged mutable/string payloads from a terminal dataclass."""
    if not dataclasses.is_dataclass(value) or isinstance(value, type):
        return
    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        if isinstance(item, str):
            replacement: object = ""
        elif isinstance(item, bytes):
            replacement = b""
        elif type(item) is np.ndarray:
            replacement = np.empty((0,), dtype=item.dtype)
        elif isinstance(item, tuple):
            replacement = ()
        elif isinstance(item, list):
            replacement = []
        elif isinstance(item, dict):
            replacement = {}
        elif dataclasses.is_dataclass(item) and not isinstance(item, type):
            _scrub_dataclass_payload(item)
            continue
        else:
            continue
        object.__setattr__(value, field.name, replacement)


def _clear_gui_handle_references_locked(handle: _GuiHandle[Any]) -> None:
    """Drop all resource-charged state from a terminal GUI handle."""
    gui_api = handle._impl.gui_api
    handle._impl.update_cb.clear()
    handle._impl.sync_cb = None
    form_uuid = handle._impl.owning_form_uuid
    if form_uuid is not None:
        form = gui_api._container_handle_from_uuid.get(form_uuid)
        if isinstance(form, GuiFormHandle):
            form._initial_field_uuids.discard(handle._impl.uuid)
    handle._impl.owning_form_uuid = None
    handle._impl.initial_value = None
    handle._impl.value = None
    _scrub_dataclass_payload(handle._impl.props)
    if isinstance(handle, GuiButtonHandle):
        handle._hold_cbs_from_freq.clear()
        handle._icon = None
    if isinstance(handle, GuiUploadButtonHandle):
        handle._icon = None
    if isinstance(handle, GuiImageHandle):
        handle._image = np.empty((0,), dtype=np.uint8)
        handle._user_format = "auto"
        handle._jpeg_quality = None
    if isinstance(handle, GuiTextHandle):
        handle._image_root = None
    if isinstance(handle, _GuiFileButtonHandle):
        handle._content = b""
        handle._filename = None
        handle._impl.retained_extra_bytes = 0
    if isinstance(handle, GuiFormHandle):
        handle._submit_cb.clear()
        handle._initial_field_uuids.clear()


def _gui_subtree_nodes(container: GuiContainerProtocol) -> tuple[object, ...]:
    """Return descendants child-first without trusting recursive user depth."""
    output: list[object] = []
    stack: list[tuple[object, bool]] = [
        (child, False) for child in reversed(tuple(container._children.values()))
    ]
    while stack:
        node, expanded = stack.pop()
        if expanded:
            output.append(node)
            continue
        stack.append((node, True))
        if isinstance(node, GuiTabGroupHandle):
            nested: tuple[object, ...] = tuple(node._tab_handles)
        elif isinstance(node, GuiContainer):
            nested = tuple(node._children.values())
        else:
            nested = ()
        stack.extend((child, False) for child in reversed(nested))
    return tuple(output)


def _gui_descendant_uuids(container: GuiContainer) -> tuple[str, ...]:
    """Return every descendant GUI component UUID in deterministic child-first order."""
    return tuple(
        node._impl.uuid
        for node in _gui_subtree_nodes(cast(GuiContainerProtocol, container))
        if isinstance(node, _GuiHandle)
    )


def _gui_descendant_tab_uuids(container: GuiContainer) -> tuple[str, ...]:
    """Return separately bounded descendant tab lifecycle IDs child-first."""
    tab_uuids = tuple(
        node._id
        for node in _gui_subtree_nodes(cast(GuiContainerProtocol, container))
        if isinstance(node, GuiTabHandle)
    )
    if len(tab_uuids) > _GUI_AGGREGATE_COLLECTION_MAX:
        raise RuntimeError("GUI tab lifecycle registry exceeds its aggregate safety limit")
    return tab_uuids


def _tab_subtree_uuids(tab: GuiTabHandle) -> tuple[str, ...]:
    """Return nested tab IDs followed by the named tab itself."""
    tab_uuids = (*_gui_descendant_tab_uuids(tab), tab._id)
    if len(tab_uuids) > _GUI_AGGREGATE_COLLECTION_MAX:
        raise RuntimeError("GUI tab lifecycle registry exceeds its aggregate safety limit")
    return tab_uuids


def _retire_gui_handle_without_queue_locked(handle: _GuiHandle[Any]) -> None:
    """Retire one GUI owner and its descendants after wire admission."""
    if handle._impl.removed:
        return
    gui_api = handle._impl.gui_api
    if isinstance(handle, GuiTabGroupHandle):
        for tab in tuple(handle._tab_handles):
            _discard_gui_subtree(tab)
            tab.removed = True
            tab._label = ""
            tab._icon = None
            gui_api._container_handle_from_uuid.pop(tab._id, None)
            gui_api._container_depth_from_uuid.pop(tab._id, None)
        handle._tab_handles.clear()
    elif isinstance(handle, GuiContainer):
        _discard_gui_subtree(cast(GuiContainerProtocol, handle))

    handle._impl.removed = True
    _clear_gui_handle_references_locked(handle)
    gui_api._live_component_count -= 1
    gui_api._release_gui_resource_locked(handle._impl.uuid)
    gui_api._gui_input_handle_from_uuid.pop(handle._impl.uuid, None)
    gui_api._container_handle_from_uuid.pop(handle._impl.uuid, None)
    gui_api._container_depth_from_uuid.pop(handle._impl.uuid, None)
    parent = gui_api._container_handle_from_uuid.get(handle._impl.parent_container_id)
    if parent is not None:
        parent._children.pop(handle._impl.uuid, None)
    if isinstance(handle, GuiUploadButtonHandle):
        gui_api._discard_file_uploads(source_component_uuid=handle._impl.uuid)
    if isinstance(handle, GuiPreviewButtonHandle):
        gui_api._discard_preview_work(source_component_uuid=handle._impl.uuid)


def _discard_gui_subtree(
    container: GuiContainerProtocol,
    gui_api: GuiApi | None = None,
) -> None:
    """Retire a GUI subtree locally after its compact removal batch is queued."""
    if gui_api is None:
        gui_api = cast(GuiContainer, container)._child_gui_api
    for child in _gui_subtree_nodes(container):
        if isinstance(child, GuiTabHandle):
            child.removed = True
            child._label = ""
            child._icon = None
            child._children.clear()
            gui_api._container_handle_from_uuid.pop(child._id, None)
            gui_api._container_depth_from_uuid.pop(child._id, None)
        if isinstance(child, GuiTabGroupHandle):
            child._tab_handles.clear()
        if isinstance(child, GuiContainer):
            child._children.clear()
        if isinstance(child, _GuiHandle):
            child._impl.removed = True
            _clear_gui_handle_references_locked(child)
            gui_api._live_component_count -= 1
            gui_api._release_gui_resource_locked(child._impl.uuid)
            gui_api._gui_input_handle_from_uuid.pop(child._impl.uuid, None)
            if isinstance(child, GuiUploadButtonHandle):
                gui_api._discard_file_uploads(source_component_uuid=child._impl.uuid)
            if isinstance(child, GuiPreviewButtonHandle):
                gui_api._discard_preview_work(source_component_uuid=child._impl.uuid)
            gui_api._container_handle_from_uuid.pop(child._impl.uuid, None)
            gui_api._container_depth_from_uuid.pop(child._impl.uuid, None)
    container._children.clear()


class GuiTabGroupHandle(_GuiHandle[None], GuiTabGroupProps):
    """Handle for a tab group. Call :meth:`add_tab()` to add a tab."""

    def __init__(self, _impl: _GuiHandleState[None]) -> None:
        object.__setattr__(self, "_tab_handles", [])
        super().__init__(impl=_impl)

    @staticmethod
    def _tab_descriptor(tab: GuiTabHandle) -> GuiTab:
        """Build one canonical protocol descriptor from its registered handle."""
        return GuiTab(
            label=tab._label,
            icon_html=None if tab._icon is None else svg_from_icon(tab._icon),
            container_id=tab.id,
        )

    def _publish_tabs_locked(
        self,
        handles: Sequence[GuiTabHandle],
        live_messages: Sequence[Message],
    ) -> None:
        """Refresh the group anchor and publish ordered tab lifecycle state."""
        gui_api = self._impl.gui_api
        gui_api._check_active_locked()
        if self._impl.removed:
            raise RuntimeError("Cannot update a removed GuiTabGroupHandle.")
        authoritative_handles = tuple(handles)
        if not live_messages:
            raise ValueError("tab anchor refresh requires a live lifecycle message")
        if len(authoritative_handles) > _GUI_COLLECTION_MAX:
            raise RuntimeError(f"A tab group cannot contain more than {_GUI_COLLECTION_MAX} tabs.")
        if len({tab.id for tab in authoritative_handles}) != len(authoritative_handles):
            raise RuntimeError("tab container registry contains duplicate identifiers")
        for tab in authoritative_handles:
            if tab.removed or tab._parent is not self:
                raise RuntimeError("tab container registry is inconsistent")
            if gui_api._container_handle_from_uuid.get(tab.id) is not tab:
                raise RuntimeError("tab container registry is inconsistent")

        descriptors = tuple(self._tab_descriptor(tab) for tab in authoritative_handles)
        current_props = cast(GuiTabGroupProps, self._impl.props)
        candidate_props = dataclasses.replace(current_props, _tabs=descriptors)
        with gui_api._gui_resource_transaction_locked(
            self._impl.uuid,
            self._impl.value,
            candidate_props,
        ):
            gui_api._websock_interface.queue_messages_or_raise(live_messages)
            self._impl.props = candidate_props

    def add_tab(self, label: str, icon: IconName | None = None) -> GuiTabHandle:
        """Add a tab. Returns a handle we can use to add GUI elements to it."""
        label = cast(str, _validate_renderer_string(label, "tab label"))
        if icon is not None:
            svg_from_icon(icon)
        gui_api = self._impl.gui_api
        with gui_api._lock:
            gui_api._check_active_locked()
            if self._impl.removed:
                raise RuntimeError("Cannot add a tab to a removed GuiTabGroupHandle.")
            if len(self._tab_handles) >= _GUI_COLLECTION_MAX:
                raise RuntimeError(
                    f"A tab group cannot contain more than {_GUI_COLLECTION_MAX} tabs."
                )
            uuid = _make_uuid()
            out = GuiTabHandle(_parent=self, _id=uuid, _label=label, _icon=icon)
            self._tab_handles.append(out)
            try:
                descriptor = self._tab_descriptor(out)
                self._publish_tabs_locked(
                    self._tab_handles,
                    (
                        GuiTabMessage(
                            out.id,
                            self._impl.uuid,
                            descriptor.label,
                            descriptor.icon_html,
                        ),
                    ),
                )
            except BaseException:
                self._tab_handles.remove(out)
                gui_api._container_handle_from_uuid.pop(uuid, None)
                gui_api._container_depth_from_uuid.pop(uuid, None)
                out.removed = True
                raise
            return out

    def remove(self) -> None:
        """Remove this tab group and all contained GUI elements."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                warnings.warn(
                    f"Attempted to remove an already removed {self.__class__.__name__}.",
                    stacklevel=2,
                )
                return
            removed_uuids = tuple(
                uuid for tab in self._tab_handles for uuid in _gui_descendant_uuids(tab)
            )
            removed_tab_uuids = tuple(
                uuid for tab in self._tab_handles for uuid in _tab_subtree_uuids(tab)
            )
            gui_api._websock_interface.queue_message_or_raise(
                GuiRemoveMessage(self._impl.uuid, removed_uuids, removed_tab_uuids)
            )
            _retire_gui_handle_without_queue_locked(self)


@dataclasses.dataclass
class GuiTabHandle(GuiContainer):
    """Use as a context to place GUI elements into a tab."""

    _parent: GuiTabGroupHandle
    _id: str  # Used as container ID of children.
    _label: str
    _icon: IconName | None
    _children: dict[str, SupportsRemoveProtocol] = dataclasses.field(default_factory=dict)
    removed: bool = False

    @property
    def _child_gui_api(self) -> GuiApi:
        return self._parent._impl.gui_api

    @property
    def _child_container_id(self) -> str:
        return self._id

    def _check_container_active(self) -> None:
        if self.removed:
            raise RuntimeError("Cannot add GUI components to a removed tab.")

    @property
    def id(self) -> str:
        """Stable identifier for this tab container."""
        return self._id

    @property
    def icon(self) -> IconName | None:
        """Icon to display on the tab. When set to None, no icon is displayed."""
        if self.removed:
            raise RuntimeError("Cannot read icon from a removed GuiTabHandle.")
        return self._icon

    @icon.setter
    def icon(self, icon: IconName | None) -> None:
        if icon is not None:
            svg_from_icon(icon)
        gui_api = self._parent._impl.gui_api
        with gui_api._lock:
            self._check_container_active()
            old_icon = self._icon
            self._icon = icon
            try:
                descriptor = self._parent._tab_descriptor(self)
                self._parent._publish_tabs_locked(
                    self._parent._tab_handles,
                    (
                        GuiTabUpdateMessage(
                            self.id,
                            self._parent._impl.uuid,
                            descriptor.label,
                            descriptor.icon_html,
                        ),
                    ),
                )
            except BaseException:
                self._icon = old_icon
                raise

    def __post_init__(self) -> None:
        gui_api = self._parent._impl.gui_api
        with gui_api._lock:
            gui_api._check_active_locked()
            if self._parent._impl.removed:
                self.removed = True
                raise RuntimeError("Cannot add a tab to a removed GuiTabGroupHandle.")
            depth = gui_api._container_depth_locked(self._parent._impl.uuid) + 1
            if depth > _GUI_CONTAINER_DEPTH_MAX:
                self.removed = True
                raise RuntimeError(
                    f"GUI component graph depth cannot exceed {_GUI_CONTAINER_DEPTH_MAX}."
                )
            gui_api._container_handle_from_uuid[self._id] = self
            gui_api._container_depth_from_uuid[self._id] = depth

    def remove(self) -> None:
        """Permanently remove this tab and all contained GUI elements from the
        visualizer."""
        gui_api = self._parent._impl.gui_api
        with gui_api._lock:
            if self.removed:
                warnings.warn(
                    f"Attempted to remove an already removed {self.__class__.__name__}.",
                    stacklevel=2,
                )
                return
            if self not in self._parent._tab_handles:
                raise RuntimeError("tab container registry is inconsistent")
            remaining_handles = tuple(tab for tab in self._parent._tab_handles if tab is not self)
            # The registry-derived group update removes the tab descriptor; the
            # compact removal carries every nested GUI entity so persistent
            # replay and incomplete client ancestry are purged too.
            removed_uuids = _gui_descendant_uuids(self)
            removed_tab_uuids = _gui_descendant_tab_uuids(self)
            self._parent._publish_tabs_locked(
                remaining_handles,
                (GuiRemoveMessage(self._id, removed_uuids, removed_tab_uuids),),
            )
            _discard_gui_subtree(self)
            self.removed = True
            self._label = ""
            self._icon = None
            self._parent._tab_handles = list(remaining_handles)
            gui_api._container_handle_from_uuid.pop(self._id, None)
            gui_api._container_depth_from_uuid.pop(self._id, None)


class GuiFolderHandle(_GuiHandle[None], GuiFolderProps, GuiContainer):
    """Use as a context to place GUI elements into a folder."""

    _children: dict[str, SupportsRemoveProtocol]

    def __init__(self, _impl: _GuiHandleState[None]) -> None:
        gui_api = _impl.gui_api
        object.__setattr__(self, "_children", {})
        with gui_api._lock:
            gui_api._container_handle_from_uuid[_impl.uuid] = self
            try:
                super().__init__(impl=_impl)
            except BaseException:
                gui_api._container_handle_from_uuid.pop(_impl.uuid, None)
                raise

    @property
    def _child_gui_api(self) -> GuiApi:
        return self._impl.gui_api

    @property
    def _child_container_id(self) -> str:
        return self._impl.uuid

    def _check_container_active(self) -> None:
        if self._impl.removed:
            raise RuntimeError("Cannot add GUI components to a removed folder.")

    def remove(self) -> None:
        """Permanently remove this folder and all contained GUI elements from the
        visualizer."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                warnings.warn(
                    f"Attempted to remove an already removed {self.__class__.__name__}.",
                    stacklevel=2,
                )
                return
            removed_uuids = _gui_descendant_uuids(self)
            removed_tab_uuids = _gui_descendant_tab_uuids(self)
            gui_api._websock_interface.queue_message_or_raise(
                GuiRemoveMessage(self._impl.uuid, removed_uuids, removed_tab_uuids)
            )
            _retire_gui_handle_without_queue_locked(self)


def _fields_within(container: Any) -> Iterable[_GuiInputHandle]:
    """Yield editable non-button inputs under a container without recursion."""
    stack = list(reversed(tuple(getattr(container, "_children", {}).values())))
    while stack:
        child = stack.pop()
        if (
            isinstance(child, _GuiInputHandle)
            and not child._impl.is_button
            and getattr(child._impl.props, "editable", True)
        ):
            yield child
        if isinstance(child, GuiTabGroupHandle):
            nested: tuple[object, ...] = tuple(child._tab_handles)
        else:
            nested = tuple(getattr(child, "_children", {}).values())
        stack.extend(reversed(nested))


class GuiFormHandle(GuiFolderHandle):
    """Use as a context to place GUI elements into a form.

    A form is a container whose children's values can be committed together by
    calling :meth:`submit_form` (typically from a button's ``on_click`` handler) or
    by pressing Enter in a single-line text input inside the form.

    It takes ONE row in the panel: its ``label``, and a button that opens the
    fields in a popout, keeping them apart from the live controls around them.

    The popout ends in a Reset and a Submit, added as the form's last child
    and reachable as ``form.actions`` (:meth:`reset_form` /
    :meth:`submit_form`). The maximum finite float order is reserved for that
    terminal actions row; assigning it to another child raises
    :class:`ValueError`.

    A form built by :meth:`GuiApi.add_mini_form` holds exactly one direct,
    editable field and is drawn as that field's own row with a send button on
    the end of it -- no popout, no sibling rows or nested containers, and no
    ``actions``, the send button being the client's rather than a child of the
    form.

    Children of a form behave exactly like children of a folder. ``on_update``
    callbacks on individual inputs continue to fire on every keystroke; the
    form's :meth:`on_submit` callback fires only when the form is submitted.
    Register one or both depending on whether you want live or commit
    semantics.

    Forms cannot be nested. Calling :meth:`GuiApi.add_form` inside an
    existing form's context will raise :class:`ValueError`, because nested
    ``<form>`` elements are invalid HTML on the client.

    Example::

        with server.gui.add_form(label="Profile") as form:
            name = server.gui.add_text("Name", "")
            age = server.gui.add_number("Age", 0)
            save = server.gui.add_button("Save")

        save.on_click(lambda _: form.submit_form())

        @form.on_submit
        def _(event):
            print(name.value, age.value)
    """

    def __init__(self, _impl: _GuiHandleState[None]) -> None:
        object.__setattr__(self, "_submit_cb", [])
        object.__setattr__(self, "_initial_field_uuids", set())
        self.actions: GuiButtonGroupHandle
        super().__init__(_impl)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        super().__exit__(exc_type, exc_value, traceback)
        if exc_type is not None:
            return

        fields = list(_fields_within(self))
        props = cast(GuiFormProps, self._impl.props)
        if props.mini and len(fields) != 1:
            # The client has no valid layout for zero or multiple answer fields.
            # Retire the whole provisional subtree before reporting the error.
            self.remove()
            raise ValueError(
                "A mini form holds a single field (exactly one), but "
                f"{len(fields)} were added to this one. Use add_form() for "
                "several fields."
            )

    def on_submit(
        self,
        func: Callable[[GuiEvent[GuiFormHandle]], NoneOrCoroutine],
    ) -> Callable[[GuiEvent[GuiFormHandle]], NoneOrCoroutine]:
        """Attach a function to call when the form is submitted.

        ``on_submit`` is independent from ``on_update`` callbacks on child
        inputs: child ``on_update`` callbacks fire on every keystroke (as
        normal), and the form's ``on_submit`` fires when commit happens (via
        ``form.submit_form()`` or Enter in a single-line text input).

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.
        """
        if not callable(func):
            raise TypeError("callback must be callable")
        with self._impl.gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot register a callback on a removed handle.")
            if len(self._submit_cb) >= _GUI_CALLBACK_MAX:
                raise RuntimeError(
                    f"A form cannot own more than {_GUI_CALLBACK_MAX} submit callbacks."
                )
            self._submit_cb.append(func)
        return func

    def remove_submit_callback(self, callback: Literal["all"] | Callable = "all") -> None:
        """Remove submit callbacks from the form.

        Args:
            callback: Either "all" to remove all callbacks, or a specific callback function to remove.
        """
        with self._impl.gui_api._lock:
            if callback == "all":
                self._submit_cb.clear()
            else:
                self._submit_cb = [cb for cb in self._submit_cb if cb != callback]

    def reset_form(self) -> None:
        """Put every field in this form back to the value it was declared with.

        What a browser's own form reset does, except that the values live on
        the server: the fields are driven from Python, so this is the only side
        that knows what "back" means. Fields inside folders or tabs within the
        form are reset too; buttons are not fields and are left alone.

        Assigning those values fires each field's ``on_update``, as any other
        assignment from Python does. The form's own ``on_submit`` does not
        fire: nothing has been submitted. Reset baselines remain retained and
        count against the GUI scope's resource budgets for the field lifetime.
        """
        gui_api = self._impl.gui_api
        callback_work: list[tuple[tuple[Callable[[Any], object], ...], GuiEvent[Any]]] = []
        while True:
            with gui_api._lock:
                if self._impl.removed:
                    raise RuntimeError("Cannot reset a removed GuiFormHandle.")
                registry = gui_api._gui_input_handle_from_uuid
                snapshots: list[
                    tuple[
                        _GuiInputHandle[Any],
                        object,
                        object,
                        tuple[bool, bool] | None,
                        Path | None,
                    ]
                ] = []
                for field_uuid in tuple(self._initial_field_uuids):
                    field = registry.get(field_uuid)
                    if field is None or field._impl.removed:
                        self._initial_field_uuids.discard(field_uuid)
                        continue
                    normalized = field._normalize_assigned_value_locked(
                        copy.deepcopy(field._impl.initial_value)
                    )
                    props = field._impl.props
                    if isinstance(field, GuiTextHandle):
                        text_props = cast(GuiTextProps, props)
                        mode: tuple[bool, bool] | None = (
                            text_props.markdown,
                            text_props.editable,
                        )
                        image_root = field._image_root
                    else:
                        mode = None
                        image_root = None
                    snapshots.append((field, normalized, props, mode, image_root))

            sources: dict[str, str] = {}
            for field, normalized, _, mode, image_root in snapshots:
                if mode is not None:
                    sources[field._impl.uuid] = _gui_text_source(
                        cast(str, normalized),
                        markdown=mode[0],
                        editable=mode[1],
                        image_root=image_root,
                        server=gui_api._server,
                    )

            with gui_api._lock:
                if self._impl.removed:
                    raise RuntimeError("Cannot reset a removed GuiFormHandle.")
                if any(
                    registry.get(field._impl.uuid) is not field
                    or field._impl.removed
                    or field._impl.props is not props
                    or (
                        mode is not None
                        and mode
                        != (
                            cast(GuiTextProps, field._impl.props).markdown,
                            cast(GuiTextProps, field._impl.props).editable,
                        )
                    )
                    for field, _, props, mode, _ in snapshots
                ):
                    continue

                targets: list[
                    tuple[
                        _GuiInputHandle[Any],
                        object,
                        object,
                        dict[str, Any],
                        bool,
                    ]
                ] = []
                for field, normalized, props, _, _ in snapshots:
                    try:
                        value_unchanged = field._impl.value == normalized
                    except (TypeError, ValueError):
                        value_unchanged = False
                    if isinstance(field, GuiTextHandle):
                        source = sources[field._impl.uuid]
                        text_props = cast(GuiTextProps, props)
                        source_unchanged = text_props._source == source
                        candidate_props: object = dataclasses.replace(text_props, _source=source)
                    else:
                        source = None
                        source_unchanged = True
                        candidate_props = props
                    if value_unchanged and source_unchanged:
                        continue
                    updates: dict[str, Any] = {}
                    if not value_unchanged:
                        updates["value"] = normalized
                    if not source_unchanged:
                        updates["_source"] = source
                    targets.append(
                        (field, normalized, candidate_props, updates, not value_unchanged)
                    )

                if not targets:
                    break
                with contextlib.ExitStack() as transactions:
                    for field, normalized, candidate_props, _, value_changed in targets:
                        if value_changed:
                            transactions.enter_context(
                                field._value_assignment_transaction(normalized)
                            )
                        transactions.enter_context(
                            gui_api._gui_resource_transaction_locked(
                                field._impl.uuid, normalized, candidate_props
                            )
                        )
                    now = time.time()
                    gui_api._websock_interface.queue_messages_or_raise(
                        [
                            GuiUpdateMessage(field._impl.uuid, updates)
                            for field, _, _, updates, _ in targets
                        ]
                    )
                    for field, normalized, candidate_props, _, value_changed in targets:
                        if value_changed:
                            field._impl.value = normalized
                            field._impl.update_timestamp = now
                        if isinstance(field, GuiTextHandle):
                            field._impl.props = cast(GuiTextProps, candidate_props)
                    for field, _, _, _, value_changed in targets:
                        if value_changed:
                            callback_work.append(
                                (
                                    tuple(field._impl.update_cb),
                                    GuiEvent(client_id=None, client=None, target=field),
                                )
                            )
                break

        for callbacks, event in callback_work:
            _invoke_programmatic_callbacks(
                callbacks,
                event,
                gui_api=gui_api,
            )

    def submit_form(self) -> None:
        """Programmatically submit this form.

        Fires all registered ``on_submit`` callbacks, and closes the form's
        popout on every client: the question has been answered, whoever
        answered it.
        """
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot submit a removed GuiFormHandle.")
            props = cast(GuiFormProps, self._impl.props)
            if props.mini and len(list(_fields_within(self))) != 1:
                raise ValueError("A mini form must contain exactly one field before submission.")
            # Publish before entering user code, matching browser-originated form
            # submissions. A callback failure must not leave every popout open
            # after earlier callbacks already performed arbitrary side effects.
            gui_api._websock_interface.queue_message_or_raise(
                GuiFormSubmitMessage(uuid=self._impl.uuid)
            )
            callbacks = tuple(self._submit_cb)
            event = GuiEvent(client_id=None, client=None, target=self)
        _invoke_programmatic_callbacks(
            callbacks,
            event,
            gui_api=gui_api,
        )


@dataclasses.dataclass
class GuiModalHandle(GuiContainer):
    """Use as a context to place GUI elements into a modal."""

    _gui_api: GuiApi
    _uuid: str  # Used as container ID of children.
    _children: dict[str, SupportsRemoveProtocol] = dataclasses.field(default_factory=dict)
    closed: bool = False
    _create_message: Message | None = None

    @property
    def _child_gui_api(self) -> GuiApi:
        return self._gui_api

    @property
    def _child_container_id(self) -> str:
        return self._uuid

    def _check_container_active(self) -> None:
        if self.closed:
            raise RuntimeError("Cannot add GUI components to a closed modal.")

    @property
    def id(self) -> str:
        """Stable identifier for this modal container."""
        return self._uuid

    def __post_init__(self) -> None:
        with self._gui_api._lock:
            self._gui_api._check_active_locked()
            if len(self._gui_api._modal_handle_from_uuid) >= _GUI_MODAL_MAX:
                self.closed = True
                raise RuntimeError(f"A GUI scope cannot own more than {_GUI_MODAL_MAX} modals.")
            self._gui_api._container_handle_from_uuid[self._uuid] = self
            # A modal shell is a portal graph root, not a GuiComponent node.
            self._gui_api._container_depth_from_uuid[self._uuid] = 0
            self._gui_api._modal_handle_from_uuid[self._uuid] = self
            try:
                title = getattr(self._create_message, "title", "")
                self._gui_api._set_gui_resource_locked(
                    f"modal:{self._uuid}", _gui_resource_cost(None, title)
                )
                if self._create_message is not None:
                    self._gui_api._websock_interface.queue_message_or_raise(self._create_message)
                    self._create_message = None
            except BaseException:
                self._gui_api._container_handle_from_uuid.pop(self._uuid, None)
                self._gui_api._container_depth_from_uuid.pop(self._uuid, None)
                self._gui_api._modal_handle_from_uuid.pop(self._uuid, None)
                self._gui_api._release_gui_resource_locked(f"modal:{self._uuid}")
                self.closed = True
                raise

    def close(self) -> None:
        """Close this modal and permanently remove all contained GUI elements."""
        with self._gui_api._lock:
            if self.closed:
                warnings.warn(
                    "Attempted to close an already closed GuiModalHandle.",
                    stacklevel=2,
                )
                return
            removed_uuids = _gui_descendant_uuids(self)
            removed_tab_uuids = _gui_descendant_tab_uuids(self)
            self._gui_api._websock_interface.queue_message_or_raise(
                GuiCloseModalMessage(self._uuid, removed_uuids, removed_tab_uuids),
            )
            _discard_gui_subtree(self)
            self.closed = True
            self._create_message = None
            self._gui_api._container_handle_from_uuid.pop(self._uuid, None)
            self._gui_api._container_depth_from_uuid.pop(self._uuid, None)
            self._gui_api._modal_handle_from_uuid.pop(self._uuid, None)
            self._gui_api._release_gui_resource_locked(f"modal:{self._uuid}")

    def remove(self) -> None:
        """Compatibility alias for :meth:`close`."""

        self.close()


class _UnsafeMarkdownAssetPath(ValueError):
    """A markdown image reference that leaves its declared asset root."""


@dataclasses.dataclass(frozen=True)
class _ResolvedMarkdownAsset:
    path: Path
    metadata: os.stat_result


def _resolve_markdown_asset(image_root: Path, url: str) -> _ResolvedMarkdownAsset:
    """Resolve and capture one contained local Markdown asset's identity."""
    posix_path = PurePosixPath(url)
    windows_path = PureWindowsPath(url)
    if (
        posix_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
        or ".." in windows_path.parts
        or any(":" in part for part in windows_path.parts)
    ):
        raise _UnsafeMarkdownAssetPath(url)

    root = image_root.resolve()
    path = (root / Path(*posix_path.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise _UnsafeMarkdownAssetPath(url) from error
    return _ResolvedMarkdownAsset(path, path.stat())


def _resolve_markdown_asset_path(image_root: Path, url: str) -> Path:
    """Compatibility helper returning the validated asset's canonical path."""
    return _resolve_markdown_asset(image_root, url).path


_MARKDOWN_INLINE_MAX_ASSET_BYTES = 8 * 1024 * 1024
_MARKDOWN_INLINE_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*_[\]{}()#+\-.!<> ])")
_MARKDOWN_FENCE = re.compile(r"^[ \t]{0,3}([`~]{3,})(.*)$")


@dataclasses.dataclass
class _InlineMarkdownBudget:
    remaining_output_bytes: int


@dataclasses.dataclass(frozen=True)
class _MarkdownImageDestination:
    start: int
    end: int
    value: str


def _markdown_unescape(value: str) -> str:
    return _MARKDOWN_ESCAPE.sub(r"\1", value)


def _fenced_markdown_ranges(markdown: str) -> list[tuple[int, int]]:
    """Return fenced-code spans, preserving offsets for the rewrite pass."""
    ranges: list[tuple[int, int]] = []
    fence_character: str | None = None
    fence_length = 0
    fence_start = 0
    offset = 0
    for line in markdown.splitlines(keepends=True):
        match = _MARKDOWN_FENCE.match(line.rstrip("\r\n"))
        if fence_character is None:
            if match is not None:
                marker = match.group(1)
                fence_character = marker[0]
                fence_length = len(marker)
                fence_start = offset
        elif (
            match is not None
            and match.group(1)[0] == fence_character
            and len(match.group(1)) >= fence_length
            and not match.group(2).strip()
        ):
            ranges.append((fence_start, offset + len(line)))
            fence_character = None
        offset += len(line)
    if fence_character is not None:
        ranges.append((fence_start, len(markdown)))
    return ranges


def _markdown_image_destinations(markdown: str) -> Iterator[_MarkdownImageDestination]:
    """Yield destination spans for inline images outside code constructs."""
    fenced = _fenced_markdown_ranges(markdown)
    fence_index = 0
    index = 0
    length = len(markdown)
    while index < length:
        while fence_index < len(fenced) and index >= fenced[fence_index][1]:
            fence_index += 1
        if fence_index < len(fenced) and fenced[fence_index][0] <= index:
            index = fenced[fence_index][1]
            continue

        if markdown[index] == "`":
            run_end = index + 1
            while run_end < length and markdown[run_end] == "`":
                run_end += 1
            delimiter = markdown[index:run_end]
            closing = markdown.find(delimiter, run_end)
            while closing >= 0 and (
                (closing > 0 and markdown[closing - 1] == "`")
                or (closing + len(delimiter) < length and markdown[closing + len(delimiter)] == "`")
            ):
                closing = markdown.find(delimiter, closing + len(delimiter))
            index = closing + len(delimiter) if closing >= 0 else run_end
            continue

        if not markdown.startswith("![", index):
            index += 1
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and markdown[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            index += 2
            continue

        cursor = index + 2
        label_depth = 1
        while cursor < length and label_depth:
            character = markdown[cursor]
            if character == "\\" and cursor + 1 < length:
                cursor += 2
                continue
            if character == "[":
                label_depth += 1
            elif character == "]":
                label_depth -= 1
                if label_depth == 0:
                    break
            cursor += 1
        if label_depth or cursor + 1 >= length or markdown[cursor + 1] != "(":
            index += 2
            continue

        cursor += 2
        while cursor < length and markdown[cursor].isspace():
            cursor += 1
        if cursor >= length:
            return

        if markdown[cursor] == "<":
            destination_start = cursor + 1
            cursor += 1
            while cursor < length:
                if markdown[cursor] == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if markdown[cursor] == ">":
                    break
                if markdown[cursor] in "\r\n":
                    break
                cursor += 1
            if cursor >= length or markdown[cursor] != ">":
                index += 2
                continue
            destination_end = cursor
            cursor += 1
        else:
            destination_start = cursor
            depth = 0
            destination_end = -1
            while cursor < length:
                character = markdown[cursor]
                if character == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if character == "(":
                    depth += 1
                elif character == ")":
                    if depth == 0:
                        destination_end = cursor
                        break
                    depth -= 1
                elif character.isspace() and depth == 0:
                    destination_end = cursor
                    break
                cursor += 1
            if destination_end < 0:
                index += 2
                continue

        while cursor < length and markdown[cursor].isspace():
            cursor += 1
        if cursor < length and markdown[cursor] in ('"', "'"):
            quote = markdown[cursor]
            cursor += 1
            while cursor < length:
                if markdown[cursor] == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if markdown[cursor] == quote:
                    cursor += 1
                    break
                cursor += 1
            else:
                index += 2
                continue
            while cursor < length and markdown[cursor].isspace():
                cursor += 1
        if cursor >= length or markdown[cursor] != ")":
            index += 2
            continue

        raw_destination = markdown[destination_start:destination_end]
        yield _MarkdownImageDestination(
            destination_start,
            destination_end,
            _markdown_unescape(raw_destination),
        )
        index = cursor + 1


def _rewrite_markdown_images(markdown: str, rewrite: Callable[[str], str | None]) -> str:
    pieces: list[str] = []
    cursor = 0
    for destination in _markdown_image_destinations(markdown):
        replacement = rewrite(destination.value)
        if replacement is None:
            continue
        pieces.extend((markdown[cursor : destination.start], replacement))
        cursor = destination.end
    if not pieces:
        return markdown
    pieces.append(markdown[cursor:])
    return "".join(pieces)


def _relative_markdown_asset(url: str) -> str | None:
    """Return a true relative file destination; leave all URI forms alone."""
    if not url or url.startswith(("#", "//")):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    try:
        return unquote(parsed.path, errors="strict")
    except UnicodeDecodeError:
        return None


def _get_data_url(
    url: str,
    image_root: Path | None,
    budget: _InlineMarkdownBudget | None = None,
) -> str:
    local_url = _relative_markdown_asset(url)
    if local_url is None:
        return url
    if image_root is None:
        warnings.warn(
            (
                "No `image_root` provided. All relative paths will be scoped to the "
                "Leika installation path."
            ),
            stacklevel=2,
        )
        image_root = Path(__file__).parent
    try:
        source = _resolve_markdown_asset(image_root, local_url)
    except _UnsafeMarkdownAssetPath:
        warnings.warn(
            f"Refused image {url}, which is outside image_root {image_root}.",
            stacklevel=2,
        )
        return url
    except OSError:
        warnings.warn(
            f"Failed to read image {url}, with image_root set to {image_root}.",
            stacklevel=2,
        )
        return url
    if budget is None:
        budget = _InlineMarkdownBudget(_MARKDOWN_INLINE_MAX_TOTAL_BYTES)
    try:
        with open_regular_file(source.path, expected_metadata=source.metadata) as file:
            before = os.fstat(file.fileno())
            size = before.st_size
            encoded_size = 4 * ((size + 2) // 3)
            # ``image/png``/``image/gif`` are the shortest supported
            # content-derived prefixes. If even this lower bound cannot fit,
            # avoid the disk read; the exact MIME check follows validation.
            output_size = len("data:image/png;base64,") + encoded_size
            if (
                size > _MARKDOWN_INLINE_MAX_ASSET_BYTES
                or output_size > budget.remaining_output_bytes
            ):
                warnings.warn(
                    f"Refused to inline image {url}: the Markdown image byte limit "
                    "would be exceeded.",
                    stacklevel=2,
                )
                return url
            binary = file.read(_MARKDOWN_INLINE_MAX_ASSET_BYTES + 1)
            after = os.fstat(file.fileno())
        validate_unchanged_file_snapshot(source.path, before, after)
        if len(binary) != size:
            raise OSError(f"{source.path} changed size while it was being read")
        image_kind, _ = safe_image_info(binary)
        mime_type = "image/jpeg" if image_kind == "jpeg" else f"image/{image_kind}"
        exact_output_size = len(f"data:{mime_type};base64,") + 4 * ((len(binary) + 2) // 3)
        if exact_output_size > budget.remaining_output_bytes:
            warnings.warn(
                f"Refused to inline image {url}: the Markdown image byte limit would be exceeded.",
                stacklevel=2,
            )
            return url
        encoded = base64.b64encode(binary).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        budget.remaining_output_bytes -= len(data_url)
        return data_url
    except (OSError, ValueError):
        warnings.warn(
            f"Failed to read image {url}, with image_root set to {image_root}.",
            stacklevel=2,
        )
        return url


def _parse_markdown(markdown: str, image_root: Path | None) -> str:
    budget = _InlineMarkdownBudget(_MARKDOWN_INLINE_MAX_TOTAL_BYTES)
    return _rewrite_markdown_images(markdown, lambda url: _get_data_url(url, image_root, budget))


def _link_markdown_assets(
    markdown: str,
    image_root: Path,
    register: Callable[[Path, os.stat_result], HttpAsset],
) -> str:
    """Point a document's relative images at server URLs of their own.

    The counterpart of :func:`_parse_markdown` for when there is a server to
    fetch from. Inlining images works anywhere but puts every byte of them in
    front of the text, so nothing shows until all of it has arrived;
    registering them (:meth:`Server.register_http_asset`) leaves the document
    the size of its writing, and the browser fetches the images alongside it.

    Web addresses, fragments, protocol-relative destinations, and every URI
    scheme are already self-contained and pass through untouched. A local
    image that cannot be read keeps its original reference, so the document
    renders with the same broken figure it would show anywhere else.
    """

    def linked(url: str) -> str | None:
        local_url = _relative_markdown_asset(url)
        if local_url is None:
            return None
        try:
            source = _resolve_markdown_asset(image_root, local_url)
        except _UnsafeMarkdownAssetPath:
            warnings.warn(
                f"Refused image {url}, which is outside image_root {image_root}.",
                stacklevel=2,
            )
            return None
        except OSError:
            warnings.warn(
                f"Failed to read image {url}, relative to {image_root}.",
                stacklevel=2,
            )
            return None
        try:
            asset = register(source.path, source.metadata)
        except (OSError, ValueError):
            warnings.warn(
                f"Failed to read image {url}, relative to {image_root}.",
                stacklevel=2,
            )
            return None
        if asset.pixel_size is None:
            return asset.url
        width, height = asset.pixel_size
        return f"{asset.url}?w={width}&h={height}"

    return _rewrite_markdown_images(markdown, linked)


class GuiProgressBarHandle(_GuiInputHandle[float], GuiProgressBarProps):
    """Handle for updating and removing progress bars."""

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        value = _finite_number(value)
        if not 0 <= value <= 100:
            raise ValueError("Progress bar value must be within [0, 100].")
        return float(value)

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


class GuiHtmlHandle(_GuiHandle[None], GuiHtmlProps):
    """Handle for trusted raw HTML bounded by the 1 Mi-character limit.

    ``content`` is injected by the browser without sanitization and may act with
    the page's authority. Sanitize any untrusted input before assigning it or
    passing it to :meth:`GuiApi.add_html`.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "content":
            value = _validate_gui_html_content(value)
        super().__setattr__(name, value)


class GuiDividerHandle(_GuiHandle[None], GuiDividerProps):
    """Handle for updating and removing dividers."""


_PLOTLY_JSON_MAX_UTF16_CODE_UNITS = 16 * 1024 * 1024
"""Bundled browser JSON parser limit for one Plotly payload."""

_PLOTLY_PREFLIGHT_MAX_NODES = 500_000
_PLOTLY_CONFIG_MAX_ITEMS = 4096


def _validate_plotly_json_size(json_str: str) -> str:
    if utf16_code_unit_length_exceeds(json_str, _PLOTLY_JSON_MAX_UTF16_CODE_UNITS):
        raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    return json_str


def _plotly_string_json_upper_bound(value: str) -> int:
    """Conservative UTF-16 length of a JSON string without allocating it."""
    total = 2
    for character in value:
        codepoint = ord(character)
        if character in ('"', "\\"):
            total += 2
        elif codepoint < 0x20:
            total += 6
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("Plotly data cannot contain unpaired Unicode surrogates")
        elif codepoint > 0xFFFF:
            total += 12
        elif codepoint > 0x7F:
            total += 6
        else:
            total += 1
        if total > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
            raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    return total


def _plotly_graph_json_upper_bound(*roots: object) -> int:
    """Bound an exact plain Plotly property graph before serialization.

    BasePlotlyType instances are accepted only by dedicated, hook-free figure,
    frame, and template extractors. Encountering one inside raw data/layout is
    an unsupported injected object, not a safe serialized leaf.
    """
    total = 0
    nodes = 0
    active: set[int] = set()
    stack: list[tuple[object, int, bool]] = [(root, 0, False) for root in reversed(roots)]
    while stack:
        item, depth, exiting = stack.pop()
        if exiting:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > _PLOTLY_PREFLIGHT_MAX_NODES:
            raise ValueError("Plotly figure contains too many values")
        if depth > 64:
            raise ValueError("Plotly figure is nested too deeply")
        if item is None or type(item) is bool:
            total += 5
        elif type(item) is str:
            total += _plotly_string_json_upper_bound(item)
        elif type(item) is int:
            total += max(1, (abs(item).bit_length() * 30103 + 99_999) // 100_000) + 1
        elif type(item) is float:
            total += 32
        elif type(item) in (datetime.date, datetime.datetime):
            total += 128
        elif type(item) is decimal.Decimal:
            # PlotlyJSONEncoder converts Decimal through float(), which has a
            # fixed-size result and avoids constructing its potentially huge
            # decimal spelling.
            float(item)
            total += 32
        elif isinstance(item, np.generic):
            scalar_dtype = np.dtype(type(item))
            if scalar_dtype.type is not type(item):
                raise TypeError("custom numpy scalar subclasses are not supported in Plotly data")
            kind = scalar_dtype.kind
            if kind == "U":
                total += (int(scalar_dtype.itemsize) // 4) * 12 + 2
            elif kind == "S":
                total += int(scalar_dtype.itemsize) * 6 + 2
            elif kind in "mM":
                total += 128
            elif kind in "biufc":
                total += 128
            else:
                raise TypeError(f"unsupported Plotly numpy scalar dtype: {scalar_dtype}")
        elif type(item) is np.ndarray:
            kind = item.dtype.kind
            element_count = int(item.size)
            if item.ndim + depth > 64:
                raise ValueError("Plotly figure is nested too deeply")
            # Plotly 5.21 renders ndarrays as nested JSON lists. Charge every
            # list container, including empty/singleton dimensions; later
            # Plotly versions may instead use one compact base64 record.
            container_count = 0
            prefix = 1
            for dimension in item.shape:
                container_count += prefix
                if container_count > _PLOTLY_PREFLIGHT_MAX_NODES:
                    raise ValueError("Plotly figure contains too many values")
                prefix *= int(dimension)
            if element_count + container_count > _PLOTLY_PREFLIGHT_MAX_NODES - nodes:
                raise ValueError("Plotly figure contains too many values")
            # Brackets plus a conservative comma for every child edge.
            list_punctuation_bound = 3 * container_count + element_count + 128
            if item.dtype.hasobject:
                children = tuple(item.flat)
                nodes += container_count
                total += list_punctuation_bound
                identity = id(item)
                if identity in active:
                    raise ValueError("Plotly figure cannot contain cycles")
                active.add(identity)
                stack.append((item, depth, True))
                stack.extend((child, depth + item.ndim, False) for child in reversed(children))
                continue
            nodes += element_count + container_count
            if kind == "U":
                per_item = (int(item.dtype.itemsize) // 4) * 12 + 3
            elif kind == "S":
                per_item = int(item.dtype.itemsize) * 6 + 3
            elif kind in "mM":
                per_item = 129
            elif kind == "b":
                per_item = 6
            elif kind in "iu":
                bits = int(item.dtype.itemsize) * 8
                digits = (bits * 30103 + 99_999) // 100_000
                per_item = digits + (2 if kind == "i" else 1)
            elif kind == "f":
                per_item = 33
            elif kind == "c":
                raise TypeError("complex Plotly ndarray values are not supported")
            else:
                raise TypeError(f"unsupported Plotly ndarray dtype: {item.dtype}")
            list_bound = element_count * per_item + list_punctuation_bound
            base64_bound = 4 * ((int(item.nbytes) + 2) // 3) + 256
            total += max(list_bound, base64_bound)
        else:
            children: tuple[object, ...]
            identity = id(item)
            if type(item) is dict:
                mapping = cast(dict[object, object], item)
                item_count = len(mapping)
                if 2 * item_count > _PLOTLY_PREFLIGHT_MAX_NODES - nodes:
                    raise ValueError("Plotly figure contains too many values")
                total += 2 + 2 * item_count
                identity = id(item)
                if identity in active:
                    raise ValueError("Plotly figure cannot contain cycles")
                active.add(identity)
                stack.append((item, depth, True))
                for key, child in reversed(tuple(mapping.items())):
                    if type(key) is not str:
                        raise TypeError("Plotly mappings must have string keys")
                    stack.append((child, depth + 1, False))
                    stack.append((key, depth + 1, False))
                continue
            elif type(item) in (list, tuple):
                sequence = cast(list[object] | tuple[object, ...], item)
                item_count = len(sequence)
                if item_count > _PLOTLY_PREFLIGHT_MAX_NODES - nodes:
                    raise ValueError("Plotly figure contains too many values")
                total += 2 + item_count
                identity = id(item)
                if identity in active:
                    raise ValueError("Plotly figure cannot contain cycles")
                active.add(identity)
                stack.append((item, depth, True))
                for child in reversed(sequence):
                    stack.append((child, depth + 1, False))
                continue
            else:
                raise TypeError(f"unsupported Plotly value: {type(item).__name__}")
            if identity in active:
                raise ValueError("Plotly figure cannot contain cycles")
            active.add(identity)
            stack.append((item, depth, True))
            stack.extend((child, depth + 1, False) for child in reversed(children))
            continue
        if total > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
            raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    if total > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
        raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    return total


def _snapshot_plotly_config(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Take a bounded private JSON config snapshot."""
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise TypeError("Plotly config must be a mapping or None")
    try:
        reported = len(config)
    except RuntimeError:
        # Preserve renderer-preparation reentrancy (and explicit custom
        # mapping RuntimeErrors) instead of disguising it as a shape error.
        raise
    except Exception as error:
        raise TypeError("Plotly config must be a finite mapping") from error
    if reported > _PLOTLY_CONFIG_MAX_ITEMS:
        raise ValueError(f"Plotly config cannot contain more than {_PLOTLY_CONFIG_MAX_ITEMS} items")
    try:
        items = tuple(itertools.islice(config.items(), _PLOTLY_CONFIG_MAX_ITEMS + 1))
    except RuntimeError:
        raise
    except Exception as error:
        raise TypeError("Plotly config must provide finite key/value items") from error
    if len(items) != reported or len(items) > _PLOTLY_CONFIG_MAX_ITEMS:
        raise ValueError("Plotly config length does not match its finite items")

    active: set[int] = set()
    nodes = 0

    def snapshot(value: object, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > _PLOTLY_PREFLIGHT_MAX_NODES:
            raise ValueError("Plotly config contains too many values")
        if depth > 64:
            raise ValueError("Plotly config is nested too deeply")
        if value is None or type(value) in (bool, int, str):
            if type(value) is str:
                _plotly_string_json_upper_bound(value)
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("Plotly config numbers must be finite")
            return value
        if type(value) not in (dict, list, tuple):
            raise TypeError(f"unsupported Plotly config value: {type(value).__name__}")
        identity = id(value)
        if identity in active:
            raise ValueError("Plotly config cannot contain cycles")
        active.add(identity)
        try:
            if type(value) is dict:
                output: dict[str, object] = {}
                reported = len(value)
                if reported > _PLOTLY_CONFIG_MAX_ITEMS:
                    raise ValueError(
                        f"Plotly config mappings cannot contain more than "
                        f"{_PLOTLY_CONFIG_MAX_ITEMS} items"
                    )
                items = tuple(itertools.islice(value.items(), _PLOTLY_CONFIG_MAX_ITEMS + 1))
                if len(items) != reported or len(items) > _PLOTLY_CONFIG_MAX_ITEMS:
                    raise ValueError("Plotly config mapping length changed during snapshot")
                for key, child in items:
                    if type(key) is not str:
                        raise TypeError("Plotly config mappings must have string keys")
                    _plotly_string_json_upper_bound(key)
                    output[key] = snapshot(child, depth + 1)
                return output
            values = cast(list[object] | tuple[object, ...], value)
            reported = len(values)
            if reported > _PLOTLY_CONFIG_MAX_ITEMS:
                raise ValueError(
                    f"Plotly config collections cannot contain more than "
                    f"{_PLOTLY_CONFIG_MAX_ITEMS} items"
                )
            materialized = tuple(itertools.islice(iter(values), _PLOTLY_CONFIG_MAX_ITEMS + 1))
            if len(materialized) != reported or len(materialized) > _PLOTLY_CONFIG_MAX_ITEMS:
                raise ValueError("Plotly config collection length changed during snapshot")
            copied = [snapshot(child, depth + 1) for child in materialized]
            return copied if type(value) is list else tuple(copied)
        finally:
            active.remove(identity)

    result: dict[str, Any] = {}
    for key, value in items:
        if type(key) is not str:
            raise TypeError("Plotly config mappings must have string keys")
        _plotly_string_json_upper_bound(key)
        if key in result:
            raise ValueError(f"Plotly config contains duplicate key {key!r}")
        result[key] = snapshot(value, 1)
    _plotly_graph_json_upper_bound(result)
    return result


def _plotly_figure_raw_graph(figure: go.Figure) -> tuple[object, object, object]:
    """Return exact stock Figure storage without invoking user overrides."""
    import plotly.graph_objects as go
    from plotly.basedatatypes import BaseFigure

    if type(figure) is not go.Figure:
        raise TypeError("figure must be an exact plotly.graph_objects.Figure")
    figure_type = type(figure)
    try:
        figure_to_json = type.__getattribute__(figure_type, "to_json")
        figure_to_dict = type.__getattribute__(figure_type, "to_dict")
        figure_getattribute = type.__getattribute__(figure_type, "__getattribute__")
    except AttributeError as error:
        raise TypeError("custom Plotly serialization overrides are not supported") from error
    if (
        type(figure_type) is not type
        or figure_to_json is not BaseFigure.to_json
        or figure_to_dict is not BaseFigure.to_dict
        or figure_getattribute is not object.__getattribute__
    ):
        raise TypeError("custom Plotly serialization overrides are not supported")
    state = object.__getattribute__(figure, "__dict__")
    if "to_json" in state or "to_dict" in state:
        raise TypeError("instance Plotly serialization overrides are not supported")
    frames = state.get("_frame_objs", []) or []
    from plotly.graph_objs import Frame

    if type(frames) is not list or any(type(frame) is not Frame for frame in frames):
        raise TypeError("custom Plotly frame objects are not supported")
    raw_frames: list[dict[str, object]] = []
    for frame in frames:
        frame_state = object.__getattribute__(frame, "__dict__")
        raw = frame_state.get("_orphan_props", {})
        if type(raw) is not dict:
            raise TypeError("Plotly frame properties must be an exact mapping")
        raw_frames.append(cast(dict[str, object], raw))
    return (
        state.get("_data", []),
        state.get("_layout", {}),
        raw_frames,
    )


def _plotly_json_and_config(
    figure: go.Figure, config: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any] | None]:
    """Serialize a preflighted Plotly figure and return its private config."""
    from plotly.basedatatypes import BaseFigure

    private_config = _snapshot_plotly_config(config)
    figure_bound = _plotly_graph_json_upper_bound(*_plotly_figure_raw_graph(figure))
    config_bound = 0 if private_config is None else _plotly_graph_json_upper_bound(private_config)
    if figure_bound + config_bound + 256 > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
        raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")

    json_str = BaseFigure.to_json(figure)
    if not isinstance(json_str, str):
        raise TypeError("Plotly Figure.to_json() must return a string")
    json_str = _validate_plotly_json_size(json_str)
    if private_config is not None:
        plot_dict = json.loads(json_str)
        plot_dict["config"] = {**plot_dict.get("config", {}), **private_config}
        json_str = json.dumps(plot_dict)
    return _validate_plotly_json_size(json_str), private_config


def _plotly_json_with_config(figure: go.Figure, config: Mapping[str, Any] | None) -> str:
    """Serialize a bounded Plotly figure, merging an optional private config."""
    return _plotly_json_and_config(figure, config)[0]


def _plotly_payload_from_json(
    source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Decode one bounded owned wire snapshot into fresh figure/config graphs."""
    # This is the immutable, already-admitted retained snapshot. Reapplying a
    # mutable test/configuration limit here could make a previously valid
    # handle unreadable; reconstruction remains serialized by the renderer
    # preparation reservation.
    payload = json.loads(source)
    if type(payload) is not dict:
        raise RuntimeError("stored Plotly payload is not a mapping")
    config = payload.pop("config", None)
    if config is not None and type(config) is not dict:
        raise RuntimeError("stored Plotly config is not a mapping")
    return cast(dict[str, Any], payload), cast(dict[str, Any] | None, config)


def _plotly_figure_from_json(source: str) -> go.Figure:
    """Reconstruct independently without consulting Plotly's global template."""
    import plotly.graph_objects as go

    payload, _ = _plotly_payload_from_json(source)
    layout = payload.get("layout")
    if layout is None:
        layout = {}
        payload["layout"] = layout
    if type(layout) is not dict:
        raise RuntimeError("stored Plotly layout is not a mapping")
    template_was_absent = "template" not in layout
    if template_was_absent:
        # BaseFigure injects the mutable process-global default whenever the
        # prospective layout has no template. A private empty template is the
        # race-free constructor sentinel; clear it afterward so the returned
        # Figure still represents the admitted template-free JSON exactly.
        layout["template"] = {}
    figure = go.Figure(payload)
    if template_was_absent:
        figure.layout.template = None
    return figure


class GuiPlotlyHandle(_GuiHandle[None], GuiPlotlyProps):
    """Handle backed only by bounded JSON, never by the caller's mutable Figure."""

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "aspect":
            value = _positive_number(value, "aspect")
        super().__setattr__(name, value)

    @property
    def figure(self) -> go.Figure:
        """Independent snapshot of the displayed figure. Assign it to publish edits."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot read figure from a removed GuiPlotlyHandle.")
            source = cast(GuiPlotlyProps, self._impl.props)._plotly_json_str
        with gui_api._server._reserve_renderer_preparation():
            figure = _plotly_figure_from_json(source)
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot read figure from a removed GuiPlotlyHandle.")
        return figure

    @figure.setter
    def figure(self, figure: go.Figure) -> None:
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed GuiPlotlyHandle.")
            source = cast(GuiPlotlyProps, self._impl.props)._plotly_json_str
        # Plotly can copy and encode a large graph. Never wait for renderer
        # preparation while holding the GUI registry/resource lock.
        with gui_api._server._reserve_renderer_preparation():
            _, config = _plotly_payload_from_json(source)
            json_str = _plotly_json_with_config(figure, config)
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed GuiPlotlyHandle.")
            props = cast(GuiPlotlyProps, self._impl.props)
            if props._plotly_json_str != source:
                raise RuntimeError("Plotly figure changed during serialization")
            old_json = props._plotly_json_str
            props._plotly_json_str = json_str
            try:
                with gui_api._gui_resource_transaction_locked(
                    self._impl.uuid, self._impl.value, props
                ):
                    gui_api._websock_interface.queue_message_or_raise(
                        GuiUpdateMessage(self._impl.uuid, {"_plotly_json_str": json_str})
                    )
            except BaseException:
                props._plotly_json_str = old_json
                raise


class GuiImageHandle(_GuiHandle[None], GuiImageProps):
    """Handle for updating and removing images."""

    _user_format: Literal["auto", "jpeg", "png"]
    """The format the caller asked for, which ``_format`` resolves 'auto' from.
    Kept so a later re-encode makes the same choice as the first one."""

    def __init__(
        self,
        _impl: _GuiHandleState,
        _image: np.ndarray,
        _jpeg_quality: int | None,
        _user_format: Literal["auto", "jpeg", "png"] = "auto",
    ):
        # ``GuiApi.add_image`` has already taken the sole private snapshot;
        # transfer that owned array rather than transiently duplicating it.
        object.__setattr__(self, "_image", _image)
        object.__setattr__(self, "_jpeg_quality", _jpeg_quality)
        object.__setattr__(self, "_user_format", _user_format)
        super().__init__(impl=_impl)

    @property
    def image(self) -> np.ndarray:
        """Current content of this image element. Synchronized automatically when assigned."""
        if self._impl.removed:
            raise RuntimeError("Cannot read image from a removed GuiImageHandle.")
        return self._image.copy()

    @image.setter
    def image(self, image: np.ndarray) -> None:
        spec = _ndarray_snapshot_spec(image)
        if spec[2] > _GUI_AGGREGATE_PAYLOAD_MAX_BYTES:
            raise RuntimeError("Image source exceeds the 128 MiB GUI retained payload budget.")
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed GuiImageHandle.")
            user_format = self._user_format
            jpeg_quality = self._jpeg_quality
        with gui_api._server._reserve_image_preparation(spec[2]):
            snapshot = _private_ndarray_snapshot(image, spec)
            resolved_format, data = encode_image_binary(
                snapshot, user_format, jpeg_quality=jpeg_quality
            )
            with gui_api._lock:
                if self._impl.removed:
                    raise RuntimeError("Cannot update a removed GuiImageHandle.")
                if self._user_format != user_format or self._jpeg_quality != jpeg_quality:
                    raise RuntimeError("Image encoding settings changed during preparation.")
                self._commit_image_snapshot(snapshot, resolved_format, data)

    def _commit_image_snapshot(
        self,
        snapshot: np.ndarray,
        resolved_format: Literal["jpeg", "png"],
        data: bytes,
    ) -> None:
        """Publish one already-prepared private image snapshot."""
        props = cast(GuiImageProps, self._impl.props)
        old_image = self._image
        old_format = props._format
        old_data = props._data
        self._image = snapshot
        props._format = resolved_format
        props._data = data
        try:
            decoded_pixels = int(self._image.shape[0]) * int(self._image.shape[1])
            with self._impl.gui_api._gui_resource_transaction_locked(
                self._impl.uuid,
                self._impl.value,
                props,
                decoded_pixels=decoded_pixels,
                retained_extra_bytes=int(self._image.nbytes),
            ):
                self._impl.gui_api._websock_interface.queue_message_or_raise(
                    GuiUpdateMessage(
                        self._impl.uuid,
                        {"_format": resolved_format, "_data": data},
                    )
                )
                self._impl.decoded_pixels = decoded_pixels
                self._impl.retained_extra_bytes = int(self._image.nbytes)
        except BaseException:
            self._image = old_image
            props._format = old_format
            props._data = old_data
            raise

    @property
    def format(self) -> Literal["auto", "jpeg", "png"]:
        """Image format. 'auto' will use PNG for RGBA images and JPEG for RGB."""
        if self._impl.removed:
            raise RuntimeError("Cannot read format from a removed GuiImageHandle.")
        return self._user_format

    @format.setter
    def format(self, value: Literal["auto", "jpeg", "png"]) -> None:
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed GuiImageHandle.")
            _validate_image_encoding_options(value, self._jpeg_quality)
            old_user_format = self._user_format
            if old_user_format == value:
                return
            image = self._image
            jpeg_quality = self._jpeg_quality
            source_bytes = int(image.nbytes)
            has_alpha = image.shape[2] == 4

        # Encoding may allocate an image-sized working buffer. Admission must
        # happen outside the GUI lock so it cannot deadlock with another image
        # preparation that later needs the GUI lock to publish.
        with gui_api._server._reserve_image_preparation(source_bytes):
            resolved_format, data = encode_image_binary(image, value, jpeg_quality=jpeg_quality)

        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed GuiImageHandle.")
            if (
                self._image is not image
                or self._user_format != old_user_format
                or self._jpeg_quality != jpeg_quality
            ):
                raise RuntimeError("Image changed during format preparation.")
            if value == "jpeg" and has_alpha:
                warnings.warn(
                    "Converting RGBA image to JPEG will discard the alpha channel.",
                    stacklevel=2,
                )
            props = cast(GuiImageProps, self._impl.props)
            old_format = props._format
            old_data = props._data
            self._user_format = value
            props._format = resolved_format
            props._data = data
            try:
                with gui_api._gui_resource_transaction_locked(
                    self._impl.uuid, self._impl.value, props
                ):
                    gui_api._websock_interface.queue_message_or_raise(
                        GuiUpdateMessage(
                            self._impl.uuid,
                            {"_format": resolved_format, "_data": data},
                        )
                    )
            except BaseException:
                self._user_format = old_user_format
                props._format = old_format
                props._data = old_data
                raise


@dataclasses.dataclass(frozen=True)
class CommandEvent:
    """Information associated with a command trigger from the command palette.

    Passed as input to callback functions.

    Every command trigger originates from a browser client, so ``client`` and
    ``client_id`` are always populated when a callback runs, despite being
    typed as Optional."""

    # Optional for parity with GuiEvent, which can fire server-side, and to
    # leave room for a future programmatic handle.trigger() path. The
    # dispatcher drops the event when the client can't be resolved, so
    # callbacks never observe None today.

    client: ClientHandle | None
    """Client that triggered this command."""
    client_id: int | None
    """ID of client that triggered this command."""
    target: CommandHandle
    """Command handle that was triggered."""


@dataclasses.dataclass
class _CommandHandleState:
    """Internal state for a registered command."""

    uuid: str
    gui_api: GuiApi
    props: CommandProps
    icon: IconName | None
    trigger_cb: list[Callable[[CommandEvent], None | Coroutine]] = dataclasses.field(
        default_factory=list
    )
    removed: bool = False

    @property
    def state_lock(self) -> ContextManager[object]:
        return self.gui_api._lock


class CommandHandle(AssignablePropsBase[_CommandHandleState], CommandProps):
    """Handle for a command registered in the command palette.

    Commands are shown in a command palette (Ctrl/Cmd+K, also Ctrl/Cmd+Shift+P
    on non-Firefox browsers) and can optionally be triggered via hotkeys.

    (Experimental) The command palette API may change in future releases."""

    def __init__(self, _impl: _CommandHandleState) -> None:
        super().__init__(impl=_impl)

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_impl" and hasattr(self, "_impl") and name in self._prop_hints:
            prop = getattr(type(self), name, None)
            if not (isinstance(prop, property) and prop.fset is not None):
                self.update(**{name: value})
                return
        super().__setattr__(name, value)

    def update(self, **updates: Any) -> None:
        """Atomically update command properties and hotkey invariants."""
        _reject_derived_protocol_props(updates)
        custom = [
            name
            for name in updates
            if isinstance(getattr(type(self), name, None), property)
            and getattr(type(self), name).fset is not None
        ]
        if custom:
            if len(updates) != 1:
                raise TypeError("icon must be updated separately from command properties")
            setattr(self, custom[0], updates[custom[0]])
            return
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed CommandHandle.")
            normalized: dict[str, Any] = {}
            for name, value in updates.items():
                if name not in self._prop_hints:
                    raise TypeError(f"CommandHandle.update() got an unknown property {name!r}.")
                if name == "modifier":
                    if value is not None and not isinstance(value, str):
                        raise TypeError("modifier must be a string or None")
                    value = _normalize_key_modifier(value)
                normalized[name] = self._cast_value_recursive(self._prop_hints[name], value)
            if not normalized:
                return
            candidate = dataclasses.replace(self._impl.props, **normalized)
            _validate_renderer_string(candidate.label, "command label")
            _validate_renderer_string(candidate.description, "command description", optional=True)
            if candidate.hotkey is None and candidate.modifier is not None:
                raise ValueError("modifier requires hotkey to also be set.")
            with gui_api._gui_resource_transaction_locked(
                f"command:{self._impl.uuid}", None, candidate
            ):
                gui_api._websock_interface.queue_message_or_raise(
                    CommandUpdateMessage(uuid=self._impl.uuid, updates=normalized)
                )
                self._impl.props = candidate

    @override
    def _prop_assignment_transaction(self, name: str) -> ContextManager[object]:
        del name
        return self._impl.gui_api._gui_resource_transaction_locked(
            f"command:{self._impl.uuid}", None, self._impl.props
        )

    @property
    def id(self) -> str:
        """Stable command identifier."""
        return self._impl.uuid

    def __str__(self) -> str:
        return self._impl.uuid

    @property
    def icon(self) -> IconName | None:
        """Icon displayed in the command palette."""
        if self._impl.removed:
            raise RuntimeError("Cannot read icon from a removed CommandHandle.")
        return self._impl.icon

    @icon.setter
    @_locked_gui_handle_method
    def icon(self, icon: IconName | None) -> None:
        # Removed-guard enforced upstream by AssignablePropsBase.__setattr__.
        icon_html = None if icon is None else svg_from_icon(icon)
        old_icon = self._impl.icon
        old_html = self._impl.props._icon_html
        self._impl.icon = icon
        self._impl.props._icon_html = icon_html
        try:
            with self._impl.gui_api._gui_resource_transaction_locked(
                f"command:{self._impl.uuid}", None, self._impl.props
            ):
                self._queue_update("_icon_html", icon_html)
        except BaseException:
            self._impl.icon = old_icon
            self._impl.props._icon_html = old_html
            raise

    def _queue_update(self, name: str, value: Any) -> None:
        self._impl.gui_api._websock_interface.queue_message_or_raise(
            CommandUpdateMessage(uuid=self._impl.uuid, updates={name: value})
        )

    def on_trigger(
        self, func: Callable[[CommandEvent], NoneOrCoroutine]
    ) -> Callable[[CommandEvent], NoneOrCoroutine]:
        """Attach a function to call when this command is triggered.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        if not callable(func):
            raise TypeError("trigger callback must be callable")
        with self._impl.gui_api._lock:
            if self._impl.removed:
                raise RuntimeError("Cannot attach a trigger callback to a removed CommandHandle.")
            if len(self._impl.trigger_cb) >= _GUI_CALLBACK_MAX:
                raise RuntimeError(f"A command cannot own more than {_GUI_CALLBACK_MAX} callbacks.")
            self._impl.trigger_cb.append(func)
        return func

    def _retire_without_queue_locked(self) -> None:
        """Release a command after removal admission or scope retirement."""
        if self._impl.removed:
            return
        gui_api = self._impl.gui_api
        self._impl.removed = True
        self._impl.trigger_cb.clear()
        self._impl.icon = None
        _scrub_dataclass_payload(self._impl.props)
        gui_api._command_handle_from_uuid.pop(self._impl.uuid, None)
        gui_api._release_gui_resource_locked(f"command:{self._impl.uuid}")

    def remove(self) -> None:
        """Remove this command from the command palette."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                warnings.warn(
                    "Attempted to remove an already removed CommandHandle.",
                    stacklevel=2,
                )
                return
            gui_api._websock_interface.queue_message_or_raise(RemoveCommandMessage(self._impl.uuid))
            self._retire_without_queue_locked()
