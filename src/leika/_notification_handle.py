from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import math
import warnings
import weakref
from asyncio import AbstractEventLoop
from typing import Any, Callable, ContextManager

from typing_extensions import override

from ._assignable_props_api import AssignablePropsBase
from ._messages import (
    NotificationProps,
    NotificationShowMessage,
    NotificationUpdateMessage,
    RemoveNotificationMessage,
)
from ._validation import validate_renderer_string
from .infra._infra import WebsockMessageHandler


@dataclasses.dataclass
class _NotificationHandleState:
    websock_interface: WebsockMessageHandler
    event_loop: AbstractEventLoop
    uuid: str
    props: NotificationProps
    state_lock: ContextManager[object]
    on_terminal: Callable[[str], None] = lambda _uuid: None
    resource_transaction: Callable[[NotificationProps], ContextManager[object]] = lambda _props: (
        contextlib.nullcontext()
    )
    removed: bool = False
    expiry_generation: int = 0
    expiry_handle: asyncio.TimerHandle | None = None


_MAX_AUTO_CLOSE_SECONDS = 2_147_483.647


def validate_auto_close_seconds(value: object) -> float | None:
    """Validate and normalize a notification timeout."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("auto_close_seconds must be a number or None.")
    try:
        normalized = float(value)
    except OverflowError as error:
        raise ValueError(
            "auto_close_seconds must be a finite non-negative number or None."
        ) from error
    if not math.isfinite(normalized) or normalized < 0.0 or normalized > _MAX_AUTO_CLOSE_SECONDS:
        raise ValueError("auto_close_seconds must be within [0, 2147483.647] seconds or None.")
    return normalized


def _scrub_notification_state_locked(state: _NotificationHandleState) -> None:
    """Drop charged strings, timer state, and owner closures terminally."""
    if state.expiry_handle is not None:
        state.expiry_handle.cancel()
        state.expiry_handle = None
    state.props = NotificationProps(
        title="",
        body="",
        loading=False,
        with_close_button=False,
        auto_close_seconds=None,
    )
    state.on_terminal = lambda _uuid: None
    state.resource_transaction = lambda _props: contextlib.nullcontext()


class NotificationHandle(NotificationProps, AssignablePropsBase[_NotificationHandleState]):
    """Synchronize and permanently retire a scoped notification."""

    def __init__(self, impl: _NotificationHandleState) -> None:
        self._impl = impl

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_impl" and hasattr(self, "_impl") and name in self._prop_hints:
            self.update(**{name: value})
            return
        super().__setattr__(name, value)

    @property
    def id(self) -> str:
        """Stable identifier for this notification."""

        return self._impl.uuid

    def update(self, **props: Any) -> None:
        """Atomically update one or more notification properties.

        A successful update restarts the browser and server expiry deadline.
        Loading notifications, and timeouts of None or 0, remain until a later
        update or explicit removal.
        """
        with self._impl.state_lock:
            if self._impl.removed:
                raise RuntimeError("Cannot update a removed NotificationHandle.")
            normalized: dict[str, Any] = {}
            for name, value in props.items():
                if name not in self._prop_hints:
                    raise TypeError(
                        f"NotificationHandle.update() got an unknown property {name!r}."
                    )
                if name == "auto_close_seconds":
                    value = validate_auto_close_seconds(value)
                normalized[name] = self._cast_value_recursive(self._prop_hints[name], value)
            candidate = dataclasses.replace(self._impl.props, **normalized)
            validate_renderer_string(candidate.title, "notification title")
            validate_renderer_string(candidate.body, "notification body")
            old_props = self._impl.props
            with self._impl.resource_transaction(candidate):
                self._impl.websock_interface.queue_message_or_raise(
                    NotificationUpdateMessage(self._impl.uuid, candidate)
                )
                self._impl.props = candidate
                try:
                    self._restart_expiry_locked()
                except Exception:
                    self._impl.props = old_props
                    # Restore the authoritative full-props update. Its redundancy
                    # key replaces the candidate before either can be delivered.
                    self._impl.websock_interface.queue_message_or_raise(
                        NotificationUpdateMessage(self._impl.uuid, old_props)
                    )
                    raise

    @override
    def _queue_update(self, name: str, value: Any) -> None:
        # Send the full props each time; the redundancy key collapses
        # successive updates to "latest wins".
        del name, value
        self._impl.websock_interface.queue_message_or_raise(
            NotificationUpdateMessage(self._impl.uuid, self._impl.props)
        )

    def _show(self) -> None:
        """Emit the initial NotificationShowMessage."""
        with self._impl.state_lock:
            if self._impl.removed:
                raise RuntimeError("Cannot show a removed NotificationHandle.")
            self._impl.websock_interface.queue_message_or_raise(
                NotificationShowMessage(self._impl.uuid, self._impl.props)
            )
            try:
                self._restart_expiry_locked()
            except Exception:
                self._impl.websock_interface.queue_message_or_raise(
                    RemoveNotificationMessage(self._impl.uuid)
                )
                raise

    def _scrub_terminal_locked(self) -> None:
        _scrub_notification_state_locked(self._impl)

    def _restart_expiry_locked(self) -> None:
        """Mirror the browser toast deadline without retaining this handle."""
        state = self._impl
        generation = state.expiry_generation + 1
        old_handle = state.expiry_handle
        state.expiry_generation = generation
        state.expiry_handle = None
        timeout = state.props.auto_close_seconds
        delay = 0.0 if timeout is None else float(timeout)
        should_expire = (
            not state.removed and not state.props.loading and timeout is not None and timeout > 0.0
        )
        state_ref = weakref.ref(state)

        def _install() -> None:
            if old_handle is not None:
                old_handle.cancel()
            current = state_ref()
            if current is None:
                return
            with current.state_lock:
                if current.removed or current.expiry_generation != generation or not should_expire:
                    return

                def _expire() -> None:
                    expiring = state_ref()
                    if expiring is None:
                        return
                    with expiring.state_lock:
                        if expiring.removed or expiring.expiry_generation != generation:
                            return
                        expiring.expiry_handle = None
                        try:
                            expiring.websock_interface.queue_message_or_raise(
                                RemoveNotificationMessage(expiring.uuid)
                            )
                            # A tombstone retires replay state permanently; a
                            # later update would be an orphan that no future
                            # client could apply.
                            expiring.removed = True
                            expiring.expiry_generation += 1
                            try:
                                expiring.on_terminal(expiring.uuid)
                            finally:
                                _scrub_notification_state_locked(expiring)
                        except RuntimeError:
                            # The server can finish shutting down between the
                            # timer callback and message admission.
                            return

                current.expiry_handle = current.event_loop.call_later(delay, _expire)

        try:
            state.event_loop.call_soon_threadsafe(_install)
        except Exception:
            state.expiry_generation -= 1
            state.expiry_handle = old_handle
            raise

    def _retire_without_queue(self) -> None:
        """Terminally release an owner whose connection can no longer receive."""
        with self._impl.state_lock:
            if self._impl.removed:
                return
            self._impl.removed = True
            self._impl.expiry_generation += 1
            if self._impl.expiry_handle is not None:
                self._impl.expiry_handle.cancel()
                self._impl.expiry_handle = None
            try:
                self._impl.on_terminal(self._impl.uuid)
            finally:
                self._scrub_terminal_locked()

    def remove(self) -> None:
        """Permanently remove this notification.

        Repeated removal is harmless and emits a warning.
        """
        with self._impl.state_lock:
            if self._impl.removed:
                warnings.warn(
                    "Attempted to remove an already removed NotificationHandle.",
                    stacklevel=2,
                )
                return
            self._impl.websock_interface.queue_message_or_raise(
                RemoveNotificationMessage(self._impl.uuid)
            )
            self._impl.removed = True
            self._impl.expiry_generation += 1
            try:
                self._impl.on_terminal(self._impl.uuid)
            finally:
                self._scrub_terminal_locked()
