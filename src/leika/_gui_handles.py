from __future__ import annotations

import base64
import dataclasses
import json
import re
import time
import uuid
import warnings
from collections.abc import Coroutine, Mapping
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
    CommandProps,
    CommandUpdateMessage,
    GuiBaseProps,
    GuiButtonGroupProps,
    GuiButtonProps,
    GuiCheckboxProps,
    GuiCloseModalMessage,
    GuiDividerProps,
    GuiDropdownProps,
    GuiFolderProps,
    GuiFormSubmitMessage,
    GuiHtmlProps,
    GuiImageProps,
    GuiMarkdownProps,
    GuiMultiSliderProps,
    GuiNumberProps,
    GuiPlotlyProps,
    GuiProgressBarProps,
    GuiRemoveMessage,
    GuiRgbaProps,
    GuiRgbProps,
    GuiSliderProps,
    GuiTabGroupProps,
    GuiTextProps,
    GuiToggleGroupProps,
    GuiToggleProps,
    GuiUpdateMessage,
    GuiUploadButtonProps,
    GuiUplotProps,
    GuiVector2Props,
    GuiVector3Props,
    RemoveCommandMessage,
)
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


class GuiContainerProtocol(Protocol):
    _children: dict[str, SupportsRemoveProtocol] = dataclasses.field(default_factory=dict)


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


@dataclasses.dataclass
class _GuiButtonHandleState(_GuiHandleState[bool]):
    """Internal API for button GUI elements with hold callback support."""

    hold_cbs_from_freq: dict[float, list[Callable[[GuiEvent], None | Coroutine]]] = (
        dataclasses.field(default_factory=dict)
    )
    """Mapping from frequency (Hz) to list of callbacks to call when button is held."""


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

        # Warn if already removed.
        if self._impl.removed:
            warnings.warn(
                f"Attempted to remove an already removed {self.__class__.__name__}.",
                stacklevel=2,
            )
            return
        self._impl.removed = True

        gui_api = self._impl.gui_api
        gui_api._websock_interface.queue_message(GuiRemoveMessage(self._impl.uuid))
        parent = gui_api._container_handle_from_uuid[self._impl.parent_container_id]
        parent._children.pop(self._impl.uuid)

        if isinstance(self, _GuiInputHandle):
            gui_api._gui_input_handle_from_uuid.pop(self._impl.uuid)


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
        # ^Note: we mark this property as private for Sphinx because I haven't
        # been able to get it to resolve the TypeVar in a readable way.
        # For the documentation's sake, we'll be manually adding ::attribute directives below.
        return self._impl.value

    def _coerce_assigned_value(self, value: T | np.ndarray) -> T | np.ndarray:
        """Hook for input-type-specific coercion of an assigned value. The base
        is identity; rgb/rgba handles override this to normalize colors."""
        return value

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
                self._impl.gui_api._event_loop.create_task(cb_out)

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


class GuiToggleGroupHandle(GuiInputHandle[Tuple[str, ...]], GuiToggleGroupProps):
    """Handle for a row of toggles.

    .. attribute:: value
       :type: tuple[str, ...]

       The options currently on, in the order they were declared. A tuple in
       both modes, so reading a group does not depend on how it was
       configured: with ``multiple=False`` it simply never holds more than one.
       Assigning turns exactly those options on and the rest off.
    """


class GuiCheckboxHandle(GuiInputHandle[bool], GuiCheckboxProps):
    """Handle for checkbox inputs.

    .. attribute:: value
       :type: bool

       Value of the input. Synchronized automatically when assigned.
    """


class GuiTextHandle(GuiInputHandle[str], GuiTextProps):
    """Handle for text inputs.

    .. attribute:: value
       :type: str

       Value of the input. Synchronized automatically when assigned.
    """


IntOrFloat = TypeVar("IntOrFloat", int, float)


class GuiNumberHandle(GuiInputHandle[IntOrFloat], Generic[IntOrFloat], GuiNumberProps):
    """Handle for number inputs.

    .. attribute:: value
       :type: IntOrFloat

       Value of the input. Synchronized automatically when assigned.
    """


class GuiSliderHandle(GuiInputHandle[IntOrFloat], Generic[IntOrFloat], GuiSliderProps):
    """Handle for slider inputs.

    .. attribute:: value
       :type: IntOrFloat

       Value of the input. Synchronized automatically when assigned.
    """


class GuiMultiSliderHandle(
    GuiInputHandle[Tuple[IntOrFloat, ...]], Generic[IntOrFloat], GuiMultiSliderProps
):
    """Handle for multi-slider inputs.

    .. attribute:: value
       :type: tuple[IntOrFloat, ...]

       Value of the input. Synchronized automatically when assigned.
    """


def _colors_to_int_tuple(value: Any) -> tuple[int, ...]:
    """Coerce an RGB/RGBA color to an int tuple in [0, 255].

    Integer channels are taken as absolute [0, 255]; float channels are
    interpreted as [0, 1] and scaled (the matplotlib convention), so ``1.0`` ->
    255 (white) but ``1`` -> 1. The result is clamped to [0, 255] -- matching
    ``colors_to_uint8`` -- so out-of-range inputs (e.g. a float ``255.0`` or a
    negative value) degrade gracefully instead of producing a wild value.
    Generalized to any channel count (RGB and RGBA)."""
    if isinstance(value, np.ndarray):
        assert value.ndim == 1, f"Expected a 1D color, got shape {value.shape}."
    return tuple(
        max(0, min(255, int(v) if np.issubdtype(type(v), np.integer) else int(v * 255)))
        for v in value
    )


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
        return cast(Tuple[int, int, int], _colors_to_int_tuple(value))


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
        return cast(Tuple[int, int, int, int], _colors_to_int_tuple(value))


class GuiVector2Handle(GuiInputHandle[Tuple[float, float]], GuiVector2Props):
    """Handle for 2D vector inputs.

    .. attribute:: value
       :type: tuple[float, float]

       Value of the input. Synchronized automatically when assigned.
    """


class GuiVector3Handle(GuiInputHandle[Tuple[float, float, float]], GuiVector3Props):
    """Handle for 3D vector inputs.

    .. attribute:: value
       :type: tuple[float, float, float]

       Value of the input. Synchronized automatically when assigned.
    """


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
        """Compatibility view of the affected handle value."""
        return getattr(self.target, "value", True)


class GuiButtonHandle(_GuiInputHandle[bool], GuiButtonProps):
    """Handle for a button input in our visualizer.

    .. attribute:: value
       :type: bool

       Value of the button. Set to `True` when the button is pressed. Can be manually set back to `False`.
    """

    def __init__(self, _impl: _GuiButtonHandleState, _icon: IconName | None):
        super().__init__(impl=_impl)
        self._icon = _icon

    @property
    def _button_impl(self) -> _GuiButtonHandleState:
        """Access the button-specific implementation state."""
        assert isinstance(self._impl, _GuiButtonHandleState)
        return self._impl

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
        button_impl = self._button_impl

        def register_callback(
            f: GuiButtonHandle._HoldCallback,
        ) -> GuiButtonHandle._HoldCallback:
            # Add callback to the frequency-specific list.
            if callback_hz not in button_impl.hold_cbs_from_freq:
                button_impl.hold_cbs_from_freq[callback_hz] = []
            button_impl.hold_cbs_from_freq[callback_hz].append(f)

            # Update the prop to notify client of new frequency.
            self._hold_callback_freqs = tuple(button_impl.hold_cbs_from_freq.keys())

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
    def disabled(self) -> bool:
        """Button groups cannot be disabled."""
        return False

    @disabled.setter
    def disabled(self, disabled: bool) -> None:  # type: ignore
        """Button groups cannot be disabled."""
        assert not disabled, "Button groups cannot be disabled."


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
        options = tuple(options)
        if len(options) == 0:
            raise ValueError("Dropdown requires at least one option.")
        self._impl.props.options = options

        self._impl.gui_api._websock_interface.queue_message(
            GuiUpdateMessage(
                self._impl.uuid,
                {"options": options},
            )
        )
        if self.value not in options:
            self.value = options[0]


class GuiTabGroupHandle(_GuiHandle[None], GuiTabGroupProps):
    """Handle for a tab group. Call :meth:`add_tab()` to add a tab."""

    def __init__(self, _impl: _GuiHandleState[None]) -> None:
        super().__init__(impl=_impl)
        self._tab_handles: list[GuiTabHandle] = []

    def add_tab(self, label: str, icon: IconName | None = None) -> GuiTabHandle:
        """Add a tab. Returns a handle we can use to add GUI elements to it."""

        uuid = _make_uuid()

        # We may want to make this thread-safe in the future.
        out = GuiTabHandle(_parent=self, _id=uuid, _label=label, _icon=icon)

        self._tab_handles.append(out)
        self._tab_labels = self._tab_labels + (label,)
        self._tab_icons_html = self._tab_icons_html + (
            None if icon is None else svg_from_icon(icon),
        )
        self._tab_container_ids = tuple(handle._id for handle in self._tab_handles)
        return out

    def __post_init__(self) -> None:
        parent = self._impl.gui_api._container_handle_from_uuid[self._impl.parent_container_id]
        parent._children[self._impl.uuid] = self

    def remove(self) -> None:
        """Remove this tab group and all contained GUI elements."""
        # Warn if already removed.
        if self._impl.removed:
            warnings.warn(
                f"Attempted to remove an already removed {self.__class__.__name__}.",
                stacklevel=2,
            )
            return

        # Remove tabs first. Each tab.remove() writes back to this group's
        # tab-list props (_tab_labels / _tab_icons_html / _tab_container_ids), so
        # we must NOT mark the group removed until afterwards -- otherwise the
        # removed-handle guard in AssignablePropsBase raises on those writes, leaving
        # the group half-removed (still in its parent's _children with
        # removed=True). A subsequent gui.reset() then spins forever, since its
        # `while root._children: child.remove()` loop hits that group whose
        # remove() now no-ops via the already-removed guard.
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
        self._icon = icon
        # Find the index of this tab in the parent's tab list.
        tab_index = self._parent._tab_handles.index(self)
        # Update the icon HTML in the parent's tuple.
        icons_list = list(self._parent._tab_icons_html)
        icons_list[tab_index] = None if icon is None else svg_from_icon(icon)
        self._parent._tab_icons_html = tuple(icons_list)

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

        # We may want to make this thread-safe in the future.
        found_index = -1
        for i, tab in enumerate(self._parent._tab_handles):
            if tab is self:
                found_index = i
                break
        assert found_index != -1, "Tab already removed!"

        self._parent._tab_labels = (
            self._parent._tab_labels[:found_index] + self._parent._tab_labels[found_index + 1 :]
        )
        self._parent._tab_icons_html = (
            self._parent._tab_icons_html[:found_index]
            + self._parent._tab_icons_html[found_index + 1 :]
        )
        self._parent._tab_handles = (
            self._parent._tab_handles[:found_index] + self._parent._tab_handles[found_index + 1 :]
        )
        # Keep the container-id list in sync with the handles. Otherwise the
        # client receives mismatched `_tab_labels` / `_tab_container_ids`
        # lengths and renders a stale (orphaned) tab panel.
        self._parent._tab_container_ids = tuple(handle._id for handle in self._parent._tab_handles)

        for child in tuple(self._children.values()):
            child.remove()
        self._parent._impl.gui_api._container_handle_from_uuid.pop(self._id)


class GuiFolderHandle(_GuiHandle[None], GuiFolderProps, GuiContainer):
    """Use as a context to place GUI elements into a folder."""

    def __init__(self, _impl: _GuiHandleState[None]) -> None:
        super().__init__(impl=_impl)
        self._impl.gui_api._container_handle_from_uuid[self._impl.uuid] = self
        self._children = {}
        parent = self._impl.gui_api._container_handle_from_uuid[self._impl.parent_container_id]
        parent._children[self._impl.uuid] = self

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
    """Every input under `container`, however deeply folders or tabs nest it.

    Buttons are excluded: their "value" is the fact of a press, so there is
    nothing about one to remember or put back."""
    for child in getattr(container, "_children", {}).values():
        if isinstance(child, _GuiInputHandle) and not child._impl.is_button:
            yield child
        yield from _fields_within(child)


class GuiFormHandle(GuiFolderHandle):
    """Use as a context to place GUI elements into a form.

    A form is a container whose children's values can be committed together by
    calling :meth:`submit_form` (typically from a button's ``on_click`` handler) or
    by pressing Enter in a single-line text input inside the form.

    It takes ONE row in the panel: its ``label``, and a button that opens the
    fields in a popout. A form is one question asked in several parts, and the
    parts belong together and apart from the live controls around them -- so
    they are somewhere else, and the row is the way in.

    The popout ends in the form's two ways out, a Reset and a Submit added as
    the form's last child and reachable as ``form.actions``: start the answer
    again (:meth:`reset_form`), or give it (:meth:`submit_form`).

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
        # What Reset puts back. Read here rather than at reset time, because by
        # then the field holds whatever was typed into it: a field is at its
        # declared value the moment it is created, and this is the first look
        # at it after that. Fields added later are picked up on their own exit.
        for field in _fields_within(self):
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
        gui_api = self._impl.gui_api
        # Fire on_submit callbacks. Server-initiated submits have no client.
        for cb in self._submit_cb:
            cb_out = cb(GuiEvent(client_id=None, client=None, target=self))
            if isinstance(cb_out, Coroutine):
                gui_api._event_loop.create_task(cb_out)
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
        """Close this modal and permananently remove all contained GUI elements."""
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
        import imageio.v3 as iio

        image = iio.imread(image_root / url)
        _, binary = encode_image_binary(image, "png")
        url = base64.b64encode(binary).decode("utf-8")
        return f"data:image/png;base64,{url}"
    except (IOError, FileNotFoundError):
        warnings.warn(
            f"Failed to read image {url}, with image_root set to {image_root}.",
            stacklevel=2,
        )
        return url


def _parse_markdown(markdown: str, image_root: Path | None) -> str:
    markdown = re.sub(
        r"\!\[([^]]*)\]\(([^]]*)\)",
        lambda match: f"![{match.group(1)}]({_get_data_url(match.group(2), image_root)})",
        markdown,
    )
    return markdown


class GuiProgressBarHandle(_GuiInputHandle[float], GuiProgressBarProps):
    """Handle for updating and removing progress bars."""


class GuiMarkdownHandle(_GuiHandle[None], GuiMarkdownProps):
    """Handling for updating and removing markdown elements."""

    def __init__(self, _impl: _GuiHandleState, _content: str, _image_root: Path | None):
        super().__init__(impl=_impl)
        self._content = _content
        self._image_root = _image_root

    @property
    def content(self) -> str:
        """Current content of this markdown element. Synchronized automatically when assigned."""
        assert self._content is not None
        return self._content

    @content.setter
    def content(self, content: str) -> None:
        self._content = content
        self._markdown = _parse_markdown(content, self._image_root)


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


class GuiUplotHandle(_GuiHandle[None], GuiUplotProps):
    """Handle for updating and removing Uplot figures."""

    pass


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
        self._image = _image
        self._jpeg_quality = _jpeg_quality
        self._user_format = _user_format

    @property
    def image(self) -> np.ndarray:
        """Current content of this image element. Synchronized automatically when assigned."""
        assert self._image is not None
        return self._image

    @image.setter
    def image(self, image: np.ndarray) -> None:
        self._image = image
        resolved_format, data = encode_image_binary(
            image, self._user_format, jpeg_quality=self._jpeg_quality
        )
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

        self._user_format = value

        # Re-encode image.
        if value == "jpeg" and self._image.shape[2] == 4:
            warnings.warn("Converting RGBA image to JPEG will discard the alpha channel.")
        resolved_format, data = encode_image_binary(
            self._image, value, jpeg_quality=self._jpeg_quality
        )
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
