from __future__ import annotations

import abc
import dataclasses
import math
import types
from functools import cached_property
from typing import (
    Any,
    ContextManager,
    Dict,
    Generic,
    Literal,
    Protocol,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

import numpy as np
import numpy.typing as npt

from .infra._messages import validated_protocol_value_copy


class HasProps(Protocol):
    props: Any  # One of the `*Props` objects in _messages.py.
    removed: bool  # Lifecycle flag; see AssignablePropsBase guard below.

    @property
    def state_lock(self) -> ContextManager[object]: ...

    """Shared owner lock for props, lifecycle, registries, and wire order."""


TImpl = TypeVar("TImpl", bound=HasProps)

_TUPLE_PROPERTY_MAX_ITEMS = 4096
"""Maximum variadic tuple items materialized by synchronized GUI props."""


def colors_to_uint8(colors: np.ndarray) -> npt.NDArray[np.uint8]:
    """Convert intensity values to uint8. We assume the range [0,1] for floats, and
    [0,255] for integers. Accepts any shape."""
    if colors.dtype == np.uint8:
        return colors
    if np.issubdtype(colors.dtype, np.floating):
        if not np.isfinite(colors).all():
            raise ValueError("Image values must be finite.")
        # Clip before scaling: a large but finite float16 would otherwise
        # overflow during multiplication and emit a RuntimeWarning even though
        # the documented result is simple saturation.
        return (np.clip(colors, 0, 1) * 255.0).astype(np.uint8)
    if np.issubdtype(colors.dtype, np.integer):
        return np.clip(colors, 0, 255).astype(np.uint8)
    raise TypeError("Image values must use an integer or floating dtype.")


class _null_transaction:
    """Allocation-free no-op context manager for ordinary assignable props."""

    def __enter__(self) -> object:
        return self

    def __exit__(self, *exc: object) -> None:
        del exc


class AssignablePropsBase(Generic[TImpl]):
    """Base class for all API objects with assignable properties."""

    _impl: TImpl

    def __init__(self, impl: TImpl):
        # Make sure arrays are copied to avoid shared references.
        # This will also make sure that our `np.array_equal` checks below work
        # correctly.
        for k, v in vars(impl.props).items():
            if isinstance(v, np.ndarray):
                setattr(impl.props, k, v.copy())

        # Store the implementation object.
        self._impl = impl

    def _cast_value_recursive(self, hint: Any, value: Any) -> Any:
        """Validate one public property value against its protocol annotation.

        Tuple properties retain the convenient list/tuple input form and are
        normalized recursively. Primitive and Literal fields are otherwise
        strict, preventing Python from queuing schema-invalid GUI updates.
        """
        if hint is Any:
            return validated_protocol_value_copy(value)
        if hint is type(None):
            if value is not None:
                raise TypeError("property value must be None")
            return None
        if hint is bool:
            if type(value) is not bool:
                raise TypeError("property value must be a bool")
            return value
        if hint is str:
            if type(value) is not str:
                raise TypeError("property value must be a string")
            return value
        if hint is bytes:
            if type(value) is not bytes:
                raise TypeError("property value must be bytes")
            return value
        if hint is int:
            if type(value) is not int:
                raise TypeError("property value must be an integer")
            return value
        if hint is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError("property value must be a number")
            try:
                converted = float(value)
            except OverflowError:
                raise ValueError("property value must be finite") from None
            if not math.isfinite(converted):
                raise ValueError("property value must be finite")
            return converted
        origin = get_origin(hint)
        if origin is Union or origin is types.UnionType:
            errors: list[Exception] = []
            for option in get_args(hint):
                try:
                    return self._cast_value_recursive(option, value)
                except (TypeError, ValueError) as error:
                    errors.append(error)
            for error in errors:
                if "one-dimensional tuple" in str(error):
                    raise TypeError(str(error)) from error
            raise TypeError(f"property value does not match {hint!r}") from errors[-1]

        if origin is Literal:
            if any(type(value) is type(option) and value == option for option in get_args(hint)):
                return value
            raise ValueError(f"property value must be one of {get_args(hint)!r}")

        if origin is tuple:
            args = get_args(hint)
            variadic = len(args) == 2 and args[1] is Ellipsis
            if type(value) is np.ndarray:
                if value.ndim != 1:
                    raise TypeError(
                        "numpy arrays are only accepted for one-dimensional tuple properties"
                    )
                item_count = int(value.shape[0])
                if variadic and item_count > _TUPLE_PROPERTY_MAX_ITEMS:
                    raise ValueError(
                        f"property value cannot contain more than {_TUPLE_PROPERTY_MAX_ITEMS} items"
                    )
                if not variadic and item_count != len(args):
                    raise ValueError(
                        f"property value must contain {len(args)} items, got {item_count}"
                    )
                value = value.tolist()
            elif isinstance(value, np.ndarray):
                raise TypeError("numpy array subclasses are not accepted for properties")
            if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
                raise TypeError("property value must be a sequence")
            if variadic:
                if len(value) > _TUPLE_PROPERTY_MAX_ITEMS:
                    raise ValueError(
                        f"property value cannot contain more than {_TUPLE_PROPERTY_MAX_ITEMS} items"
                    )
                item_hints = (args[0],) * len(value)
            else:
                if len(value) != len(args):
                    raise ValueError(
                        f"property value must contain {len(args)} items, got {len(value)}"
                    )
                item_hints = args
            return tuple(
                self._cast_value_recursive(item_hint, item)
                for item_hint, item in zip(item_hints, value)
            )

        if isinstance(value, np.ndarray):
            raise TypeError("numpy arrays are only accepted for one-dimensional tuple properties")

        if isinstance(hint, type) and dataclasses.is_dataclass(hint):
            if not isinstance(value, hint):
                raise TypeError(f"property value must be a {hint.__name__}")
            return value

        # No protocol property currently uses another runtime shape. Preserve
        # support for a future explicitly validated property setter rather than
        # inventing a coercion here.
        return value

    @cached_property
    def _prop_hints(self) -> Dict[str, Any]:
        return get_type_hints(type(self._impl.props))

    @abc.abstractmethod
    def _queue_update(self, name: str, value: Any) -> None:
        """Queue an update message with the property change."""

    def _on_prop_assigned(self, name: str) -> None:
        """Hook called after a props field is assigned and its update is queued.
        Subclasses can override to enforce cross-field invariants (e.g. keeping
        an array's dtype in sync with another field). No-op by default."""

    def _prop_assignment_transaction(self, name: str) -> ContextManager[object]:
        """Reserve owner resources around a temporary prospective props state."""
        del name
        return _null_transaction()

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_impl":
            return object.__setattr__(self, name, value)
        prop = getattr(self.__class__, name, None)
        prop_setter = prop.fset if isinstance(prop, property) and prop.fset is not None else None
        if prop_setter is not None:
            # Custom setters own their lock scope so callbacks can run after
            # state/wire commit without holding the shared GUI lock.
            prop_setter(self, value)
            return
        with self._impl.state_lock:
            self._setattr_locked(name, value)

    def _setattr_locked(self, name: str, value: Any) -> None:
        """Assign a protocol prop while the owner's shared lock is held."""
        is_prop_hint = name in self._prop_hints

        # Reject property writes after the handle has been removed. This prevents
        # stale update messages from being queued against a no-longer-registered
        # entity, which would otherwise re-introduce it on the client (ghost
        # entity) because the client blindly processes incoming updates. Guard
        # both the @property.setter path (e.g. `value` on GUI input handles) and
        # the _prop_hints path (generic props forwarded to _queue_update).
        if is_prop_hint and self._impl.removed:
            raise RuntimeError(f"Cannot assign to {name!r} on a removed {type(self).__name__}.")

        # Try to handle as a props field.
        if is_prop_hint:
            # Handle type casting (arrays, tuples of arrays, etc.).
            value = self._cast_value_recursive(self._prop_hints[name], value)
            current_value = getattr(self._impl.props, name)

            # Skip update if value hasn't changed.
            try:
                hash(current_value)
                if current_value == value:
                    return
            except (TypeError, ValueError):
                pass

            # Snapshot every prop because assignment hooks may update a related
            # field. On any queue or hook failure, restore the exact pre-call
            # state rather than leaving Python ahead of the wire.
            prop_snapshot = {
                key: (item, item.copy() if isinstance(item, np.ndarray) else item)
                for key, item in vars(self._impl.props).items()
            }

            # Update the value based on type.
            if isinstance(value, np.ndarray):
                if hasattr(current_value, "dtype"):
                    # Ensure consistent dtype.
                    if value.dtype != current_value.dtype:
                        value = value.astype(current_value.dtype)
                    if np.array_equal(current_value, value):
                        return

                # In-place update for same shape arrays.
                if hasattr(current_value, "shape") and value.shape == current_value.shape:
                    current_value[:] = value
                else:
                    setattr(self._impl.props, name, value.copy())
                # Queue a private snapshot for the wire. It must alias NEITHER the
                # caller's ``value`` (which the caller may mutate after assignment,
                # e.g. an animation loop reusing one buffer) NOR the server's stored
                # array (which a later same-shape update mutates in place, possibly
                # while the event-loop thread is still serializing this message).
                queued: Any = value.copy()
            else:
                # Non-array properties (immutable / already a fresh cast).
                setattr(self._impl.props, name, value)
                queued = value
        else:
            return object.__setattr__(self, name, value)

        try:
            # Queue the primary update while the temporary full props state is
            # visible (notification updates serialize all props), then commit
            # any purely local derived state in the hook.
            with self._prop_assignment_transaction(name):
                self._queue_update(name, queued)
                self._on_prop_assigned(name)
        except BaseException:
            for key, (original, snapshot) in prop_snapshot.items():
                if isinstance(original, np.ndarray):
                    original[...] = snapshot
                    setattr(self._impl.props, key, original)
                else:
                    setattr(self._impl.props, key, original)
            raise

    def __getattr__(self, name: str) -> Any:
        if name in self._prop_hints:
            with self._impl.state_lock:
                if self._impl.removed:
                    raise RuntimeError(
                        f"Cannot read {name!r} from a removed {type(self).__name__}."
                    )
                value = getattr(self._impl.props, name)
                return value.copy() if isinstance(value, np.ndarray) else value
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}.")
