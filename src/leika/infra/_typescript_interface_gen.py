import dataclasses
import functools
import hashlib
import json
import math
import re
import types
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Tuple, Type, Union, cast
from typing import Literal as TypingLiteral

import numpy as np
import numpy.typing as npt
from typing_extensions import (
    Annotated,
    Literal,
    Never,
    NotRequired,
    get_args,
    get_origin,
    get_type_hints,
    is_typeddict,
)

from ._messages import Message

_raw_type_mapping = {
    bool: "boolean",
    float: "number",
    int: "number",
    str: "string",
    # For numpy arrays, we directly serialize the underlying data buffer.
    # The hybrid wire format delivers these as typed array views.
    bytes: "Uint8Array<ArrayBuffer>",
    Any: "any",
    None: "null",
    Never: "never",
    type(None): "null",
}

_typescript_typed_array_union = (
    "Uint8Array<ArrayBuffer> | Int8Array | Uint16Array | Int16Array | "
    "Uint32Array | Int32Array | Float32Array | Float64Array"
)
_javascript_safe_integer_max = (1 << 53) - 1
_typescript_identifier = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_typescript_reserved_words = frozenset(
    {
        "await",
        "abstract",
        "any",
        "as",
        "asserts",
        "bigint",
        "boolean",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "import",
        "implements",
        "in",
        "instanceof",
        "interface",
        "keyof",
        "let",
        "module",
        "namespace",
        "never",
        "new",
        "null",
        "number",
        "object",
        "package",
        "private",
        "protected",
        "public",
        "readonly",
        "require",
        "return",
        "super",
        "static",
        "string",
        "switch",
        "symbol",
        "this",
        "throw",
        "true",
        "try",
        "type",
        "typeof",
        "undefined",
        "unique",
        "unknown",
        "var",
        "void",
        "while",
        "with",
        "yield",
    }
)

# Mapping from numpy dtype to TypeScript typed array type.
_numpy_dtype_to_ts_typed_array = {
    np.bool_: "Uint8Array<ArrayBuffer>",
    np.float16: "Uint16Array",  # No Float16Array in JS; stored as Uint16.
    np.float32: "Float32Array",
    np.float64: "Float64Array",
    np.uint8: "Uint8Array<ArrayBuffer>",
    np.uint16: "Uint16Array",
    np.uint32: "Uint32Array",
    np.int8: "Int8Array",
    np.int16: "Int16Array",
    np.int32: "Int32Array",
}

_numpy_dtype_to_runtime_typed_array = {
    np.bool_: "Uint8Array",
    np.float16: "Uint16Array",
    np.float32: "Float32Array",
    np.float64: "Float64Array",
    np.uint8: "Uint8Array",
    np.uint16: "Uint16Array",
    np.uint32: "Uint32Array",
    np.int8: "Int8Array",
    np.int16: "Int16Array",
    np.int32: "Int32Array",
}


def _type_args(typ: Any) -> Tuple[Any, ...]:
    """The parameters of a generic, including numpy's own generic aliases.

    numpy < 2.5 builds ``NDArray[dtype]`` out of a private alias class that
    ``get_args()`` does not recognize and reports as unparameterized. Falling
    back to ``__args__`` keeps the generated TypeScript -- and so the protocol
    fingerprint -- identical across numpy versions, rather than silently
    widening every typed array to the untyped byte buffer.
    """
    return get_args(typ) or tuple(getattr(typ, "__args__", ()))


def _typescript_literal(value: object) -> str:
    """Render one Python Literal/member/property name as safe TS source."""
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        if abs(value) > _javascript_safe_integer_max:
            raise TypeError(f"Protocol integer literal is not JavaScript-safe: {value!r}.")
        return repr(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise TypeError(f"Protocol numeric literal must be finite: {value!r}.")
        return repr(value)
    if type(value) is str:
        # ASCII escaping also protects JavaScript's U+2028/U+2029 source-line
        # separator edge and makes fingerprints locale/encoding independent.
        return json.dumps(value, ensure_ascii=True)
    raise TypeError(f"Unsupported protocol literal {value!r}.")


def _validate_typescript_identifier(value: str, *, label: str) -> None:
    if not _typescript_identifier.fullmatch(value) or value in _typescript_reserved_words:
        raise TypeError(f"{label} {value!r} is not a safe TypeScript identifier.")


def _get_ts_type(typ: Type[Any]) -> str:
    origin_typ = get_origin(typ)

    # Look for TypeScriptAnnotationOverride in the annotations.
    if origin_typ is Annotated:
        args = get_args(typ)
        for arg in args[1:]:
            if isinstance(arg, TypeScriptAnnotationOverride):
                return arg.annotation

        # No override -- recurse on the unwrapped type so we re-derive the
        # origin. (Just reassigning origin_typ here would skip the origin
        # checks below for parameterized types like ``Literal[...]``.)
        return _get_ts_type(args[0])

    # Automatic Python => TypeScript conversion.
    if origin_typ is tuple:
        args = get_args(typ)
        if not args:
            raise TypeError(f"Tuple annotation must have type arguments, got {typ!r}.")
        if len(args) == 2 and args[1] == ...:
            return "(" + _get_ts_type(args[0]) + ")[]"
        else:
            return "[" + ", ".join(map(_get_ts_type, args)) + "]"
    elif origin_typ is list:
        args = get_args(typ)
        if len(args) != 1:
            raise TypeError(f"List annotation must have one type argument, got {typ!r}.")
        return "(" + _get_ts_type(args[0]) + ")[]"
    elif origin_typ is dict:
        args = get_args(typ)
        if len(args) != 2:
            raise TypeError(f"Dict annotation must have two type arguments, got {typ!r}.")
        return "{[key: " + _get_ts_type(args[0]) + "]: " + _get_ts_type(args[1]) + "}"
    elif origin_typ in (Literal, TypingLiteral):
        values = get_args(typ)
        if not values:
            raise TypeError(f"Protocol Literal must contain at least one value: {typ!r}.")
        return " | ".join(_typescript_literal(value) for value in values)
    elif origin_typ in (Union, types.UnionType):
        return (
            "("
            + " | ".join(
                # We're using dictionary as an ordered set.
                {_get_ts_type(t): None for t in get_args(typ)}.keys()
            )
            + ")"
        )
    elif is_typeddict(typ) or dataclasses.is_dataclass(typ):
        hints = get_type_hints(typ)
        if dataclasses.is_dataclass(typ):
            hints = {field.name: hints[field.name] for field in dataclasses.fields(typ)}
        optional_keys = getattr(typ, "__optional_keys__", [])

        def fmt(key):
            val = hints[key]
            optional = key in optional_keys
            if is_typeddict(typ) and get_origin(val) is NotRequired:
                val = get_args(val)[0]
            ret = f"{_typescript_literal(key)}{'?' if optional else ''}: {_get_ts_type(val)}"
            return ret

        ret = "{" + ", ".join(map(fmt, hints)) + "}"
        return ret
    else:
        # Like get_origin(), but also supports numpy.typing.NDArray[dtype].
        raw_typ = cast(Any, getattr(typ, "__origin__", typ))

        # For NDArray[dtype], resolve to the specific TypeScript typed array.
        if raw_typ is np.ndarray or raw_typ is npt.NDArray:
            # Extract the dtype from NDArray[dtype] annotation. Older numpy
            # parameterizes it as ndarray[Any, np.dtype[dt]]; numpy >= 2.5
            # exposes NDArray as a type alias whose args are (dt,) directly.
            args = _type_args(typ)
            if args:
                dtype_arg = args[-1]
                dtype_args = _type_args(dtype_arg)
                dtype = dtype_args[0] if dtype_args else dtype_arg
                if dtype in _numpy_dtype_to_ts_typed_array:
                    return _numpy_dtype_to_ts_typed_array[dtype]
                if dtype is not Any:
                    raise TypeError(f"Unsupported browser numpy dtype {dtype!r}.")
            return _typescript_typed_array_union

        if raw_typ not in _raw_type_mapping:
            raise TypeError(f"Unsupported type annotation {typ!r}.")
        return _raw_type_mapping[raw_typ]


@dataclasses.dataclass(frozen=True)
class TypeScriptAnnotationOverride:
    """Use with `typing.Annotated[]` to override the automatically-generated
    TypeScript annotation corresponding to a dataclass field."""

    annotation: str


def _runtime_validator_expression(
    typ: Type[Any],
    value: str,
    structs: dict[Type[Any], str],
) -> str:
    """Generate one allocation-conscious runtime schema predicate."""
    origin_typ = get_origin(typ)
    if origin_typ is Annotated:
        return _runtime_validator_expression(get_args(typ)[0], value, structs)

    if origin_typ is tuple:
        args = get_args(typ)
        if not args:
            raise TypeError(f"Tuple annotation must have type arguments, got {typ!r}.")
        if len(args) == 2 and args[1] == ...:
            item = _runtime_validator_expression(args[0], "item", structs)
            return f"isProtocolArray({value}, (item) => {item})"
        items = [
            _runtime_validator_expression(item_typ, f"{value}[{index}]", structs)
            for index, item_typ in enumerate(args)
        ]
        suffix = "" if not items else " && " + " && ".join(items)
        return f"(Array.isArray({value}) && {value}.length === {len(args)}{suffix})"
    if origin_typ is list:
        args = get_args(typ)
        if len(args) != 1:
            raise TypeError(f"List annotation must have one type argument, got {typ!r}.")
        item = _runtime_validator_expression(args[0], "item", structs)
        return f"isProtocolArray({value}, (item) => {item})"
    if origin_typ is dict:
        args = get_args(typ)
        if len(args) != 2:
            raise TypeError(f"Dict annotation must have two type arguments, got {typ!r}.")
        if args[0] is not str:
            raise TypeError(
                f"Runtime protocol mappings currently require string keys, got {typ!r}."
            )
        item = _runtime_validator_expression(args[1], "item", structs)
        return f"isProtocolMapping({value}, (item) => {item})"
    if origin_typ in (Literal, TypingLiteral):
        literals = [f"{value} === {_typescript_literal(item)}" for item in get_args(typ)]
        if not literals:
            raise TypeError(f"Protocol Literal must contain at least one value: {typ!r}.")
        return "(" + " || ".join(literals) + ")"
    if origin_typ in (Union, types.UnionType):
        options = [
            _runtime_validator_expression(option, value, structs) for option in get_args(typ)
        ]
        return "(" + " || ".join(dict.fromkeys(options)) + ")"
    if is_typeddict(typ) or dataclasses.is_dataclass(typ):
        validator = structs.setdefault(typ, f"isProtocolStruct{len(structs)}")
        return f"{validator}({value})"

    raw_typ = cast(Any, getattr(typ, "__origin__", typ))
    if raw_typ is np.ndarray or raw_typ is npt.NDArray:
        args = _type_args(typ)
        if args:
            dtype_arg = args[-1]
            dtype_args = _type_args(dtype_arg)
            dtype = dtype_args[0] if dtype_args else dtype_arg
            typed_array = _numpy_dtype_to_runtime_typed_array.get(dtype)
            if typed_array is not None:
                return f"{value} instanceof {typed_array}"
            if dtype is not Any:
                raise TypeError(f"Unsupported browser numpy dtype {dtype!r}.")
        return f"isProtocolTypedArray({value})"

    if raw_typ is Any:
        return f"isProtocolValue({value})"
    if raw_typ in (None, type(None)):
        return f"{value} === null"
    if raw_typ is Never:
        return "false"
    if raw_typ is bool:
        return f'typeof {value} === "boolean"'
    if raw_typ is str:
        return f'typeof {value} === "string"'
    if raw_typ is bytes:
        return f"{value} instanceof Uint8Array"
    if raw_typ is int:
        return f"Number.isSafeInteger({value})"
    if raw_typ is float:
        return f'(typeof {value} === "number" && Number.isFinite({value}))'
    raise TypeError(f"Unsupported runtime protocol annotation {typ!r}.")


def _runtime_struct_fields(typ: Type[Any]) -> tuple[dict[str, Any], frozenset[str]]:
    hints = get_type_hints(typ, include_extras=True)
    if dataclasses.is_dataclass(typ):
        return (
            {field.name: hints[field.name] for field in dataclasses.fields(typ)},
            frozenset(),
        )
    optional = frozenset(getattr(typ, "__optional_keys__", ()))
    fields: dict[str, Any] = {}
    for name, value in hints.items():
        if get_origin(value) is NotRequired:
            value = get_args(value)[0]
        fields[name] = value
    return fields, optional


def _runtime_record_expression(
    fields: dict[str, Any],
    optional: frozenset[str],
    value: str,
    structs: dict[Type[Any], str],
) -> str:
    keys = list(fields)
    required = [key for key in keys if key not in optional]
    if optional:
        allowed = " || ".join(f"key === {json.dumps(key)}" for key in keys) or "false"
        clauses = [
            f"isProtocolRecord({value})",
            f"Object.keys({value}).every((key) => {allowed})",
        ]
    else:
        clauses = [
            f"isProtocolRecord({value})",
            f"Object.keys({value}).length === {len(keys)}",
        ]
    clauses.extend(f"Object.hasOwn({value}, {json.dumps(key)})" for key in required)
    for key, annotation in fields.items():
        property_value = f"{value}[{json.dumps(key)}]"
        predicate = _runtime_validator_expression(annotation, property_value, structs)
        if key in {
            "uuid",
            "container_uuid",
            "container_id",
            "pane_id",
            "relative_to",
            "source_component_uuid",
            "source_uuid",
            "transfer_uuid",
            "workspace_id",
        }:
            predicate = (
                f'({predicate} && (typeof {property_value} !== "string" || '
                f"isProtocolIdentifier({property_value})))"
            )
        elif key in {"equalize_group", "pane_ids"}:
            predicate = (
                f"({predicate} && (!Array.isArray({property_value}) || "
                f"{property_value}.every(isProtocolIdentifier)))"
            )
        if key in optional:
            predicate = f"(!Object.hasOwn({value}, {json.dumps(key)}) || {predicate})"
        clauses.append(predicate)
    return " &&\n    ".join(clauses)


def _runtime_validation_source(message_types: Sequence[Type[Message]]) -> list[str]:
    structs: dict[Type[Any], str] = {}
    validators: list[tuple[str, str]] = []
    for cls in message_types:
        hints = get_type_hints(cls, include_extras=True)
        fields = {
            "type": TypingLiteral[cls.__name__],
            **{field.name: hints[field.name] for field in dataclasses.fields(cast(Any, cls))},
        }
        validators.append(
            (
                cls.__name__,
                _runtime_record_expression(fields, frozenset(), "message", structs),
            )
        )

    struct_sources: list[str] = []
    processed: set[Type[Any]] = set()
    while True:
        pending = next((typ for typ in structs if typ not in processed), None)
        if pending is None:
            break
        processed.add(pending)
        fields, optional = _runtime_struct_fields(pending)
        expression = _runtime_record_expression(fields, optional, "value", structs)
        validator = structs[pending]
        struct_sources.extend(
            [
                f"function {validator}(value: unknown): boolean {{",
                "  return (",
                "    " + expression,
                "  );",
                "}",
                "",
            ]
        )

    out = [
        "const PROTOCOL_VALIDATION_MAX_VALUES = 500_000;",
        "",
        "function isProtocolRecord(value: unknown): value is Record<string, unknown> {",
        '  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;',
        "  const prototype = Object.getPrototypeOf(value);",
        "  return prototype === Object.prototype || prototype === null;",
        "}",
        "",
        "const PROTOCOL_IDENTIFIER_MAX_CODE_UNITS = 1024;",
        "function isProtocolIdentifier(value: unknown): value is string {",
        "  return (",
        '    typeof value === "string" &&',
        "    value.length > 0 &&",
        "    value.length <= PROTOCOL_IDENTIFIER_MAX_CODE_UNITS &&",
        '    value !== "__proto__" &&',
        '    value !== "prototype" &&',
        '    value !== "constructor" &&',
        "    !/[\\uD800-\\uDFFF]/.test(value)",
        "  );",
        "}",
        "",
        "function isProtocolTypedArray(value: unknown): boolean {",
        "  return (",
        "    value instanceof Uint8Array ||",
        "    value instanceof Uint16Array ||",
        "    value instanceof Uint32Array ||",
        "    value instanceof Int8Array ||",
        "    value instanceof Int16Array ||",
        "    value instanceof Int32Array ||",
        "    value instanceof Float32Array ||",
        "    value instanceof Float64Array",
        "  );",
        "}",
        "",
        "function isProtocolValue(value: unknown): boolean {",
        "  // The hybrid decoder has already bounded the complete graph's depth",
        "  // and node count. This second iterative pass rejects values that Any",
        "  // cannot safely expose without risking call-stack/argument expansion.",
        "  const pending: unknown[] = [value];",
        "  let visited = 0;",
        "  while (pending.length > 0) {",
        "    const item = pending.pop();",
        "    visited += 1;",
        "    if (visited > PROTOCOL_VALIDATION_MAX_VALUES) return false;",
        '    if (item === null || typeof item === "string" || typeof item === "boolean") continue;',
        '    if (typeof item === "number") {',
        "      if (!Number.isFinite(item)) return false;",
        "      continue;",
        "    }",
        "    if (isProtocolTypedArray(item)) continue;",
        "    if (Array.isArray(item)) {",
        "      for (let index = item.length - 1; index >= 0; index -= 1) {",
        "        pending.push(item[index]);",
        "      }",
        "      continue;",
        "    }",
        "    if (!isProtocolRecord(item)) return false;",
        "    for (const key in item) {",
        "      if (Object.hasOwn(item, key)) pending.push(item[key]);",
        "    }",
        "  }",
        "  return true;",
        "}",
        "",
        "function isProtocolArray(",
        "  value: unknown,",
        "  validateItem: (item: unknown) => boolean,",
        "): value is unknown[] {",
        "  if (!Array.isArray(value)) return false;",
        "  for (const item of value) if (!validateItem(item)) return false;",
        "  return true;",
        "}",
        "",
        "function isProtocolMapping(",
        "  value: unknown,",
        "  validateItem: (item: unknown) => boolean,",
        "): value is Record<string, unknown> {",
        "  if (!isProtocolRecord(value)) return false;",
        "  for (const key in value) {",
        "    if (Object.hasOwn(value, key) && !validateItem(value[key])) return false;",
        "  }",
        "  return true;",
        "}",
        "",
        *struct_sources,
        "const messageValidators = new Map<",
        "  string,",
        "  (message: Record<string, unknown>) => boolean",
        ">([",
    ]
    for name, expression in validators:
        out.extend(
            [
                f"  [{json.dumps(name)}, (message) =>",
                "    " + expression + "],",
            ]
        )
    out.extend(
        [
            "]);",
            "",
            "/** Fail closed before a decoded batch reaches any stateful handler. */",
            "export function validateMessage(message: unknown): asserts message is Message {",
            '  if (!isProtocolRecord(message) || typeof message.type !== "string") {',
            '    throw new Error("decoded payload contains an invalid message envelope");',
            "  }",
            "  const validator = messageValidators.get(message.type);",
            "  if (validator === undefined) {",
            '    throw new Error("decoded payload contains an unsupported message type");',
            "  }",
            "  if (!validator(message)) {",
            "    throw new Error(`decoded ${message.type} does not match its protocol schema`);",
            "  }",
            "}",
            "",
        ]
    )
    return out


@functools.lru_cache(maxsize=1)
def protocol_fingerprint(message_cls: Type[Message]) -> str:
    """A short hash of the message schema, for both sides to compare.

    The version alone cannot catch a browser and a server that agree on the
    version but disagree about what a field means -- which is the normal state
    of affairs while the protocol is being edited, and reaches the user as a
    client that connects and then breaks on a field the server never sent.

    Hashes the GENERATED TypeScript rather than the dataclasses directly, so
    the fingerprint changes exactly when the file the client is built from
    changes, and no more often.
    """
    source = generate_typescript_interfaces(message_cls)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def generate_typescript_interfaces(message_cls: Type[Message]) -> str:
    """Generate TypeScript definitions for all subclasses of a base message class."""
    out_lines = []
    # Reuse the deserializer's canonical lookup: in particular, fail rather
    # than letting two equal class names declaration-merge in TypeScript and
    # silently overwrite one another in the runtime validator map.
    message_types = list(message_cls._subclass_from_type_string().values())
    for cls in message_types:
        _validate_typescript_identifier(cls.__name__, label="Protocol message name")
        if any(field.name == "type" for field in dataclasses.fields(cast(Any, cls))):
            raise TypeError(
                f"Protocol message {cls.__name__!r} cannot declare the reserved 'type' field."
            )

    tag_map = defaultdict(list)

    # Generate interfaces for each specific message.
    for cls in message_types:
        if cls.__doc__ is not None:
            docstring = "\n * ".join(
                line.strip().replace("*/", "*\\/") for line in cls.__doc__.split("\n")
            )
            out_lines.append(f"/** {docstring}")
            out_lines.append(" *")
            out_lines.append(" * (automatically generated)")
            out_lines.append(" */")

        for tag in getattr(cls, "_tags", []):
            _validate_typescript_identifier(tag, label="Protocol tag name")
            tag_map[tag].append(cls.__name__)

        out_lines.append(f"export interface {cls.__name__} " + "{")
        out_lines.append(f'  type: "{cls.__name__}";')
        hints = get_type_hints(cls, include_extras=True)
        for field in dataclasses.fields(cast(Any, cls)):
            name = field.name
            typ = _get_ts_type(hints[name])
            out_lines.append(f"  {_typescript_literal(name)}: {typ};")
        out_lines.append("}")
    out_lines.append("")

    # Generate union type over all messages.
    if message_types:
        out_lines.append("export type Message = ")
        for cls in message_types:
            out_lines.append(f"  | {cls.__name__}")
        out_lines[-1] = out_lines[-1] + ";"
    else:
        out_lines.append("export type Message = never;")

    # Generate union type over all tags.
    for tag, cls_names in tag_map.items():
        out_lines.append(f"export type {tag} = ")
        for cls_name in cls_names:
            out_lines.append(f"  | {cls_name}")
        out_lines[-1] = out_lines[-1] + ";"

    for tag, cls_names in tag_map.items():
        out_lines.extend(
            [
                f"const typeSet{tag} = new Set(["
                + ", ".join(_typescript_literal(name) for name in cls_names)
                + "]);",
                f"export function is{tag}(message: Message): message is {tag}" + " {",
                f"    return typeSet{tag}.has(message.type);",
                "}",
            ]
        )

    out_lines.append("")
    out_lines.extend(_runtime_validation_source(message_types))
    generated_typescript = "\n".join(out_lines) + "\n"

    # Add header and return.
    return (
        "\n".join(
            [
                (
                    "// AUTOMATICALLY GENERATED message interfaces, from Python"
                    " dataclass definitions."
                ),
                "// This file should not be manually modified.",
                "",
            ]
        )
        + generated_typescript
    )
