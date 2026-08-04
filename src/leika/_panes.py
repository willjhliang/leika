"""Native image, matplotlib, Plotly, and viser panes for a Leika workspace."""

from __future__ import annotations

import copy
import dataclasses
import io
import json
import threading
import urllib.parse
import uuid
import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Generic, Literal, NewType, TypeVar, cast

import numpy as np
from typing_extensions import TypeAlias

from . import _messages
from ._gui_handles import _plotly_json_with_config
from ._image_encoding import encode_image_binary
from ._validation import validate_positive_integer as _validate_positive_integer

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


def _plotly_json_for_pane(figure: go.Figure, config: Mapping[str, Any] | None) -> str:
    """Serialize a figure for a Plotly pane.

    Figures bake the global default template in at construction time, so a
    figure whose template matches plotly's stock "plotly" template is treated
    as "no template chosen": the template is stripped so the client can apply
    a default matched to its current light/dark theme. Any explicitly
    assigned template, or a customized ``plotly.io.templates.default``, is
    preserved.
    """
    import plotly.io as pio

    global _stock_plotly_template_json
    if _stock_plotly_template_json is None:
        _stock_plotly_template_json = pio.templates["plotly"].to_plotly_json()

    json_str = _plotly_json_with_config(figure, config)
    template = figure.layout.template
    if template is None or template.to_plotly_json() == _stock_plotly_template_json:
        plot_dict = json.loads(json_str)
        plot_dict.get("layout", {}).pop("template", None)
        json_str = json.dumps(plot_dict)
    return json_str


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
    buffer = io.BytesIO()
    savefig(buffer, format="svg")
    return buffer.getvalue().decode("utf-8")


def _plotly_theme_templates_json() -> str:
    """Themed default templates for figures that don't specify one. The
    client picks by its current color scheme: "plotly_white" when Leika is in
    light mode, "plotly_dark" in dark mode."""
    import plotly.io as pio

    global _theme_templates_json
    if _theme_templates_json is None:
        _theme_templates_json = json.dumps(
            {
                "light": pio.templates["plotly_white"].to_plotly_json(),
                "dark": pio.templates["plotly_dark"].to_plotly_json(),
            }
        )
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
        parts = urllib.parse.urlsplit(target)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"Viser target URLs must be absolute http(s) URLs; got {target!r}.")
        return target, None

    get_port = getattr(target, "get_port", None)
    get_host = getattr(target, "get_host", None)
    if callable(get_port) and callable(get_host):
        port = int(cast("Any", get_port()))
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
        dock_right()
        minimize()


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
    figure: Any
    removed: bool = False


@dataclasses.dataclass
class _PlotlyPaneHandleState:
    pane_id: str
    props: _messages.ViewportPlotlyProps
    api: Panes
    figure: go.Figure
    config: Mapping[str, Any] | None
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


class PaneHandle(Generic[_PaneStateT]):
    """Lifecycle and property logic shared by all pane handles."""

    _impl: _PaneStateT

    def _check_not_removed(self) -> None:
        if self._impl.removed:
            raise RuntimeError(f"Cannot update a removed {type(self).__name__}.")

    def _queue_update(self, updates: dict[str, Any]) -> None:
        self._impl.api._websock_interface.queue_message(
            _messages.ViewportPaneUpdateMessage(
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

        return self._impl.props.title

    @title.setter
    def title(self, value: str) -> None:
        self._check_not_removed()
        value = str(value)
        with self._impl.api._lock:
            self._check_not_removed()
            if value == self._impl.props.title:
                return
            self._impl.props.title = value
            self._queue_update({"title": value})

    @property
    def visible(self) -> bool:
        """Whether this pane is visible."""

        return self._impl.props.visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._check_not_removed()
        value = bool(value)
        with self._impl.api._lock:
            self._check_not_removed()
            if value == self._impl.props.visible:
                return
            self._impl.props.visible = value
            self._queue_update({"visible": value})

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
            self._impl.removed = True
            api._handle_from_pane_id.pop(self._impl.pane_id, None)
            api._websock_interface.queue_message(
                _messages.ViewportPaneRemoveMessage(pane_id=self._impl.pane_id)
            )
            api._queue_snapshot()


class ImagePaneHandle(PaneHandle[_ImagePaneHandleState]):
    """Handle for updating or removing a native image pane."""

    def __init__(self, state: _ImagePaneHandleState) -> None:
        self._impl = state

    @property
    def image(self) -> np.ndarray:
        """Current image. Assign a new array to stream another frame."""

        return self._impl.image.copy()

    @image.setter
    def image(self, image: np.ndarray) -> None:
        self._check_not_removed()
        image = _validate_image(image)
        resolved_format, data = encode_image_binary(
            image,
            self._impl.requested_format,
            jpeg_quality=self._impl.jpeg_quality,
        )
        if self._impl.requested_format == "jpeg" and image.shape[2] == 4:
            warnings.warn(
                "Encoding an RGBA pane image as JPEG discards its alpha channel.",
                stacklevel=2,
            )
        with self._impl.api._lock:
            # Encoding can be expensive. Recheck after taking the lock so a
            # concurrent remove cannot queue an update for a reused pane ID.
            self._check_not_removed()
            self._impl.image = image.copy()
            self._impl.props._format = resolved_format
            self._impl.props._data = data
            self._queue_update({"_format": resolved_format, "_data": data})

    def update(self, image: np.ndarray) -> None:
        """Replace the pane image using its configured transport encoding."""

        self.image = image

    @property
    def format(self) -> Literal["auto", "jpeg", "png"]:
        """Encoding requested when this pane was created."""

        return self._impl.requested_format

    @property
    def fit(self) -> ImageFit | None:
        """How the image is sized within its pane, or None to follow the
        viewer's own "Image fit" setting."""

        return self._impl.props.fit

    @fit.setter
    def fit(self, value: ImageFit | None) -> None:
        self._check_not_removed()
        value = _validate_fit(value)
        with self._impl.api._lock:
            self._check_not_removed()
            if value == self._impl.props.fit:
                return
            self._impl.props.fit = value
            self._queue_update({"fit": value})


class MatplotlibPaneHandle(PaneHandle[_MatplotlibPaneHandleState]):
    """Handle for updating or removing a native matplotlib pane."""

    def __init__(self, state: _MatplotlibPaneHandleState) -> None:
        self._impl = state

    @property
    def figure(self) -> Any:
        """Current matplotlib figure. Assign a new figure to update the pane."""

        return self._impl.figure

    @figure.setter
    def figure(self, figure: Any) -> None:
        self._check_not_removed()
        svg = _matplotlib_svg(figure)
        with self._impl.api._lock:
            # Serialization can be expensive. Recheck after taking the lock so
            # a concurrent remove cannot queue an update for a reused pane ID.
            self._check_not_removed()
            self._impl.figure = figure
            self._impl.props._svg = svg
            self._queue_update({"_svg": svg})

    def update(self, figure: Any) -> None:
        """Replace the matplotlib figure while retaining the pane configuration.

        Call this after redrawing to push a new frame; matplotlib mutates
        figures in place, so re-passing the same figure is normal.
        """

        self.figure = figure


class PlotlyPaneHandle(PaneHandle[_PlotlyPaneHandleState]):
    """Handle for updating or removing a native Plotly pane."""

    def __init__(self, state: _PlotlyPaneHandleState) -> None:
        self._impl = state

    @property
    def figure(self) -> go.Figure:
        """Current Plotly figure. Assign a new figure to update the pane."""

        return self._impl.figure

    @figure.setter
    def figure(self, figure: go.Figure) -> None:
        self._check_not_removed()
        json_str = _plotly_json_for_pane(figure, self._impl.config)
        with self._impl.api._lock:
            # Serialization can be expensive. Recheck after taking the lock so
            # a concurrent remove cannot queue an update for a reused pane ID.
            self._check_not_removed()
            self._impl.figure = figure
            self._impl.props._plotly_json_str = json_str
            self._queue_update({"_plotly_json_str": json_str})

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

        return self._impl.props._url

    @property
    def port(self) -> int | None:
        """Viser server port for port-based targets, or None when the pane
        was pointed at an explicit URL."""

        return self._impl.props._port

    def update(self, target: str | Any) -> None:
        """Re-point the pane at another viser server or URL. Accepts the
        same targets as :meth:`Panes.add_viser`, and re-applies the pane's
        creation-time ``minimize_gui`` choice to server targets — including
        the current one, so calling with the same server re-minimizes a
        panel the viewer expanded."""

        self._check_not_removed()
        url, port = _viser_embed_target(target)
        if port is not None and self._impl.minimize_gui:
            _minimize_viser_gui(target)
        with self._impl.api._lock:
            self._check_not_removed()
            if url == self._impl.props._url and port == self._impl.props._port:
                return
            self._impl.props._url = url
            self._impl.props._port = port
            # Both keys are always sent so the exactly-one-set invariant
            # holds on the client after any update.
            self._queue_update({"_url": url, "_port": port})


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
        self._api = api
        self._axis: Literal["row", "column"] = axis
        self._placement: Placement = placement
        self._relative_to = relative_to
        self._members: list[PaneHandle[Any]] = []

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

        members = [
            handle.pane_id
            for handle in self._members
            if self._api._handle_from_pane_id.get(handle.pane_id) is handle and handle.visible
        ]
        if not members:
            return self._placement, self._api._resolve_relative_to(self._relative_to), ()
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

        with self._api._lock:
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
            self._members.append(handle)
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

        with self._api._lock:
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
            self._members.append(handle)
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

        with self._api._lock:
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
            self._members.append(handle)
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

        with self._api._lock:
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
            self._members.append(handle)
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
        self._api = api
        self._columns = columns
        self._row = PaneGroup(api, "row", placement, relative_to)
        self._column_groups: list[PaneGroup] = []
        self._count = 0

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
            column._members.append(handle)
            self._column_groups.append(column)
        self._count += 1

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

        with self._api._lock:
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

        with self._api._lock:
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

        with self._api._lock:
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

        with self._api._lock:
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

    def __init__(self, owner: Server) -> None:
        self._lock = threading.RLock()
        self._owner = owner
        self._websock_interface = owner._websock_server
        self._handle_from_pane_id: dict[str, PaneHandle[Any]] = {}
        self._queue_snapshot()

    def _known_pane_ids(self) -> tuple[str, ...]:
        """Return live pane IDs in declaration order."""

        with self._lock:
            return tuple(self._handle_from_pane_id)

    def _visible_pane_ids(self) -> set[str]:
        return {self._root_pane_id} | {
            handle.pane_id for handle in self._handle_from_pane_id.values() if handle.visible
        }

    def _queue_snapshot(self) -> None:
        """Queue the authoritative pane registry after lifecycle messages."""

        self._websock_interface.queue_message(
            _messages.ViewportPaneSnapshotMessage(pane_ids=self._known_pane_ids())
        )

    def _validate_pane_declaration(
        self,
        pane_id: str | None,
        placement: Placement,
    ) -> str:
        """Validate shared pane arguments and return the resolved pane ID."""

        if pane_id is None:
            pane_id = str(uuid.uuid4())
        elif not isinstance(pane_id, str):
            raise TypeError("Pane ID must be a string.")
        elif not pane_id:
            raise ValueError("Pane ID must not be empty.")
        if pane_id == self._root_pane_id:
            raise ValueError(f"Pane ID {pane_id!r} is reserved.")
        if placement not in ("left", "right", "top", "bottom"):
            raise ValueError("placement must be left, right, top, or bottom.")
        return pane_id

    def _resolve_relative_to(self, relative_to: str | None) -> str:
        """Resolve ``None`` placement to the latest live, visible pane."""

        visible = self._visible_pane_ids()
        if relative_to is not None:
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
    ) -> None:
        """Register a new pane handle and queue its creation messages."""

        with self._lock:
            if pane_id in self._handle_from_pane_id:
                raise ValueError(f"Pane ID {pane_id!r} already exists.")
            if relative_to not in self._visible_pane_ids():
                raise ValueError(f"Unknown or hidden relative pane ID: {relative_to!r}.")
            self._handle_from_pane_id[pane_id] = handle
            self._websock_interface.queue_message(create_message)
            self._queue_snapshot()

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
        image = _validate_image(image)
        title = str(title)
        visible = bool(visible)
        pane_id = self._validate_pane_declaration(pane_id, placement)
        fit = _validate_fit(fit)
        if format == "jpeg" and image.shape[2] == 4:
            warnings.warn(
                "Encoding an RGBA pane image as JPEG discards its alpha channel.",
                # Both public entry points (add_image, group add_image) are
                # one frame above; point the warning at the user's call.
                stacklevel=3,
            )

        resolved_format, data = encode_image_binary(image, format, jpeg_quality=jpeg_quality)
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
                image=image.copy(),
                requested_format=format,
                jpeg_quality=jpeg_quality,
            )
        )
        relative_to = self._resolve_relative_to(relative_to)
        self._register_pane(
            pane_id,
            handle,
            _messages.ViewportImageMessage(
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
                is not a Leika dependency. Assign to the returned handle's
                ``figure`` property to update it.
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
        title = str(title)
        visible = bool(visible)
        pane_id = self._validate_pane_declaration(pane_id, placement)

        props = _messages.ViewportMatplotlibProps(
            _svg=_matplotlib_svg(figure),
            title=title,
            visible=visible,
        )
        handle = MatplotlibPaneHandle(
            _MatplotlibPaneHandleState(
                pane_id=pane_id,
                props=copy.deepcopy(props),
                api=self,
                figure=figure,
            )
        )
        relative_to = self._resolve_relative_to(relative_to)
        self._register_pane(
            pane_id,
            handle,
            _messages.ViewportMatplotlibMessage(
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
            figure: Plotly figure to display. Assign to the returned handle's
                ``figure`` property to update it.
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
        title = str(title)
        visible = bool(visible)
        pane_id = self._validate_pane_declaration(pane_id, placement)

        # Clients cannot render the figure until plotly.min.js has been sent.
        # This must be queued before the pane creation message.
        self._owner.gui._ensure_plotly_js_sent()

        props = _messages.ViewportPlotlyProps(
            _plotly_json_str=_plotly_json_for_pane(figure, config),
            _theme_templates=_plotly_theme_templates_json(),
            title=title,
            visible=visible,
        )
        handle = PlotlyPaneHandle(
            _PlotlyPaneHandleState(
                pane_id=pane_id,
                props=copy.deepcopy(props),
                api=self,
                figure=figure,
                config=config,
            )
        )
        relative_to = self._resolve_relative_to(relative_to)
        self._register_pane(
            pane_id,
            handle,
            _messages.ViewportPlotlyMessage(
                pane_id=pane_id,
                props=props,
                placement=placement,
                relative_to=relative_to,
                equalize_group=equalize_group,
            ),
            relative_to,
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
        title = str(title)
        visible = bool(visible)
        minimize_gui = bool(minimize_gui)
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

        Panes added through the returned group's ``add_image`` and
        ``add_plotly`` methods are placed along a shared row and re-divided
        equally on each addition, so three panes yield exact thirds. (Divisions
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

        Panes added through the returned grid's ``add_image`` and
        ``add_plotly`` methods fill left to right, top to bottom, wrapping to
        a new row after every ``columns`` panes. Rows and columns are
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
    if value is not None and value not in ("fit", "fill", "stretch"):
        raise ValueError("fit must be 'fit', 'fill', 'stretch', or None.")
    return cast("ImageFit | None", value)


def _validate_image(image: np.ndarray) -> np.ndarray:
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError(
            "Pane images must have shape (height, width, 3) for RGB or (height, width, 4) for RGBA."
        )
    if not (np.issubdtype(image.dtype, np.integer) or np.issubdtype(image.dtype, np.floating)):
        raise TypeError("Pane images must use an integer or floating dtype.")
    return image
