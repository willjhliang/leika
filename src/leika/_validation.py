"""Shared runtime validation for public numeric arguments."""

from __future__ import annotations

import math


def validate_finite_number(value: object, name: str = "value") -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, not {type(value).__name__}.")
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite.")
    return value


def validate_positive_number(value: object, name: str) -> int | float:
    value = validate_finite_number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def validate_positive_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer.")


def validate_nonnegative_integer(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")
