"""Native image, matplotlib, Plotly, and viser panes for a Leika workspace."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import json
import threading
import urllib.parse
import uuid
import warnings
import weakref
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable, Generic, Literal, NewType, TypeVar, cast

import numpy as np
from typing_extensions import TypeAlias

from . import _messages
from ._gui_handles import (
    _ndarray_snapshot_spec,
    _plotly_figure_from_json,
    _plotly_graph_json_upper_bound,
    _plotly_json_and_config,
    _plotly_payload_from_json,
    _private_ndarray_snapshot,
    _snapshot_plotly_config,
    _validate_plotly_json_size,
)
from ._image_encoding import _validate_image_encoding_options, encode_image_binary
from ._validation import (
    utf16_code_unit_length,
    utf16_code_unit_length_exceeds,
    validate_layout_id,
    validate_renderer_string,
)
from ._validation import (
    validate_positive_integer as _validate_positive_integer,
)
from .infra._image_headers import validate_image_pixel_size

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from ._server import Server


# Named the way this control usually is, rather than after the CSS keywords the
# browser ends up applying: "fill" here means filling the pane (CSS `cover`),
# and stretching is spelled out.
ImageFit: TypeAlias = Literal["fit", "fill", "stretch"]
Placement: TypeAlias = Literal["left", "right", "top", "bottom"]
PaneId = NewType("PaneId", str)


_stock_plotly_template_json: dict[str, Any] | None = None
_theme_templates_json: str | None = None

_PANE_MAX = 128
_VISER_PANE_MAX = 16
_PANE_TEXT_MAX_UTF16_CODE_UNITS = 32 * 1024 * 1024
_PANE_PAYLOAD_MAX_BYTES = 256 * 1024 * 1024
_PANE_PIXELS_MAX = 64 * 1024 * 1024


@dataclasses.dataclass(frozen=True)
class _PaneResourceCost:
    text_units: int = 0
    payload_bytes: int = 0
    decoded_pixels: int = 0


class _PanesAggregate:
    """Server-wide ownership shared by every page's local pane registry."""

    def __init__(self, owner: Server) -> None:
        self._owner = owner
        self._lock = threading.RLock()
        self.resource_total = _PaneResourceCost()
        self.live_panes = 0
        self.live_viser_panes = 0

    def replace_resource(
        self,
        old: _PaneResourceCost,
        new: _PaneResourceCost,
    ) -> None:
        with self._lock:
            prospective = _PaneResourceCost(
                self.resource_total.text_units - old.text_units + new.text_units,
                self.resource_total.payload_bytes - old.payload_bytes + new.payload_bytes,
                self.resource_total.decoded_pixels - old.decoded_pixels + new.decoded_pixels,
            )
            if prospective.text_units > _PANE_TEXT_MAX_UTF16_CODE_UNITS:
                raise RuntimeError("Panes exceeded the 32 Mi UTF-16 source budget.")
            if prospective.payload_bytes > _PANE_PAYLOAD_MAX_BYTES:
                raise RuntimeError("Panes exceeded the 256 MiB retained payload budget.")
            if prospective.decoded_pixels > _PANE_PIXELS_MAX:
                raise RuntimeError("Panes exceeded the 64 Mi-pixel raster budget.")
            if (
                min(
                    prospective.text_units,
                    prospective.payload_bytes,
                    prospective.decoded_pixels,
                )
                < 0
            ):
                raise RuntimeError("pane aggregate resource accounting underflow")

            # Pane rasters share the browser page allowance with server.gui.
            from ._gui_handles import _GuiResourceCost

            self._owner._replace_gui_resource_cost(
                _GuiResourceCost(decoded_pixels=old.decoded_pixels),
                _GuiResourceCost(decoded_pixels=new.decoded_pixels),
                page_global=True,
            )
            self.resource_total = prospective

    def reserve_pane(self, *, viser: bool) -> None:
        with self._lock:
            if self.live_panes >= _PANE_MAX:
                raise RuntimeError(f"A workspace cannot own more than {_PANE_MAX} panes.")
            if viser and self.live_viser_panes >= _VISER_PANE_MAX:
                raise RuntimeError(
                    f"A workspace cannot own more than {_VISER_PANE_MAX} viser panes."
                )
            self.live_panes += 1
            if viser:
                self.live_viser_panes += 1

    def release_pane(self, *, viser: bool) -> None:
        with self._lock:
            if self.live_panes <= 0 or (viser and self.live_viser_panes <= 0):
                raise RuntimeError("pane aggregate count accounting underflow")
            self.live_panes -= 1
            if viser:
                self.live_viser_panes -= 1


def _pane_resource_cost(handle: "PaneHandle[Any]") -> _PaneResourceCost:
    props = handle._impl.props
    text_units = 0
    payload_bytes = 0
    for field in dataclasses.fields(props):
        value = getattr(props, field.name)
        if isinstance(value, str):
            text_units += utf16_code_unit_length(value)
            payload_bytes += len(value.encode("utf-8"))
        elif isinstance(value, bytes):
            payload_bytes += len(value)
    decoded_pixels = 0
    if isinstance(handle, ImagePaneHandle):
        image = handle._impl.image
        payload_bytes += int(image.nbytes)
        decoded_pixels = int(image.shape[0]) * int(image.shape[1])
    return _PaneResourceCost(text_units, payload_bytes, decoded_pixels)


_MATPLOTLIB_SVG_MAX_UTF16_CODE_UNITS = 16 * 1024 * 1024
"""Bundled browser parser limit for one Matplotlib SVG pane."""


class _BoundedSvgBuffer(io.BytesIO):
    """Bound Matplotlib output before exact UTF-16 validation."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__()
        self._max_bytes = max_bytes

    def write(self, data: Any) -> int:
        proposed = self.tell() + len(data)
        if proposed > self._max_bytes:
            raise ValueError("Matplotlib figure exceeds the 16 Mi-character browser render limit.")
        return super().write(data)


def _validate_title_visible(title: object, visible: object) -> tuple[str, bool]:
    title = cast(str, validate_renderer_string(title, "pane title"))
    if type(visible) is not bool:
        raise TypeError("visible must be a bool")
    return title, visible


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
    from ._gui_handles import _plotly_figure_raw_graph

    return _plotly_figure_raw_graph(figure)[1]


def _matplotlib_figure_ref(figure: Any) -> weakref.ReferenceType[Any]:
    """Require a renderer and non-owning introspection before any work."""
    if not callable(getattr(figure, "savefig", None)):
        raise TypeError(
            f"figure must be a matplotlib Figure (an object with a savefig method); got {figure!r}."
        )
    try:
        return weakref.ref(figure)
    except TypeError as error:
        raise TypeError(
            "matplotlib figure sources must support weak references so Leika "
            "does not retain an unbounded caller-owned graph"
        ) from error


def _matplotlib_svg(figure: Any) -> str:
    """Serialize a matplotlib figure to SVG source.

    SVG rather than pixels so a resized pane rescales the figure crisply
    without a Python redraw. The figure is written exactly as composed --
    no tight bounding box, no recoloring -- so what the pane shows is what
    ``savefig`` would have written.
    """

    savefig = getattr(figure, "savefig", None)
    if not callable(savefig):
        raise TypeError(
            f"figure must be a matplotlib Figure (an object with a savefig method); got {figure!r}."
        )
    # A valid string within the UTF-16 limit needs at most three UTF-8 bytes
    # per code unit. Bound generation at that conservative ceiling, then apply
    # the client's exact JavaScript-string limit after decoding.
    buffer = _BoundedSvgBuffer(_MATPLOTLIB_SVG_MAX_UTF16_CODE_UNITS * 3)
    savefig(buffer, format="svg")
    svg = buffer.getvalue().decode("utf-8")
    if utf16_code_unit_length_exceeds(svg, _MATPLOTLIB_SVG_MAX_UTF16_CODE_UNITS):
        raise ValueError("Matplotlib figure exceeds the 16 Mi-character browser render limit.")
    return svg


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


def _viser_embed_target(target: str | Any) -> tuple[str | None, int | None]:
    """Normalize a viser target into ``(url, port)``, exactly one set.

    Accepts an absolute http(s) URL, used near-verbatim, or a viser
    ``ViserServer``-like object, duck-typed on callable ``get_port()`` and
    ``get_host()``. Only the port is kept from server objects: viser binds
    ``0.0.0.0`` by default, so its Python-side host is not something a
    browser can connect to. The client instead combines the port with the
    hostname the Leika page itself was loaded from.
    """

    if isinstance(target, str):
        target = cast(str, validate_renderer_string(target, "Viser target URL"))
        if target != target.strip() or any(
            ord(character) <= 32 or ord(character) == 127 for character in target
        ):
            raise ValueError(f"Viser target URL is malformed: {target!r}.")
        try:
            parts = urllib.parse.urlsplit(target)
            port = parts.port
        except ValueError as error:
            raise ValueError(f"Viser target URL is malformed: {target!r}.") from error
        if (
            parts.scheme not in ("http", "https")
            or not parts.netloc
            or parts.hostname is None
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
        ):
            raise ValueError(f"Viser target URLs must be absolute http(s) URLs; got {target!r}.")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError(f"Viser target URL has an invalid port: {target!r}.")
        host = parts.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        authority = host if port is None else f"{host}:{port}"
        return urllib.parse.urlunsplit(
            (parts.scheme.lower(), authority, parts.path, parts.query, "")
        ), None

    get_port = getattr(target, "get_port", None)
    get_host = getattr(target, "get_host", None)
    if callable(get_port) and callable(get_host):
        port = cast("Any", get_port())
        if type(port) is not int:
            raise TypeError(f"Viser server reported a non-integer port: {port!r}.")
        if port == 0:
            raise ValueError(
                "Viser server reported port 0: released viser versions do not "
                "report the bound port for ViserServer(port=0). Construct the "
                "server with a concrete port instead; viser probes upward if "
                "it is taken and get_port() then reports the real one."
            )
        if not 1 <= port <= 65535:
            raise ValueError(f"Viser server reported an invalid port: {port!r}.")
        return None, port

    raise TypeError(
        "target must be a viser ViserServer (an object with get_port() and "
        f"get_host() methods) or an absolute http(s) URL; got {target!r}."
    )


def _minimize_viser_gui(target: Any) -> None:
    """Best-effort: dock viser's control panel to the right viewport edge and
    minimize it to a vertical rail, so Leika's own GUI is the one in charge.

    Uses viser's ``gui.main_panel`` placement API, duck-typed so Leika never
    imports viser. The commands are imperative and replayed to clients that
    connect later, so calling this before the pane's iframe loads still
    applies. Released viser (<= 1.0.30) predates ``main_panel``; there this
    is a no-op and viser's panel stays visible.
    """

    main_panel = getattr(getattr(target, "gui", None), "main_panel", None)
    dock_right = getattr(main_panel, "dock_right", None)
    minimize = getattr(main_panel, "minimize", None)
    if callable(dock_right) and callable(minimize):
        try:
            dock_right()
            minimize()
        except Exception as error:
            warnings.warn(
                f"Could not minimize viser's control panel: {error}",
                RuntimeWarning,
                stacklevel=3,
            )


@dataclasses.dataclass
class _ImagePaneHandleState:
    pane_id: str
    props: _messages.ViewportImageProps
    api: Panes
    image: np.ndarray
    requested_format: Literal["auto", "jpeg", "png"]
    jpeg_quality: int | None
    removed: bool = False


@dataclasses.dataclass
class _MatplotlibPaneHandleState:
    pane_id: str
    props: _messages.ViewportMatplotlibProps
    api: Panes
    figure_ref: weakref.ReferenceType[Any] | None
    removed: bool = False


@dataclasses.dataclass
class _PlotlyPaneHandleState:
    pane_id: str
    props: _messages.ViewportPlotlyProps
    api: Panes
    removed: bool = False


@dataclasses.dataclass
class _ViserPaneHandleState:
    pane_id: str
    props: _messages.ViewportViserProps
    api: Panes
    minimize_gui: bool
    removed: bool = False


_PaneStateT = TypeVar(
    "_PaneStateT",
    _ImagePaneHandleState,
    _MatplotlibPaneHandleState,
    _PlotlyPaneHandleState,
    _ViserPaneHandleState,
)


def _scrub_pane_handle_locked(handle: "PaneHandle[Any]") -> None:
    """Drop all resource-charged state after terminal pane retirement."""
    props = handle._impl.props
    props.title = ""
    if isinstance(handle, ImagePaneHandle):
        handle._impl.image = np.empty((0,), dtype=np.uint8)
        handle._impl.requested_format = "auto"
        handle._impl.jpeg_quality = None
        handle._impl.props._data = b""
    elif isinstance(handle, MatplotlibPaneHandle):
        handle._impl.figure_ref = None
        handle._impl.props._svg = ""
    elif isinstance(handle, PlotlyPaneHandle):
        handle._impl.props._plotly_json_str = ""
        handle._impl.props._theme_templates = ""
    elif isinstance(handle, ViserPaneHandle):
        handle._impl.props._url = None
        handle._impl.props._port = None


class PaneHandle(Generic[_PaneStateT]):
    """Lifecycle and property logic shared by all pane handles."""

    _impl: _PaneStateT

    def _check_not_removed(self) -> None:
        if self._impl.removed:
            raise RuntimeError(f"Cannot update a removed {type(self).__name__}.")

    def _queue_update(self, updates: dict[str, Any]) -> None:
        self._impl.api._websock_interface.queue_message_or_raise(
            _messages.ViewportPaneUpdateMessage(
                page_id=self._impl.api._page_id,
                pane_id=self._impl.pane_id,
                updates=updates,
            )
        )

    @property
    def pane_id(self) -> PaneId:
        """Stable identifier used to restore browser-managed layouts."""

        return PaneId(self._impl.pane_id)

    @property
    def title(self) -> str:
        """Title rendered in the pane's corner label."""

        self._check_not_removed()
        return self._impl.props.title

    @title.setter
    def title(self, value: str) -> None:
        self._check_not_removed()
        value = cast(str, validate_renderer_string(value, "pane title"))
        with self._impl.api._lock:
            self._check_not_removed()
            if value == self._impl.props.title:
                return
            old_value = self._impl.props.title
            self._impl.props.title = value
            try:
                with self._impl.api._resource_transaction_locked(self):
                    self._queue_update({"title": value})
            except BaseException:
                self._impl.props.title = old_value
                raise

    @property
    def visible(self) -> bool:
        """Whether this pane is visible."""

        self._check_not_removed()
        return self._impl.props.visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._check_not_removed()
        if type(value) is not bool:
            raise TypeError("visible must be a bool")
        with self._impl.api._lock:
            self._check_not_removed()
            if value == self._impl.props.visible:
                return
            old_value = self._impl.props.visible
            self._impl.props.visible = value
            try:
                self._queue_update({"visible": value})
            except BaseException:
                self._impl.props.visible = old_value
                raise

    def remove(self) -> None:
        """Permanently remove this pane from the workspace."""

        api = self._impl.api
        with api._lock:
            if self._impl.removed:
                warnings.warn(
                    f"Attempted to remove an already removed {type(self).__name__}.",
                    stacklevel=2,
                )
                return
            remaining = tuple(
                pane_id for pane_id in api._handle_from_pane_id if pane_id != self._impl.pane_id
            )
            api._websock_interface.queue_messages_or_raise(
                (
                    _messages.ViewportPaneRemoveMessage(
                        page_id=api._page_id,
                        pane_id=self._impl.pane_id,
                    ),
                    api._snapshot_message(remaining),
                )
            )
            self._impl.removed = True
            api._handle_from_pane_id.pop(self._impl.pane_id, None)
            try:
                api._release_resource_locked(self._impl.pane_id)
            finally:
                try:
                    api._aggregate.release_pane(viser=isinstance(self, ViserPaneHandle))
                finally:
                    _scrub_pane_handle_locked(self)


class ImagePaneHandle(PaneHandle[_ImagePaneHandleState]):
    """Handle for updating or removing a native image pane."""

    def __init__(self, state: _ImagePaneHandleState) -> None:
        self._impl = state

    @property
    def image(self) -> np.ndarray:
        """Current image. Assign a new array to stream another frame."""

        self._check_not_removed()
        return self._impl.image.copy()

    @image.setter
    def image(self, image: np.ndarray) -> None:
        self._check_not_removed()
        image = _validate_image(image)
        spec = _ndarray_snapshot_spec(image)
        if spec[2] > _PANE_PAYLOAD_MAX_BYTES:
            raise RuntimeError("Image source exceeds the 256 MiB pane retained payload budget.")
        with self._impl.api._owner._reserve_image_preparation(spec[2]):
            snapshot = _private_ndarray_snapshot(image, spec)
            resolved_format, data = encode_image_binary(
                snapshot,
                self._impl.requested_format,
                jpeg_quality=self._impl.jpeg_quality,
            )
            if self._impl.requested_format == "jpeg" and snapshot.shape[2] == 4:
                warnings.warn(
                    "Encoding an RGBA pane image as JPEG discards its alpha channel.",
                    stacklevel=2,
                )
            self._commit_image_snapshot(snapshot, resolved_format, data)

    def _commit_image_snapshot(
        self,
        image: np.ndarray,
        resolved_format: Literal["jpeg", "png"],
        data: bytes,
    ) -> None:
        """Publish one already-prepared private pane image snapshot."""
        with self._impl.api._lock:
            # Encoding can be expensive. Recheck after taking the lock so a
            # concurrent remove cannot queue an update for a reused pane ID.
            self._check_not_removed()
            old_image = self._impl.image
            old_format = self._impl.props._format
            old_data = self._impl.props._data
            self._impl.image = image
            self._impl.props._format = resolved_format
            self._impl.props._data = data
            try:
                with self._impl.api._resource_transaction_locked(self):
                    self._queue_update({"_format": resolved_format, "_data": data})
            except BaseException:
                self._impl.image = old_image
                self._impl.props._format = old_format
                self._impl.props._data = old_data
                raise

    def update(self, image: np.ndarray) -> None:
        """Replace the pane image using its configured transport encoding."""

        self.image = image

    @property
    def format(self) -> Literal["auto", "jpeg", "png"]:
        """Encoding requested when this pane was created."""

        self._check_not_removed()
        return self._impl.requested_format

    @property
    def fit(self) -> ImageFit | None:
        """How the image is sized within its pane, or None to follow the
        viewer's own "Image fit" setting."""

        self._check_not_removed()
        return self._impl.props.fit

    @fit.setter
    def fit(self, value: ImageFit | None) -> None:
        self._check_not_removed()
        value = _validate_fit(value)
        with self._impl.api._lock:
            self._check_not_removed()
            if value == self._impl.props.fit:
                return
            old_value = self._impl.props.fit
            self._impl.props.fit = value
            try:
                self._queue_update({"fit": value})
            except BaseException:
                self._impl.props.fit = old_value
                raise


class MatplotlibPaneHandle(PaneHandle[_MatplotlibPaneHandleState]):
    """Handle that owns bounded SVG, with only a weak caller-Figure reference."""

    def __init__(self, state: _MatplotlibPaneHandleState) -> None:
        self._impl = state

    @property
    def figure(self) -> Any:
        """Caller-owned source figure, if it is still alive. Assign to update."""

        self._check_not_removed()
        reference = self._impl.figure_ref
        figure = None if reference is None else reference()
        if figure is None:
            raise RuntimeError(
                "The caller-owned Matplotlib figure is no longer available; "
                "retain it or assign another figure."
            )
        return figure

    @figure.setter
    def figure(self, figure: Any) -> None:
        self._check_not_removed()
        figure_ref = _matplotlib_figure_ref(figure)
        with self._impl.api._owner._reserve_renderer_preparation():
            svg = _matplotlib_svg(figure)
        with self._impl.api._lock:
            # Serialization can be expensive. Recheck after taking the lock so
            # a concurrent remove cannot queue an update for a reused pane ID.
            self._check_not_removed()
            old_figure_ref = self._impl.figure_ref
            old_svg = self._impl.props._svg
            self._impl.figure_ref = figure_ref
            self._impl.props._svg = svg
            try:
                with self._impl.api._resource_transaction_locked(self):
                    self._queue_update({"_svg": svg})
            except BaseException:
                self._impl.figure_ref = old_figure_ref
                self._impl.props._svg = old_svg
                raise

    def update(self, figure: Any) -> None:
        """Replace the matplotlib figure while retaining the pane configuration.

        Call this after redrawing to push a new frame; matplotlib mutates
        figures in place, so re-passing the same figure is normal.
        """

        self.figure = figure


class PlotlyPaneHandle(PaneHandle[_PlotlyPaneHandleState]):
    """Handle backed only by bounded JSON, never by the caller's mutable Figure."""

    def __init__(self, state: _PlotlyPaneHandleState) -> None:
        self._impl = state

    @property
    def figure(self) -> go.Figure:
        """Independent snapshot of the displayed figure. Assign it to publish edits."""

        api = self._impl.api
        with api._lock:
            self._check_not_removed()
            source = self._impl.props._plotly_json_str
        with api._owner._reserve_renderer_preparation():
            figure = _plotly_figure_from_json(source)
        with api._lock:
            self._check_not_removed()
        return figure

    @figure.setter
    def figure(self, figure: go.Figure) -> None:
        api = self._impl.api
        with api._lock:
            self._check_not_removed()
            source = self._impl.props._plotly_json_str
        with api._owner._reserve_renderer_preparation():
            _, config = _plotly_payload_from_json(source)
            json_str, _ = _plotly_json_for_pane(figure, config)
        with api._lock:
            # Serialization can be expensive. Recheck after taking the lock so
            # a concurrent remove cannot queue an update for a reused pane ID.
            self._check_not_removed()
            if self._impl.props._plotly_json_str != source:
                raise RuntimeError("Plotly figure changed during serialization")
            old_json = self._impl.props._plotly_json_str
            self._impl.props._plotly_json_str = json_str
            try:
                with self._impl.api._resource_transaction_locked(self):
                    self._queue_update({"_plotly_json_str": json_str})
            except BaseException:
                self._impl.props._plotly_json_str = old_json
                raise

    def update(self, figure: go.Figure) -> None:
        """Replace the Plotly figure while retaining the pane configuration."""

        self.figure = figure


class ViserPaneHandle(PaneHandle[_ViserPaneHandleState]):
    """Handle for re-pointing or removing an embedded viser pane."""

    def __init__(self, state: _ViserPaneHandleState) -> None:
        self._impl = state

    @property
    def url(self) -> str | None:
        """Embed URL currently shown in the pane, or None for port-based
        targets, where the browser derives the address itself."""

        self._check_not_removed()
        return self._impl.props._url

    @property
    def port(self) -> int | None:
        """Viser server port for port-based targets, or None when the pane
        was pointed at an explicit URL."""

        self._check_not_removed()
        return self._impl.props._port

    def update(self, target: str | Any) -> None:
        """Re-point the pane at another viser server or URL. Accepts the
        same targets as :meth:`Panes.add_viser`, and re-applies the pane's
        creation-time ``minimize_gui`` choice to server targets — including
        the current one, so calling with the same server re-minimizes a
        panel the viewer expanded."""

        self._check_not_removed()
        url, port = _viser_embed_target(target)
        with self._impl.api._lock:
            self._check_not_removed()
            changed = url != self._impl.props._url or port != self._impl.props._port
            if changed:
                old_url = self._impl.props._url
                old_port = self._impl.props._port
                self._impl.props._url = url
                self._impl.props._port = port
                # Both keys are always sent so the exactly-one-set invariant
                # holds on the client after any update.
                try:
                    with self._impl.api._resource_transaction_locked(self):
                        self._queue_update({"_url": url, "_port": port})
                except BaseException:
                    self._impl.props._url = old_url
                    self._impl.props._port = old_port
                    raise
        if port is not None and self._impl.minimize_gui:
            _minimize_viser_gui(target)


class PaneGroup:
    """Adds panes to an equally divided row or column.

    Returned by :meth:`Panes.add_row` and :meth:`Panes.add_column`.
    Each pane added through the group is placed along the group's axis and the
    group re-divides its combined space equally, without disturbing panes
    outside the group. The group only shapes creation-time placement: creating
    it sends nothing to clients, panes it creates are ordinary panes
    afterwards, and browser-saved arrangements still take precedence on
    reload.
    """

    def __init__(
        self,
        api: Panes,
        axis: Literal["row", "column"],
        placement: Placement,
        relative_to: str | None,
    ) -> None:
        if type(axis) is not str or axis not in ("row", "column"):
            raise ValueError("axis must be 'row' or 'column'.")
        if type(placement) is not str or placement not in (
            "left",
            "right",
            "top",
            "bottom",
        ):
            raise ValueError("placement must be left, right, top, or bottom.")
        self._api = api
        self._axis: Literal["row", "column"] = axis
        self._placement: Placement = placement
        self._relative_to = (
            None if relative_to is None else validate_layout_id(relative_to, "relative_to")
        )
        self._members: list[weakref.ReferenceType[PaneHandle[Any]]] = []
        self._declaration_lock = threading.Lock()

    def _next_declaration(
        self,
    ) -> tuple[Placement, str, tuple[str, ...]]:
        """Placement hints for the group's next pane.

        Hidden and removed members cannot anchor placement or take part in
        equalization, so the next pane attaches to the group's last member
        that is still visible; when none remain, it falls back to the group's
        own placement, like a first pane. Membership is checked by handle
        identity so an unrelated pane reusing a removed member's ID is not
        adopted into the group.
        """

        with self._api._lock:
            live_handles = [
                handle
                for reference in self._members
                if (handle := reference()) is not None
                and self._api._handle_from_pane_id.get(handle.pane_id) is handle
            ]
        self._members = [weakref.ref(handle) for handle in live_handles]
        members = [handle.pane_id for handle in live_handles if handle.visible]
        if not members:
            # A group's original anchor can itself be hidden or removed before
            # the next member is declared (notably a grid column whose adopted
            # top-row seed disappeared). Fall back to the API's current visible
            # default instead of resolving a stale ID.
            visible = self._api._visible_pane_ids()
            relative_to = self._relative_to if self._relative_to in visible else None
            return self._placement, self._api._resolve_relative_to(relative_to), ()
        placement: Placement = "right" if self._axis == "row" else "bottom"
        return placement, members[-1], tuple(members)

    def add_image(
        self,
        image: np.ndarray,
        *,
        pane_id: str | None = None,
        title: str = "Image",
        format: Literal["auto", "png", "jpeg"] = "auto",
        jpeg_quality: int | None = None,
        fit: ImageFit | None = None,
        visible: bool = True,
    ) -> ImagePaneHandle:
        """Add an image pane to the group. Accepts the same arguments as
        :meth:`Panes.add_image`, minus placement, which the group
        owns."""

        with self._declaration_lock:
            placement, relative_to, equalize_group = self._next_declaration()
            handle = self._api._add_image(
                image,
                pane_id=pane_id,
                title=title,
                format=format,
                jpeg_quality=jpeg_quality,
                fit=fit,
                visible=visible,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            )
            self._members.append(weakref.ref(handle))
        return handle

    def add_matplotlib(
        self,
        figure: Any,
        *,
        pane_id: str | None = None,
        title: str = "Figure",
        visible: bool = True,
    ) -> MatplotlibPaneHandle:
        """Add a matplotlib pane to the group. Accepts the same arguments as
        :meth:`Panes.add_matplotlib`, minus placement, which the group
        owns."""

        with self._declaration_lock:
            placement, relative_to, equalize_group = self._next_declaration()
            handle = self._api._add_matplotlib(
                figure,
                pane_id=pane_id,
                title=title,
                visible=visible,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            )
            self._members.append(weakref.ref(handle))
        return handle

    def add_plotly(
        self,
        figure: go.Figure,
        *,
        config: Mapping[str, Any] | None = None,
        pane_id: str | None = None,
        title: str = "Plotly",
        visible: bool = True,
    ) -> PlotlyPaneHandle:
        """Add a Plotly pane to the group. Accepts the same arguments as
        :meth:`Panes.add_plotly`, minus placement, which the group
        owns."""

        with self._declaration_lock:
            placement, relative_to, equalize_group = self._next_declaration()
            handle = self._api._add_plotly(
                figure,
                config=config,
                pane_id=pane_id,
                title=title,
                visible=visible,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            )
            self._members.append(weakref.ref(handle))
        return handle

    def add_viser(
        self,
        target: str | Any,
        *,
        pane_id: str | None = None,
        title: str = "viser",
        visible: bool = True,
        minimize_gui: bool = True,
    ) -> ViserPaneHandle:
        """Add a viser pane to the group. Accepts the same arguments as
        :meth:`Panes.add_viser`, minus placement, which the group
        owns."""

        with self._declaration_lock:
            placement, relative_to, equalize_group = self._next_declaration()
            handle = self._api._add_viser(
                target,
                pane_id=pane_id,
                title=title,
                visible=visible,
                minimize_gui=minimize_gui,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            )
            self._members.append(weakref.ref(handle))
        return handle


class PaneGrid:
    """Adds panes to an equally divided grid.

    Returned by :meth:`Panes.add_grid`. Panes fill left to right, top
    to bottom: the first ``columns`` panes form the top row, and later panes
    wrap onto new rows beneath it, re-dividing their row and column equally
    on each addition. Like :class:`PaneGroup`, the grid only shapes
    creation-time placement; see it for details.
    """

    def __init__(
        self,
        api: Panes,
        columns: int,
        placement: Placement,
        relative_to: str | None,
    ) -> None:
        _validate_positive_integer(columns, "columns")
        self._api = api
        self._columns = columns
        self._row = PaneGroup(api, "row", placement, relative_to)
        self._column_groups: list[PaneGroup] = []
        self._count = 0
        self._declaration_lock = threading.Lock()

    def _next_group(self) -> PaneGroup:
        """Group that places the grid's next pane: the shared top row while
        it is still filling, then the column the pane wraps onto."""

        if self._count < self._columns:
            return self._row
        return self._column_groups[self._count % self._columns]

    def _track(self, group: PaneGroup, handle: PaneHandle[Any]) -> None:
        """Advance the fill position after a successful add. A top-row pane
        seeds its column group as an adopted first member, so panes beneath
        equalize together with it into exact equal parts."""

        if group is self._row:
            column = PaneGroup(self._api, "column", "bottom", relative_to=handle.pane_id)
            column._members.append(weakref.ref(handle))
            self._column_groups.append(column)
        self._count += 1
        if self._count >= 2 * self._columns:
            self._count = self._columns

    def add_image(
        self,
        image: np.ndarray,
        *,
        pane_id: str | None = None,
        title: str = "Image",
        format: Literal["auto", "png", "jpeg"] = "auto",
        jpeg_quality: int | None = None,
        fit: ImageFit | None = None,
        visible: bool = True,
    ) -> ImagePaneHandle:
        """Add an image pane to the grid's next cell. Accepts the same
        arguments as :meth:`Panes.add_image`, minus placement, which
        the grid owns."""

        with self._declaration_lock:
            group = self._next_group()
            handle = group.add_image(
                image,
                pane_id=pane_id,
                title=title,
                format=format,
                jpeg_quality=jpeg_quality,
                fit=fit,
                visible=visible,
            )
            self._track(group, handle)
        return handle

    def add_matplotlib(
        self,
        figure: Any,
        *,
        pane_id: str | None = None,
        title: str = "Figure",
        visible: bool = True,
    ) -> MatplotlibPaneHandle:
        """Add a matplotlib pane to the grid's next cell. Accepts the same
        arguments as :meth:`Panes.add_matplotlib`, minus placement, which
        the grid owns."""

        with self._declaration_lock:
            group = self._next_group()
            handle = group.add_matplotlib(
                figure,
                pane_id=pane_id,
                title=title,
                visible=visible,
            )
            self._track(group, handle)
        return handle

    def add_plotly(
        self,
        figure: go.Figure,
        *,
        config: Mapping[str, Any] | None = None,
        pane_id: str | None = None,
        title: str = "Plotly",
        visible: bool = True,
    ) -> PlotlyPaneHandle:
        """Add a Plotly pane to the grid's next cell. Accepts the same
        arguments as :meth:`Panes.add_plotly`, minus placement, which
        the grid owns."""

        with self._declaration_lock:
            group = self._next_group()
            handle = group.add_plotly(
                figure,
                config=config,
                pane_id=pane_id,
                title=title,
                visible=visible,
            )
            self._track(group, handle)
        return handle

    def add_viser(
        self,
        target: str | Any,
        *,
        pane_id: str | None = None,
        title: str = "viser",
        visible: bool = True,
        minimize_gui: bool = True,
    ) -> ViserPaneHandle:
        """Add a viser pane to the grid's next cell. Accepts the same
        arguments as :meth:`Panes.add_viser`, minus placement, which
        the grid owns."""

        with self._declaration_lock:
            group = self._next_group()
            handle = group.add_viser(
                target,
                pane_id=pane_id,
                title=title,
                visible=visible,
                minimize_gui=minimize_gui,
            )
            self._track(group, handle)
        return handle


class Panes:
    """Declare image, matplotlib, Plotly, and viser panes in the browser-managed
    workspace."""

    _root_pane_id: Literal["__leika_root__"] = "__leika_root__"
    """Hidden layout sentinel used when no data pane can anchor a split."""

    def __init__(
        self,
        owner: Server,
        *,
        page_id: str = "default",
        aggregate: _PanesAggregate | None = None,
        queue_snapshot: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._owner = owner
        self._page_id = validate_layout_id(page_id, "Page ID")
        self._aggregate = aggregate if aggregate is not None else _PanesAggregate(owner)
        self._websock_interface = owner._websock_server
        self._handle_from_pane_id: dict[str, PaneHandle[Any]] = {}
        self._resource_from_pane_id: dict[str, _PaneResourceCost] = {}
        self._resource_total = _PaneResourceCost()
        self._terminal = False
        if queue_snapshot:
            self._queue_snapshot()

    def _set_resource_locked(self, pane_id: str, cost: _PaneResourceCost) -> _PaneResourceCost:
        old = self._resource_from_pane_id.get(pane_id, _PaneResourceCost())
        prospective = _PaneResourceCost(
            self._resource_total.text_units - old.text_units + cost.text_units,
            self._resource_total.payload_bytes - old.payload_bytes + cost.payload_bytes,
            self._resource_total.decoded_pixels - old.decoded_pixels + cost.decoded_pixels,
        )
        self._aggregate.replace_resource(old, cost)
        self._resource_total = prospective
        if cost == _PaneResourceCost():
            self._resource_from_pane_id.pop(pane_id, None)
        else:
            self._resource_from_pane_id[pane_id] = cost
        return old

    @contextlib.contextmanager
    def _resource_transaction_locked(self, handle: PaneHandle[Any]) -> Any:
        old = self._set_resource_locked(handle._impl.pane_id, _pane_resource_cost(handle))
        try:
            yield
        except BaseException:
            self._set_resource_locked(handle._impl.pane_id, old)
            raise

    def _release_resource_locked(self, pane_id: str) -> None:
        self._set_resource_locked(pane_id, _PaneResourceCost())

    def _retire_without_queue(self) -> None:
        with self._lock:
            if self._terminal:
                return
            self._terminal = True
            for handle in tuple(self._handle_from_pane_id.values()):
                handle._impl.removed = True
                try:
                    self._aggregate.release_pane(viser=isinstance(handle, ViserPaneHandle))
                finally:
                    _scrub_pane_handle_locked(handle)
            self._handle_from_pane_id.clear()
            # Release every reservation, including a defensive orphan left by
            # an interrupted or corrupted registry transition.
            for pane_id in tuple(self._resource_from_pane_id):
                self._release_resource_locked(pane_id)
            self._resource_total = _PaneResourceCost()

    def _known_pane_ids(self) -> tuple[str, ...]:
        """Return live pane IDs in declaration order."""

        with self._lock:
            return tuple(self._handle_from_pane_id)

    def _visible_pane_ids(self) -> set[str]:
        with self._lock:
            return {self._root_pane_id} | {
                handle.pane_id for handle in self._handle_from_pane_id.values() if handle.visible
            }

    def _snapshot_message(
        self, pane_ids: tuple[str, ...] | None = None
    ) -> _messages.ViewportPaneSnapshotMessage:
        """Build the authoritative pane-registry reconciliation message."""
        return _messages.ViewportPaneSnapshotMessage(
            page_id=self._page_id, pane_ids=self._known_pane_ids() if pane_ids is None else pane_ids
        )

    def _queue_snapshot(self) -> None:
        self._websock_interface.queue_message_or_raise(self._snapshot_message())

    def _validate_pane_declaration(
        self,
        pane_id: str | None,
        placement: Placement,
    ) -> str:
        """Validate shared pane arguments and return the resolved pane ID."""

        if pane_id is None:
            pane_id = str(uuid.uuid4())
        else:
            pane_id = validate_layout_id(pane_id, "Pane ID")
        if pane_id == self._root_pane_id:
            raise ValueError(f"Pane ID {pane_id!r} is reserved.")
        if type(placement) is not str or placement not in (
            "left",
            "right",
            "top",
            "bottom",
        ):
            raise ValueError("placement must be left, right, top, or bottom.")
        return pane_id

    def _resolve_relative_to(self, relative_to: str | None) -> str:
        """Resolve ``None`` placement to the latest live, visible pane."""

        with self._lock:
            visible = self._visible_pane_ids()
            if relative_to is not None:
                relative_to = validate_layout_id(relative_to, "relative_to")
                if relative_to not in visible:
                    raise ValueError(f"Unknown or hidden relative pane ID: {relative_to!r}.")
                return relative_to
            for pane_id, handle in reversed(tuple(self._handle_from_pane_id.items())):
                if handle.visible:
                    return pane_id
            return self._root_pane_id

    def _register_pane(
        self,
        pane_id: str,
        handle: PaneHandle[Any],
        create_message: _messages.Message,
        relative_to: str,
        before_publish: Callable[[], None] | None = None,
    ) -> None:
        """Register a new pane handle and queue its creation messages."""

        with self._lock:
            if self._terminal:
                raise RuntimeError("Panes is no longer active.")
            if pane_id in self._handle_from_pane_id:
                raise ValueError(f"Pane ID {pane_id!r} already exists.")
            if relative_to not in self._visible_pane_ids():
                raise ValueError(f"Unknown or hidden relative pane ID: {relative_to!r}.")
            is_viser = isinstance(handle, ViserPaneHandle)
            self._aggregate.reserve_pane(viser=is_viser)
            try:
                old_resource = self._set_resource_locked(pane_id, _pane_resource_cost(handle))
                self._handle_from_pane_id[pane_id] = handle
                try:
                    if before_publish is not None:
                        before_publish()
                    self._websock_interface.queue_messages_or_raise(
                        (create_message, self._snapshot_message())
                    )
                except BaseException:
                    self._handle_from_pane_id.pop(pane_id, None)
                    self._set_resource_locked(pane_id, old_resource)
                    raise
            except BaseException:
                self._aggregate.release_pane(viser=is_viser)
                raise

    def add_image(
        self,
        image: np.ndarray,
        *,
        pane_id: str | None = None,
        title: str = "Image",
        format: Literal["auto", "png", "jpeg"] = "auto",
        jpeg_quality: int | None = None,
        fit: ImageFit | None = None,
        visible: bool = True,
        placement: Placement = "right",
        relative_to: str | None = None,
    ) -> ImagePaneHandle:
        """Add a native image pane to the workspace.

        The browser owns pane arrangement and persists it locally. Placement
        and relative_to are only used when the browser first encounters a pane
        that is not already present in its saved layout.

        Args:
            image: RGB or RGBA image with shape (height, width, 3|4).
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            format: Transport encoding. "auto" chooses PNG for RGBA and JPEG
                for RGB.
            jpeg_quality: JPEG encoder quality from 0 to 100.
            fit: Image sizing policy within the pane. By default the viewer's
                own "Image fit" setting decides; pass a value to override it.
            visible: Initial visibility.
            placement: Initial split edge relative to relative_to.
            relative_to: Visible pane used for initial placement.

        Returns:
            Handle for updating or removing the image pane.
        """

        return self._add_image(
            image,
            pane_id=pane_id,
            title=title,
            format=format,
            jpeg_quality=jpeg_quality,
            fit=fit,
            visible=visible,
            placement=placement,
            relative_to=relative_to,
            equalize_group=(),
        )

    def _add_image(
        self,
        image: np.ndarray,
        *,
        pane_id: str | None,
        title: str,
        format: Literal["auto", "png", "jpeg"],
        jpeg_quality: int | None,
        fit: ImageFit | None,
        visible: bool,
        placement: Placement,
        relative_to: str | None,
        equalize_group: tuple[str, ...],
    ) -> ImagePaneHandle:
        _validate_image_encoding_options(format, jpeg_quality)
        image = _validate_image(image)
        spec = _ndarray_snapshot_spec(image)
        if spec[2] > _PANE_PAYLOAD_MAX_BYTES:
            raise RuntimeError("Image source exceeds the 256 MiB pane retained payload budget.")
        title, visible = _validate_title_visible(title, visible)
        pane_id = self._validate_pane_declaration(pane_id, placement)
        fit = _validate_fit(fit)
        relative_to = self._resolve_relative_to(relative_to)
        with self._owner._reserve_image_preparation(spec[2]):
            snapshot = _private_ndarray_snapshot(image, spec)
            if format == "jpeg" and snapshot.shape[2] == 4:
                warnings.warn(
                    "Encoding an RGBA pane image as JPEG discards its alpha channel.",
                    stacklevel=3,
                )
            resolved_format, data = encode_image_binary(snapshot, format, jpeg_quality=jpeg_quality)
            props = _messages.ViewportImageProps(
                _data=data,
                _format=resolved_format,
                title=title,
                visible=visible,
                fit=fit,
            )
            handle = ImagePaneHandle(
                _ImagePaneHandleState(
                    pane_id=pane_id,
                    props=copy.deepcopy(props),
                    api=self,
                    image=snapshot,
                    requested_format=format,
                    jpeg_quality=jpeg_quality,
                )
            )
            self._register_pane(
                pane_id,
                handle,
                _messages.ViewportImageMessage(
                    page_id=self._page_id,
                    pane_id=pane_id,
                    props=props,
                    placement=placement,
                    relative_to=relative_to,
                    equalize_group=equalize_group,
                ),
                relative_to,
            )
            return handle

    def add_matplotlib(
        self,
        figure: Any,
        *,
        pane_id: str | None = None,
        title: str = "Figure",
        visible: bool = True,
        placement: Placement = "right",
        relative_to: str | None = None,
    ) -> MatplotlibPaneHandle:
        """Add a native matplotlib pane to the workspace.

        The figure is relayed as SVG, so a resized pane rescales it crisply
        without redrawing in Python. It is a picture of a figure: there is no
        hover, zoom, or pan, and the axes do not reflow to the pane's shape.
        Use :meth:`add_plotly` for a chart the viewer can interact with.

        The bundled browser accepts at most 16,777,216 UTF-16 code units of
        generated SVG per pane; larger figures raise before publication.

        SVG suits the line and scatter plots figures usually hold. A figure
        with very many marks -- a scatter of 100k points, a fine-grained
        heatmap -- serializes one element per mark and is better sent as an
        interactive Plotly figure, or rasterized and sent with
        :meth:`add_image`.

        The browser owns pane arrangement and persists it locally. Placement
        and relative_to are only used when the browser first encounters a
        pane that is not already present in its saved layout.

        Args:
            figure: matplotlib figure to display, e.g. from
                ``plt.subplots()``. Duck-typed on ``savefig``, so matplotlib
                is not a Leika dependency. Leika retains the bounded SVG, not
                this arbitrary source graph; keep your own reference if you
                want to read it back, mutate it, and assign it to the handle
                again to update the pane.
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            visible: Initial visibility.
            placement: Initial split edge relative to relative_to.
            relative_to: Visible pane used for initial placement.

        Returns:
            Handle for updating or removing the matplotlib pane.
        """

        return self._add_matplotlib(
            figure,
            pane_id=pane_id,
            title=title,
            visible=visible,
            placement=placement,
            relative_to=relative_to,
            equalize_group=(),
        )

    def _add_matplotlib(
        self,
        figure: Any,
        *,
        pane_id: str | None,
        title: str,
        visible: bool,
        placement: Placement,
        relative_to: str | None,
        equalize_group: tuple[str, ...],
    ) -> MatplotlibPaneHandle:
        title, visible = _validate_title_visible(title, visible)
        pane_id = self._validate_pane_declaration(pane_id, placement)

        figure_ref = _matplotlib_figure_ref(figure)
        with self._owner._reserve_renderer_preparation():
            svg = _matplotlib_svg(figure)
        props = _messages.ViewportMatplotlibProps(
            _svg=svg,
            title=title,
            visible=visible,
        )
        handle = MatplotlibPaneHandle(
            _MatplotlibPaneHandleState(
                pane_id=pane_id,
                props=copy.deepcopy(props),
                api=self,
                figure_ref=figure_ref,
            )
        )
        relative_to = self._resolve_relative_to(relative_to)
        self._register_pane(
            pane_id,
            handle,
            _messages.ViewportMatplotlibMessage(
                page_id=self._page_id,
                pane_id=pane_id,
                props=props,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            ),
            relative_to,
        )
        return handle

    def add_plotly(
        self,
        figure: go.Figure,
        *,
        config: Mapping[str, Any] | None = None,
        pane_id: str | None = None,
        title: str = "Plotly",
        visible: bool = True,
        placement: Placement = "right",
        relative_to: str | None = None,
    ) -> PlotlyPaneHandle:
        """Add a native interactive Plotly pane to the workspace.
        Requires the `plotly` package to be installed.

        The plot is dynamically sized: it always fills its pane, including
        when panes are resized in the browser. The browser owns pane
        arrangement and persists it locally. Placement and relative_to are
        only used when the browser first encounters a pane that is not
        already present in its saved layout.

        Figures that carry plotly's stock default template are rendered with
        a template matched to each viewer's theme: "plotly_white" when Leika
        is in light mode and "plotly_dark" in dark mode, tracking the
        browser's current setting live (including automatically chosen
        themes). Set any other template explicitly on the figure (or change
        ``plotly.io.templates.default``) to override this; assigning the
        stock "plotly" template itself is indistinguishable from the default
        and stays theme-aware.

        Args:
            figure: Plotly figure to snapshot and display. The pane does
                not retain this mutable object; its ``figure`` getter rebuilds
                an independent copy from bounded JSON. Assign that copy back
                to publish edits. The final JSON must fit the bundled browser's
                16,777,216 UTF-16-code-unit render limit.
            config: Plotly config dict merged into the figure JSON. Controls
                display options like ``{"displayModeBar": False}``. Values
                must be JSON-serializable. See
                https://plotly.com/javascript/configuration-options/
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            visible: Initial visibility.
            placement: Initial split edge relative to relative_to.
            relative_to: Visible pane used for initial placement.

        Returns:
            Handle for updating or removing the Plotly pane.
        """

        return self._add_plotly(
            figure,
            config=config,
            pane_id=pane_id,
            title=title,
            visible=visible,
            placement=placement,
            relative_to=relative_to,
            equalize_group=(),
        )

    def _add_plotly(
        self,
        figure: go.Figure,
        *,
        config: Mapping[str, Any] | None,
        pane_id: str | None,
        title: str,
        visible: bool,
        placement: Placement,
        relative_to: str | None,
        equalize_group: tuple[str, ...],
    ) -> PlotlyPaneHandle:
        title, visible = _validate_title_visible(title, visible)
        pane_id = self._validate_pane_declaration(pane_id, placement)

        with self._owner._reserve_renderer_preparation():
            plotly_json, _ = _plotly_json_for_pane(figure, config)
            theme_templates = _plotly_theme_templates_json()
        props = _messages.ViewportPlotlyProps(
            _plotly_json_str=plotly_json,
            _theme_templates=theme_templates,
            title=title,
            visible=visible,
        )
        handle = PlotlyPaneHandle(
            _PlotlyPaneHandleState(
                pane_id=pane_id,
                props=copy.deepcopy(props),
                api=self,
            )
        )
        relative_to = self._resolve_relative_to(relative_to)
        self._register_pane(
            pane_id,
            handle,
            _messages.ViewportPlotlyMessage(
                page_id=self._page_id,
                pane_id=pane_id,
                props=props,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            ),
            relative_to,
            before_publish=self._owner.gui._ensure_plotly_js_sent,
        )
        return handle

    def add_viser(
        self,
        target: str | Any,
        *,
        pane_id: str | None = None,
        title: str = "viser",
        visible: bool = True,
        minimize_gui: bool = True,
        placement: Placement = "right",
        relative_to: str | None = None,
    ) -> ViserPaneHandle:
        """Add a pane embedding a live viser 3D scene.

        The pane shows viser's own interactive client — orbit controls and
        gizmos — for a viser server you create and own. Leika does not
        require ``viser`` to be installed; the target is duck-typed. By
        default viser's own control panel is docked to the pane's right
        edge and minimized to a vertical rail (``minimize_gui``), leaving
        Leika's GUI in charge; viewers can still expand it from the rail.
        This uses viser's ``gui.main_panel`` API — on older viser without
        it (through 1.0.30), the panel just stays visible.

        The intended pattern is to build controls with Leika's
        ``server.gui.add_*`` and mutate ``viser_server.scene`` in their
        callbacks, so the Leika dock drives the 3D scene::

            viser_server = viser.ViserServer()
            server.panes.add_viser(viser_server)
            slider = server.gui.add_slider("Size", min=1, max=10, step=1, initial_value=3)

            @slider.on_update
            def _(_) -> None:
                viser_server.scene.add_icosphere("/ball", radius=slider.value)

        For server-object targets, only the port is used: the viewer's
        browser connects to that port on the same hostname it loaded the
        Leika page from. Anyone viewing Leika remotely therefore needs the
        viser port reachable too — over SSH, forward both ports. When that
        doesn't hold (tunnels, reverse proxies), pass an explicit URL
        instead. Note that a URL pane served over plain ``http://`` cannot
        be embedded into an ``https://``-served Leika page (mixed content).

        The embedded client follows Leika's light/dark theme. The browser
        owns pane arrangement and persists it locally; placement and
        relative_to are only used when the browser first encounters a pane
        that is not already present in its saved layout.

        Args:
            target: What to embed: a ``viser.ViserServer`` (any object with
                ``get_port()`` and ``get_host()`` methods), or an absolute
                http(s) URL of a viser client.
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            visible: Initial visibility.
            minimize_gui: Dock viser's own control panel to the right edge
                and minimize it to a rail. Applies to server-object targets
                on viser versions with ``gui.main_panel``; ignored for URL
                targets, which Python cannot reach into.
            placement: Initial split edge relative to relative_to.
            relative_to: Visible pane used for initial placement.

        Returns:
            Handle for re-pointing or removing the viser pane.
        """

        return self._add_viser(
            target,
            pane_id=pane_id,
            title=title,
            visible=visible,
            minimize_gui=minimize_gui,
            placement=placement,
            relative_to=relative_to,
            equalize_group=(),
        )

    def _add_viser(
        self,
        target: str | Any,
        *,
        pane_id: str | None,
        title: str,
        visible: bool,
        minimize_gui: bool,
        placement: Placement,
        relative_to: str | None,
        equalize_group: tuple[str, ...],
    ) -> ViserPaneHandle:
        title, visible = _validate_title_visible(title, visible)
        if type(minimize_gui) is not bool:
            raise TypeError("minimize_gui must be a bool")
        pane_id = self._validate_pane_declaration(pane_id, placement)

        url, port = _viser_embed_target(target)
        props = _messages.ViewportViserProps(
            _url=url,
            _port=port,
            title=title,
            visible=visible,
        )
        handle = ViserPaneHandle(
            _ViserPaneHandleState(
                pane_id=pane_id,
                props=copy.deepcopy(props),
                api=self,
                minimize_gui=minimize_gui,
            )
        )
        relative_to = self._resolve_relative_to(relative_to)
        self._register_pane(
            pane_id,
            handle,
            _messages.ViewportViserMessage(
                page_id=self._page_id,
                pane_id=pane_id,
                props=props,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            ),
            relative_to,
        )
        # Only after registration succeeds: a failed add (duplicate pane_id,
        # bad relative_to) must leave the user's viser server untouched. The
        # placement commands replay to late-joining clients, so applying
        # them after the pane's create message changes nothing.
        if port is not None and minimize_gui:
            _minimize_viser_gui(target)
        return handle

    def add_row(
        self,
        *,
        relative_to: str | None = None,
    ) -> PaneGroup:
        """Create a group that lays out added panes side by side with equal
        widths.

        Panes added through the returned group's ``add_*`` methods are placed
        along a shared row and re-divided equally on each addition, so three
        panes yield exact thirds. (Divisions
        snap to the workspace grid; in workspaces small enough that minimum
        pane sizes dominate, they are as equal as the grid allows.) ``relative_to``
        positions the group's first pane; like all placement hints, it only
        applies when the browser has no saved arrangement for these panes.

        Args:
            relative_to: Visible pane used for the group's initial placement.

        Returns:
            Group for adding equally sized panes.
        """

        return PaneGroup(self, "row", "right", relative_to)

    def add_column(
        self,
        *,
        relative_to: str | None = None,
    ) -> PaneGroup:
        """Create a group that lays out added panes stacked with equal
        heights.

        The column counterpart of :meth:`add_row`; see it for placement
        semantics.

        Args:
            relative_to: Visible pane used for the group's initial placement.

        Returns:
            Group for adding equally sized panes.
        """

        return PaneGroup(self, "column", "bottom", relative_to)

    def add_grid(
        self,
        *,
        columns: int = 2,
        relative_to: str | None = None,
    ) -> PaneGrid:
        """Create a group that lays out added panes in an equally divided
        grid.

        Panes added through the returned grid's ``add_*`` methods fill left to
        right, top to bottom, wrapping to a new row after every ``columns``
        panes. Rows and columns are
        re-divided equally on each addition, so a filled grid has equal
        cells. The grid counterpart of :meth:`add_row`; see it for placement
        semantics.

        Args:
            columns: Number of panes per row.
            relative_to: Visible pane used for the grid's initial placement.

        Returns:
            Grid for adding equally sized panes.
        """

        _validate_positive_integer(columns, "columns")
        return PaneGrid(self, columns, "right", relative_to)


def _validate_fit(value: object) -> ImageFit | None:
    if value is not None and (type(value) is not str or value not in ("fit", "fill", "stretch")):
        raise ValueError("fit must be 'fit', 'fill', 'stretch', or None.")
    return cast("ImageFit | None", value)


def _validate_image(image: np.ndarray) -> np.ndarray:
    if type(image) is not np.ndarray:
        raise TypeError("Pane images must use a base numpy.ndarray.")
    if (
        image.ndim != 3
        or image.shape[0] <= 0
        or image.shape[1] <= 0
        or image.shape[2] not in (3, 4)
    ):
        raise ValueError(
            "Pane images must have positive height and width and shape "
            "(height, width, 3) for RGB or (height, width, 4) for RGBA."
        )
    validate_image_pixel_size(image.shape[1], image.shape[0])
    if not (np.issubdtype(image.dtype, np.integer) or np.issubdtype(image.dtype, np.floating)):
        raise TypeError("Pane images must use an integer or floating dtype.")
    return image
