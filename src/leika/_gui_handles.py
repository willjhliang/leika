from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import math
import mimetypes
import re
import time
import uuid
import warnings
from collections.abc import Coroutine, Mapping, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Iterable,
    Literal,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

import numpy as np
from typing_extensions import Protocol, Self, override

from ._assignable_props_api import AssignablePropsBase
from ._icons import svg_from_icon
from ._icons_enum import IconName
from ._image_encoding import encode_image_binary
from ._messages import (
    ButtonColor,
    CommandProps,
    CommandUpdateMessage,
    GuiBaseProps,
    GuiButtonGroupProps,
    GuiButtonProps,
    GuiCheckboxProps,
    GuiChecklistProps,
    GuiCloseModalMessage,
    GuiDividerProps,
    GuiDropdownProps,
    GuiFolderProps,
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
    GuiSliderProps,
    GuiTab,
    GuiTabGroupProps,
    GuiTextProps,
    GuiToggleGroupProps,
    GuiToggleProps,
    GuiUpdateMessage,
    GuiUploadButtonProps,
    GuiVector2Props,
    GuiVector3Props,
    RemoveCommandMessage,
)
from ._threadpool_exceptions import print_threadpool_errors
from ._validation import validate_finite_number as _finite_number
from .infra import ClientId

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from ._gui_api import GuiApi
    from ._server import ClientHandle


T = TypeVar("T")
TGuiHandle = TypeVar("TGuiHandle", bound="_GuiHandle")
NoneOrCoroutine = TypeVar("NoneOrCoroutine", None, Coroutine)


def _make_uuid() -> str:
    """Return a unique ID for referencing GUI elements."""
    return str(uuid.uuid4())


def _string_options(options: Iterable[Any], control: str) -> tuple[str, ...]:
    """Validate labels used as both display text and stable values."""
    if isinstance(options, str):
        raise ValueError(f"{control} options must be a sequence, not one string.")
    values = tuple(options)
    if not values:
        raise ValueError(f"{control} requires at least one option.")
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{control} options must be strings; got {value!r}.")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"{control} options must be unique; repeated {sorted(duplicates)!r}.")
    return values


@overload
def _cast_vector(vector: tuple | np.ndarray, length: Literal[2]) -> tuple[float, float]: ...


@overload
def _cast_vector(vector: tuple | np.ndarray, length: Literal[3]) -> tuple[float, float, float]: ...


def _cast_vector(vector: tuple | np.ndarray, length: int) -> tuple[float, ...]:
    """Normalize a fixed-length vector."""
    array = np.asarray(vector)
    if array.shape != (length,):
        raise ValueError(f"Expected vector of shape {(length,)}, got {array.shape}.")
    values = tuple(map(float, array))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Vector components must be finite.")
    return values


def _schedule_coroutine(
    event_loop: asyncio.AbstractEventLoop,
    coroutine: Coroutine[Any, Any, Any],
) -> None:
    """Schedule a callback on its owning loop from any thread."""
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None
    if running_loop is event_loop:
        event_loop.create_task(coroutine)
    else:
        future = asyncio.run_coroutine_threadsafe(coroutine, event_loop)
        future.add_done_callback(print_threadpool_errors)


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

    def __exit__(self, *args: Any) -> None:
        del args
        self._child_gui_api._pop_container_uuid()

    def _add_child(self, method: str, *args: Any, **kwargs: Any) -> Any:
        gui_api = self._child_gui_api
        with self:
            return getattr(gui_api, method)(*args, **kwargs)


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

    sync_cb: Callable[[ClientId, dict[str, Any]], None] | None = None
    """Callback for synchronizing inputs across clients."""

    removed: bool = False


# Not exported: some GUI handles do not inherit from `_GuiHandle` -- notably
# `GuiModalHandle` and `GuiTabHandle`, which are containers rather than
# elements. Exporting it would invite isinstance checks that those fail.
class _GuiHandle(Generic[T], AssignablePropsBase[_GuiHandleState]):
    def __init__(self, impl: _GuiHandleState[T]) -> None:
        super().__init__(impl=impl)
        parent = self._impl.gui_api._container_handle_from_uuid[self._impl.parent_container_id]
        parent._children[self._impl.uuid] = self

        if isinstance(self, _GuiInputHandle):
            self._impl.gui_api._gui_input_handle_from_uuid[self._impl.uuid] = self

    @property
    def id(self) -> str:
        """Stable identifier for this GUI component."""
        return self._impl.uuid

    @override
    def _queue_update(self, name: str, value: Any) -> None:
        self._impl.gui_api._websock_interface.queue_message(
            GuiUpdateMessage(self._impl.uuid, {name: value})
        )

    def update(self, **props: Any) -> None:
        """Update one or more synchronized properties."""

        for name, value in props.items():
            prop = getattr(type(self), name, None)
            has_setter = isinstance(prop, property) and prop.fset is not None
            if name not in self._prop_hints and not has_setter:
                raise TypeError(f"{type(self).__name__}.update() got an unknown property {name!r}.")
            setattr(self, name, value)

    def remove(self) -> None:
        """Permanently remove this GUI element from the visualizer."""

        gui_api = self._impl.gui_api
        if isinstance(self, GuiUploadButtonHandle):
            with gui_api._file_upload_lock:
                self._remove_impl()
        else:
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
        self._impl.removed = True

        gui_api = self._impl.gui_api
        gui_api._websock_interface.queue_message(GuiRemoveMessage(self._impl.uuid))
        parent = gui_api._container_handle_from_uuid[self._impl.parent_container_id]
        parent._children.pop(self._impl.uuid)

        if isinstance(self, _GuiInputHandle):
            gui_api._gui_input_handle_from_uuid.pop(self._impl.uuid)
        if isinstance(self, GuiUploadButtonHandle):
            gui_api._discard_file_uploads(source_component_uuid=self._impl.uuid)


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
        return self._impl.value

    def _coerce_assigned_value(self, value: T | np.ndarray) -> T | np.ndarray:
        """Hook for input-type-specific coercion of an assigned value. The base
        is identity; rgb/rgba handles override this to normalize colors."""
        return value

    def _coerce_client_value(self, value: Any) -> Any:
        """Cast a value the browser sent to the shape this handle holds.

        JavaScript sends integers where floats are expected, and arrays where
        tuples are, so the value already here is what says what the new one
        should be. A handle whose value has more structure than that -- a tuple
        of pairs rather than of numbers -- overrides this.
        """
        current = self._impl.value
        if not isinstance(current, tuple):
            return type(current)(value)
        if len(current) == 0:
            return tuple(value)
        # Tuple contents are assumed homogeneous.
        typ = type(current[0])
        return tuple(typ(new) for new in value)

    @value.setter
    def value(self, value: T | np.ndarray) -> None:
        value = self._coerce_assigned_value(value)
        if isinstance(value, np.ndarray):
            assert len(value.shape) <= 1, f"{value.shape} should be at most 1D!"
            # Preserve each element's expected Python type -- float for vectors,
            # int for colors. A blanket `float(...)` would turn an int tuple into
            # floats, and the `tuple(...)` cast below does not restore types.
            elems = value.tolist()
            current = self._impl.value
            if isinstance(current, tuple) and len(current) == len(elems):
                value = tuple(type(c)(e) for c, e in zip(current, elems))  # type: ignore
            else:
                value = tuple(elems)  # type: ignore

        # Convert to internal type early so we can compare.
        value = type(self._impl.value)(value)  # type: ignore

        # Skip if value hasn't changed (but always process buttons).
        if not self._impl.is_button:
            try:
                if self._impl.value == value:
                    return
            except (TypeError, ValueError):
                pass

        # Send to client, except for buttons.
        if not self._impl.is_button:
            self._impl.gui_api._websock_interface.queue_message(
                GuiUpdateMessage(self._impl.uuid, {"value": value})
            )

        # Set internal state.
        self._impl.value = value  # type: ignore
        self._impl.update_timestamp = time.time()

        # Call update callbacks.
        for cb in self._impl.update_cb:
            # As a design decision: we choose to call update callbacks
            # synchronously instead of in the thread pool. It's rare that there
            # are significant blocking callbacks for GUI updates; this also
            # reduces the likelihood of many common race conditions.
            cb_out = cb(GuiEvent(client_id=None, client=None, target=self))
            if isinstance(cb_out, Coroutine):
                _schedule_coroutine(self._impl.gui_api._event_loop, cb_out)

    @property
    def update_timestamp(self) -> float:
        """Read-only timestamp when this input was last updated."""
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
        self._impl.update_cb.append(func)
        return func

    def remove_update_callback(self, callback: Literal["all"] | Callable = "all") -> None:
        """Remove update callbacks from the GUI input.

        Args:
            callback: Either "all" to remove all callbacks, or a specific callback function to remove.
        """
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
    assert isinstance(props, (GuiButtonGroupProps, GuiToggleGroupProps))
    return props


def _row_colors(handle: Any) -> Tuple[ButtonColor, ...]:
    """The colorways a row of buttons or toggles is currently wearing."""
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
    props.color = colors
    handle._queue_update("color", colors)


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
    def color(self, color: ButtonColor | Sequence[ButtonColor]) -> None:  # type: ignore
        _set_row_colors(self, color)

    def _normalize_value(self, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            raise ValueError("A toggle group value must be a sequence of option names.")
        wanted = tuple(value)
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
        entries = tuple(value)
        for entry in entries:
            if not isinstance(entry, str):
                raise ValueError(f"List entries must be strings; got {entry!r}.")
        return entries

    @override
    def _coerce_client_value(self, value: Any) -> Any:
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
    items: list[Tuple[str, bool]] = []
    for item in value:
        if isinstance(item, str):
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
            raise ValueError(
                f"A checklist item's text is a string; got {text!r}. Pass str(...) for"
                " anything else."
            )
        items.append((text, bool(checked)))
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
        # The browser sends `[[text, checked], ...]`, which the base would turn
        # into a tuple of LISTS -- and into nothing at all when the checklist is
        # empty and there is no item to take the shape from.
        return _checklist_items(value)


class GuiCheckboxHandle(GuiInputHandle[bool], GuiCheckboxProps):
    """Handle for checkbox inputs.

    .. attribute:: value
       :type: bool

       Value of the input. Synchronized automatically when assigned.
    """


class GuiTextHandle(GuiInputHandle[str], GuiTextProps):
    """Handle for text, editable or read-only.

    .. attribute:: value
       :type: str

       The text itself, whether it is being edited or only read. Synchronized
       automatically when assigned.
    """

    def __init__(self, _impl: _GuiHandleState, _image_root: Path | None = None):
        super().__init__(impl=_impl)
        self._image_root = _image_root

    def _refresh_source(self) -> None:
        """Re-resolve the markdown a rendered field draws from.

        Called wherever the value the viewer READS could have changed: on an
        assignment to the value, and on one to ``editable`` or ``markdown``,
        which is what turns a field into something that renders. Client-side
        edits write the value without coming through here, and do not need to --
        a field being typed into is showing its source, and the flip that would
        render it refreshes this on the way past.
        """
        self._source = _parse_markdown(self.value, self._image_root)

    @property
    def value(self) -> str:
        return _GuiInputHandle.value.fget(self)  # type: ignore[attr-defined]

    @value.setter
    def value(self, value: str | np.ndarray) -> None:
        _GuiInputHandle.value.fset(self, value)  # type: ignore[attr-defined]
        self._refresh_source()

    def _on_prop_assigned(self, name: str) -> None:
        if name in ("editable", "markdown"):
            self._refresh_source()


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
        value = type(self._impl.value)(value)
        return self._coerce_assigned_value(value)


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
        value = type(self._impl.value)(value)
        return self._coerce_assigned_value(value)


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
        values = tuple(_finite_number(item) for item in value)
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
        return self._normalize_value(value)


def _colors_to_int_tuple(value: Any, channels: int | None = None) -> tuple[int, ...]:
    """Coerce an RGB/RGBA color to an int tuple in [0, 255].

    Integer channels are taken as absolute [0, 255]; float channels are
    interpreted as [0, 1] and scaled (the matplotlib convention), so ``1.0`` ->
    255 (white) but ``1`` -> 1. The result is clamped to [0, 255] -- matching
    ``colors_to_uint8`` -- so out-of-range inputs (e.g. a float ``255.0`` or a
    negative value) degrade gracefully instead of producing a wild value.
    Generalized to any channel count (RGB and RGBA)."""
    array = np.asarray(value, dtype=object)
    if array.ndim != 1:
        raise ValueError(f"Expected a 1D color, got shape {array.shape}.")
    if channels is not None and len(array) != channels:
        raise ValueError(f"Expected {channels} color channels, got {len(array)}.")
    normalized: list[int] = []
    for channel in array:
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


@dataclasses.dataclass(frozen=True)
class GuiEvent(Generic[TGuiHandle]):
    """Information associated with a GUI event, such as an update or click.

    Passed as input to callback functions."""

    client: ClientHandle | None
    """Client that triggered this event."""
    client_id: int | None
    """ID of client that triggered this event."""
    target: TGuiHandle
    """GUI element that was affected."""

    @property
    def value(self) -> Any:
        """Value of the affected handle, or None for a handle that has no
        value of its own (e.g. a form)."""
        return getattr(self.target, "value", None)


class GuiButtonHandle(_GuiInputHandle[bool], GuiButtonProps):
    """Handle for a button input in our visualizer.

    .. attribute:: value
       :type: bool

       Value of the button. Set to `True` when the button is pressed. Can be manually set back to `False`.
    """

    def __init__(self, _impl: _GuiHandleState[bool], _icon: IconName | None):
        super().__init__(impl=_impl)
        self._icon = _icon
        # Callbacks to run while the button is held, by frequency (Hz).
        self._hold_cbs_from_freq: dict[float, list[Callable[[GuiEvent], None | Coroutine]]] = {}

    @property
    def icon(self) -> IconName | None:
        """Icon to display on the button. When set to None, no icon is displayed."""
        return self._icon

    @icon.setter
    def icon(self, icon: IconName | None) -> None:
        self._icon = icon
        self._icon_html = None if icon is None else svg_from_icon(icon)

    def on_click(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a button is pressed.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        self._impl.update_cb.append(func)
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
        if not math.isfinite(callback_hz) or callback_hz <= 0.0:
            raise ValueError("callback_hz must be a positive, finite number.")

        def register_callback(
            f: GuiButtonHandle._HoldCallback,
        ) -> GuiButtonHandle._HoldCallback:
            self._hold_cbs_from_freq.setdefault(callback_hz, []).append(f)
            # Update the prop to notify client of new frequency.
            self._hold_callback_freqs = tuple(self._hold_cbs_from_freq.keys())

            return f

        if func is not None:
            return register_callback(func)
        return register_callback


@dataclasses.dataclass
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
        super().__init__(impl=_impl)
        self._icon = _icon

    @property
    def icon(self) -> IconName | None:
        """Icon to display on the upload button. When set to None, no icon is displayed."""
        return self._icon

    @icon.setter
    def icon(self, icon: IconName | None) -> None:
        self._icon = icon
        self._icon_html = None if icon is None else svg_from_icon(icon)

    def on_upload(
        self: TGuiHandle, func: Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]
    ) -> Callable[[GuiEvent[TGuiHandle]], NoneOrCoroutine]:
        """Attach a function to call when a file is uploaded.

        Note:
        - If `func` is a regular function (defined with `def`), it will be executed in a thread pool.
        - If `func` is an async function (defined with `async def`), it will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        self._impl.update_cb.append(func)
        return func


PREVIEW_MAX_BYTES = 64 * 1024 * 1024
"""Past this, a preview is refused rather than sent. Generous for the text and
images most previews are, and short of the size at which holding a whole file
in a tab becomes the browser's problem."""

FileContent = Union[bytes, Path, Callable[["GuiEvent[Any]"], Union[bytes, Path]]]
"""What a file button sends: the bytes themselves, a path to read them from, or
a function called at click time returning either."""

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
        super().__init__(_impl=_impl, _icon=_icon)
        self._content = _content
        self._filename = _filename

    @property
    def content(self) -> FileContent:
        """What the button sends: bytes, a path to read at click time, or a
        function of the click event returning one of those."""
        return self._content

    @content.setter
    def content(self, content: FileContent) -> None:
        self._content = content

    @property
    def filename(self) -> str | None:
        """Name the file is sent under, or None to take it from the path that
        the contents were read from."""
        return self._filename

    @filename.setter
    def filename(self, filename: str | None) -> None:
        self._filename = filename

    def _resolve(self, event: GuiEvent[Any]) -> Tuple[str, bytes | Path]:
        """The name and contents to send for one press."""
        content = self._content(event) if callable(self._content) else self._content
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

    def _send(self, event: GuiEvent[Any]) -> None:
        """Send the file to whoever pressed the button."""
        if event.client is None:
            return
        # Held down for the length of the transfer, not just the production of
        # the contents: the click that starts a second copy of a large file is
        # the one made while the first is still going out.
        self._set_disabled_if_present(True)
        try:
            filename, content = self._resolve(event)
            self._deliver(event.client, filename, content)
        finally:
            self._set_disabled_if_present(False)

    def _set_disabled_if_present(self, disabled: bool) -> None:
        """Assign `disabled`, unless the button has been removed underneath us.

        Assigning to a removed handle raises, which would replace whatever the
        callback was really doing with an error about the button.
        """
        if not self._impl.removed:
            self.disabled = disabled


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
        super().__init__(_impl=_impl, _icon=_icon, _content=_content, _filename=_filename)
        self._max_bytes = _max_bytes

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
            source = content.read_bytes().decode("utf-8", errors="replace")
            return _link_markdown_assets(
                source, content.parent, client._server.register_http_asset
            ).encode("utf-8")
        return content

    @override
    def _deliver(self, client: ClientHandle, filename: str, content: bytes | Path) -> None:
        content = self._prepared(client, filename, content)
        client.send_file_preview(filename, content, max_bytes=self._max_bytes)

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
        if callable(content):
            return
        filename = self._filename
        if filename is None:
            filename = content.name if isinstance(content, Path) else None
        if filename is None:
            return
        try:
            prepared = self._prepared(client, filename, content)
            size = len(prepared) if isinstance(prepared, bytes) else prepared.stat().st_size
            if size > self._max_bytes:
                return
            client._send_file(filename, prepared, 1024 * 1024, "warm")
        except OSError:
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
        self._impl.update_cb.append(func)
        return func

    @property
    def color(self) -> Tuple[ButtonColor, ...]:
        """One colorway per button, as a tuple however it was assigned.

        Assigning a single role sets the whole row; assigning a sequence sets
        one button at a time, and must be as long as ``options``."""
        return _row_colors(self)

    @color.setter
    def color(self, color: ButtonColor | Sequence[ButtonColor]) -> None:  # type: ignore
        _set_row_colors(self, color)

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        if value not in self.options:
            raise ValueError(f"Button value must be one of {self.options!r}; got {value!r}.")
        return value

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
        assert isinstance(self._impl.props, GuiDropdownProps)
        return self._impl.props.options  # type: ignore

    @options.setter
    def options(self, options: Iterable[StringType]) -> None:  # type: ignore
        assert isinstance(self._impl.props, GuiDropdownProps)
        options = cast("tuple[StringType, ...]", _string_options(options, "Dropdown"))
        if options == self._impl.props.options:
            return
        self._impl.props.options = options

        self._impl.gui_api._websock_interface.queue_message(
            GuiUpdateMessage(
                self._impl.uuid,
                {"options": options},
            )
        )
        if self.value not in options:
            self.value = options[0]

    @override
    def _coerce_assigned_value(self, value: Any) -> Any:
        if value not in self.options:
            raise ValueError(f"Dropdown value must be one of {self.options!r}; got {value!r}.")
        return value

    @override
    def _coerce_client_value(self, value: Any) -> Any:
        return self._coerce_assigned_value(value)


class GuiTabGroupHandle(_GuiHandle[None], GuiTabGroupProps):
    """Handle for a tab group. Call :meth:`add_tab()` to add a tab."""

    def __init__(self, _impl: _GuiHandleState[None]) -> None:
        super().__init__(impl=_impl)
        self._tab_handles: list[GuiTabHandle] = []

    def add_tab(self, label: str, icon: IconName | None = None) -> GuiTabHandle:
        """Add a tab. Returns a handle we can use to add GUI elements to it."""

        if self._impl.removed:
            raise RuntimeError("Cannot add a tab to a removed GuiTabGroupHandle.")

        uuid = _make_uuid()

        out = GuiTabHandle(_parent=self, _id=uuid, _label=label, _icon=icon)

        self._tab_handles.append(out)
        self._tabs = self._tabs + (
            GuiTab(
                label=label,
                icon_html=None if icon is None else svg_from_icon(icon),
                container_id=uuid,
            ),
        )
        return out

    def remove(self) -> None:
        """Remove this tab group and all contained GUI elements."""
        # Warn if already removed.
        if self._impl.removed:
            warnings.warn(
                f"Attempted to remove an already removed {self.__class__.__name__}.",
                stacklevel=2,
            )
            return

        # Tabs update the group's props as they leave, so remove them before
        # marking the group itself removed.
        for tab in tuple(self._tab_handles):
            tab.remove()
        self._impl.removed = True
        gui_api = self._impl.gui_api
        gui_api._websock_interface.queue_message(GuiRemoveMessage(self._impl.uuid))
        parent = gui_api._container_handle_from_uuid[self._impl.parent_container_id]
        parent._children.pop(self._impl.uuid)


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
        return self._icon

    @icon.setter
    def icon(self, icon: IconName | None) -> None:
        self._check_container_active()
        self._icon = icon
        icon_html = None if icon is None else svg_from_icon(icon)
        self._parent._tabs = tuple(
            dataclasses.replace(tab, icon_html=icon_html) if tab.container_id == self._id else tab
            for tab in self._parent._tabs
        )

    def __post_init__(self) -> None:
        self._parent._impl.gui_api._container_handle_from_uuid[self._id] = self

    def remove(self) -> None:
        """Permanently remove this tab and all contained GUI elements from the
        visualizer."""
        # Warn if already removed.
        if self.removed:
            warnings.warn(
                f"Attempted to remove an already removed {self.__class__.__name__}.",
                stacklevel=2,
            )
            return
        self.removed = True

        assert self in self._parent._tab_handles, "Tab already removed!"
        self._parent._tab_handles = [tab for tab in self._parent._tab_handles if tab is not self]
        self._parent._tabs = tuple(
            tab for tab in self._parent._tabs if tab.container_id != self._id
        )

        for child in tuple(self._children.values()):
            child.remove()
        self._parent._impl.gui_api._container_handle_from_uuid.pop(self._id)


class GuiFolderHandle(_GuiHandle[None], GuiFolderProps, GuiContainer):
    """Use as a context to place GUI elements into a folder."""

    def __init__(self, _impl: _GuiHandleState[None]) -> None:
        # `_GuiHandle.__init__` already registered this handle with its parent.
        super().__init__(impl=_impl)
        self._impl.gui_api._container_handle_from_uuid[self._impl.uuid] = self
        self._children = {}

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
        # Warn if already removed.
        if self._impl.removed:
            warnings.warn(
                f"Attempted to remove an already removed {self.__class__.__name__}.",
                stacklevel=2,
            )
            return
        self._impl.removed = True

        # Remove children, then self.
        gui_api = self._impl.gui_api
        gui_api._websock_interface.queue_message(GuiRemoveMessage(self._impl.uuid))
        for child in tuple(self._children.values()):
            child.remove()
        parent = gui_api._container_handle_from_uuid[self._impl.parent_container_id]
        parent._children.pop(self._impl.uuid)
        gui_api._container_handle_from_uuid.pop(self._impl.uuid)


def _fields_within(container: Any) -> Iterable[_GuiInputHandle]:
    """Every input under `container` the viewer can answer with, however deeply
    folders or tabs nest it.

    Buttons are excluded: their "value" is the fact of a press, so there is
    nothing about one to remember or put back. So is text that is only there to
    be read -- prose above a field, a rendered heading -- which holds a value
    the way a button does not, but is no more a part of the answer than the
    label beside a slider is."""
    for child in getattr(container, "_children", {}).values():
        if (
            isinstance(child, _GuiInputHandle)
            and not child._impl.is_button
            and getattr(child._impl.props, "editable", True)
        ):
            yield child
        yield from _fields_within(child)


class GuiFormHandle(GuiFolderHandle):
    """Use as a context to place GUI elements into a form.

    A form is a container whose children's values can be committed together by
    calling :meth:`submit_form` (typically from a button's ``on_click`` handler) or
    by pressing Enter in a single-line text input inside the form.

    It takes ONE row in the panel: its ``label``, and a button that opens the
    fields in a popout, keeping them apart from the live controls around them.

    The popout ends in a Reset and a Submit, added as the form's last child
    and reachable as ``form.actions`` (:meth:`reset_form` /
    :meth:`submit_form`).

    A form built by :meth:`GuiApi.add_mini_form` holds one field and is drawn
    as that field's own row with a send button on the end of it -- no popout,
    no row of its own, and no ``actions``, the send button being the client's
    rather than a child of the form.

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
        super().__init__(_impl)
        self._submit_cb: list[Callable[[GuiEvent[GuiFormHandle]], None | Coroutine]] = []
        self._initial_values: dict[str, Any] = {}
        self.actions: GuiButtonGroupHandle

    def __exit__(self, *args: Any) -> None:
        super().__exit__(*args)
        # An exception on its way out of the block takes precedence: whatever
        # is half-built in here, the error that got us here is the one to
        # report.
        if args and args[0] is not None:
            return

        fields = list(_fields_within(self))
        # A mini form is drawn as its one field's own row, so a second field
        # has nowhere to go. Caught here rather than swallowed on the client,
        # where it would come out as a field that silently never appeared.
        if self._impl.props.mini and len(fields) > 1:  # type: ignore[attr-defined]
            raise ValueError(
                "A mini form holds a single field, but "
                f"{len(fields)} were added to this one. Use add_form() for "
                "several fields."
            )

        # What Reset puts back. Read here rather than at reset time, because by
        # then the field holds whatever was typed into it: a field is at its
        # declared value the moment it is created, and this is the first look
        # at it after that. Fields added later are picked up on their own exit.
        for field in fields:
            self._initial_values.setdefault(field._impl.uuid, field.value)

        # Keep the action buttons at the bottom, where a form's submit belongs.
        #
        # They are created with the form, which is necessarily BEFORE the
        # fields they act on -- so they hold the smallest order number in the
        # form and would otherwise render above everything they submit. That
        # number is re-stamped here instead, once everything added inside has
        # taken one. Children added through `form.add_text(...)` rather than
        # the context manager arrive one exit at a time, and each of them moves
        # the buttons along again.
        actions = getattr(self, "actions", None)
        if actions is not None:
            # Runtime import to break the circular edge with `_gui_api`.
            from ._gui_api import _apply_default_order

            actions.order = _apply_default_order(None)

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
        self._submit_cb.append(func)
        return func

    def remove_submit_callback(self, callback: Literal["all"] | Callable = "all") -> None:
        """Remove submit callbacks from the form.

        Args:
            callback: Either "all" to remove all callbacks, or a specific callback function to remove.
        """
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
        fire: nothing has been submitted.
        """
        registry = self._impl.gui_api._gui_input_handle_from_uuid
        for field_uuid, initial in self._initial_values.items():
            field = registry.get(field_uuid)
            if field is None or field._impl.removed:
                continue
            field.value = initial

    def submit_form(self) -> None:
        """Programmatically submit this form.

        Fires all registered ``on_submit`` callbacks, and closes the form's
        popout on every client: the question has been answered, whoever
        answered it.
        """
        if self._impl.removed:
            raise RuntimeError("Cannot submit a removed GuiFormHandle.")
        gui_api = self._impl.gui_api
        # Fire on_submit callbacks. Server-initiated submits have no client.
        for cb in self._submit_cb:
            cb_out = cb(GuiEvent(client_id=None, client=None, target=self))
            if isinstance(cb_out, Coroutine):
                _schedule_coroutine(gui_api._event_loop, cb_out)
        gui_api._websock_interface.queue_message(GuiFormSubmitMessage(uuid=self._impl.uuid))


@dataclasses.dataclass
class GuiModalHandle(GuiContainer):
    """Use as a context to place GUI elements into a modal."""

    _gui_api: GuiApi
    _uuid: str  # Used as container ID of children.
    _children: dict[str, SupportsRemoveProtocol] = dataclasses.field(default_factory=dict)
    closed: bool = False

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
        self._gui_api._container_handle_from_uuid[self._uuid] = self
        self._gui_api._modal_handle_from_uuid[self._uuid] = self

    def close(self) -> None:
        """Close this modal and permanently remove all contained GUI elements."""
        if self.closed:
            warnings.warn(
                "Attempted to close an already closed GuiModalHandle.",
                stacklevel=2,
            )
            return
        self.closed = True
        self._gui_api._websock_interface.queue_message(
            GuiCloseModalMessage(self._uuid),
        )
        for child in tuple(self._children.values()):
            child.remove()
        self._gui_api._container_handle_from_uuid.pop(self._uuid)
        self._gui_api._modal_handle_from_uuid.pop(self._uuid)

    def remove(self) -> None:
        """Compatibility alias for :meth:`close`."""

        self.close()


def _get_data_url(url: str, image_root: Path | None) -> str:
    if not url.startswith("http") and not image_root:
        warnings.warn(
            (
                "No `image_root` provided. All relative paths will be scoped to Leika's"
                " installation path."
            ),
            stacklevel=2,
        )
    if url.startswith("http") or url.startswith("data:"):
        return url
    if image_root is None:
        image_root = Path(__file__).parent
    try:
        path = image_root / url
        binary = path.read_bytes()
        mime_type = mimetypes.guess_type(path.name, strict=False)[0] or "application/octet-stream"
        encoded = base64.b64encode(binary).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
    except (IOError, FileNotFoundError):
        warnings.warn(
            f"Failed to read image {url}, with image_root set to {image_root}.",
            stacklevel=2,
        )
        return url


def _parse_markdown(markdown: str, image_root: Path | None) -> str:
    markdown = re.sub(
        r"\!\[([^]]*)\]\(([^)\n]*)\)",
        lambda match: f"![{match.group(1)}]({_get_data_url(match.group(2), image_root)})",
        markdown,
    )
    return markdown


def _link_markdown_assets(markdown: str, image_root: Path, register: Callable[[Path], str]) -> str:
    """Point a document's relative images at server URLs of their own.

    The counterpart of :func:`_parse_markdown` for when there is a server to
    fetch from. Inlining images works anywhere but puts every byte of them in
    front of the text, so nothing shows until all of it has arrived;
    registering them (:meth:`Server.register_http_asset`) leaves the document
    the size of its writing, and the browser fetches the images alongside it.

    Web addresses and data URLs are already self-contained and pass through
    untouched. An image that cannot be read keeps its original reference --
    the document renders with the same broken figure it would show anywhere
    else, rather than failing to show at all.
    """

    def linked(match: re.Match[str]) -> str:
        url = match.group(2)
        if url.startswith("http") or url.startswith("data:"):
            return match.group(0)
        try:
            return f"![{match.group(1)}]({register(image_root / url)})"
        except OSError:
            warnings.warn(
                f"Failed to read image {url}, relative to {image_root}.",
                stacklevel=2,
            )
            return match.group(0)

    return re.sub(r"\!\[([^]]*)\]\(([^)\n]*)\)", linked, markdown)


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
    """Handling for updating and removing HTML elements."""


class GuiDividerHandle(_GuiHandle[None], GuiDividerProps):
    """Handle for updating and removing dividers."""


def _plotly_json_with_config(figure: go.Figure, config: Mapping[str, Any] | None) -> str:
    """Serialize a Plotly figure to JSON, merging in an optional config dict."""
    json_str = figure.to_json()
    assert isinstance(json_str, str)
    if config is not None:
        plot_dict = json.loads(json_str)
        plot_dict["config"] = {**plot_dict.get("config", {}), **config}
        json_str = json.dumps(plot_dict)
    return json_str


class GuiPlotlyHandle(_GuiHandle[None], GuiPlotlyProps):
    """Handle for updating and removing Plotly figures."""

    def __init__(
        self,
        _impl: _GuiHandleState,
        _figure: go.Figure,
        _config: Mapping[str, Any] | None = None,
    ):
        super().__init__(impl=_impl)
        self._figure = _figure
        self._config = _config

    @property
    def figure(self) -> go.Figure:
        """Current Plotly figure. Synchronized automatically when assigned."""
        assert self._figure is not None
        return self._figure

    @figure.setter
    def figure(self, figure: go.Figure) -> None:
        self._figure = figure
        self._plotly_json_str = _plotly_json_with_config(figure, self._config)


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
        super().__init__(impl=_impl)
        self._image = np.asarray(_image).copy()
        self._jpeg_quality = _jpeg_quality
        self._user_format = _user_format

    @property
    def image(self) -> np.ndarray:
        """Current content of this image element. Synchronized automatically when assigned."""
        return self._image.copy()

    @image.setter
    def image(self, image: np.ndarray) -> None:
        resolved_format, data = encode_image_binary(
            image, self._user_format, jpeg_quality=self._jpeg_quality
        )
        self._image = np.asarray(image).copy()
        self._format = resolved_format
        self._data = data

    @property
    def format(self) -> Literal["auto", "jpeg", "png"]:
        """Image format. 'auto' will use PNG for RGBA images and JPEG for RGB."""
        return self._user_format

    @format.setter
    def format(self, value: Literal["auto", "jpeg", "png"]) -> None:
        # Skip if format isn't changing.
        if self._user_format == value:
            return

        if value == "jpeg" and self._image.shape[2] == 4:
            warnings.warn(
                "Converting RGBA image to JPEG will discard the alpha channel.",
                stacklevel=2,
            )
        resolved_format, data = encode_image_binary(
            self._image, value, jpeg_quality=self._jpeg_quality
        )
        self._user_format = value
        self._format = resolved_format
        self._data = data


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


class CommandHandle(AssignablePropsBase[_CommandHandleState], CommandProps):
    """Handle for a command registered in the command palette.

    Commands are shown in a command palette (Ctrl/Cmd+K, also Ctrl/Cmd+Shift+P
    on non-Firefox browsers) and can optionally be triggered via hotkeys.

    (Experimental) The command palette API may change in future releases."""

    def __init__(self, _impl: _CommandHandleState) -> None:
        super().__init__(impl=_impl)

    @property
    def id(self) -> str:
        """Stable command identifier."""
        return self._impl.uuid

    def __str__(self) -> str:
        return self._impl.uuid

    @property
    def icon(self) -> IconName | None:
        """Icon displayed in the command palette."""
        return self._impl.icon

    @icon.setter
    def icon(self, icon: IconName | None) -> None:
        # Removed-guard enforced upstream by AssignablePropsBase.__setattr__.
        self._impl.icon = icon
        self._impl.props._icon_html = None if icon is None else svg_from_icon(icon)
        self._queue_update("_icon_html", self._impl.props._icon_html)

    def _queue_update(self, name: str, value: Any) -> None:
        self._impl.gui_api._websock_interface.queue_message(
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
        if self._impl.removed:
            raise RuntimeError("Cannot attach a trigger callback to a removed CommandHandle.")
        self._impl.trigger_cb.append(func)
        return func

    def remove(self) -> None:
        """Remove this command from the command palette."""
        if self._impl.removed:
            warnings.warn(
                "Attempted to remove an already removed CommandHandle.",
                stacklevel=2,
            )
            return
        self._impl.removed = True
        gui_api = self._impl.gui_api
        gui_api._websock_interface.queue_message(RemoveCommandMessage(self._impl.uuid))
        gui_api._command_handle_from_uuid.pop(self._impl.uuid, None)
