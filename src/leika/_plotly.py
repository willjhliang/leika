"""Bounded Plotly snapshots shared by GUI controls and workspace panes.

Figure preflight, serialization, config ownership, and template handling belong
together here. Plotly remains an optional dependency and is imported only when
one of its operations is requested.
"""

from __future__ import annotations

import datetime
import decimal
import itertools
import json
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from ._validation import utf16_code_unit_length_exceeds

if TYPE_CHECKING:
    import plotly.graph_objects as go


_stock_plotly_template_json: dict[str, Any] | None = None
_theme_templates_json: str | None = None

_PLOTLY_JSON_MAX_UTF16_CODE_UNITS = 16 * 1024 * 1024
"""Bundled browser JSON parser limit for one Plotly payload."""

_PLOTLY_PREFLIGHT_MAX_NODES = 500_000
_PLOTLY_CONFIG_MAX_ITEMS = 4096


def _validate_plotly_json_size(json_str: str) -> str:
    if utf16_code_unit_length_exceeds(json_str, _PLOTLY_JSON_MAX_UTF16_CODE_UNITS):
        raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    return json_str


def _plotly_string_json_upper_bound(value: str) -> int:
    """Conservative UTF-16 length of a JSON string without allocating it."""
    total = 2
    for character in value:
        codepoint = ord(character)
        if character in ('"', "\\"):
            total += 2
        elif codepoint < 0x20:
            total += 6
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ValueError("Plotly data cannot contain unpaired Unicode surrogates")
        elif codepoint > 0xFFFF:
            total += 12
        elif codepoint > 0x7F:
            total += 6
        else:
            total += 1
        if total > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
            raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    return total


def _plotly_graph_json_upper_bound(*roots: object) -> int:
    """Bound an exact plain Plotly property graph before serialization.

    BasePlotlyType instances are accepted only by dedicated, hook-free figure,
    frame, and template extractors. Encountering one inside raw data/layout is
    an unsupported injected object, not a safe serialized leaf.
    """
    total = 0
    nodes = 0
    active: set[int] = set()
    stack: list[tuple[object, int, bool]] = [(root, 0, False) for root in reversed(roots)]
    while stack:
        item, depth, exiting = stack.pop()
        if exiting:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > _PLOTLY_PREFLIGHT_MAX_NODES:
            raise ValueError("Plotly figure contains too many values")
        if depth > 64:
            raise ValueError("Plotly figure is nested too deeply")
        if item is None or type(item) is bool:
            total += 5
        elif type(item) is str:
            total += _plotly_string_json_upper_bound(item)
        elif type(item) is int:
            total += max(1, (abs(item).bit_length() * 30103 + 99_999) // 100_000) + 1
        elif type(item) is float:
            total += 32
        elif type(item) in (datetime.date, datetime.datetime):
            total += 128
        elif type(item) is decimal.Decimal:
            # PlotlyJSONEncoder converts Decimal through float(), which has a
            # fixed-size result and avoids constructing its potentially huge
            # decimal spelling.
            float(item)
            total += 32
        elif isinstance(item, np.generic):
            scalar_dtype = np.dtype(type(item))
            if scalar_dtype.type is not type(item):
                raise TypeError("custom numpy scalar subclasses are not supported in Plotly data")
            kind = scalar_dtype.kind
            if kind == "U":
                total += (int(scalar_dtype.itemsize) // 4) * 12 + 2
            elif kind == "S":
                total += int(scalar_dtype.itemsize) * 6 + 2
            elif kind in "mM":
                total += 128
            elif kind in "biufc":
                total += 128
            else:
                raise TypeError(f"unsupported Plotly numpy scalar dtype: {scalar_dtype}")
        elif type(item) is np.ndarray:
            kind = item.dtype.kind
            element_count = int(item.size)
            if item.ndim + depth > 64:
                raise ValueError("Plotly figure is nested too deeply")
            # Plotly 5.21 renders ndarrays as nested JSON lists. Charge every
            # list container, including empty/singleton dimensions; later
            # Plotly versions may instead use one compact base64 record.
            container_count = 0
            prefix = 1
            for dimension in item.shape:
                container_count += prefix
                if container_count > _PLOTLY_PREFLIGHT_MAX_NODES:
                    raise ValueError("Plotly figure contains too many values")
                prefix *= int(dimension)
            if element_count + container_count > _PLOTLY_PREFLIGHT_MAX_NODES - nodes:
                raise ValueError("Plotly figure contains too many values")
            # Brackets plus a conservative comma for every child edge.
            list_punctuation_bound = 3 * container_count + element_count + 128
            if item.dtype.hasobject:
                children = tuple(item.flat)
                nodes += container_count
                total += list_punctuation_bound
                identity = id(item)
                if identity in active:
                    raise ValueError("Plotly figure cannot contain cycles")
                active.add(identity)
                stack.append((item, depth, True))
                stack.extend((child, depth + item.ndim, False) for child in reversed(children))
                continue
            nodes += element_count + container_count
            if kind == "U":
                per_item = (int(item.dtype.itemsize) // 4) * 12 + 3
            elif kind == "S":
                per_item = int(item.dtype.itemsize) * 6 + 3
            elif kind in "mM":
                per_item = 129
            elif kind == "b":
                per_item = 6
            elif kind in "iu":
                bits = int(item.dtype.itemsize) * 8
                digits = (bits * 30103 + 99_999) // 100_000
                per_item = digits + (2 if kind == "i" else 1)
            elif kind == "f":
                per_item = 33
            elif kind == "c":
                raise TypeError("complex Plotly ndarray values are not supported")
            else:
                raise TypeError(f"unsupported Plotly ndarray dtype: {item.dtype}")
            list_bound = element_count * per_item + list_punctuation_bound
            base64_bound = 4 * ((int(item.nbytes) + 2) // 3) + 256
            total += max(list_bound, base64_bound)
        else:
            identity = id(item)
            if type(item) is dict:
                mapping = cast(dict[object, object], item)
                item_count = len(mapping)
                if 2 * item_count > _PLOTLY_PREFLIGHT_MAX_NODES - nodes:
                    raise ValueError("Plotly figure contains too many values")
                total += 2 + 2 * item_count
                identity = id(item)
                if identity in active:
                    raise ValueError("Plotly figure cannot contain cycles")
                active.add(identity)
                stack.append((item, depth, True))
                for key, child in reversed(tuple(mapping.items())):
                    if type(key) is not str:
                        raise TypeError("Plotly mappings must have string keys")
                    stack.append((child, depth + 1, False))
                    stack.append((key, depth + 1, False))
                continue
            elif type(item) in (list, tuple):
                sequence = cast(list[object] | tuple[object, ...], item)
                item_count = len(sequence)
                if item_count > _PLOTLY_PREFLIGHT_MAX_NODES - nodes:
                    raise ValueError("Plotly figure contains too many values")
                total += 2 + item_count
                identity = id(item)
                if identity in active:
                    raise ValueError("Plotly figure cannot contain cycles")
                active.add(identity)
                stack.append((item, depth, True))
                for child in reversed(sequence):
                    stack.append((child, depth + 1, False))
                continue
            else:
                raise TypeError(f"unsupported Plotly value: {type(item).__name__}")
        if total > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
            raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    if total > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
        raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")
    return total


def _snapshot_plotly_config(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Take a bounded private JSON config snapshot."""
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise TypeError("Plotly config must be a mapping or None")
    try:
        reported = len(config)
    except RuntimeError:
        # Preserve renderer-preparation reentrancy (and explicit custom
        # mapping RuntimeErrors) instead of disguising it as a shape error.
        raise
    except Exception as error:
        raise TypeError("Plotly config must be a finite mapping") from error
    if reported > _PLOTLY_CONFIG_MAX_ITEMS:
        raise ValueError(f"Plotly config cannot contain more than {_PLOTLY_CONFIG_MAX_ITEMS} items")
    try:
        items = tuple(itertools.islice(config.items(), _PLOTLY_CONFIG_MAX_ITEMS + 1))
    except RuntimeError:
        raise
    except Exception as error:
        raise TypeError("Plotly config must provide finite key/value items") from error
    if len(items) != reported or len(items) > _PLOTLY_CONFIG_MAX_ITEMS:
        raise ValueError("Plotly config length does not match its finite items")

    active: set[int] = set()
    nodes = 0

    def snapshot(value: object, depth: int) -> object:
        nonlocal nodes
        nodes += 1
        if nodes > _PLOTLY_PREFLIGHT_MAX_NODES:
            raise ValueError("Plotly config contains too many values")
        if depth > 64:
            raise ValueError("Plotly config is nested too deeply")
        if value is None or type(value) in (bool, int, str):
            if type(value) is str:
                _plotly_string_json_upper_bound(value)
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("Plotly config numbers must be finite")
            return value
        if type(value) not in (dict, list, tuple):
            raise TypeError(f"unsupported Plotly config value: {type(value).__name__}")
        identity = id(value)
        if identity in active:
            raise ValueError("Plotly config cannot contain cycles")
        active.add(identity)
        try:
            if type(value) is dict:
                output: dict[str, object] = {}
                reported = len(value)
                if reported > _PLOTLY_CONFIG_MAX_ITEMS:
                    raise ValueError(
                        f"Plotly config mappings cannot contain more than "
                        f"{_PLOTLY_CONFIG_MAX_ITEMS} items"
                    )
                items = tuple(itertools.islice(value.items(), _PLOTLY_CONFIG_MAX_ITEMS + 1))
                if len(items) != reported or len(items) > _PLOTLY_CONFIG_MAX_ITEMS:
                    raise ValueError("Plotly config mapping length changed during snapshot")
                for key, child in items:
                    if type(key) is not str:
                        raise TypeError("Plotly config mappings must have string keys")
                    _plotly_string_json_upper_bound(key)
                    output[key] = snapshot(child, depth + 1)
                return output
            values = cast(list[object] | tuple[object, ...], value)
            reported = len(values)
            if reported > _PLOTLY_CONFIG_MAX_ITEMS:
                raise ValueError(
                    f"Plotly config collections cannot contain more than "
                    f"{_PLOTLY_CONFIG_MAX_ITEMS} items"
                )
            materialized = tuple(itertools.islice(iter(values), _PLOTLY_CONFIG_MAX_ITEMS + 1))
            if len(materialized) != reported or len(materialized) > _PLOTLY_CONFIG_MAX_ITEMS:
                raise ValueError("Plotly config collection length changed during snapshot")
            copied = [snapshot(child, depth + 1) for child in materialized]
            return copied if type(value) is list else tuple(copied)
        finally:
            active.remove(identity)

    result: dict[str, Any] = {}
    for key, value in items:
        if type(key) is not str:
            raise TypeError("Plotly config mappings must have string keys")
        _plotly_string_json_upper_bound(key)
        if key in result:
            raise ValueError(f"Plotly config contains duplicate key {key!r}")
        result[key] = snapshot(value, 1)
    _plotly_graph_json_upper_bound(result)
    return result


def _plotly_figure_raw_graph(figure: go.Figure) -> tuple[object, object, object]:
    """Return exact stock Figure storage without invoking user overrides."""
    import plotly.graph_objects as go
    from plotly.basedatatypes import BaseFigure

    if type(figure) is not go.Figure:
        raise TypeError("figure must be an exact plotly.graph_objects.Figure")
    figure_type = type(figure)
    try:
        figure_to_json = type.__getattribute__(figure_type, "to_json")
        figure_to_dict = type.__getattribute__(figure_type, "to_dict")
        figure_getattribute = type.__getattribute__(figure_type, "__getattribute__")
    except AttributeError as error:
        raise TypeError("custom Plotly serialization overrides are not supported") from error
    if (
        type(figure_type) is not type
        or figure_to_json is not BaseFigure.to_json
        or figure_to_dict is not BaseFigure.to_dict
        or figure_getattribute is not object.__getattribute__
    ):
        raise TypeError("custom Plotly serialization overrides are not supported")
    state = object.__getattribute__(figure, "__dict__")
    if "to_json" in state or "to_dict" in state:
        raise TypeError("instance Plotly serialization overrides are not supported")
    frames = state.get("_frame_objs", []) or []
    from plotly.graph_objs import Frame

    if type(frames) is not list or any(type(frame) is not Frame for frame in frames):
        raise TypeError("custom Plotly frame objects are not supported")
    raw_frames: list[dict[str, object]] = []
    for frame in frames:
        frame_state = object.__getattribute__(frame, "__dict__")
        raw = frame_state.get("_orphan_props", {})
        if type(raw) is not dict:
            raise TypeError("Plotly frame properties must be an exact mapping")
        raw_frames.append(cast(dict[str, object], raw))
    return (
        state.get("_data", []),
        state.get("_layout", {}),
        raw_frames,
    )


def _plotly_json_and_config(
    figure: go.Figure, config: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any] | None]:
    """Serialize a preflighted Plotly figure and return its private config."""
    from plotly.basedatatypes import BaseFigure

    private_config = _snapshot_plotly_config(config)
    figure_bound = _plotly_graph_json_upper_bound(*_plotly_figure_raw_graph(figure))
    config_bound = 0 if private_config is None else _plotly_graph_json_upper_bound(private_config)
    if figure_bound + config_bound + 256 > _PLOTLY_JSON_MAX_UTF16_CODE_UNITS:
        raise ValueError("Plotly figure exceeds the 16 Mi-character browser render limit.")

    json_str = BaseFigure.to_json(figure)
    if not isinstance(json_str, str):
        raise TypeError("Plotly Figure.to_json() must return a string")
    json_str = _validate_plotly_json_size(json_str)
    if private_config is not None:
        plot_dict = json.loads(json_str)
        plot_dict["config"] = {**plot_dict.get("config", {}), **private_config}
        json_str = json.dumps(plot_dict)
    return _validate_plotly_json_size(json_str), private_config


def _plotly_json_with_config(figure: go.Figure, config: Mapping[str, Any] | None) -> str:
    """Serialize a bounded Plotly figure, merging an optional private config."""
    return _plotly_json_and_config(figure, config)[0]


def _plotly_payload_from_json(
    source: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Decode one bounded owned wire snapshot into fresh figure/config graphs."""
    # This is the immutable, already-admitted retained snapshot. Reapplying a
    # mutable test/configuration limit here could make a previously valid
    # handle unreadable; reconstruction remains serialized by the renderer
    # preparation reservation.
    payload = json.loads(source)
    if type(payload) is not dict:
        raise RuntimeError("stored Plotly payload is not a mapping")
    config = payload.pop("config", None)
    if config is not None and type(config) is not dict:
        raise RuntimeError("stored Plotly config is not a mapping")
    return cast(dict[str, Any], payload), cast(dict[str, Any] | None, config)


def _plotly_figure_from_json(source: str) -> go.Figure:
    """Reconstruct independently without consulting Plotly's global template."""
    import plotly.graph_objects as go

    payload, _ = _plotly_payload_from_json(source)
    layout = payload.get("layout")
    if layout is None:
        layout = {}
        payload["layout"] = layout
    if type(layout) is not dict:
        raise RuntimeError("stored Plotly layout is not a mapping")
    template_was_absent = "template" not in layout
    if template_was_absent:
        # BaseFigure injects the mutable process-global default whenever the
        # prospective layout has no template. A private empty template is the
        # race-free constructor sentinel; clear it afterward so the returned
        # Figure still represents the admitted template-free JSON exactly.
        layout["template"] = {}
    figure = go.Figure(payload)
    if template_was_absent:
        figure.layout.template = None
    return figure


def _raw_plotly_template_graph(template: object) -> tuple[object, ...]:
    """Return exact stock-template storage without invoking attribute hooks."""
    from plotly.graph_objs.layout import Template

    if type(template) is not Template:
        raise TypeError("Plotly template must be an exact stock Template")
    state = object.__getattribute__(template, "__dict__")
    raw = state.get("_orphan_props", {})
    if type(raw) is not dict:
        raise TypeError("Plotly template properties must be an exact mapping")
    return (raw,)


def _bounded_plotly_template_dict(template: object) -> dict[str, Any]:
    """Preflight and structurally snapshot one mutable global template."""
    raw = _raw_plotly_template_graph(template)[0]
    _plotly_graph_json_upper_bound(raw)
    result = _snapshot_plotly_config(cast(dict[str, Any], raw))
    if result is None:  # pragma: no cover - raw template storage is a dict
        raise RuntimeError("Plotly template snapshot unexpectedly vanished")
    _plotly_graph_json_upper_bound(result)
    return result


def _plotly_json_for_pane(
    figure: go.Figure, config: Mapping[str, Any] | None
) -> tuple[str, dict[str, Any] | None]:
    """Serialize a figure for a Plotly pane and return its private config."""
    import plotly.io as pio

    global _stock_plotly_template_json
    if _stock_plotly_template_json is None:
        _stock_plotly_template_json = _bounded_plotly_template_dict(pio.templates["plotly"])

    json_str, private_config = _plotly_json_and_config(figure, config)
    raw_layout = _plotly_figure_layout(figure)
    template = raw_layout.get("template") if type(raw_layout) is dict else None
    if template is None or template == _stock_plotly_template_json:
        plot_dict = json.loads(json_str)
        plot_dict.get("layout", {}).pop("template", None)
        json_str = json.dumps(plot_dict)
    return _validate_plotly_json_size(json_str), private_config


def _plotly_figure_layout(figure: go.Figure) -> object:
    """Read BaseFigure raw layout storage after shared preflight."""
    return _plotly_figure_raw_graph(figure)[1]


def _plotly_theme_templates_json() -> str:
    """Themed defaults for figures that do not specify a template."""
    import plotly.io as pio

    global _theme_templates_json
    if _theme_templates_json is None:
        templates = {
            "light": _bounded_plotly_template_dict(pio.templates["plotly_white"]),
            "dark": _bounded_plotly_template_dict(pio.templates["plotly_dark"]),
        }
        _plotly_graph_json_upper_bound(templates)
        _theme_templates_json = _validate_plotly_json_size(json.dumps(templates))
    return _theme_templates_json
