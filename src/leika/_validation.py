"""Shared runtime validation for public API values."""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from typing import cast


def validate_finite_number(value: object, name: str = "value") -> int | float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a number, not {type(value).__name__}.")
    number = cast(int | float, value)
    try:
        finite = math.isfinite(float(number))
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{name} must be finite.")
    return number


def validate_positive_number(value: object, name: str) -> int | float:
    value = validate_finite_number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def validate_positive_integer(value: object, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")


def validate_nonnegative_integer(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")


_UTF16_CHUNK_SIZE = 64 * 1024
_SURROGATE_PATTERN = re.compile("[\\ud800-\\udfff]")


def _utf16_extra_units(value: str) -> Iterator[int]:
    """Count supplementary code points in native code with bounded scratch space."""
    for start in range(0, len(value), _UTF16_CHUNK_SIZE):
        chunk = value[start : start + _UTF16_CHUNK_SIZE]
        # A surrogate code point itself still counts as one unit. Validation
        # of wire-representable Unicode is a separate responsibility.
        yield len(chunk.encode("utf-16-le", errors="surrogatepass")) // 2 - len(chunk)


def utf16_code_unit_length(value: str) -> int:
    """Return JavaScript String.length without a Python loop per character."""
    length = len(value)
    if value.isascii():
        return length
    return length + sum(_utf16_extra_units(value))


def utf16_code_unit_length_exceeds(value: str, limit: int) -> bool:
    """Whether JavaScript String.length exceeds a limit, with early exit."""
    units = len(value)
    if units > limit:
        return True
    if units * 2 <= limit or value.isascii():
        return False
    for extra in _utf16_extra_units(value):
        units += extra
        if units > limit:
            return True
    return False


_LAYOUT_ID_MAX_UTF16_CODE_UNITS = 1_024
_LAYOUT_ID_RESERVED = frozenset({"__proto__", "prototype", "constructor"})


def validate_layout_id(value: object, name: str) -> str:
    """Return one browser-persisted layout ID within the wire contract."""
    if type(value) is not str:
        raise TypeError(f"{name} must be a string.")
    if not value:
        raise ValueError(f"{name} must not be empty.")
    if value in _LAYOUT_ID_RESERVED:
        raise ValueError(f"{name} uses a reserved browser object identifier.")
    validate_unicode_string(value, name)
    if utf16_code_unit_length_exceeds(value, _LAYOUT_ID_MAX_UTF16_CODE_UNITS):
        raise ValueError(
            f"{name} must not exceed {_LAYOUT_ID_MAX_UTF16_CODE_UNITS} UTF-16 code units."
        )
    return value


def validate_unicode_string(value: object, name: str) -> str:
    """Return a string that is representable by the UTF-8 wire format."""
    if type(value) is not str:
        raise TypeError(f"{name} must be a string.")
    if not value.isascii() and _SURROGATE_PATTERN.search(value) is not None:
        raise ValueError(f"{name} must contain valid Unicode without surrogate code points.")
    return value


_RENDERER_STRING_MAX_UTF16_CODE_UNITS = 16 * 1024


def validate_renderer_string(
    value: object,
    name: str,
    *,
    optional: bool = False,
) -> str | None:
    """Validate one short string placed directly into browser-rendered UI."""
    if value is None and optional:
        return None
    if type(value) is not str:
        suffix = " or None" if optional else ""
        raise TypeError(f"{name} must be a string{suffix}.")
    value = validate_unicode_string(value, name)
    if utf16_code_unit_length_exceeds(value, _RENDERER_STRING_MAX_UTF16_CODE_UNITS):
        raise ValueError(
            f"{name} cannot exceed {_RENDERER_STRING_MAX_UTF16_CODE_UNITS} UTF-16 code units."
        )
    return value
