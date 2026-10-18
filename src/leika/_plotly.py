"""Plotly serialization shared by GUI plots and Plotly panes.

Plotly is an optional dependency, imported only when a figure is used.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import plotly.graph_objects as go


def plotly_config(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a private JSON copy of a Plotly config mapping."""
    if config is None:
        return None
    if not isinstance(config, Mapping):
        raise TypeError("Plotly config must be a mapping or None.")
    return json.loads(json.dumps(dict(config)))


def plotly_json(figure: go.Figure, config: dict[str, Any] | None) -> str:
    """Serialize a figure, with its config, for the browser.

    A figure without a template, or with Plotly's stock default, is sent
    without one; the browser then applies the light or dark template that
    matches the viewer's theme.
    """
    import plotly.graph_objects as go
    from plotly.utils import PlotlyJSONEncoder

    if not isinstance(figure, go.Figure):
        raise TypeError("figure must be a plotly.graph_objects.Figure.")
    plot = figure.to_dict()
    layout = plot.setdefault("layout", {})
    if layout.get("template") in (None, _stock_template()):
        layout.pop("template", None)
    if config is not None:
        plot["config"] = config
    return json.dumps(plot, cls=PlotlyJSONEncoder, separators=(",", ":"))


def plotly_figure(source: str) -> go.Figure:
    """Rebuild an independent figure from :func:`plotly_json` output."""
    import plotly.graph_objects as go

    plot = json.loads(source)
    plot.pop("config", None)
    layout = plot.setdefault("layout", {})
    themed = "template" not in layout
    if themed:
        # An empty template keeps Plotly from applying its global default.
        layout["template"] = {}
    figure = go.Figure(plot)
    if themed:
        figure.layout.template = None
    return figure


@functools.cache
def plotly_theme_templates() -> str:
    """Light and dark templates for figures that leave theming to the viewer."""
    import plotly.io as pio
    from plotly.utils import PlotlyJSONEncoder

    templates = {
        "light": pio.templates["plotly_white"].to_plotly_json(),
        "dark": pio.templates["plotly_dark"].to_plotly_json(),
    }
    return json.dumps(templates, cls=PlotlyJSONEncoder, separators=(",", ":"))


@functools.cache
def _stock_template() -> dict[str, Any]:
    import plotly.io as pio

    return pio.templates["plotly"].to_plotly_json()
