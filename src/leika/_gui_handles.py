"""GUI handles: synchronized state, validation, callbacks and removal.

Every handle keeps its state in one ``_GuiHandleState``. A change goes through
one path: the handle's ``_validate`` normalizes a candidate state, the change is
queued as one message, and only then is the state committed, so a failed queue
leaves the handle unchanged.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import inspect
import math
import numbers
import time
import uuid as uuid_module
import warnings
from collections.abc import Coroutine, Iterator, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Generic,
    Literal,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

import numpy as np
from typing_extensions import Self, override

from . import _messages
from ._async_errors import callback_result_is_awaitable, print_async_exception
from ._file_preview import iter_preview_text
from ._file_transfer import validate_file_display_name
from ._icons import svg_from_icon
from ._icons_enum import IconName
from ._image_encoding import _validate_image_encoding_options, prepare_image
from ._markdown import _link_markdown_assets
from ._messages import (
    ButtonColor,
    CommandProps,
    CommandUpdateMessage,
    FileDisposition,
    GuiButtonGroupProps,
    GuiButtonProps,
    GuiCheckboxProps,
    GuiCloseModalMessage,
    GuiColorProps,
    GuiDividerProps,
    GuiDropdownProps,
    GuiFolderProps,
    GuiFormProps,
    GuiFormSubmitMessage,
    GuiHtmlProps,
    GuiImageProps,
    GuiListProps,
    GuiModalMessage,
    GuiMultiSliderProps,
    GuiNumberProps,
    GuiPlaybackProps,
    GuiPlotlyProps,
    GuiPreviewImageMessage,
    GuiPreviewOpenMessage,
    GuiPreviewReadyMessage,
    GuiPreviewTextMessage,
    GuiProgressBarProps,
    GuiRemoveMessage,
    GuiSliderMark,
    GuiSliderProps,
    GuiTabGroupProps,
    GuiTabMessage,
    GuiTabProps,
    GuiTabUpdateMessage,
    GuiTextProps,
    GuiToggleGroupProps,
    GuiUpdateMessage,
    GuiUploadButtonProps,
    GuiVectorProps,
    GuiVideoControlsProps,
    Message,
    PlaybackAction,
    RemoveCommandMessage,
    _normalize_key_modifier,
)
from ._plotly import plotly_figure, plotly_json
from ._transport._websocket import ClientId
from ._validation import validate_finite_number as _finite_number
from ._validation import validate_layout_id
from ._validation import validate_positive_number as _positive_number

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from ._client_handle import ClientHandle
    from ._gui_api import GuiApi


T = TypeVar("T")
TGuiHandle = TypeVar("TGuiHandle", bound="_GuiHandle")
NoneOrCoroutine = TypeVar("NoneOrCoroutine", None, Coroutine)

MARKDOWN_RENDER_MAX_BYTES = 1024 * 1024
"""The bundled browser's Markdown render limit, which previews are measured against."""


def _make_uuid() -> str:
    """Return a unique ID for referencing GUI elements."""
    return str(uuid_module.uuid4())


@functools.cache
def _field_names(props_type: type) -> frozenset[str]:
    return frozenset(field.name for field in dataclasses.fields(props_type))


def _strings(values: Any, name: str) -> tuple[str, ...]:
    """A sequence of strings, refusing one string where several were meant."""
    if isinstance(values, str):
        raise ValueError(f"{name} must be a sequence of strings, not one string.")
    strings = tuple(values)
    for item in strings:
        if not isinstance(item, str):
            raise TypeError(f"{name} must contain only strings; got {item!r}.")
    return strings


def _options(values: Any, name: str) -> tuple[str, ...]:
    """Labels used as both display text and stable values."""
    options = _strings(values, f"{name} options")
    if not options:
        raise ValueError(f"{name} requires at least one option.")
    if len(set(options)) != len(options):
        raise ValueError(f"{name} options must be unique.")
    return options


def _option(options: tuple[str, ...], value: Any, name: str) -> str:
    """The declared option equal to ``value``."""
    option = next((option for option in options if option == value), None)
    if option is None:
        raise ValueError(f"{name} value must be one of {options!r}; got {value!r}.")
    return option


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} value must be a bool; got {value!r}.")
    return value


def _role(color: Any) -> ButtonColor:
    if type(color) is not str or color not in ("default", "inverse"):
        raise ValueError(
            f"Button color must be 'default' or 'inverse', not {color!r}. Buttons take"
            " a role rather than a color; the accent itself is a viewer setting."
        )
    return cast(ButtonColor, color)


def _roles(count: int, color: Any) -> tuple[ButtonColor, ...]:
    """One role per button: a single role answers for the whole row."""
    if isinstance(color, str):
        return (_role(color),) * count
    colors: tuple[ButtonColor, ...] = tuple(_role(one) for one in color)
    if len(colors) != count:
        raise ValueError(
            f"color= takes one role per option: {count} for this row, but got {len(colors)}."
        )
    return colors


def _merge_flags(count: int, merge: Any) -> tuple[bool, ...]:
    """One flag per gap between buttons: a single bool answers for every gap."""
    gaps = max(0, count - 1)
    if isinstance(merge, bool):
        return (merge,) * gaps
    flags = tuple(merge)
    if any(type(flag) is not bool for flag in flags):
        raise TypeError("merge= sequence entries must be bools.")
    if len(flags) != gaps:
        raise ValueError(
            f"merge= takes one flag per gap between options: {gaps} for {count}, but got"
            f" {len(flags)}."
        )
    return flags


def _slider_marks(marks: Any) -> tuple[GuiSliderMark, ...] | None:
    """Marks as values, (value, label) pairs, or GuiSliderMark records."""
    if marks is None:
        return None
    normalized: list[GuiSliderMark] = []
    for mark in marks:
        if isinstance(mark, GuiSliderMark):
            value, label = mark.value, mark.label
        elif isinstance(mark, tuple):
            if len(mark) != 2:
                raise ValueError("slider mark tuples must contain a value and a label.")
            value, label = mark
        else:
            value, label = mark, None
        if label is not None and not isinstance(label, str):
            raise TypeError("slider mark labels must be strings.")
        normalized.append(GuiSliderMark(float(_finite_number(value, "slider mark value")), label))
    return tuple(normalized)


def _vector(value: Any, length: int, name: str = "value") -> tuple[float, ...]:
    """A fixed-length vector of finite reals, from a sequence or a 1-D array."""
    if isinstance(value, (str, bytes)) or (isinstance(value, np.ndarray) and value.ndim != 1):
        raise ValueError(f"{name} must be a vector of {length} numbers.")
    components = tuple(value)
    if len(components) != length:
        raise ValueError(f"{name} must have {length} components, got {len(components)}.")
    vector: list[float] = []
    for component in components:
        if isinstance(component, (bool, np.bool_)) or not isinstance(component, numbers.Real):
            raise TypeError(f"{name} components must be real numbers; got {component!r}.")
        if not math.isfinite(component):
            raise ValueError(f"{name} components must be finite.")
        vector.append(float(component))
    return tuple(vector)


def _color(value: Any, channels: int) -> tuple[int, ...]:
    """Color channels: integers in [0, 255], or floats in [0, 1] scaled to match."""
    if isinstance(value, (str, bytes)):
        raise TypeError("Color values must be a sequence of numeric channels.")
    components = tuple(value)
    if len(components) != channels:
        raise ValueError(f"Expected {channels} color channels, got {len(components)}.")
    color: list[int] = []
    for channel in components:
        if isinstance(channel, (bool, np.bool_)) or not isinstance(channel, numbers.Real):
            raise TypeError("Color channels must be integers or floats.")
        scaled = float(channel)
        if isinstance(channel, (float, np.floating)):
            if not math.isfinite(scaled):
                raise ValueError("Color channels must be finite.")
            scaled *= 255
        color.append(max(0, min(255, int(scaled))))
    return tuple(color)


@dataclasses.dataclass
class _GuiHandleState(Generic[T]):
    """One handle's synchronized state. Commits replace ``props`` wholesale, so
    a read never sees half of an update."""

    uuid: str
    gui_api: GuiApi
    props: Any
    """The handle's wire props, or None for a handle without any."""
    value: T
    parent_container_id: str | None
    """Container this handle is placed in; None outside the GUI tree (modals,
    commands and notifications)."""
    icon: IconName | None = None
    initial_value: Any = None
    """The value a field was declared with, which a form reset restores; None
    for handles that are not fields."""
    update_timestamp: float = 0.0
    callbacks: list[Callable[..., Any]] = dataclasses.field(default_factory=list)
    children: dict[str, _GuiHandle[Any]] = dataclasses.field(default_factory=dict)
    """Contained handles in creation order: a container's elements, a tab
    group's tabs."""
    removed: bool = False


@dataclasses.dataclass(frozen=True)
class _Change:
    """A validated candidate state and the wire fields it changes."""

    props: Any
    value: Any
    icon: IconName | None
    updates: dict[str, Any]
    value_set: bool
    """Whether this change assigns the value: it changed, or a button was pressed."""


class _GuiHandle(Generic[T]):
    """Base of every handle: identity, synchronized props, callbacks and retirement."""

    _impl: _GuiHandleState[T]
    _message_type: ClassVar[type[Message]]
    _is_button: ClassVar[bool] = False
    """Whether the value is a press: never synchronized, and reported every time."""

    # Identity, not the props dataclass's field-wise equality.
    __eq__ = object.__eq__
    __hash__ = object.__hash__

    def __init__(self, impl: _GuiHandleState[T]) -> None:
        object.__setattr__(self, "_impl", impl)

    @property
    def id(self) -> str:
        """Stable identifier for this handle."""
        return self._impl.uuid

    def __getattr__(self, name: str) -> Any:
        props = getattr(self.__dict__.get("_impl"), "props", None)
        if props is not None and name in _field_names(type(props)):
            return getattr(props, name)
        raise AttributeError(f"{type(self).__name__} has no attribute {name!r}.")

    def __setattr__(self, name: str, value: Any) -> None:
        if isinstance(getattr(type(self), name, None), property):
            object.__setattr__(self, name, value)
        elif not name.startswith("_"):
            self.update(**{name: value})
        else:
            props = self.__dict__["_impl"].props
            if props is not None and name in _field_names(type(props)):
                raise AttributeError(f"{name!r} is derived internal state.")
            object.__setattr__(self, name, value)

    def update(self, **changes: Any) -> None:
        """Validate and publish one or more properties together.

        The browser receives them in one message, and Python commits them only
        once that message is queued.
        """
        props = self._impl.props
        fields = frozenset() if props is None else _field_names(type(props))
        names = {name for name in fields if not name.startswith("_")}
        if isinstance(self, GuiInputHandle):
            names.add("value")
        if "_icon_html" in fields:
            names.add("icon")
        unknown = sorted(set(changes) - names)
        if unknown:
            raise TypeError(f"{type(self).__name__} has no settable property {unknown[0]!r}.")
        self._update(changes)

    def _update(self, changes: dict[str, Any]) -> None:
        """Publish a change, including derived private props, then run value callbacks."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            change = self._prepare(changes)
            if change is None:
                return
            self._commit(change)
            if not change.value_set or not self._impl.callbacks:
                return
            callbacks = tuple(self._impl.callbacks)
        gui_api._schedule_callbacks(callbacks, GuiEvent(None, None, self, change.value))

    def _prepare(self, changes: dict[str, Any]) -> _Change | None:
        """Validate a candidate state; None when it would change nothing."""
        self._check_live()
        changes = dict(changes)
        # `value` is an input's own state; other handles may have a `value` prop.
        value_given = isinstance(self, GuiInputHandle) and "value" in changes
        value = changes.pop("value") if value_given else self._impl.value
        icon = self._impl.icon
        if "icon" in changes:
            icon = changes.pop("icon")
            changes["_icon_html"] = None if icon is None else svg_from_icon(icon)
        old = self._impl.props
        props = dataclasses.replace(old, **changes) if changes else old
        props, value = self._validate(props, value)
        updates: dict[str, Any] = {}
        if props is not None:
            _messages.check_wire_types(props)
            updates = {
                field.name: getattr(props, field.name)
                for field in dataclasses.fields(props)
                if getattr(props, field.name) != getattr(old, field.name)
            }
        value_changed = value != self._impl.value
        if value_changed and not self._is_button:
            updates["value"] = value
        value_set = value_changed or (value_given and self._is_button)
        if not updates and not value_set:
            return None
        return _Change(props, value, icon, updates, value_set)

    def _validate(self, props: Any, value: T) -> tuple[Any, T]:
        """Check and normalize a candidate state; each component has one of these."""
        return props, value

    def _commit(self, change: _Change, exclude_client: ClientId | None = None) -> None:
        """Queue a validated change, then apply it."""
        if change.updates:
            message = self._update_message(change.updates, change.props)
            message.excluded_self_client = exclude_client
            self._impl.gui_api._websock_interface.queue_message_or_raise(message)
        self._apply(change)

    def _apply(self, change: _Change) -> None:
        impl = self._impl
        impl.props, impl.value, impl.icon = change.props, change.value, change.icon
        if change.value_set:
            impl.update_timestamp = time.time()

    def _create_message(self) -> Message:
        impl = self._impl
        fields = _field_names(self._message_type)
        arguments: dict[str, Any] = {"uuid": impl.uuid, "props": impl.props}
        if "container_uuid" in fields:
            arguments["container_uuid"] = impl.parent_container_id
        if "value" in fields:
            arguments["value"] = impl.value
        return self._message_type(**arguments)

    def _update_message(self, updates: dict[str, Any], props: Any) -> Message:
        del props
        return GuiUpdateMessage(self._impl.uuid, updates)

    def _removal_message(self) -> Message:
        return GuiRemoveMessage(self._impl.uuid, tuple(child.id for child in self._descendants()))

    def _descendants(self) -> Iterator[_GuiHandle[Any]]:
        for child in self._impl.children.values():
            yield child
            yield from child._descendants()

    def _remove(self) -> None:
        """Remove this handle and everything inside it, for every browser."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            if self._impl.removed:
                warnings.warn(
                    f"Attempted to remove an already removed {type(self).__name__}.",
                    stacklevel=3,
                )
                return
            gui_api._websock_interface.queue_message_or_raise(self._removal_message())
            self._retire()

    def _retire(self) -> None:
        """Mark this subtree removed and unregister it, without messages."""
        for child in tuple(self._impl.children.values()):
            child._retire()
        self._impl.removed = True
        self._impl.gui_api._unregister(self)

    def _check_live(self) -> None:
        if self._impl.removed:
            raise RuntimeError(f"Cannot update a removed {type(self).__name__}.")

    def _add_callback(self, func: Any) -> Any:
        if not callable(func):
            raise TypeError("callback must be callable")
        with self._impl.gui_api._lock:
            self._check_live()
            self._impl.callbacks.append(func)
        return func

    def _remove_callback(self, callback: Literal["all"] | Callable[..., Any] = "all") -> None:
        with self._impl.gui_api._lock:
            if callback == "all":
                self._impl.callbacks.clear()
            else:
                self._impl.callbacks[:] = [cb for cb in self._impl.callbacks if cb != callback]


class _HasIcon:
    """An element showing an icon, set by name."""

    _impl: _GuiHandleState[Any]

    @property
    def icon(self) -> IconName | None:
        """Icon to display. When set to None, no icon is displayed."""
        return self._impl.icon

    @icon.setter
    def icon(self, icon: IconName | None) -> None:
        cast(_GuiHandle[Any], self).update(icon=icon)


class _Removable(_GuiHandle[T]):
    def remove(self) -> None:
        """Permanently remove this element, and everything inside it.

        Removal is terminal: later updates and callback registrations raise
        ``RuntimeError``, while reads return the last state.
        """
        self._remove()


class GuiContainer(_GuiHandle[None]):
    """A handle whose ``with`` block places new GUI elements inside it.

    If the block raises, the container and everything built in it is removed,
    so a failed construction leaves no partial subtree behind.
    """

    def __enter__(self) -> Self:
        self._check_live()
        self._impl.gui_api._push_container_uuid(self.id)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        del exc_value, traceback
        self._impl.gui_api._pop_container_uuid()
        if exc_type is not None and not self._impl.removed:
            try:
                self._remove()
            except Exception as cleanup_error:
                # Preserve the caller's original exception.
                print_async_exception(cleanup_error)


class GuiInputHandle(_Removable[T], Generic[T]):
    """A handle is created for each GUI element that is added in `Leika`.
    Handles can be used to read and write state.

    When a GUI element is added via :attr:`Server.gui`, state is
    synchronized between all connected clients. When a GUI element is added via
    :attr:`ClientHandle.gui`, state is local to a specific client.
    """

    @property
    def value(self) -> T:
        """Value of the GUI input. Synchronized automatically when assigned.

        :meta private:
        """
        # Private for Sphinx, which cannot resolve the TypeVar readably; the
        # docs declare these attributes manually instead.
        return self._impl.value

    @value.setter
    def value(self, value: T) -> None:
        self.update(value=value)

    @property
    def update_timestamp(self) -> float:
        """Read-only timestamp when this input was last updated."""
        return self._impl.update_timestamp

    def on_update(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a GUI input is updated.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        return self._add_callback(func)

    def remove_update_callback(self, callback: Literal["all"] | Callable = "all") -> None:
        """Remove update callbacks from the GUI input.

        Args:
            callback: Either "all" to remove all callbacks, or a specific callback function to remove.
        """
        self._remove_callback(callback)

    def _accepts_input(self) -> bool:
        """Whether a browser may change this input now."""
        props = self._impl.props
        return (
            not self._impl.removed
            and props.visible
            and not props.disabled
            and getattr(props, "editable", True)
        )

    def _client_value(self, value: Any) -> Any:
        """A browser's value, before the validation every value goes through.

        A sequence-valued control takes only an array from the browser, never
        another iterable such as a mapping's keys."""
        if isinstance(self._impl.value, tuple) and type(value) is not list:
            raise TypeError("This control takes an array from the browser.")
        return value

    def _is_field(self) -> bool:
        """Whether this input holds an answer a form can reset."""
        return not self._is_button and getattr(self._impl.props, "editable", True)


class GuiCheckboxHandle(GuiInputHandle[bool], GuiCheckboxProps):
    """Handle for checkbox inputs.

    .. attribute:: value
       :type: bool

       Value of the input. Synchronized automatically when assigned.
    """

    _message_type = _messages.GuiCheckboxMessage

    @override
    def _validate(self, props: Any, value: bool) -> tuple[Any, bool]:
        return props, _bool(value, "checkbox")


class GuiToggleGroupHandle(GuiInputHandle[Tuple[str, ...]], GuiToggleGroupProps):
    """Handle for a row of toggles.

    .. attribute:: value
       :type: tuple[str, ...]

       The options currently on, in the order they were declared. A tuple in
       both modes, so reading a group does not depend on how it was
       configured: with ``multiple=False`` it simply never holds more than one.
       Assigning turns exactly those options on and the rest off; one option's
       text names that option alone.
    """

    _message_type = _messages.GuiToggleGroupMessage

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, tuple[str, ...]]:
        options = _options(props.options, "Toggle")
        props = dataclasses.replace(
            props,
            options=options,
            color=_roles(len(options), props.color),
            merge=_merge_flags(len(options), props.merge),
        )
        wanted = (value,) if isinstance(value, str) else _strings(value, "Toggle value")
        unknown = [option for option in wanted if option not in options]
        if unknown:
            raise ValueError(f"Unknown toggle option(s) {unknown!r}; options are {options!r}.")
        if len(set(wanted)) != len(wanted):
            raise ValueError("A toggle group value cannot repeat an option.")
        if not props.multiple and len(wanted) > 1:
            raise ValueError(
                f"{wanted!r} turns on {len(wanted)} options, but this row holds one at a"
                " time. Pass multiple=True to allow several."
            )
        if props.required and not wanted:
            raise ValueError("A required row of toggles cannot be empty.")
        return props, tuple(option for option in options if option in wanted)


def _list_rows(value: Any, mark: Any) -> Any:
    """A list's rows: strings without a mark, ``(text, marked)`` pairs with one.

    A bare string is an unmarked row; without a mark, a pair keeps its text.
    """
    if mark not in (None, "check", "radio"):
        raise ValueError(f"mark must be None, 'check', or 'radio'; got {mark!r}.")
    if isinstance(value, str):
        raise ValueError("A list value must be a sequence of rows, not one string.")
    rows: list[Tuple[str, bool]] = []
    for row in value:
        if isinstance(row, str):
            rows.append((row, False))
            continue
        try:
            text, marked = row
        except (TypeError, ValueError):
            raise ValueError(f"Rows are strings or (text, bool) pairs; got {row!r}.") from None
        if not isinstance(text, str) or type(marked) is not bool:
            raise TypeError(f"Rows are strings or (text, bool) pairs; got {row!r}.")
        rows.append((text, marked))
    if mark is None:
        return tuple(text for text, _ in rows)
    if mark == "radio" and sum(marked for _, marked in rows) > 1:
        raise ValueError("A radio list can have at most one selected row.")
    return tuple(rows)


TRows = TypeVar("TRows", Tuple[str, ...], Tuple[Tuple[str, bool], ...])


class GuiListHandle(GuiInputHandle[TRows], Generic[TRows], GuiListProps):
    """Handle for an editable list of text rows, each optionally with a mark.

    .. attribute:: value
       :type: tuple[str, ...] | tuple[tuple[str, bool], ...]

       Without a mark, the entries in the order they are shown. With a mark,
       one ``(text, marked)`` pair per row, so ``for text, checked in
       handle.value`` reads a checklist as it stands. Editing a row, adding
       one, removing one, or dragging one somewhere else reports the whole
       tuple, and a row's mark travels with its text. Assigning sets the list
       to exactly those rows, which is how Python adds, removes and reorders:
       ``handle.value += ("next",)``. With a mark, a bare string among them is
       an unmarked row.
    """

    _message_type = _messages.GuiListMessage

    @property
    def marked(self) -> Tuple[str, ...]:
        """The text of the marked rows, in the order they are shown.

        For a checklist these are the ticked items; for a radio list, the one
        selected choice, if any."""
        if self._impl.props.mark is None:
            return ()
        return tuple(text for text, marked in self._impl.value if marked)

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, Any]:
        return props, _list_rows(value, props.mark)

    @override
    def _client_value(self, value: Any) -> Any:
        props = self._impl.props
        rows = _list_rows(super()._client_value(value), props.mark)
        current = self._impl.value
        if props.frozen and (
            len(rows) != len(current)
            or (props.mark is not None and [t for t, _ in rows] != [t for t, _ in current])
        ):
            raise ValueError("A frozen list keeps its rows' count and order.")
        return rows


class GuiTextHandle(GuiInputHandle[str], GuiTextProps):
    """Handle for text, editable or read-only.

    .. attribute:: value
       :type: str

       The text itself, whether it is being edited or only read. Synchronized
       automatically when assigned.
    """

    _message_type = _messages.GuiTextMessage
    _image_root: Path | None

    @override
    def _validate(self, props: Any, value: str) -> tuple[Any, str]:
        if type(value) is not str:
            raise TypeError(f"Text value must be a string; got {value!r}.")
        if props.markdown and props.editable:
            raise ValueError("markdown text must be read-only (editable=False).")
        if props.rows is not None and (type(props.rows) is not int or props.rows < 1):
            raise ValueError("rows= is a height in lines and must be a positive integer or None.")
        # Rendered Markdown points its relative images at server URLs; other
        # text shows its value and needs no second copy. Linking reads every
        # image, so it runs only when what is rendered changes.
        old = self._impl.props
        if not props.markdown:
            source = ""
        elif old.markdown and old._source and value == self._impl.value:
            source = old._source
        elif self._image_root is None:
            source = value
        else:
            server = self._impl.gui_api._server
            source = _link_markdown_assets(value, self._image_root, server._register_http_image)
        return dataclasses.replace(props, _source=source), value


IntOrFloat = TypeVar("IntOrFloat", int, float)


class GuiNumberHandle(GuiInputHandle[IntOrFloat], Generic[IntOrFloat], GuiNumberProps):
    """Handle for number inputs.

    .. attribute:: value
       :type: IntOrFloat

       Value of the input. Synchronized automatically when assigned.
    """

    _message_type = _messages.GuiNumberMessage

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, Any]:
        value = type(self._impl.value)(_finite_number(value))
        _positive_number(props.step, "step")
        if props.min is not None and props.max is not None and props.min > props.max:
            raise ValueError(f"max= must be at least min=; got {props.min} > {props.max}.")
        if props.min is not None and value < props.min:
            raise ValueError(f"value {value} is below min={props.min}.")
        if props.max is not None and value > props.max:
            raise ValueError(f"value {value} is above max={props.max}.")
        return props, value


def _check_slider_range(props: Any) -> Any:
    """Check a slider's range, clamp its step to the range, and normalize its marks."""
    step = _positive_number(props.step, "step")
    if _finite_number(props.min, "min") > _finite_number(props.max, "max"):
        raise ValueError(f"max= must be at least min=; got {props.min} > {props.max}.")
    if props.max > props.min:
        step = min(step, props.max - props.min)
    return dataclasses.replace(props, step=step, marks=_slider_marks(props.marks))


class GuiSliderHandle(GuiInputHandle[IntOrFloat], Generic[IntOrFloat], GuiSliderProps):
    """Handle for slider inputs.

    .. attribute:: value
       :type: IntOrFloat

       Value of the input. Synchronized automatically when assigned.
    """

    _message_type = _messages.GuiSliderMessage

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, Any]:
        props = _check_slider_range(props)
        value = type(self._impl.value)(_finite_number(value))
        if not props.min <= value <= props.max:
            raise ValueError(f"value {value} is outside [{props.min}, {props.max}].")
        return props, value


class GuiMultiSliderHandle(
    GuiInputHandle[Tuple[IntOrFloat, ...]], Generic[IntOrFloat], GuiMultiSliderProps
):
    """Handle for multi-slider inputs.

    .. attribute:: value
       :type: tuple[IntOrFloat, ...]

       Value of the input. Synchronized automatically when assigned.
    """

    _message_type = _messages.GuiMultiSliderMessage

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, Any]:
        props = _check_slider_range(props)
        if isinstance(value, (str, bytes)):
            raise ValueError("value must be a sequence of numbers.")
        number = type(self._impl.value[0]) if self._impl.value else float
        values = tuple(number(_finite_number(item, "value entries")) for item in value)
        if not values:
            raise ValueError("value must contain at least one slider value.")
        if any(not props.min <= item <= props.max for item in values):
            raise ValueError(f"value {values} has entries outside [{props.min}, {props.max}].")
        if any(left > right for left, right in zip(values, values[1:])):
            raise ValueError("value entries must be in ascending order.")
        if props.min_range is not None:
            if props.min_range < 0:
                raise ValueError("min_range must be non-negative.")
            if any(right - left < props.min_range for left, right in zip(values, values[1:])):
                raise ValueError("value entries are closer than min_range.")
        return props, values


TColor = TypeVar("TColor", bound=Tuple[int, ...])


class GuiColorHandle(GuiInputHandle[TColor], Generic[TColor], GuiColorProps):
    """Handle for color inputs, RGB or RGBA.

    .. attribute:: value
       :type: tuple[int, int, int] | tuple[int, int, int, int]

       Channels in [0, 255], as many as the color was created with.
       Synchronized automatically when assigned; float channels in [0, 1] are
       scaled to match.
    """

    _message_type = _messages.GuiColorMessage

    @override
    def _client_value(self, value: Any) -> Any:
        value = super()._client_value(value)
        if any(type(channel) is not int or not 0 <= channel <= 255 for channel in value):
            raise ValueError("A browser sends color channels as integers in [0, 255].")
        return value

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, Any]:
        channels = len(self._impl.value)
        if channels not in (3, 4):
            raise ValueError(f"A color has 3 (RGB) or 4 (RGBA) channels, got {channels}.")
        return props, _color(value, channels)


TVector = TypeVar("TVector", bound=Tuple[float, ...])


class GuiVectorHandle(GuiInputHandle[TVector], Generic[TVector], GuiVectorProps):
    """Handle for vector inputs of two or three components.

    .. attribute:: value
       :type: tuple[float, float] | tuple[float, float, float]

       Components, as many as the vector was created with. Synchronized
       automatically when assigned.
    """

    _message_type = _messages.GuiVectorMessage

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, Any]:
        length = len(self._impl.value)
        if length not in (2, 3):
            raise ValueError(f"A vector has 2 or 3 components, got {length}.")
        vector = _vector(value, length)
        low = None if props.min is None else _vector(props.min, length, "min")
        high = None if props.max is None else _vector(props.max, length, "max")
        _positive_number(props.step, "step")
        if low is not None and high is not None and any(lo > hi for lo, hi in zip(low, high)):
            raise ValueError("Each vector min component must be at most its max component.")
        if low is not None and any(item < lo for item, lo in zip(vector, low)):
            raise ValueError(f"value {vector} has a component below min={low}.")
        if high is not None and any(item > hi for item, hi in zip(vector, high)):
            raise ValueError(f"value {vector} has a component above max={high}.")
        return dataclasses.replace(props, min=low, max=high), vector


StringType = TypeVar("StringType", bound=str)


class GuiDropdownHandle(GuiInputHandle[StringType], Generic[StringType], GuiDropdownProps):
    """Handle for a dropdown-style GUI input in our visualizer.

    .. attribute:: value
       :type: StringType

       Value of the input. Represents the currently selected option in the dropdown.
    """

    _message_type = _messages.GuiDropdownMessage

    @property
    def options(self) -> tuple[StringType, ...]:
        """Options for our dropdown. Synchronized automatically when assigned.

        Assigning options without the current value selects the first option.

        For projects that care about typing: the static type of `options` should be
        consistent with the `StringType` associated with a handle. Literal types will be
        inferred where possible when handles are instantiated; for the most flexibility,
        we can declare handles as `GuiDropdownHandle[str]`.
        """
        return cast("tuple[StringType, ...]", self._impl.props.options)

    @options.setter
    def options(self, options: Sequence[StringType]) -> None:  # type: ignore[override]
        self.update(options=options)

    @override
    def _prepare(self, changes: dict[str, Any]) -> _Change | None:
        if "options" in changes and "value" not in changes:
            changes = {**changes, "value": None}
        return super()._prepare(changes)

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, Any]:
        """None keeps the current value while it is an option, else selects the first."""
        options = _options(props.options, "Dropdown")
        if value is None:
            value = self._impl.value if self._impl.value in options else options[0]
        return dataclasses.replace(props, options=options), _option(options, value, "Dropdown")


@dataclasses.dataclass(frozen=True)
class GuiEvent(Generic[TGuiHandle]):
    """Information associated with a GUI event, such as an update or click.

    Passed as input to callback functions. ``value`` is the value at the time
    of the event, not a live read from ``target``; overlapping clients therefore
    cannot change what an earlier async callback observes after it awaits.
    """

    client: ClientHandle | None
    """Client that triggered this event."""
    client_id: int | None
    """ID of client that triggered this event."""
    target: TGuiHandle
    """GUI element that was affected."""
    value: Any = dataclasses.field(default=None, repr=False)
    """Value at event creation, or None when the handle has no value."""


class GuiButtonHandle(_HasIcon, GuiInputHandle[bool], GuiButtonProps):
    """Handle for a button input in our visualizer.

    .. attribute:: value
       :type: bool

       Value of the button. Set to `True` when the button is pressed. Can be manually set back to `False`.
    """

    _message_type = _messages.GuiButtonMessage
    _is_button = True

    def __init__(self, impl: _GuiHandleState[bool]) -> None:
        super().__init__(impl)
        self._hold_callbacks: dict[float, list[Callable[..., Any]]] = {}

    @override
    def _validate(self, props: Any, value: bool) -> tuple[Any, bool]:
        _role(props.color)
        return props, _bool(value, "button")

    @override
    def _client_value(self, value: Any) -> Any:
        """A browser sends only presses, which are True."""
        if value is not True:
            raise ValueError("A browser button update must be a press.")
        return value

    def on_click(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a button is pressed.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        return self._add_callback(func)

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
                the button is held, at most 60. Defaults to 10.0 Hz.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        callback_hz = float(_positive_number(callback_hz, "callback_hz"))
        if callback_hz > 60.0:
            raise ValueError("callback_hz must be a positive number no greater than 60 Hz.")

        def register_callback(f: GuiButtonHandle._HoldCallback) -> GuiButtonHandle._HoldCallback:
            if not callable(f):
                raise TypeError("callback must be callable")
            with self._impl.gui_api._lock:
                frequencies = (*self._hold_callbacks, callback_hz)
                self._update({"_hold_callback_freqs": tuple(dict.fromkeys(frequencies))})
                self._hold_callbacks.setdefault(callback_hz, []).append(f)
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
            remaining: dict[float, list[Callable[..., Any]]] = {}
            for frequency, callbacks in self._hold_callbacks.items():
                if callback_hz is None or frequency == callback_hz:
                    callbacks = [] if callback == "all" else [c for c in callbacks if c != callback]
                if callbacks:
                    remaining[frequency] = callbacks
            self._update({"_hold_callback_freqs": tuple(remaining)})
            self._hold_callbacks = remaining


@dataclasses.dataclass(frozen=True)
class UploadedFile:
    """Result of a file upload."""

    name: str
    """Name of the file."""
    content: bytes
    """Contents of the file."""


class GuiUploadButtonHandle(_HasIcon, GuiInputHandle[UploadedFile], GuiUploadButtonProps):
    """Handle for an upload file button in our visualizer.

    The `.value` attribute will be updated with the contents of uploaded files.

    .. attribute:: value
       :type: UploadedFile

       Value of the input. Contains information about the uploaded file.
    """

    _message_type = _messages.GuiUploadButtonMessage
    _is_button = True

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, UploadedFile]:
        _role(props.color)
        if not isinstance(value, UploadedFile):
            raise TypeError("upload button value must be an UploadedFile")
        if type(value.content) is not bytes:
            raise TypeError("UploadedFile.content must be bytes")
        # An empty name is the value before any upload.
        name = validate_file_display_name(value.name) if value.name else ""
        return props, UploadedFile(name, value.content)

    def on_upload(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a file is uploaded.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        return self._add_callback(func)


FileContent = Union[bytes, Path, Callable[["GuiEvent[Any]"], Union[bytes, Path]]]
"""What a file button sends: the bytes themselves, a path to read them from, or
a synchronous function called at click time returning either."""


def _file_content(content: object, filename: str | None, factory: str) -> FileContent:
    """Check a file button's contents and name before they are used."""
    if filename is not None:
        validate_file_display_name(filename)
    if type(content) is not bytes and not isinstance(content, Path) and not callable(content):
        raise TypeError(
            "content= must be bytes, a Path, or a synchronous callable returning one of those"
        )
    call = getattr(content, "__call__", None)
    if inspect.iscoroutinefunction(content) or inspect.iscoroutinefunction(call):
        raise TypeError(
            "content providers must be synchronous callables; async providers are not supported"
        )
    if filename is None and type(content) is bytes:
        raise ValueError(
            f"filename= is required when the contents are bytes, which carry"
            f" no name of their own. Passed to {factory}."
        )
    return cast(FileContent, content)


class _GuiFileButtonHandle(GuiButtonHandle):
    """A button that hands one file to the client that pressed it.

    Subclasses say what becomes of the file; everything before that -- what to
    send, what to call it, and not sending it twice at once -- is the same
    whether the browser saves it or shows it. While the file is produced the
    button is busy, which the browser draws as disabled without touching the
    caller's own ``disabled``.
    """

    #: Named in the errors this raises, so each subclass points at the method
    #: the caller actually used.
    _factory = "add_download_button()"
    #: Completes "A <verb> of bytes has no name...".
    _noun = "download"
    _content: FileContent
    _filename: str | None

    @property
    def content(self) -> FileContent:
        """What the button sends: bytes, a path to read at click time, or a
        synchronous function of the click event returning one of those."""
        return self._content

    @content.setter
    def content(self, content: FileContent) -> None:
        with self._impl.gui_api._lock:
            self._check_live()
            self._content = _file_content(content, self._filename, self._factory)

    @property
    def filename(self) -> str | None:
        """Name the file is sent under, or None to take it from the path that
        the contents were read from."""
        return self._filename

    @filename.setter
    def filename(self, filename: str | None) -> None:
        with self._impl.gui_api._lock:
            self._check_live()
            _file_content(self._content, filename, self._factory)
            self._filename = filename

    def _resolve(self, event: GuiEvent[Any]) -> Tuple[str, bytes | Path]:
        """The name and contents to send for one press."""
        content = self._content(event) if callable(self._content) else self._content
        if callback_result_is_awaitable(content):
            close = getattr(content, "close", None)
            if callable(close):
                close()
            raise TypeError(
                "content providers must return bytes or a Path directly; async "
                "providers are not supported"
            )
        if type(content) is not bytes and not isinstance(content, Path):
            raise TypeError("content providers must return bytes or a Path")
        if self._filename is not None:
            return self._filename, content
        if isinstance(content, Path):
            return validate_file_display_name(content.name), content
        # Bytes name nothing. Raised at press time because a callable's return
        # type is only known once it has run.
        raise ValueError(
            f"A {self._noun} of bytes has no name to save under; pass filename="
            f" to {self._factory}, or return a Path to take the name from."
        )

    def _finish_press(self) -> None:
        with self._impl.gui_api._lock:
            if not self._impl.removed and self._impl.props._busy:
                self._update({"_busy": False})


class GuiDownloadButtonHandle(_GuiFileButtonHandle):
    """Handle for a download button in our visualizer.

    A button that sends a file to the client that pressed it. The press is an
    ordinary one -- the handle is a :class:`GuiButtonHandle`, and `on_click`
    still works -- so what this adds is the sending: the file goes to the one
    client that asked for it rather than to every connected browser, the
    browser saves it on arrival, and the button stays busy while the contents
    are produced, so a slow export cannot be started twice over.

    .. attribute:: value
       :type: bool

       Value of the button. Set to `True` when the button is pressed. Can be manually set back to `False`.
    """

    def _send(self, event: GuiEvent[Any]) -> None:
        """Send the file to whoever pressed, then release the busy state."""
        try:
            if event.client is not None:
                filename, content = self._resolve(event)
                # A press is already the ask, so the file saves rather than
                # arriving as a link to press again.
                event.client.send_file_download(filename, content, save_immediately=True)
        finally:
            self._finish_press()


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
    _max_bytes: int

    def _send_text_stream(
        self, client: ClientHandle, filename: str, content: bytes | Path, version: str | None
    ) -> str | None:
        filename = validate_file_display_name(filename)
        stream_uuid = f"{self._impl.uuid}:{version}" if version is not None else _make_uuid()
        for mime, size, index, text, done in iter_preview_text(filename, content, self._max_bytes):
            queued = client._websock_connection.queue_message(
                GuiPreviewTextMessage(
                    self._impl.uuid,
                    filename,
                    mime,
                    size,
                    text,
                    stream_uuid,
                    version,
                    index,
                    done,
                )
            )
            if queued is False:
                return None
            client.flush()
        return stream_uuid

    def _prepared(
        self,
        client: ClientHandle,
        filename: str,
        content: bytes | Path,
        stream_uuid: str | None = None,
    ) -> bytes | Path:
        """The contents as the browser should receive them.

        A path-backed document knows where its relative images live, but the
        browser receives it as an isolated blob with no base URL to resolve
        them against. Each image is registered with the server instead and the
        document keeps only its URL, so the text arrives on its own and the
        browser fills the figures in as they load. Bytes have no corresponding
        directory and are left exactly as the caller supplied them.
        """
        if not isinstance(content, Path) or Path(filename).suffix.lower() not in (
            ".md",
            ".markdown",
        ):
            return content
        limit = min(self._max_bytes, MARKDOWN_RENDER_MAX_BYTES)
        with open(content, "rb") as file:
            payload = file.read(limit + 1)
        if len(payload) > limit:
            return content
        published_images = 0

        def image_ready(source: str, url: str) -> None:
            nonlocal published_images
            # The browser retains at most 128 early resolutions per stream.
            # Remaining figures still arrive through the completed document.
            if published_images >= 128:
                return
            published_images += 1
            assert stream_uuid is not None
            client._websock_connection.queue_message(
                GuiPreviewImageMessage(self._impl.uuid, stream_uuid, source, url)
            )
            client.flush()

        linked = _link_markdown_assets(
            payload.decode("utf-8", errors="replace"),
            content.parent,
            client._server._register_http_image,
            image_ready if stream_uuid is not None else None,
        ).encode("utf-8")
        return linked if len(linked) <= MARKDOWN_RENDER_MAX_BYTES else content

    def _version(self) -> str | None:
        """What the watched file is right now, as a stamp to compare against.

        Modification time and size together: the pair a build, an editor's
        save and an append all move. ``None`` for contents that are not a path,
        and for a file that has gone missing -- a preview of a file being
        rewritten in place should not blink out and back.
        """
        if not isinstance(self._content, Path):
            return None
        try:
            stat = self._content.stat()
        except OSError:
            return None
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    def _show(
        self,
        client: ClientHandle,
        filename: str,
        content: bytes | Path,
        disposition: FileDisposition,
        *,
        request_uuid: str | None = None,
        cached_key: str | None = None,
    ) -> None:
        """Send one file to one client's dialog, opening it or refilling it.

        The version is read *before* the contents, so a file written to while
        this is sending is left looking newer than what went out, and the next
        watch sends it again.
        """
        version = self._version()
        stream_uuid = None
        if disposition == "preview" and cached_key is None:
            stream_uuid = self._send_text_stream(client, filename, content, version)
        prepared = self._prepared(client, filename, content, stream_uuid)
        # Hash the prepared Markdown, including its immutable image URLs. Only
        # identical output may reuse a browser copy.
        cache_key = None
        if (
            isinstance(prepared, bytes)
            and len(prepared) <= MARKDOWN_RENDER_MAX_BYTES
            and Path(filename).suffix.lower() in (".md", ".markdown")
        ):
            cache_key = hashlib.sha256(filename.encode() + b"\0" + prepared).hexdigest()
        reused = cached_key is not None and cached_key == cache_key
        client._websock_connection.queue_message(
            GuiPreviewReadyMessage(self._impl.uuid, request_uuid, cache_key, version, reused)
        )
        if reused:
            client.flush()
            return
        if disposition == "preview" and cached_key is not None:
            self._send_text_stream(client, filename, content, version)
        client._send_preview(
            filename,
            prepared,
            max_bytes=self._max_bytes,
            disposition=disposition,
            source_uuid=self._impl.uuid,
            source_version=version,
        )

    def _send(self, event: GuiEvent[Any], request: GuiPreviewOpenMessage | None = None) -> None:
        """Show the file for one press, revalidating a document the browser kept."""
        if event.client is None:
            return
        filename, content = self._resolve(event)
        self._show(
            event.client,
            filename,
            content,
            "preview",
            request_uuid=None if request is None else request.request_uuid,
            cached_key=None if request is None else request.cached_key,
        )

    def _reload(self, event: GuiEvent[Any]) -> None:
        """Send the file again because the reader asked, resolving it the way a
        press does, and land it in the dialog that is already open."""
        if event.client is None:
            return
        filename, content = self._resolve(event)
        self._show(event.client, filename, content, "reload")

    def _watch(self, client: ClientHandle, version: str | None) -> None:
        """Send the file again if it is no longer what the reader is holding.

        Advisory and quiet: an unwatchable source, an unchanged file, or one
        grown past the limit is a return, because nobody asked.
        """
        current = self._version()
        if current is None or current == version or not isinstance(self._content, Path):
            return
        path = self._content
        try:
            filename = self._filename or validate_file_display_name(path.name)
            if path.stat().st_size > self._max_bytes:
                return
            self._show(client, filename, path, "reload")
        except (OSError, ValueError):
            # Read out from under us between the stat and the send; the next
            # watch will find it.
            return

    def _warm(self, client: ClientHandle) -> None:
        """Begin the press's transfer before the press, held rather than shown.

        Only a path warms: a callable is the caller's code, run on a press, and
        bytes have no stable revision to address a warmed copy by.
        """
        content = self._content
        if not isinstance(content, Path):
            return
        try:
            filename = self._filename or validate_file_display_name(content.name)
            version = self._version()
            stream_uuid = self._send_text_stream(client, filename, content, version)
            prepared = self._prepared(client, filename, content, stream_uuid)
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
            # An unreadable file warms nothing; a press will say so.
            return


class GuiButtonGroupHandle(GuiInputHandle[str], GuiButtonGroupProps):
    """Handle for a button group input in our visualizer.

    .. attribute:: value
       :type: str

       Value of the input. Represents the currently selected button in the group.
    """

    _message_type = _messages.GuiButtonGroupMessage
    _is_button = True

    def on_click(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a button in the group is clicked.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        return self._add_callback(func)

    @override
    def _validate(self, props: Any, value: Any) -> tuple[Any, str]:
        options = _options(props.options, "Button")
        props = dataclasses.replace(
            props,
            options=options,
            color=_roles(len(options), props.color),
            merge=_merge_flags(len(options), props.merge),
        )
        return props, _option(options, value, "Button")


class GuiTabGroupHandle(_Removable[None], GuiTabGroupProps):
    """Handle for a tab group. Call :meth:`add_tab()` to add a tab."""

    _message_type = _messages.GuiTabGroupMessage

    def add_tab(self, label: str, icon: IconName | None = None) -> GuiTabHandle:
        """Add a tab. Returns a handle we can use to add GUI elements to it."""
        return self._impl.gui_api._add(
            GuiTabHandle, GuiTabProps(label=label, _icon_html=None), parent=self.id, icon=icon
        )


class GuiTabHandle(_HasIcon, GuiContainer, _Removable[None], GuiTabProps):
    """Use as a context to place GUI elements into a tab."""

    @override
    def _create_message(self) -> Message:
        impl = self._impl
        return GuiTabMessage(impl.uuid, cast(str, impl.parent_container_id), impl.props)

    @override
    def _update_message(self, updates: dict[str, Any], props: Any) -> Message:
        impl = self._impl
        return GuiTabUpdateMessage(impl.uuid, cast(str, impl.parent_container_id), props)


class GuiFolderHandle(GuiContainer, _Removable[None], GuiFolderProps):
    """Use as a context to place GUI elements into a folder.

    With ``popup`` set, the folder is one labelled panel row, and its children
    appear in a popout opened from that row.
    """

    _message_type = _messages.GuiFolderMessage

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        if props.popup and props.label is None:
            raise ValueError("A popup folder needs a label for its row.")
        return props, value


def _fields_within(container: _GuiHandle[Any]) -> Iterator[GuiInputHandle[Any]]:
    """The fields a form holds, through any folders and tabs inside it."""
    for child in container._descendants():
        if isinstance(child, GuiInputHandle) and child._impl.initial_value is not None:
            yield child


class GuiFormHandle(GuiContainer, _Removable[None], GuiFormProps):
    """Use as a context to place GUI elements into a form.

    A form is a container whose children's values can be committed together by
    calling :meth:`submit_form` (typically from a button's ``on_click`` handler) or
    by pressing Enter in a single-line text input inside the form.

    It takes ONE row in the panel: its ``label``, and a button that opens the
    fields in a popout, keeping them apart from the live controls around them.
    The popout ends in a Reset and a Submit, drawn by the browser, which call
    :meth:`reset_form` and submit the form.

    A form added with ``mini=True`` holds exactly one direct, editable field and
    is drawn as that field's own row with a send button on the end of it -- no
    popout, no sibling rows or nested containers, and no Reset.

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

        @form.on_submit
        def _(event):
            print(name.value, age.value)
    """

    _message_type = _messages.GuiFormMessage

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        if props.mini != self._impl.props.mini:
            raise ValueError("A form cannot change between mini and regular after it is added.")
        return props, value

    def _admit(self, child: _GuiHandle[Any]) -> None:
        """Enforce a mini form's one rule: a single, direct, editable field."""
        if self._impl.props.mini and (
            not (isinstance(child, GuiInputHandle) and child._is_field()) or self._impl.children
        ):
            raise ValueError(
                "A mini form holds a single field (exactly one direct editable field); "
                "use add_form() for additional rows or containers."
            )

    @override
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        super().__exit__(exc_type, exc_value, traceback)
        if exc_type is None and self._impl.props.mini and not self._impl.children:
            self.remove()
            raise ValueError("A mini form holds a single field, but none was added to this one.")

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
        return self._add_callback(func)

    def remove_submit_callback(self, callback: Literal["all"] | Callable = "all") -> None:
        """Remove submit callbacks from the form.

        Args:
            callback: Either "all" to remove all callbacks, or a specific callback function to remove.
        """
        self._remove_callback(callback)

    def reset_form(self) -> None:
        """Put every field in this form back to the value it was declared with.

        Fields inside folders or tabs within the form are reset too; buttons
        are not fields and are left alone. Assigning those values fires each
        field's ``on_update``, as any other assignment from Python does. The
        form's own ``on_submit`` does not fire: nothing has been submitted.
        """
        gui_api = self._impl.gui_api
        with gui_api._lock:
            self._check_live()
            changes = [
                (field, change)
                for field in _fields_within(self)
                if (change := field._prepare({"value": field._impl.initial_value})) is not None
            ]
            messages = [
                field._update_message(change.updates, change.props)
                for field, change in changes
                if change.updates
            ]
            if messages:
                gui_api._websock_interface.queue_messages_or_raise(messages)
            for field, change in changes:
                field._apply(change)
            work = [
                (tuple(field._impl.callbacks), GuiEvent(None, None, field, change.value))
                for field, change in changes
            ]
        for callbacks, event in work:
            gui_api._schedule_callbacks(callbacks, event)

    def submit_form(self) -> None:
        """Programmatically submit this form.

        Fires all registered ``on_submit`` callbacks, and closes the form's
        popout on every client: the question has been answered, whoever
        answered it.
        """
        self._impl.gui_api._schedule_callbacks(self._submit(), GuiEvent(None, None, self))

    def _submit(self) -> tuple[Callable[..., Any], ...]:
        """Publish a submit, which closes the popout everywhere, and return the
        callbacks to run. Published before user code, so a raising callback
        cannot leave a popout open."""
        gui_api = self._impl.gui_api
        with gui_api._lock:
            self._check_live()
            gui_api._websock_interface.queue_message_or_raise(GuiFormSubmitMessage(self.id))
            return tuple(self._impl.callbacks)


class GuiModalHandle(GuiContainer):
    """Use as a context to place GUI elements into a modal."""

    _order: float
    _title: str

    def close(self) -> None:
        """Close this modal and permanently remove all contained GUI elements."""
        self._remove()

    @override
    def _create_message(self) -> Message:
        return GuiModalMessage(self._order, self._impl.uuid, self._title)

    @override
    def _removal_message(self) -> Message:
        return GuiCloseModalMessage(
            self._impl.uuid, tuple(child.id for child in self._descendants())
        )


class GuiProgressBarHandle(_Removable[None], GuiProgressBarProps):
    """Handle for updating and removing progress bars. Display only: ``value``
    is a percentage that Python sets."""

    _message_type = _messages.GuiProgressBarMessage

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        if not 0 <= _finite_number(props.value) <= 100:
            raise ValueError(f"Progress bar value is a percentage in [0, 100]; got {props.value}.")
        return props, value


class GuiHtmlHandle(_Removable[None], GuiHtmlProps):
    """Handle for trusted raw HTML.

    ``content`` is injected by the browser without sanitization and may act with
    the page's authority. Sanitize any untrusted input before assigning it or
    passing it to :meth:`GuiApi.add_html`.
    """

    _message_type = _messages.GuiHtmlMessage


@dataclasses.dataclass(frozen=True)
class PlaybackState:
    """Immutable snapshot of a Python-controlled timeline, with times in seconds."""

    time: float
    duration: float
    playing: bool
    speed: float
    loop: bool
    fps: float | None
    buffering: bool


@dataclasses.dataclass(frozen=True)
class PlaybackEvent:
    """One accepted browser command and its resulting state, before user code runs."""

    client: ClientHandle
    client_id: ClientId
    target: GuiPlaybackHandle
    action: PlaybackAction
    value: float | None
    """Requested seek time, step direction (-1/+1), or speed; otherwise None."""
    state: PlaybackState


class GuiPlaybackHandle(_Removable[None], GuiPlaybackProps):
    """Playback controls with an application-owned clock.

    Assign ``time``, ``playing``, ``speed``, ``loop``, ``duration``, ``fps`` or
    ``buffering``, or use ``update(...)`` to publish several together. These
    assignments do not invoke callbacks. Browser commands update the handle
    first, then call :meth:`on_update` with an immutable state snapshot.

    No background clock or simulator is started. Call :meth:`advance` from
    your render loop, or publish the actual time of a simulator yourself.
    A server GUI shares state across browsers; a client GUI keeps it private.
    Hiding the control does not pause application work.
    """

    _message_type = _messages.GuiPlaybackMessage

    @property
    def state(self) -> PlaybackState:
        """A consistent snapshot; safe to keep after the next update."""
        props = self._impl.props
        return PlaybackState(
            **{
                field.name: getattr(props, field.name)
                for field in dataclasses.fields(PlaybackState)
            }
        )

    def on_update(
        self, func: Callable[[PlaybackEvent], NoneOrCoroutine]
    ) -> Callable[[PlaybackEvent], NoneOrCoroutine]:
        """Register a browser-command callback. Programmatic updates are silent.

        Regular functions run in the callback pool; async functions run in
        the event loop. Use ``event.state`` to read the accepted command's
        snapshot, rather than a handle that another thread may have advanced.
        """
        return self._add_callback(func)

    def remove_update_callback(self, callback: Literal["all"] | Callable = "all") -> None:
        """Remove one callback, or all callbacks."""
        self._remove_callback(callback)

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        for name in ("time", "duration"):
            _finite_number(getattr(props, name), name)
        if not 0 <= props.time <= props.duration:
            raise ValueError("playback requires 0 <= time <= duration")
        _positive_number(props.speed, "speed")
        if props.fps is not None:
            _positive_number(props.fps, "fps")
        return props, value

    @override
    def _update_message(self, updates: dict[str, Any], props: Any) -> Message:
        # Bounds and playhead are coupled: retain one complete state, so a
        # reconnect cannot replay an old seek against another duration.
        return GuiUpdateMessage(self._impl.uuid, dataclasses.asdict(props))

    def advance(self, seconds: float) -> PlaybackState:
        """Advance by elapsed wall time × speed, respecting pause, buffering and loop.

        Returns the resulting state. At the end, a non-looping timeline stops
        on its final frame. A looping timeline wraps. This does not call
        callbacks; render the returned time from your application loop.
        """
        _finite_number(seconds, "seconds")
        if seconds < 0:
            raise ValueError("seconds must be nonnegative")
        with self._impl.gui_api._lock:
            state = self.state
            if not state.playing or state.buffering or self.disabled or state.duration == 0:
                return state
            target = state.time + seconds * state.speed
            if target >= state.duration:
                if not state.loop:
                    self.update(time=state.duration, playing=False)
                    return self.state
                target %= state.duration
            self.time = target
            return self.state

    def _command(self, action: PlaybackAction, value: float) -> None:
        """Apply a validated intent against current state, never a stale browser copy."""
        state = self.state
        if action == "play":
            self.update(playing=True, time=0.0 if state.time >= state.duration else state.time)
        elif action == "pause":
            self.playing = False
        elif action == "seek":
            target = max(0.0, min(value, state.duration))
            if state.fps is not None:
                target = min(state.duration, math.floor(target * state.fps + 0.5) / state.fps)
            self.time = target
        elif action == "step":
            if state.fps is None or value not in (-1, 1):
                raise ValueError("step requires fps and a direction of -1 or 1")
            target = (math.floor(state.time * state.fps + 0.5) + value) / state.fps
            self.update(time=max(0.0, min(target, state.duration)), playing=False)
        elif action == "speed":
            self.speed = value
        else:
            self.loop = not state.loop


class GuiVideoControlsHandle(_Removable[None], GuiVideoControlsProps):
    """Dock controls for a browser-local video group, without Python playback events."""

    _message_type = _messages.GuiVideoControlsMessage

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        validate_layout_id(props.sync_group, "sync_group")
        return props, value


class GuiDividerHandle(_Removable[None], GuiDividerProps):
    """Handle for updating and removing dividers."""

    _message_type = _messages.GuiDividerMessage


class GuiPlotlyHandle(_Removable[None], GuiPlotlyProps):
    """Handle backed only by serialized JSON, never by the caller's mutable Figure."""

    _message_type = _messages.GuiPlotlyMessage
    _config: dict[str, Any] | None
    """The private Plotly config every serialization of this plot carries."""

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        _positive_number(props.aspect, "aspect")
        return props, value

    @property
    def figure(self) -> go.Figure:
        """Independent snapshot of the displayed figure. Assign it to publish edits."""
        return plotly_figure(self._impl.props._plotly_json_str)

    @figure.setter
    def figure(self, figure: go.Figure) -> None:
        self._update({"_plotly_json_str": plotly_json(figure, self._config)})


class GuiImageHandle(_Removable[None], GuiImageProps):
    """Handle for updating and removing images."""

    _message_type = _messages.GuiImageMessage
    _image: np.ndarray
    _jpeg_quality: int | None
    _user_format: Literal["auto", "jpeg", "png"]
    """The format the caller asked for, which ``_format`` resolves 'auto' from."""

    @property
    def image(self) -> np.ndarray:
        """Current content of this image element. Synchronized automatically when assigned."""
        return self._image.copy()

    @image.setter
    def image(self, image: np.ndarray) -> None:
        user_format = self._user_format
        prepared = prepare_image(image, user_format, self._jpeg_quality)
        with self._impl.gui_api._lock:
            if self._user_format != user_format:  # Changed while this encoded.
                prepared = prepare_image(image, self._user_format, self._jpeg_quality)
            self._commit_image(prepared, self._user_format)

    @property
    def format(self) -> Literal["auto", "jpeg", "png"]:
        """Image format. 'auto' will use PNG for RGBA images and JPEG for RGB."""
        return self._user_format

    @format.setter
    def format(self, value: Literal["auto", "jpeg", "png"]) -> None:
        _validate_image_encoding_options(value, self._jpeg_quality)
        image = self._image
        prepared = prepare_image(image, value, self._jpeg_quality)
        with self._impl.gui_api._lock:
            if self._image is not image:  # Replaced while this encoded.
                prepared = prepare_image(self._image, value, self._jpeg_quality)
            self._commit_image(prepared, value)

    def _commit_image(
        self,
        prepared: tuple[np.ndarray, Literal["jpeg", "png"], bytes],
        user_format: Literal["auto", "jpeg", "png"],
    ) -> None:
        """Publish an encoding made outside the lock; the caller holds it."""
        snapshot, resolved_format, data = prepared
        self._update({"_format": resolved_format, "_data": data})
        self._image = snapshot
        self._user_format = user_format


@dataclasses.dataclass(frozen=True)
class CommandEvent:
    """Information associated with a command trigger from the command palette.

    Passed as input to callback functions. Every command trigger originates
    from a browser client, so ``client`` and ``client_id`` are always populated
    when a callback runs, despite being typed as Optional."""

    client: ClientHandle | None
    """Client that triggered this command."""
    client_id: int | None
    """ID of client that triggered this command."""
    target: CommandHandle
    """Command handle that was triggered."""


class CommandHandle(_HasIcon, _Removable[None], CommandProps):
    """Handle for a command registered in the command palette.

    Commands are shown in a command palette (Ctrl/Cmd+K, also Ctrl/Cmd+Shift+P
    on non-Firefox browsers) and can optionally be triggered via hotkeys.

    (Experimental) The command palette API may change in future releases."""

    _message_type = _messages.RegisterCommandMessage

    def __str__(self) -> str:
        return self._impl.uuid

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        if props.modifier is not None and not isinstance(props.modifier, str):
            raise TypeError("modifier must be a string or None")
        modifier = _normalize_key_modifier(props.modifier)
        if props.hotkey is None and modifier is not None:
            raise ValueError("modifier requires hotkey to also be set.")
        return dataclasses.replace(props, modifier=modifier), value

    @override
    def _update_message(self, updates: dict[str, Any], props: Any) -> Message:
        return CommandUpdateMessage(self._impl.uuid, updates)

    @override
    def _removal_message(self) -> Message:
        return RemoveCommandMessage(self._impl.uuid)

    def on_trigger(
        self, func: Callable[[CommandEvent], NoneOrCoroutine]
    ) -> Callable[[CommandEvent], NoneOrCoroutine]:
        """Attach a function to call when this command is triggered.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        return self._add_callback(func)
