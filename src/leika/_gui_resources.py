"""Browser-parity measurement of retained GUI resources.

The cost value is shared by GUI handles and the server's aggregate budgets. Measuring a value never depends on a live handle or server.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from numbers import Real
from typing import cast

import numpy as np

from ._validation import utf16_code_unit_length
from ._validation import validate_unicode_string as _validate_unicode_string

_GUI_CONTAINER_DEPTH_MAX = 64


@dataclasses.dataclass(frozen=True)
class _GuiResourceCost:
    collection_items: int = 0
    text_units: int = 0
    payload_bytes: int = 0
    decoded_pixels: int = 0

    def __add__(self, other: "_GuiResourceCost") -> "_GuiResourceCost":
        return _GuiResourceCost(
            self.collection_items + other.collection_items,
            self.text_units + other.text_units,
            self.payload_bytes + other.payload_bytes,
            self.decoded_pixels + other.decoded_pixels,
        )

    def __sub__(self, other: "_GuiResourceCost") -> "_GuiResourceCost":
        return _GuiResourceCost(
            self.collection_items - other.collection_items,
            self.text_units - other.text_units,
            self.payload_bytes - other.payload_bytes,
            self.decoded_pixels - other.decoded_pixels,
        )


def _gui_resource_cost(
    value: object,
    props: object,
    *,
    decoded_pixels: int = 0,
    retained_extra_bytes: int = 0,
) -> _GuiResourceCost:
    """Measure a bounded retained value/props graph with browser-parity rules."""
    collection_items = 0
    text_units = 0
    payload_bytes = retained_extra_bytes
    nodes = 0
    active: set[int] = set()
    stack: list[tuple[object, int, bool]] = [(value, 0, False), (props, 0, False)]
    while stack:
        item, depth, exiting = stack.pop()
        if exiting:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > 100_000:
            raise ValueError("GUI retained state contains too many values")
        if depth > _GUI_CONTAINER_DEPTH_MAX:
            raise ValueError("GUI retained state is nested too deeply")
        if item is None or isinstance(item, (bool, Real)):
            continue
        if isinstance(item, str):
            item = _validate_unicode_string(item, "GUI string")
            text_units += utf16_code_unit_length(item)
            payload_bytes += len(item.encode("utf-8"))
            continue
        if isinstance(item, bytes):
            payload_bytes += len(item)
            continue
        if isinstance(item, np.ndarray):
            payload_bytes += int(item.nbytes)
            continue

        composite = (dataclasses.is_dataclass(item) and not isinstance(item, type)) or isinstance(
            item, (Mapping, tuple, list)
        )
        if not composite:
            raise TypeError(f"unsupported retained GUI value: {type(item).__name__}")
        identity = id(item)
        if identity in active:
            raise ValueError("GUI retained state cannot contain cycles")
        active.add(identity)
        stack.append((item, depth, True))
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            children = tuple(getattr(item, field.name) for field in dataclasses.fields(item))
        elif isinstance(item, Mapping):
            children = (*item.keys(), *item.values())
        else:
            children = tuple(cast(Iterable[object], item))
            collection_items += len(children)
        stack.extend((child, depth + 1, False) for child in reversed(children))
    return _GuiResourceCost(
        collection_items,
        text_units,
        payload_bytes,
        decoded_pixels,
    )
