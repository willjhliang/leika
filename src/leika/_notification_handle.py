from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import math
import weakref
from typing import Any

from typing_extensions import override

from . import _messages
from ._gui_handles import _Change, _Removable
from ._messages import (
    NotificationProps,
    NotificationUpdateMessage,
    RemoveNotificationMessage,
)

_MAX_AUTO_CLOSE_SECONDS = 2_147_483.647
"""The longest delay a browser timer accepts."""


def validate_auto_close_seconds(value: object) -> float | None:
    """Validate and normalize a notification timeout."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("auto_close_seconds must be a number or None.")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 <= normalized <= _MAX_AUTO_CLOSE_SECONDS:
        raise ValueError("auto_close_seconds must be within [0, 2147483.647] seconds or None.")
    return normalized


class NotificationHandle(_Removable[None], NotificationProps):
    """Synchronize and permanently retire a scoped notification.

    The server keeps the browser's auto-close deadline too, so a notification
    that has closed itself is not replayed to browsers that connect later.
    Each update restarts that deadline. Loading notifications, and timeouts of
    None or 0, remain until a later update or explicit removal.
    """

    _message_type = _messages.NotificationShowMessage
    _expiry_generation: int = 0
    _expiry_timer: asyncio.TimerHandle | None = None
    """The pending deadline; only the event loop touches it."""

    @override
    def _validate(self, props: Any, value: None) -> tuple[Any, None]:
        auto_close_seconds = validate_auto_close_seconds(props.auto_close_seconds)
        return dataclasses.replace(props, auto_close_seconds=auto_close_seconds), value

    @override
    def _update_message(self, updates: dict[str, Any], props: Any) -> _messages.Message:
        # The full props each time, so the client shares the show path.
        return NotificationUpdateMessage(self._impl.uuid, props)

    @override
    def _removal_message(self) -> _messages.Message:
        return RemoveNotificationMessage(self._impl.uuid)

    @override
    def _prepare(self, changes: dict[str, Any]) -> _Change | None:
        # Every update restarts the deadline, in the browser too, so even an
        # unchanged one is published.
        change = super()._prepare(changes)
        if change is None:
            props = self._impl.props
            change = _Change(props, None, None, dataclasses.asdict(props), False)
        return change

    @override
    def _apply(self, change: _Change) -> None:
        super()._apply(change)
        self._restart_expiry()

    @override
    def _retire(self) -> None:
        super()._retire()
        self._restart_expiry()

    def _restart_expiry(self) -> None:
        """Replace the deadline mirroring the browser's toast timer; a removed,
        loading, or persistent notification has none. The timer holds this
        handle only weakly."""
        self._expiry_generation += 1
        generation = self._expiry_generation
        props = self._impl.props
        delay = props.auto_close_seconds
        if self._impl.removed or props.loading or not delay:
            delay = None
        handle = weakref.ref(self)
        loop = self._impl.gui_api._event_loop

        def expire() -> None:
            notification = handle()
            if notification is not None:
                notification._expire(generation)

        def install() -> None:
            notification = handle()
            if notification is None:
                return
            if notification._expiry_timer is not None:
                notification._expiry_timer.cancel()
            notification._expiry_timer = None if delay is None else loop.call_later(delay, expire)

        loop.call_soon_threadsafe(install)

    def _expire(self, generation: int) -> None:
        with self._impl.gui_api._lock:
            if self._impl.removed or generation != self._expiry_generation:
                return
            # The server can finish stopping between the timer and the removal.
            with contextlib.suppress(RuntimeError):
                self._remove()
