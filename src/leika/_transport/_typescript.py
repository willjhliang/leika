"""Generate the browser's TypeScript message types from the Python dataclasses."""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
from collections import defaultdict
from types import UnionType
from typing import Any, Union

from typing_extensions import Literal, get_args, get_origin

from .._messages import MESSAGE_TYPES, _wire_fields

_RAW_TYPES = {
    bool: "boolean",
    float: "number",
    int: "number",
    str: "string",
    bytes: "Uint8Array<ArrayBuffer>",
    Any: "any",
    type(None): "null",
}


def _typescript_literal(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is str:
        return json.dumps(value)
    return repr(value)


def _get_ts_type(typ: Any) -> str:
    origin = get_origin(typ)
    args = get_args(typ)
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return "(" + _get_ts_type(args[0]) + ")[]"
        return "[" + ", ".join(map(_get_ts_type, args)) + "]"
    if origin is list:
        return "(" + _get_ts_type(args[0]) + ")[]"
    if origin is dict:
        return "{[key: " + _get_ts_type(args[0]) + "]: " + _get_ts_type(args[1]) + "}"
    if origin is Literal:
        return " | ".join(_typescript_literal(value) for value in args)
    if origin is Union or origin is UnionType:
        # A dictionary is an ordered set.
        return "(" + " | ".join({_get_ts_type(option): None for option in args}) + ")"
    if dataclasses.is_dataclass(typ):
        fields = (
            f"{_typescript_literal(name)}: {_get_ts_type(annotation)}"
            for name, annotation in _wire_fields(typ)
        )
        return "{" + ", ".join(fields) + "}"
    if typ not in _RAW_TYPES:
        raise TypeError(f"Unsupported type annotation {typ!r}.")
    return _RAW_TYPES[typ]


def generate_typescript_interfaces() -> str:
    """TypeScript interfaces for every wire message, their union and tag unions."""
    out_lines = [
        "// AUTOMATICALLY GENERATED message interfaces, from Python dataclass definitions.",
        "// This file should not be manually modified.",
    ]
    tag_map: defaultdict[str, list[str]] = defaultdict(list)
    for name, cls in MESSAGE_TYPES.items():
        if cls.__doc__ is not None:
            docstring = "\n * ".join(
                line.strip().replace("*/", "*\\/") for line in cls.__doc__.split("\n")
            )
            out_lines += [f"/** {docstring}", " *", " * (automatically generated)", " */"]
        for tag in cls._tags:
            tag_map[tag].append(name)
        out_lines.append(f"export interface {name} {{")
        out_lines.append(f'  type: "{name}";')
        for field_name, annotation in _wire_fields(cls):
            out_lines.append(f"  {_typescript_literal(field_name)}: {_get_ts_type(annotation)};")
        out_lines.append("}")
    out_lines.append("")

    out_lines.append("export type Message = ")
    out_lines.extend(f"  | {name}" for name in MESSAGE_TYPES)
    out_lines[-1] += ";"
    for tag, names in tag_map.items():
        out_lines.append(f"export type {tag} = ")
        out_lines.extend(f"  | {name}" for name in names)
        out_lines[-1] += ";"
    for tag, names in tag_map.items():
        out_lines += [
            f"const typeSet{tag} = new Set([" + ", ".join(map(json.dumps, names)) + "]);",
            f"export function is{tag}(message: Message): message is {tag} {{",
            f"    return typeSet{tag}.has(message.type);",
            "}",
        ]
    return "\n".join(out_lines) + "\n"


@functools.cache
def protocol_fingerprint() -> str:
    """A short hash of the package version and message schema.

    The client sends it when connecting, so a page built from different code
    than the server runs is turned away with a reason instead of breaking on
    fields it cannot read. The schema part hashes the generated TypeScript,
    so it changes exactly when the file the client is built from changes.
    """
    from .. import __version__

    source = f"{__version__}\n{generate_typescript_interfaces()}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
