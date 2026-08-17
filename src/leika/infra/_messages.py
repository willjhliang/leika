"""Message serialization shared by the Python and TypeScript protocol."""

from __future__ import annotations

import abc
import copy
import dataclasses
import functools
import math
import sys
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
    cast,
)

import msgspec.msgpack
import numpy as np
from typing_extensions import get_args, get_origin, get_type_hints

if TYPE_CHECKING:
    from ._infra import ClientId
else:
    ClientId = Any


_DECODED_NODE_LIMIT = 100_000
_DECODED_CONTAINER_ITEMS_LIMIT = 65_536
_DECODED_DEPTH_LIMIT = 64
_DECODED_PAYLOAD_BYTES_LIMIT = 4 * 1024 * 1024
_OUTBOUND_PREFLIGHT_METADATA_BYTES_LIMIT = 256 * 1024 * 1024
_OUTBOUND_PREFLIGHT_RAW_BYTES_LIMIT = 512 * 1024 * 1024
_OUTBOUND_PREFLIGHT_BINARY_BUFFER_LIMIT = 16_384
_JAVASCRIPT_SAFE_INTEGER_MAX = (1 << 53) - 1
_BROWSER_ARRAY_DTYPES = frozenset(
    {"|b1", "|u1", "|i1", "<u2", "<u4", "<i2", "<i4", "<f2", "<f4", "<f8"}
)
"""Exact NumPy storage formats understood by the bundled browser decoder."""


def _validate_decoded_shape(value: object) -> None:
    """Bound decoded amplification and reject values outside MessagePack JSON."""
    nodes = 0
    payload_bytes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _DECODED_NODE_LIMIT:
            raise ValueError("decoded protocol message contains too many values")
        if depth > _DECODED_DEPTH_LIMIT:
            raise ValueError("decoded protocol message is nested too deeply")
        if item is None or type(item) is bool:
            pass
        elif type(item) is str:
            payload_bytes += len(item.encode("utf-8"))
        elif type(item) is int:
            if abs(item) > _JAVASCRIPT_SAFE_INTEGER_MAX:
                raise ValueError("protocol integers must be JavaScript-safe")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("protocol numbers must be finite")
        elif type(item) is bytes:
            payload_bytes += len(item)
        elif type(item) is dict:
            if len(item) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("decoded protocol mapping contains too many items")
            if any(type(key) is not str for key in item):
                raise TypeError("decoded protocol mapping keys must be strings")
            stack.extend((key, depth + 1) for key in item)
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            if len(item) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("decoded protocol sequence contains too many items")
            stack.extend((child, depth + 1) for child in item)
        else:
            raise TypeError(f"unsupported decoded protocol value: {type(item).__name__}")
        if payload_bytes > _DECODED_PAYLOAD_BYTES_LIMIT:
            raise ValueError("decoded protocol string and binary payload is too large")


def _type_error(annotation: object, value: object) -> TypeError:
    return TypeError(f"expected {annotation!r}, got {type(value).__name__}")


def _prepare_for_deserialization(value: Any, annotation: Type) -> Any:
    """Validate and reconstruct one untrusted wire value from its schema type.

    Msgpack decoding only establishes broad runtime containers. This pass is
    the protocol trust boundary: scalar types are exact (bool isn't an int),
    literals are restricted to their declared values, and every nested
    dataclass/container is checked recursively before a handler sees it.
    Any remains intentionally dynamic for property-delta payloads whose
    per-component handlers own the narrower validation.
    """
    if annotation is Any:
        return value
    if annotation is type(None):
        if value is not None:
            raise _type_error(annotation, value)
        return None
    if annotation is bool:
        if type(value) is not bool:
            raise _type_error(annotation, value)
        return value
    if annotation is str:
        if type(value) is not str:
            raise _type_error(annotation, value)
        return value
    if annotation is bytes:
        if type(value) is not bytes:
            raise _type_error(annotation, value)
        return value
    if annotation is int:
        if type(value) is not int:
            raise _type_error(annotation, value)
        if abs(value) > _JAVASCRIPT_SAFE_INTEGER_MAX:
            raise ValueError("protocol integers must be JavaScript-safe")
        return value
    if annotation is float:
        # Python and TypeScript both represent integral and fractional JSON /
        # msgpack numbers under one number type, while excluding booleans.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _type_error(annotation, value)
        try:
            prepared = float(value)
        except OverflowError:
            raise ValueError("protocol numbers must be finite") from None
        if not math.isfinite(prepared):
            raise ValueError("protocol numbers must be finite")
        return prepared

    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        errors: list[TypeError] = []
        for option in get_args(annotation):
            try:
                return _prepare_for_deserialization(value, option)
            except TypeError as error:
                errors.append(error)
        raise _type_error(annotation, value) from errors[-1] if errors else None

    # Literal's origin may come from typing or typing_extensions because
    # callers can publicly define protocol dataclasses with either spelling.
    if str(origin) in ("typing.Literal", "typing_extensions.Literal"):
        if any(type(value) is type(option) and value == option for option in get_args(annotation)):
            return value
        raise _type_error(annotation, value)

    if origin is tuple:
        args = get_args(annotation)
        if not args:
            raise TypeError(f"Tuple annotation must have type arguments, got {annotation!r}")
        if not isinstance(value, (list, tuple)):
            raise _type_error(annotation, value)
        if len(args) == 2 and args[1] is Ellipsis:
            item_annotations = (args[0],) * len(value)
        else:
            if len(value) != len(args):
                raise TypeError(f"expected {annotation!r} with {len(args)} items, got {len(value)}")
            item_annotations = args
        return tuple(
            _prepare_for_deserialization(item, item_annotation)
            for item, item_annotation in zip(value, item_annotations)
        )

    if origin is list:
        if type(value) is not list:
            raise _type_error(annotation, value)
        (item_annotation,) = get_args(annotation)
        return [_prepare_for_deserialization(item, item_annotation) for item in value]

    if origin is dict:
        if type(value) is not dict:
            raise _type_error(annotation, value)
        key_annotation, item_annotation = get_args(annotation)
        return {
            _prepare_for_deserialization(key, key_annotation): (
                _prepare_for_deserialization(item, item_annotation)
            )
            for key, item in value.items()
        }

    if dataclasses.is_dataclass(annotation):
        if type(value) is not dict:
            raise _type_error(annotation, value)
        hints = get_type_hints_cached(annotation)
        fields = {field.name: field for field in dataclasses.fields(annotation)}
        unknown = set(value) - set(fields)
        if unknown:
            raise TypeError(f"unexpected field(s) for {annotation.__name__}: {sorted(unknown)!r}")
        prepared = {
            key: _prepare_for_deserialization(item, hints[key]) for key, item in value.items()
        }
        # Construct declared inputs first, honoring defaults, then restore the
        # canonical wire values of init=False fields without assuming a mutable
        # instance dictionary (slotted/frozen records are supported).
        instance = annotation(**{key: item for key, item in prepared.items() if fields[key].init})
        for key, item in prepared.items():
            if not fields[key].init:
                object.__setattr__(instance, key, item)
        return instance

    raise TypeError(f"unsupported protocol annotation: {annotation!r}")


def _validate_outbound_shape(value: object) -> tuple[int, int, int, int]:
    """Bound/cycle-check a value and return nodes, metadata, raw bytes, buffers."""
    nodes = 0
    metadata_bytes = 0
    raw_bytes = 0
    binary_buffers = 0
    active: set[int] = set()
    # The boolean marks a post-order exit used to maintain active-path identity
    # rather than a global seen set; harmless shared subobjects remain valid.
    stack: list[tuple[object, int, bool]] = [(value, 0, False)]
    while stack:
        item, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > _DECODED_NODE_LIMIT:
            raise ValueError("protocol message contains too many values")
        if depth > _DECODED_DEPTH_LIMIT:
            raise ValueError("protocol message is nested too deeply")

        children: list[object] | None = None
        if item is None or type(item) is bool:
            metadata_bytes += 1
        elif type(item) is str:
            # ASCII length is a zero-allocation lower bound. Add only the UTF-8
            # continuation-byte delta, stopping once admission is impossible.
            metadata_bytes += len(item) + 5
            if metadata_bytes <= _OUTBOUND_PREFLIGHT_METADATA_BYTES_LIMIT:
                for character in item:
                    codepoint = ord(character)
                    if codepoint >= 0x80:
                        metadata_bytes += (
                            1 if codepoint < 0x800 else 2 if codepoint < 0x10000 else 3
                        )
                        if metadata_bytes > _OUTBOUND_PREFLIGHT_METADATA_BYTES_LIMIT:
                            break
        elif isinstance(item, (int, np.integer)) and not isinstance(item, bool):
            metadata_bytes += 9
        elif isinstance(item, (float, np.floating)):
            metadata_bytes += 9
        elif type(item) is bytes:
            metadata_bytes += len(item) + 5
        elif type(item) is np.ndarray:
            _validate_ndarray_storage(item)
            metadata_bytes += 64
            raw_bytes += item.nbytes
            binary_buffers += 1
        elif dataclasses.is_dataclass(item) and not isinstance(item, type):
            fields = dataclasses.fields(item)
            if len(fields) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("protocol dataclass contains too many fields")
            metadata_bytes += 5 + sum(len(field.name) + 5 for field in fields)
            children = [getattr(item, field.name) for field in fields]
        elif type(item) is dict:
            mapping = cast(dict[object, object], item)
            if len(mapping) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("protocol mapping contains too many items")
            if any(type(key) is not str for key in mapping):
                raise TypeError("protocol dynamic mapping keys must be strings")
            metadata_bytes += 5
            children = [child for pair in mapping.items() for child in pair]
        elif type(item) in (list, tuple):
            sequence = cast(list[object] | tuple[object, ...], item)
            if len(sequence) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("protocol sequence contains too many items")
            metadata_bytes += 5
            children = list(sequence)
        else:
            raise TypeError(f"unsupported outbound protocol value: {type(item).__name__}")

        if metadata_bytes > _OUTBOUND_PREFLIGHT_METADATA_BYTES_LIMIT:
            raise ValueError("protocol message metadata exceeds the client size limit")
        if raw_bytes > _OUTBOUND_PREFLIGHT_RAW_BYTES_LIMIT:
            raise ValueError("protocol message binary data exceeds the client size limit")
        if binary_buffers > _OUTBOUND_PREFLIGHT_BINARY_BUFFER_LIMIT:
            raise ValueError("protocol message contains too many binary buffers")

        if children is None:
            continue
        identity = id(item)
        if identity in active:
            raise ValueError("protocol message contains a reference cycle")
        active.add(identity)
        stack.append((item, depth, True))
        stack.extend((child, depth + 1, False) for child in reversed(children))
    return nodes, metadata_bytes, raw_bytes, binary_buffers


def _bounded_protocol_snapshot(
    value: object,
    *,
    metadata_limit: int,
    raw_limit: int,
) -> object:
    """Copy a validated protocol graph without user deepcopy hooks.

    Caller-owned containers may mutate after the first validation pass. This
    copier therefore applies its own depth/node/byte accounting while building
    the immutable transport snapshot, and checks ndarray size before copying
    any storage.
    """
    nodes = 0
    metadata = 0
    raw = 0
    active: set[int] = set()

    def visit(item: object, depth: int) -> object:
        nonlocal nodes, metadata, raw
        nodes += 1
        metadata += 256
        if nodes > _DECODED_NODE_LIMIT:
            raise ValueError("protocol message contains too many values")
        if depth > _DECODED_DEPTH_LIMIT:
            raise ValueError("protocol message is nested too deeply")

        if item is None or type(item) in (bool, int, float):
            out = item
        elif isinstance(item, (np.integer, np.floating)):
            out = item
        elif type(item) is str:
            metadata += len(item)
            if metadata <= metadata_limit:
                for character in item:
                    codepoint = ord(character)
                    if codepoint >= 0x80:
                        metadata += 1 if codepoint < 0x800 else 2 if codepoint < 0x10000 else 3
                        if metadata > metadata_limit:
                            break
            out = item
        elif type(item) is bytes:
            metadata += len(item)
            out = item
        elif type(item) is np.ndarray:
            _validate_ndarray_storage(item)
            raw += int(item.nbytes) + 7
            if raw > raw_limit:
                raise ValueError("message snapshot binary data exceeds its preparation limit")
            shape = item.shape
            dtype = item.dtype
            out = np.empty(shape, dtype=dtype, order="C")
            np.copyto(out, item, casting="no")
            if item.shape != shape or item.dtype != dtype:
                raise ValueError("protocol ndarray changed while it was snapshotted")
        elif dataclasses.is_dataclass(item) and not isinstance(item, type):
            identity = id(item)
            if identity in active:
                raise ValueError("protocol message contains a reference cycle")
            active.add(identity)
            try:
                item_type = type(item)
                out = object.__new__(item_type)
                for field in dataclasses.fields(item):
                    object.__setattr__(out, field.name, visit(getattr(item, field.name), depth + 1))
                if isinstance(item, Message):
                    excluded = getattr(item, "excluded_self_client", None)
                    if excluded is not None:
                        object.__setattr__(out, "excluded_self_client", excluded)
                    cache = getattr(item, "__dict__", {}).get("_cached_redundancy_key")
                    if cache is not None:
                        object.__setattr__(out, "_cached_redundancy_key", cache)
            finally:
                active.remove(identity)
        elif type(item) is list:
            sequence = cast(list[object], item)
            identity = id(sequence)
            if identity in active:
                raise ValueError("protocol message contains a reference cycle")
            if len(sequence) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("protocol sequence contains too many items")
            active.add(identity)
            try:
                out = [visit(child, depth + 1) for child in sequence]
            finally:
                active.remove(identity)
        elif type(item) is tuple:
            sequence = cast(tuple[object, ...], item)
            identity = id(sequence)
            if identity in active:
                raise ValueError("protocol message contains a reference cycle")
            if len(sequence) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("protocol sequence contains too many items")
            active.add(identity)
            try:
                out = tuple(visit(child, depth + 1) for child in sequence)
            finally:
                active.remove(identity)
        elif type(item) is dict:
            mapping = cast(dict[object, object], item)
            identity = id(mapping)
            if identity in active:
                raise ValueError("protocol message contains a reference cycle")
            if len(mapping) > _DECODED_CONTAINER_ITEMS_LIMIT:
                raise ValueError("protocol mapping contains too many items")
            if any(type(key) is not str for key in mapping):
                raise TypeError("protocol dynamic mapping keys must be strings")
            active.add(identity)
            try:
                copied: dict[str, object] = {}
                for key, child in mapping.items():
                    copied_key = visit(key, depth + 1)
                    if type(copied_key) is not str:
                        raise TypeError("protocol dynamic mapping keys must be strings")
                    if copied_key in copied:
                        raise ValueError("protocol mapping changed to contain a duplicate key")
                    copied[copied_key] = visit(child, depth + 1)
                out = copied
            finally:
                active.remove(identity)
        else:
            raise TypeError(f"unsupported outbound protocol value: {type(item).__name__}")

        if metadata > metadata_limit:
            raise ValueError("message snapshot metadata exceeds its preparation limit")
        return out

    return visit(value, 0)


def _validate_ndarray_storage(value: np.ndarray) -> None:
    """Accept only raw layouts the bundled browser decodes unambiguously."""
    dtype = value.dtype
    if dtype.hasobject:
        raise TypeError("protocol numpy arrays cannot contain Python objects")
    if dtype.fields is not None or dtype.kind == "V":
        raise TypeError("protocol numpy arrays must use a plain, non-structured dtype")
    if dtype.str not in _BROWSER_ARRAY_DTYPES:
        raise TypeError(f"protocol numpy dtype {dtype.str!r} is not supported by the browser")


def validated_protocol_value_copy(value: Any) -> Any:
    """Return a validated private snapshot of one dynamic protocol value."""
    _validate_outbound_shape(value)
    _validate_for_serialization(value, Any)
    return copy.deepcopy(value)


def _validate_for_serialization(value: Any, annotation: object) -> None:
    """Validate an outbound value against its wire annotation without coercion."""
    if annotation is Any:
        # Dynamic update dictionaries still need recursive string and numeric
        # safety; their component-specific handlers own narrower semantics.
        if isinstance(value, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
                raise ValueError("protocol strings must not contain surrogate code points")
        elif isinstance(value, (int, np.integer)) and not isinstance(value, bool):
            if abs(int(value)) > _JAVASCRIPT_SAFE_INTEGER_MAX:
                raise ValueError("protocol integers must be JavaScript-safe")
        elif isinstance(value, (float, np.floating)):
            try:
                finite = math.isfinite(float(value))
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("protocol numbers must be finite")
        elif type(value) is bytes:
            pass
        elif type(value) is np.ndarray:
            _validate_ndarray_storage(value)
        elif dataclasses.is_dataclass(value) and not isinstance(value, type):
            hints = get_type_hints_cached(type(value))
            for field in dataclasses.fields(value):
                _validate_for_serialization(getattr(value, field.name), hints[field.name])
        elif isinstance(value, dict):
            for key, item in value.items():
                if type(key) is not str:
                    raise TypeError("protocol dynamic mapping keys must be strings")
                _validate_for_serialization(key, str)
                _validate_for_serialization(item, Any)
        elif isinstance(value, (list, tuple)):
            for item in value:
                _validate_for_serialization(item, Any)
        elif value is not None and type(value) is not bool:
            raise TypeError(f"unsupported outbound protocol value: {type(value).__name__}")
        return
    if annotation is type(None):
        if value is not None:
            raise _type_error(annotation, value)
        return
    if annotation is bool:
        if type(value) is not bool:
            raise _type_error(annotation, value)
        return
    if annotation is str:
        if type(value) is not str:
            raise _type_error(annotation, value)
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("protocol strings must not contain surrogate code points")
        return
    if annotation is bytes:
        if type(value) is not bytes:
            raise _type_error(annotation, value)
        return
    if annotation is int:
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise _type_error(annotation, value)
        if abs(int(value)) > _JAVASCRIPT_SAFE_INTEGER_MAX:
            raise ValueError("protocol integers must be JavaScript-safe")
        return
    if annotation is float:
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise _type_error(annotation, value)
        try:
            finite = math.isfinite(float(value))
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("protocol numbers must be finite")
        return

    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        # Scalar wire invariants are independent of which compatible union arm
        # happens to validate first. An unsafe integer cannot become acceptable
        # merely because ``float`` is another declared option; serialization
        # would still emit the original integer.
        if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
            if abs(int(value)) > _JAVASCRIPT_SAFE_INTEGER_MAX:
                raise ValueError("protocol integers must be JavaScript-safe")
        if isinstance(value, (float, np.floating)):
            try:
                finite = math.isfinite(float(value))
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError("protocol numbers must be finite")
        errors: list[Exception] = []
        for option in get_args(annotation):
            try:
                _validate_for_serialization(value, option)
                return
            except (TypeError, ValueError) as error:
                errors.append(error)
        raise _type_error(annotation, value) from errors[-1] if errors else None
    if str(origin) in ("typing.Literal", "typing_extensions.Literal"):
        if not any(
            type(value) is type(option) and value == option for option in get_args(annotation)
        ):
            raise _type_error(annotation, value)
        return
    if origin is tuple:
        args = get_args(annotation)
        if not args:
            raise TypeError(f"Tuple annotation must have type arguments, got {annotation!r}")
        if type(value) is not tuple:
            raise _type_error(annotation, value)
        if len(args) == 2 and args[1] is Ellipsis:
            item_annotations = (args[0],) * len(value)
        elif len(value) == len(args):
            item_annotations = args
        else:
            raise TypeError(f"expected {annotation!r} with {len(args)} items, got {len(value)}")
        for item, item_annotation in zip(value, item_annotations):
            _validate_for_serialization(item, item_annotation)
        return
    if origin is list:
        if type(value) is not list:
            raise _type_error(annotation, value)
        (item_annotation,) = get_args(annotation)
        for item in value:
            _validate_for_serialization(item, item_annotation)
        return
    if origin is dict:
        if type(value) is not dict:
            raise _type_error(annotation, value)
        key_annotation, item_annotation = get_args(annotation)
        for key, item in value.items():
            _validate_for_serialization(key, key_annotation)
            _validate_for_serialization(item, item_annotation)
        return
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        dataclass_type = cast(type[Any], annotation)
        if type(value) is not dataclass_type:
            # Nested records are exact structural schemas. A subclass may add
            # fields that neither the generated validator nor the matching
            # Python deserializer accepts unless a Union names it explicitly.
            raise _type_error(annotation, value)
        hints = get_type_hints_cached(dataclass_type)
        for field in dataclasses.fields(cast(Any, dataclass_type)):
            _validate_for_serialization(getattr(value, field.name), hints[field.name])
        return
    if origin is np.ndarray or annotation is np.ndarray:
        if type(value) is not np.ndarray:
            raise _type_error(annotation, value)
        _validate_ndarray_storage(value)
        return
    raise TypeError(f"unsupported protocol annotation: {annotation!r}")


def _prepare_for_serialization(
    value: Any,
    annotation: object,
    binary_buffers: Optional[List[memoryview]] = None,
) -> Any:
    """Prepare any special types for serialization.

    If ``binary_buffers`` is provided, numpy arrays are extracted into it and
    replaced with tagged placeholder dicts (``{"__binary_index": i, "dtype": "<f4"}``).
    This pairs with the hybrid wire format where binary data is appended raw
    after the msgpack payload, enabling zero-copy typed array views on the client.

    If ``binary_buffers`` is None, numpy arrays are inlined as memoryviews
    in the serialized dict itself."""
    if annotation is Any:
        annotation = type(value)

    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        errors: list[Exception] = []
        for option in get_args(annotation):
            try:
                _validate_for_serialization(value, option)
            except (TypeError, ValueError) as error:
                errors.append(error)
                continue
            return _prepare_for_serialization(value, option, binary_buffers)
        raise _type_error(annotation, value) from errors[-1] if errors else None

    # Coerce some scalar types: if we've annotated as float / int but we get an
    # np.float32 / np.int64, for example, we should cast automatically.
    if annotation is float or isinstance(value, np.floating):
        return float(value)
    if annotation is int or isinstance(value, np.integer):
        return int(value)

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if not isinstance(annotation, type) or type(value) is not annotation:
            raise _type_error(annotation, value)
        hints = get_type_hints_cached(annotation)
        return {
            field.name: _prepare_for_serialization(
                getattr(value, field.name), hints[field.name], binary_buffers
            )
            for field in dataclasses.fields(value)
        }

    # Recursively handle tuples.
    if isinstance(value, tuple):
        out = []
        if get_origin(annotation) is tuple:
            args = get_args(annotation)
            if len(args) >= 2 and args[1] == ...:
                args = (args[0],) * len(value)
            elif len(value) != len(args):
                raise TypeError(f"expected {annotation!r} with {len(args)} items, got {len(value)}")
        else:
            args = [Any] * len(value)

        for i, v in enumerate(value):
            out.append(_prepare_for_serialization(v, args[i], binary_buffers))
        return tuple(out)

    # Handle numpy arrays: extract or inline depending on mode.
    if type(value) is np.ndarray:
        array = cast(np.ndarray, value)
        _validate_ndarray_storage(array)
        data = array.data if array.data.c_contiguous else array.copy().data
        if binary_buffers is not None:
            # Extract into separate buffer with tagged placeholder.
            idx = len(binary_buffers)
            binary_buffers.append(data)
            return {"__binary_index": idx, "dtype": array.dtype.str}
        else:
            # Inline as memoryview in the serialized dict.
            return data

    if isinstance(value, list):
        return [_prepare_for_serialization(v, Any, binary_buffers) for v in value]

    if isinstance(value, dict):
        return {k: _prepare_for_serialization(v, Any, binary_buffers) for k, v in value.items()}

    return value


T = TypeVar("T", bound="Message")


@functools.lru_cache(maxsize=None)
def get_type_hints_cached(cls: Type[Any]) -> Dict[str, Any]:
    return cast(Dict[str, Any], get_type_hints(cls))


class Message(abc.ABC):
    """Base message type for server/client communication."""

    excluded_self_client: Optional[ClientId] = None
    """Don't send this message to a particular client. Useful when a client wants to
    send synchronization information to other clients."""

    # Entity lifecycle markers. Generic at this layer; application-specific
    # literals (e.g. EntityType in leika._messages) narrow these in subclasses
    # via the __init_subclass__ kwargs pattern. The buffer and GC read these
    # via the Message base to coalesce create/remove and purge stale updates
    # uniformly across entity types.
    entity_type: ClassVar[Optional[str]] = None
    lifecycle_phase: ClassVar[Optional[str]] = None
    entity_id_field: ClassVar[Optional[str | tuple[str, ...]]] = None
    """Dataclass field, or fields, that form the lifecycle identity.

    Most protocol entities have one globally unique identifier. Some are
    naturally scoped, however, and use a tuple such as ``("page_id",
    "pane_id")``. Keeping the scope structural here avoids delimiter-based
    synthetic identifiers and lets the persistent buffer treat both forms
    uniformly.
    """
    redundancy_key_is_identity: ClassVar[bool] = False
    """Whether a cached key names this message instance rather than its fields."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Invalidate dynamic type lookup whenever users define a new message."""
        super().__init_subclass__(**kwargs)
        # During initial Message class creation this descriptor doesn't exist
        # yet. Every later public subclass invalidates cached descendant maps
        # for all Message roots so late definitions become deserializable.
        for base in cls.__mro__[1:]:
            if not issubclass(base, Message):
                continue
            lookup = base.__dict__.get("_subclass_from_type_string")
            if lookup is not None:
                lookup.__func__.cache_clear()

        # The schema fingerprint is separately cached by the optional
        # TypeScript generator. Avoid importing it during protocol bootstrap,
        # but invalidate it whenever that module is already loaded.
        generator = sys.modules.get(f"{__package__}._typescript_interface_gen")
        fingerprint = getattr(generator, "protocol_fingerprint", None)
        if fingerprint is not None:
            fingerprint.cache_clear()

    def lifecycle_entity_id(self) -> object | None:
        """Return this message's scalar or composite lifecycle identity."""

        fields = self.entity_id_field
        if fields is None:
            return None
        if isinstance(fields, str):
            return getattr(self, fields)
        return tuple(getattr(self, field) for field in fields)

    def _validated_source_metrics(self) -> tuple[int, int, int, int]:
        """Validate source fields and return conservative pre-copy metrics."""
        message_type = type(self)
        if not dataclasses.is_dataclass(self):
            raise TypeError(
                f"wire message {message_type.__module__}.{message_type.__qualname__} "
                "must be a dataclass"
            )
        fields = dataclasses.fields(self)
        if any(field.name == "type" for field in fields):
            raise TypeError(
                f"wire message {message_type.__module__}.{message_type.__qualname__} "
                "cannot declare the reserved 'type' field"
            )
        metrics = _validate_outbound_shape(self)
        hints = get_type_hints_cached(message_type)
        for field in fields:
            if field.name != "excluded_self_client":
                _validate_for_serialization(getattr(self, field.name), hints[field.name])
        return metrics

    def _bounded_transport_snapshot(
        self,
        *,
        metadata_limit: int,
        raw_limit: int,
    ) -> "Message":
        """Return one hook-free, byte-bounded immutable transport snapshot."""
        return cast(
            Message,
            _bounded_protocol_snapshot(
                self,
                metadata_limit=metadata_limit,
                raw_limit=raw_limit,
            ),
        )

    def validate_schema(self) -> int:
        """Validate every outbound field and return its source node count."""
        return self._validated_source_metrics()[0]

    def purge_entities(self) -> tuple[tuple[str, object], ...]:
        """Entity states made obsolete by this lifecycle message.

        Application protocols may override this for one wire removal that
        retires a complete subtree. The buffer uses the result only for
        removal-phase messages and still retains the removal itself until all
        connected clients have received it.
        """
        if (
            self.lifecycle_phase == "remove"
            and self.entity_type is not None
            and self.entity_id_field is not None
        ):
            return ((self.entity_type, self.lifecycle_entity_id()),)
        return ()

    def serialized_metrics_upper_bound(self) -> tuple[int, int, int, int]:
        """Return metadata, raw bytes, buffer count, and decoded tree nodes."""
        binary_buffers: List[memoryview] = []
        prepared = self.as_serializable_dict(binary_buffers)
        metadata_bytes = len(msgspec.msgpack.encode(prepared))
        raw_binary_bytes = sum(buffer.nbytes + 7 for buffer in binary_buffers)

        # This models the browser traversal after MsgPack decoding and before
        # placeholder restoration: mappings contribute one node plus values
        # (keys are not traversed), and tuples decode as arrays. Extracted
        # ndarrays are already placeholder mappings here.
        decoded_nodes = 0
        stack: list[object] = [prepared]
        while stack:
            item = stack.pop()
            decoded_nodes += 1
            if type(item) is dict:
                stack.extend(cast(dict[object, object], item).values())
            elif type(item) in (list, tuple):
                stack.extend(cast(list[object] | tuple[object, ...], item))
        return metadata_bytes, raw_binary_bytes, len(binary_buffers), decoded_nodes

    def serialized_size_upper_bound(self) -> tuple[int, int, int]:
        """Return metadata, raw-binary, and binary-buffer count upper bounds."""
        metadata, raw, buffers, _ = self.serialized_metrics_upper_bound()
        return metadata, raw, buffers

    def as_serializable_dict(
        self, binary_buffers: Optional[List[memoryview]] = None
    ) -> Dict[str, Any]:
        """Convert a Python Message object into a serializable dict.

        If ``binary_buffers`` is provided, numpy arrays are extracted into it
        and replaced with tagged placeholder dicts for the hybrid wire format.
        Otherwise, arrays are inlined as memoryviews in the returned dict."""
        message_type = type(self)
        # Direct callers receive the same strict schema boundary as buffered
        # transport callers; preparation must never coerce an invalid shape
        # into something that only appears wire-compatible.
        self.validate_schema()
        if not dataclasses.is_dataclass(self):
            raise TypeError(
                f"wire message {message_type.__module__}.{message_type.__qualname__} "
                "must be a dataclass"
            )
        hints = get_type_hints_cached(message_type)
        fields = dataclasses.fields(self)
        if any(field.name == "type" for field in fields):
            raise TypeError(
                f"wire message {message_type.__module__}.{message_type.__qualname__} "
                "cannot declare the reserved 'type' field"
            )
        # Dataclass fields are the canonical wire schema. This includes slots,
        # class defaults, and init=False fields while excluding implementation
        # caches that happen to live in an instance dictionary.
        out = {
            field.name: _prepare_for_serialization(
                getattr(self, field.name), hints[field.name], binary_buffers
            )
            for field in fields
            if field.name != "excluded_self_client"
        }
        out["type"] = message_type.__name__
        return out

    @classmethod
    def _from_serializable_dict(cls, mapping: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a dict message back into a Python Message object."""

        if not dataclasses.is_dataclass(cls):
            raise TypeError(f"wire message {cls.__module__}.{cls.__qualname__} must be a dataclass")
        hints = get_type_hints_cached(cls)
        field_names = {
            field.name
            for field in dataclasses.fields(cast(Any, cls))
            if field.name != "excluded_self_client"
        }
        unknown = set(mapping) - field_names
        if unknown:
            raise TypeError(f"unexpected message field(s): {sorted(unknown)!r}")
        return {k: _prepare_for_deserialization(v, hints[k]) for k, v in mapping.items()}

    @classmethod
    def deserialize(cls, message: bytes) -> Message:
        """Convert bytes into a Python Message object."""
        mapping = msgspec.msgpack.decode(message)
        _validate_decoded_shape(mapping)
        if type(mapping) is not dict:
            raise TypeError("protocol message must decode to a mapping")
        raw_type = mapping.pop("type", None)
        if type(raw_type) is not str:
            raise TypeError("protocol message type must be a string")

        # List-to-tuple conversion is handled per-field in
        # _prepare_for_deserialization (called from _from_serializable_dict),
        # which uses type annotations to convert only where needed. This avoids
        # a blanket recursive traversal of the entire message tree.
        message_type = cls._subclass_from_type_string()[cast(str, raw_type)]
        prepared_fields = message_type._from_serializable_dict(mapping)
        if not dataclasses.is_dataclass(message_type):
            raise TypeError(
                f"wire message {message_type.__module__}.{message_type.__qualname__} "
                "must be a dataclass"
            )
        dataclass_fields = {
            field.name: field for field in dataclasses.fields(cast(Any, message_type))
        }
        message_instance = message_type(
            **{
                name: value
                for name, value in prepared_fields.items()
                if dataclass_fields[name].init
            }
        )
        for name, value in prepared_fields.items():
            if not dataclass_fields[name].init:
                object.__setattr__(message_instance, name, value)
        return message_instance

    @classmethod
    @functools.lru_cache(maxsize=100)
    def _subclass_from_type_string(cls: Type[T]) -> Dict[str, Type[T]]:
        subclasses = cls.get_subclasses()
        from_name: Dict[str, Type[T]] = {}
        for subclass in subclasses:
            previous = from_name.get(subclass.__name__)
            if previous is not None and previous is not subclass:
                # dataclass(slots=True) creates a replacement class and leaves
                # its short-lived precursor in ``__subclasses__()``. They have
                # one exact lexical identity; retain the later replacement.
                if (
                    (previous.__module__, previous.__qualname__)
                    == (subclass.__module__, subclass.__qualname__)
                    and "__slots__" not in previous.__dict__
                    and "__slots__" in subclass.__dict__
                ):
                    from_name[subclass.__name__] = subclass
                    continue
                raise RuntimeError(
                    f"duplicate protocol message type name {subclass.__name__!r}: "
                    f"{previous.__module__}.{previous.__qualname__} and "
                    f"{subclass.__module__}.{subclass.__qualname__}"
                )
            from_name[subclass.__name__] = subclass
        return from_name

    @classmethod
    def get_subclasses(cls: Type[T]) -> List[Type[T]]:
        """Return every public dataclass wire type below this protocol root.

        A dataclass remains a valid concrete message when users derive another
        message from it. Public non-dataclass intermediates are structural roots
        and are traversed, while a public non-dataclass leaf is malformed.
        Private helpers are skipped as wire types but still traversed.
        """

        def _get_subclasses(typ: Type[T]) -> List[Type[T]]:
            out: List[Type[T]] = []
            for sub in typ.__subclasses__():
                direct_children = sub.__subclasses__()
                if not sub.__name__.startswith("_"):
                    if dataclasses.is_dataclass(sub):
                        if any(field.name == "type" for field in dataclasses.fields(sub)):
                            raise TypeError(
                                f"wire message {sub.__module__}.{sub.__qualname__} cannot "
                                "declare the reserved 'type' field"
                            )
                        out.append(sub)
                    elif not direct_children:
                        raise TypeError(
                            f"wire message {sub.__module__}.{sub.__qualname__} must be a dataclass"
                        )
                out.extend(_get_subclasses(sub))
            return out

        return _get_subclasses(cls)

    @abc.abstractmethod
    def redundancy_key(self) -> str | None:
        """Return a coalescing key, or ``None`` for strictly ordered messages.

        Returns a unique key for this message, used for detecting redundant
        messages.

        For example: if we send 1000 "set value" messages for the same GUI element, we
        should only keep the latest message.
        """
