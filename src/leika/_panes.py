"""Native image, video, matplotlib, Plotly, and viser panes for a Leika workspace."""

from __future__ import annotations

import dataclasses
import io
import threading
import urllib.parse
import uuid
import warnings
import weakref
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NamedTuple, NewType, cast

import numpy as np
from typing_extensions import TypeAlias

from . import _messages
from ._image_encoding import _validate_image_encoding_options, prepare_image
from ._plotly import plotly_config, plotly_figure, plotly_json, plotly_theme_templates
from ._validation import (
    validate_layout_id,
    validate_positive_integer,
    validate_positive_number,
    validate_renderer_string,
)

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from ._server import Server


# Named the way this control usually is, rather than after the CSS keywords the
# browser ends up applying: "fill" here means filling the pane (CSS `cover`),
# and stretching is spelled out.
ImageFit: TypeAlias = Literal["fit", "fill", "stretch"]
Placement: TypeAlias = Literal["left", "right", "top", "bottom"]
PaneLoading: TypeAlias = bool | str
PaneId = NewType("PaneId", str)

_ROOT_PANE_ID = "__leika_root__"
"""Hidden layout sentinel used when no data pane can anchor a split."""


def _validate_loading(value: object) -> PaneLoading:
    if type(value) is bool:
        return cast(bool, value)
    if type(value) is str:
        return cast(str, validate_renderer_string(value, "pane loading message"))
    raise TypeError("loading must be a bool or string")


def _validate_fit(value: object) -> ImageFit | None:
    if value is not None and (type(value) is not str or value not in ("fit", "fill", "stretch")):
        raise ValueError("fit must be 'fit', 'fill', 'stretch', or None.")
    return cast("ImageFit | None", value)


def _validate_video_group(value: str | None) -> str | None:
    return None if value is None else validate_layout_id(value, "sync_group")


def _validate_video_fps(value: float | None) -> float | None:
    return None if value is None else float(validate_positive_number(value, "fps"))


def _video_url(panes: Panes, source: Path | str) -> str:
    if isinstance(source, Path):
        return panes._owner.register_http_asset(source)
    if not isinstance(source, str):
        raise TypeError("video source must be a Path or HTTP URL")
    parsed = urllib.parse.urlsplit(source)
    if (
        not (
            (parsed.scheme in ("http", "https") and parsed.netloc)
            or (source.startswith("/") and not source.startswith("//"))
        )
        or "\\" in source
        or any(ord(c) < 32 for c in source)
    ):
        raise ValueError("video URLs must be absolute HTTP(S) or root-relative URLs")
    return source


def _viser_embed_target(target: str | Any) -> tuple[str | None, int | None]:
    """Normalize a viser target into ``(url, port)``, exactly one set.

    Accepts an absolute http(s) URL, used near-verbatim, or a viser
    ``ViserServer``-like object, duck-typed on callable ``get_port()`` and
    ``get_host()``. Only the port is returned for server objects; Leika
    proxies them through its own origin.
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
                stacklevel=4,
            )


class _ViserRoute(NamedTuple):
    """Leika's same-origin proxy route to one local Viser server."""

    path: str
    address: tuple[str, int]


def _release(panes: Panes, source: object) -> None:
    """Unregister a Viser proxy route; other renderer sources need no release."""
    if isinstance(source, _ViserRoute):
        panes._websock_interface._viser_proxy.unregister(source.path)


class PaneHandle:
    """A stable workspace pane whose content can be replaced or cleared.

    ``set_*`` methods select a renderer and its settings. ``clear()`` releases
    its content while retaining layout, title, visibility and refresh bindings.
    Handles returned by ``add_video``, ``add_image``, etc. also provide their
    typed ``update`` and properties. After clearing, ``update`` restores that
    renderer with its previous settings. After selecting a different kind,
    use ``set_*`` to switch back explicitly.
    """

    # Each handle class also describes one renderer: this class the empty
    # pane, and each typed subclass its kind of content.
    _kind: ClassVar[str] = "empty"
    _props_type: ClassVar[type[Any]] = _messages.ViewportEmptyProps
    _message_type: ClassVar[type[Any]] = _messages.ViewportEmptyMessage
    _update_fields: ClassVar[tuple[str, ...]] = ()
    """Content props that ``update()`` sends; a new renderer sends them all."""

    def __init__(
        self,
        panes: Panes,
        pane_id: str,
        renderer: type[PaneHandle],
        props: Any,
        settings: dict[str, Any],
        source: Any,
    ) -> None:
        self._panes = panes
        self._pane_id = pane_id
        self._renderer = renderer
        """Handle class describing the content shown now."""
        self._props = props
        """Current props, replaced rather than mutated once published."""
        self._settings = settings
        """Settings of the last non-empty renderer, kept through ``clear()``."""
        self._settings_kind = None if renderer is PaneHandle else renderer._kind
        self._source: Any = source
        """Renderer state: an image copy, a weak figure reference, or a Viser route."""
        self._generation = 0
        """Counts renderer replacements, so in-flight preparation can detect one."""
        self._removed = False
        self._refresh_controls: dict[str, weakref.ReferenceType[Any]] = {}
        self._refresh_requests: dict[int, str] = {}
        self._refresh_revision = 0

    @staticmethod
    def _prepare(
        panes: Panes, value: Any, settings: dict[str, Any], previous: Any
    ) -> tuple[dict[str, Any], Any]:
        """Return this renderer's content props and source for ``value``.

        Runs outside the registry lock. ``previous`` is the pane's current
        source, which a renderer may reuse.
        """
        return {}, None

    @staticmethod
    def _published(value: Any, settings: dict[str, Any]) -> None:
        """React once content prepared from ``value`` is published."""

    def _check_not_removed(self) -> None:
        if self._removed:
            raise RuntimeError(f"Cannot update a removed {type(self).__name__}.")

    def _require_kind(self) -> None:
        """Check that this typed handle's kind of content is shown. Lock held."""
        self._check_not_removed()
        if self._renderer._kind != self._kind:
            raise RuntimeError(
                "This pane has different or empty content; use set_* to select its renderer."
            )

    def _update_message(self, updates: dict[str, Any]) -> _messages.ViewportPaneUpdateMessage:
        if self._refresh_controls:
            # The refresh barrier rides on the content itself, so coalescing
            # cannot drop a receipt or let an older image overtake it.
            updates = {
                **updates,
                "_refresh_revision": self._refresh_revision,
                "_refresh_controls": tuple(self._refresh_controls),
                "_refresh_requests": tuple(self._refresh_requests.values()),
            }
        return _messages.ViewportPaneUpdateMessage(
            page_id=self._panes._page_id, pane_id=self._pane_id, updates=updates
        )

    def _queue_update(self, updates: dict[str, Any]) -> None:
        self._panes._websock_interface.queue_message_or_raise(self._update_message(updates))

    def _set_prop(self, name: str, value: Any, *, setting: bool = False) -> None:
        """Publish one validated prop; a ``setting`` is also kept for ``update()``."""
        with self._panes._lock:
            if setting:
                self._require_kind()
            else:
                self._check_not_removed()
            if value == getattr(self._props, name):
                return
            self._queue_update({name: value})
            self._props = dataclasses.replace(self._props, **{name: value})
            if setting:
                self._settings[name] = value

    def _publish(
        self,
        renderer: type[PaneHandle],
        value: Any,
        settings: dict[str, Any] | None,
        loading: PaneLoading | None,
        frame: Mapping[str, Any] | None = None,
    ) -> None:
        """Prepare content outside the lock, then publish it unless the pane changed.

        ``settings`` None means ``update()``: new content for the renderer
        shown, or the cleared renderer restored with its settings. Otherwise
        the renderer is replaced. ``frame`` overrides settings for this content
        only; ``loading`` None keeps the overlay.
        """
        panes = self._panes
        if loading is not None:
            loading = _validate_loading(loading)
        with panes._lock:
            self._check_not_removed()
            replace = settings is not None
            if settings is None:
                if self._renderer is renderer:
                    settings = self._settings
                elif self._renderer is PaneHandle and self._settings_kind == renderer._kind:
                    replace, settings = True, self._settings
                else:
                    raise RuntimeError(
                        "This pane has a different renderer; use set_* to switch back."
                    )
            generation, previous = self._generation, self._source
        fields, source = renderer._prepare(panes, value, {**settings, **(frame or {})}, previous)
        try:
            with panes._lock:
                self._check_not_removed()
                # A reused Viser route must still be the current one.
                if self._generation != generation or (
                    isinstance(source, _ViserRoute)
                    and source is previous
                    and source is not self._source
                ):
                    raise RuntimeError("Pane content changed during preparation.")
                props = self._props
                if replace:
                    props = renderer._props_type(
                        title=props.title,
                        visible=props.visible,
                        loading=props.loading if loading is None else loading,
                        **fields,
                    )
                    messages = [
                        renderer._message_type(
                            page_id=panes._page_id,
                            pane_id=self._pane_id,
                            placement="right",
                            relative_to=_ROOT_PANE_ID,
                            equalize_group=(),
                            props=props,
                        )
                    ]
                    if self._refresh_controls:
                        messages.append(self._update_message({}))
                    panes._websock_interface.queue_messages_or_raise(messages)
                    self._generation += 1
                    self._renderer = renderer
                    if renderer is not PaneHandle:
                        self._settings, self._settings_kind = settings, renderer._kind
                else:
                    # A setting such as fit may have changed during preparation.
                    fields.update((k, v) for k, v in self._settings.items() if k in fields)
                    updates = {name: fields[name] for name in renderer._update_fields}
                    if loading is not None:
                        updates["loading"] = loading
                    self._queue_update(updates)
                    props = dataclasses.replace(
                        props, **fields, loading=props.loading if loading is None else loading
                    )
                replaced, self._props, self._source = self._source, props, source
        except BaseException:
            if source is not previous:
                _release(panes, source)
            raise
        if replaced is not source:
            _release(panes, replaced)
        renderer._published(value, settings)

    @property
    def pane_id(self) -> PaneId:
        """Stable identifier used to restore browser-managed layouts."""

        return PaneId(self._pane_id)

    @property
    def title(self) -> str:
        """Title rendered in the pane's corner label."""

        self._check_not_removed()
        return self._props.title

    @title.setter
    def title(self, value: str) -> None:
        self._set_prop("title", validate_renderer_string(value, "pane title"))

    @property
    def visible(self) -> bool:
        """Whether this pane is visible."""

        self._check_not_removed()
        return self._props.visible

    @visible.setter
    def visible(self, value: bool) -> None:
        if type(value) is not bool:
            raise TypeError("visible must be a bool")
        self._set_prop("visible", value)

    @property
    def loading(self) -> PaneLoading:
        """Pane loading overlay state.

        False hides the overlay, True shows the default loading indicator,
        and a string shows that text alongside the indicator. Loading covers
        the pane's content without changing its layout or unmounting its
        renderer.
        """

        self._check_not_removed()
        return self._props.loading

    @loading.setter
    def loading(self, value: PaneLoading) -> None:
        self._set_prop("loading", _validate_loading(value))

    @property
    def has_viewers(self) -> bool:
        """Whether this pane is visible and a connected browser shows its page.

        Applications can skip expensive routine work when False; explicit
        selection/loading updates should still publish their new content.
        """
        page_id = self._panes._page_id
        return self.visible and any(
            client._websock_connection.delivery_scope() == page_id
            for client in self._panes._owner.clients.values()
        )

    def invalidate_on(self, *controls: Any) -> None:
        """Hide this pane immediately when a bound GUI input changes.

        Bind shared inputs owned by this server. The input callback must clear
        stale content synchronously and reject obsolete background results.
        Once callbacks finish, the browser receives a versioned snapshot;
        late frames from earlier selections cannot reveal the previous image.
        Repeated calls add bindings and prune removed controls.
        """
        from ._gui_handles import _GuiInputHandle

        owner = self._panes._owner
        for control in controls:
            if not isinstance(control, _GuiInputHandle):
                raise TypeError("invalidate_on requires GUI input handles.")
            if control._impl.gui_api._owner is not owner or control._impl.removed:
                raise ValueError("refresh controls must be live shared inputs on this server.")
        with self._panes._lock:
            self._check_not_removed()
            bindings = {
                uuid: reference
                for uuid, reference in self._refresh_controls.items()
                if (bound := reference()) is not None and not bound._impl.removed
            }
            for control in controls:
                bindings[control._impl.uuid] = weakref.ref(control)
            previous, self._refresh_controls = self._refresh_controls, bindings
            try:
                self._queue_update({"_refresh_controls": tuple(bindings)})
            except BaseException:
                self._refresh_controls = previous
                raise

    def _ack_refresh(self, gui_uuid: str, request_id: str, client_id: int) -> None:
        with self._panes._lock:
            if self._removed or gui_uuid not in self._refresh_controls:
                return
            clients = self._panes._owner.clients
            if client_id not in clients:
                return
            # One receipt per connected client, so reconnects do not accumulate.
            self._refresh_requests = {
                key: value for key, value in self._refresh_requests.items() if key in clients
            }
            self._refresh_requests[client_id] = request_id
            self._refresh_revision += 1
            self._queue_update(dataclasses.asdict(self._props))

    def remove(self) -> None:
        """Permanently remove this pane from the workspace."""

        panes = self._panes
        with panes._lock:
            if self._removed:
                warnings.warn(
                    f"Attempted to remove an already removed {type(self).__name__}.",
                    stacklevel=2,
                )
                return
            remaining = tuple(
                pane_id for pane_id in panes._handle_from_pane_id if pane_id != self._pane_id
            )
            panes._websock_interface.queue_messages_or_raise(
                (
                    _messages.ViewportPaneRemoveMessage(
                        page_id=panes._page_id, pane_id=self._pane_id
                    ),
                    panes._snapshot_message(remaining),
                )
            )
            self._removed = True
            del panes._handle_from_pane_id[self._pane_id]
            _release(panes, self._source)
            self._source = None

    def clear(self, *, loading: PaneLoading | None = None) -> None:
        """Release content and show an empty pane, keeping its ID and layout.

        None preserves the loading overlay; False hides it. Renderer settings
        are retained for a typed handle's next ``update``; source data, media,
        figures and Viser proxy routes are released. Clearing does not stop a
        caller-owned Viser server. Work preparing the previous content cannot
        publish after this call succeeds.
        """
        self._publish(PaneHandle, None, {}, loading)

    def set_image(
        self,
        image: np.ndarray,
        *,
        format: Literal["auto", "png", "jpeg"] = "auto",
        jpeg_quality: int | None = None,
        fit: ImageFit | None = None,
        loading: PaneLoading | None = None,
    ) -> None:
        """Display an image using :meth:`Panes.add_image` settings, keeping layout."""
        settings = ImagePaneHandle._validate(format, jpeg_quality, fit)
        self._publish(ImagePaneHandle, image, settings, loading)

    def set_video(
        self,
        source: Path | str,
        *,
        autoplay: bool = True,
        loop: bool = True,
        muted: bool = True,
        controls: bool = True,
        sync_group: str | None = None,
        fps: float | None = None,
        loading: PaneLoading | None = None,
    ) -> None:
        """Display a video using :meth:`Panes.add_video` settings, keeping layout."""
        settings = VideoPaneHandle._validate(autoplay, loop, muted, controls, sync_group, fps)
        self._publish(VideoPaneHandle, source, settings, loading)

    def set_matplotlib(self, figure: Any, *, loading: PaneLoading | None = None) -> None:
        """Display a Matplotlib figure as SVG, keeping the pane's layout."""
        self._publish(MatplotlibPaneHandle, figure, {}, loading)

    def set_plotly(
        self,
        figure: go.Figure,
        *,
        config: Mapping[str, Any] | None = None,
        loading: PaneLoading | None = None,
    ) -> None:
        """Display an interactive Plotly figure, keeping the pane's layout."""
        self._publish(PlotlyPaneHandle, figure, PlotlyPaneHandle._validate(config), loading)

    def set_viser(
        self,
        target: str | Any,
        *,
        minimize_gui: bool = True,
        loading: PaneLoading | None = None,
    ) -> None:
        """Embed Viser using :meth:`Panes.add_viser` settings, keeping layout."""
        self._publish(ViserPaneHandle, target, ViserPaneHandle._validate(minimize_gui), loading)


class ImagePaneHandle(PaneHandle):
    """An image pane with frame updates and image properties."""

    _kind = "image"
    _props_type = _messages.ViewportImageProps
    _message_type = _messages.ViewportImageMessage
    _update_fields = ("_data", "_format", "fit")

    @staticmethod
    def _validate(format: object, jpeg_quality: object, fit: object) -> dict[str, Any]:
        _validate_image_encoding_options(format, jpeg_quality)
        return {"format": format, "jpeg_quality": jpeg_quality, "fit": _validate_fit(fit)}

    @staticmethod
    def _prepare(
        panes: Panes, value: Any, settings: dict[str, Any], previous: Any
    ) -> tuple[dict[str, Any], Any]:
        snapshot, image_format, data = prepare_image(
            value, settings["format"], settings["jpeg_quality"]
        )
        return {"_data": data, "_format": image_format, "fit": settings["fit"]}, snapshot

    @property
    def image(self) -> np.ndarray:
        """Independent copy of the current image. Assign to update."""
        with self._panes._lock:
            self._require_kind()
            return self._source.copy()

    @image.setter
    def image(self, image: np.ndarray) -> None:
        self.update(image)

    @property
    def format(self) -> Literal["auto", "jpeg", "png"]:
        """Requested image encoding."""
        with self._panes._lock:
            self._require_kind()
            return self._settings["format"]

    @property
    def fit(self) -> ImageFit | None:
        """How the image is sized within its pane, or None to follow the
        viewer's own "Image fit" setting."""
        with self._panes._lock:
            self._require_kind()
            return self._props.fit

    @fit.setter
    def fit(self, value: ImageFit | None) -> None:
        self._set_prop("fit", _validate_fit(value), setting=True)

    def update(
        self,
        image: np.ndarray,
        *,
        loading: PaneLoading | None = None,
        jpeg_quality: int | None = None,
    ) -> None:
        """Replace the image, optionally changing loading in the same update.

        None leaves the loading state unchanged; pass False to reveal the new
        image as part of the same update. ``jpeg_quality`` (0 to 100)
        overrides the creation quality for this frame only. After
        ``clear()``, restores the image renderer with its previous settings.
        """
        _validate_image_encoding_options("auto", jpeg_quality)  # Only quality varies per frame.
        frame = {} if jpeg_quality is None else {"jpeg_quality": jpeg_quality}
        self._publish(ImagePaneHandle, image, None, loading, frame)


class VideoPaneHandle(PaneHandle):
    """One browser-native video player.

    Updating with the same media URL preserves playback position and pause
    state. Local files use the server's immutable HTTP asset registry; no
    frames are decoded in Python or streamed through the GUI websocket.
    """

    _kind = "video"
    _props_type = _messages.ViewportVideoProps
    _message_type = _messages.ViewportVideoMessage
    _update_fields = ("_url",)

    @staticmethod
    def _validate(
        autoplay: object,
        loop: object,
        muted: object,
        controls: object,
        sync_group: str | None,
        fps: float | None,
    ) -> dict[str, Any]:
        if any(type(value) is not bool for value in (autoplay, loop, muted, controls)):
            raise TypeError("autoplay, loop, muted and controls must be bools")
        return {
            "autoplay": autoplay,
            "loop": loop,
            "muted": muted,
            "controls": controls,
            "sync_group": _validate_video_group(sync_group),
            "fps": _validate_video_fps(fps),
        }

    @staticmethod
    def _prepare(
        panes: Panes, value: Any, settings: dict[str, Any], previous: Any
    ) -> tuple[dict[str, Any], Any]:
        return {"_url": _video_url(panes, value), **settings}, None

    @property
    def sync_group(self) -> str | None:
        """Named browser-local playback group, or None for independent playback."""
        with self._panes._lock:
            self._require_kind()
            return self._props.sync_group

    @sync_group.setter
    def sync_group(self, value: str | None) -> None:
        self._set_prop("sync_group", _validate_video_group(value), setting=True)

    @property
    def fps(self) -> float | None:
        """Source frame rate for frame stepping; None disables frame stepping."""
        with self._panes._lock:
            self._require_kind()
            return self._props.fps

    @fps.setter
    def fps(self, value: float | None) -> None:
        self._set_prop("fps", _validate_video_fps(value), setting=True)

    def update(self, source: Path | str, *, loading: PaneLoading | None = None) -> None:
        """Replace the source, preserving settings; the same URL preserves playback.

        Paths are snapshotted using :meth:`Server.register_http_asset`; strings
        are HTTP(S) or root-relative URLs. A different source starts a new
        player. None leaves the loading state unchanged; False reveals the new
        video. After ``clear()``, restores the previous video settings and
        playback group.
        """
        self._publish(VideoPaneHandle, source, None, loading)


class MatplotlibPaneHandle(PaneHandle):
    """A Matplotlib figure relayed as SVG.

    SVG rather than pixels, so a resized pane rescales the figure crisply
    without a Python redraw. The figure is written exactly as composed -- no
    tight bounding box, no recoloring -- so the pane shows what ``savefig``
    would have written. Leika holds the figure only weakly.
    """

    _kind = "matplotlib"
    _props_type = _messages.ViewportMatplotlibProps
    _message_type = _messages.ViewportMatplotlibMessage
    _update_fields = ("_svg",)

    @staticmethod
    def _prepare(
        panes: Panes, value: Any, settings: dict[str, Any], previous: Any
    ) -> tuple[dict[str, Any], Any]:
        savefig = getattr(value, "savefig", None)
        if not callable(savefig):
            raise TypeError(
                "figure must be a matplotlib Figure (an object with a savefig method); "
                f"got {value!r}."
            )
        reference = weakref.ref(value)
        buffer = io.BytesIO()
        savefig(buffer, format="svg")
        return {"_svg": buffer.getvalue().decode("utf-8")}, reference

    @property
    def figure(self) -> Any:
        """Caller-owned figure, if still alive. Assign to update."""
        with self._panes._lock:
            self._require_kind()
            figure = self._source()
        if figure is None:
            raise RuntimeError(
                "The caller-owned Matplotlib figure is no longer available; "
                "retain it or assign another figure."
            )
        return figure

    @figure.setter
    def figure(self, figure: Any) -> None:
        self.update(figure)

    def update(self, figure: Any, *, loading: PaneLoading | None = None) -> None:
        """Publish a figure after redrawing it; None preserves loading.

        Matplotlib mutates figures in place, so passing the same figure again
        is normal.
        """
        self._publish(MatplotlibPaneHandle, figure, None, loading)


class PlotlyPaneHandle(PaneHandle):
    """A Plotly pane backed by serialized JSON, never by the caller's Figure."""

    _kind = "plotly"
    _props_type = _messages.ViewportPlotlyProps
    _message_type = _messages.ViewportPlotlyMessage
    _update_fields = ("_plotly_json_str",)

    @staticmethod
    def _validate(config: Mapping[str, Any] | None) -> dict[str, Any]:
        return {"config": plotly_config(config)}

    @staticmethod
    def _prepare(
        panes: Panes, value: Any, settings: dict[str, Any], previous: Any
    ) -> tuple[dict[str, Any], Any]:
        json_str = plotly_json(value, settings["config"])
        panes._owner._ensure_plotly_runtime()
        return {"_plotly_json_str": json_str, "_theme_templates": plotly_theme_templates()}, None

    @property
    def figure(self) -> go.Figure:
        """Independent snapshot of the displayed figure. Assign it to publish edits."""
        with self._panes._lock:
            self._require_kind()
            source = self._props._plotly_json_str
        return plotly_figure(source)

    @figure.setter
    def figure(self, figure: go.Figure) -> None:
        self.update(figure)

    def update(self, figure: go.Figure, *, loading: PaneLoading | None = None) -> None:
        """Replace the figure, preserving config; None preserves loading."""
        self._publish(PlotlyPaneHandle, figure, None, loading)


class ViserPaneHandle(PaneHandle):
    """An embedded Viser pane."""

    _kind = "viser"
    _props_type = _messages.ViewportViserProps
    _message_type = _messages.ViewportViserMessage
    _update_fields = ("_url", "_port")

    @staticmethod
    def _validate(minimize_gui: object) -> dict[str, Any]:
        if type(minimize_gui) is not bool:
            raise TypeError("minimize_gui must be a bool")
        return {"minimize_gui": minimize_gui}

    @staticmethod
    def _prepare(
        panes: Panes, value: Any, settings: dict[str, Any], previous: Any
    ) -> tuple[dict[str, Any], Any]:
        url, port = _viser_embed_target(value)
        if port is None:
            return {"_url": url, "_port": None}, None
        address = (value.get_host(), port)
        if isinstance(previous, _ViserRoute) and previous.address == address:
            # The same server keeps its route, so the embedded client stays loaded.
            route = previous
        else:
            route = _ViserRoute(panes._websock_interface._viser_proxy.register(*address), address)
        return {"_url": route.path, "_port": None}, route

    @staticmethod
    def _published(value: Any, settings: dict[str, Any]) -> None:
        if settings["minimize_gui"] and not isinstance(value, str):
            _minimize_viser_gui(value)

    @property
    def url(self) -> str | None:
        """Embed URL shown in the pane; a same-origin path for local servers,
        or the explicit URL supplied by the caller."""
        with self._panes._lock:
            self._require_kind()
            return self._props._url

    @property
    def port(self) -> int | None:
        """Viser server port, or None for explicit URL targets."""
        with self._panes._lock:
            self._require_kind()
            source = self._source
        return source.address[1] if isinstance(source, _ViserRoute) else None

    def update(self, target: str | Any, *, loading: PaneLoading | None = None) -> None:
        """Re-point the pane at another viser server or URL.

        Accepts the same targets as :meth:`Panes.add_viser`, and re-applies
        the pane's ``minimize_gui`` choice to server targets -- including the
        current one, so calling with the same server re-minimizes a panel the
        viewer expanded. None leaves the loading state unchanged.
        """
        self._publish(ViserPaneHandle, target, None, loading)


class _PaneAdder:
    """The ``add_*`` methods shared by a page's panes and its layout groups."""

    _panes: Panes

    def _place(
        self, placement: Placement | None, relative_to: str | None
    ) -> tuple[Placement, str, tuple[str, ...]]:
        """Edge, anchor pane, and equally divided siblings for the next pane. Lock held."""
        raise NotImplementedError

    def _placed(self, handle: PaneHandle) -> None:
        """Track a pane this adder placed. Lock held."""

    def _add(
        self,
        handle_type: type[PaneHandle],
        value: Any,
        settings: dict[str, Any],
        *,
        pane_id: str | None,
        title: str,
        visible: bool,
        loading: PaneLoading,
        placement: Placement | None,
        relative_to: str | None,
    ) -> Any:
        panes = self._panes
        title = cast(str, validate_renderer_string(title, "pane title"))
        if type(visible) is not bool:
            raise TypeError("visible must be a bool")
        loading = _validate_loading(loading)
        pane_id = str(uuid.uuid4()) if pane_id is None else validate_layout_id(pane_id, "Pane ID")
        if pane_id == _ROOT_PANE_ID:
            raise ValueError(f"Pane ID {pane_id!r} is reserved.")
        fields, source = handle_type._prepare(panes, value, settings, None)
        try:
            with panes._lock:
                if pane_id in panes._handle_from_pane_id:
                    raise ValueError(f"Pane ID {pane_id!r} already exists.")
                edge, anchor, equalize_group = self._place(placement, relative_to)
                props = handle_type._props_type(
                    title=title, visible=visible, loading=loading, **fields
                )
                declaration: dict[str, Any] = dict(
                    page_id=panes._page_id,
                    pane_id=pane_id,
                    placement=edge,
                    relative_to=anchor,
                    equalize_group=equalize_group,
                )
                panes._websock_interface.queue_messages_or_raise(
                    (
                        _messages.ViewportPaneMessage(
                            **declaration,
                            props=_messages.ViewportEmptyProps(
                                title=title, visible=visible, loading=loading
                            ),
                        ),
                        handle_type._message_type(**declaration, props=props),
                        panes._snapshot_message((*panes._handle_from_pane_id, pane_id)),
                    )
                )
                handle = handle_type(panes, pane_id, handle_type, props, settings, source)
                panes._handle_from_pane_id[pane_id] = handle
                self._placed(handle)
        except BaseException:
            _release(panes, source)
            raise
        handle_type._published(value, settings)
        return handle

    def add_pane(
        self,
        *,
        pane_id: str | None = None,
        title: str = "",
        visible: bool = True,
        loading: PaneLoading = False,
        placement: Placement | None = None,
        relative_to: str | None = None,
    ) -> PaneHandle:
        """Add an empty pane, ready for any of the handle's ``set_*`` methods.

        The pane keeps its ID and browser arrangement when its content changes.
        Empty panes render only the workspace background and optional title/loading
        overlay; they do not create a player, image, plot, or embedded server.
        Placement and persistence work just like :meth:`add_image`.
        """
        return self._add(
            PaneHandle,
            None,
            {},
            pane_id=pane_id,
            title=title,
            visible=visible,
            loading=loading,
            placement=placement,
            relative_to=relative_to,
        )

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
        loading: PaneLoading = False,
        placement: Placement | None = None,
        relative_to: str | None = None,
    ) -> ImagePaneHandle:
        """Add a native image pane to the workspace.

        The browser owns pane arrangement and persists it locally. Placement
        and relative_to are only used when the browser first encounters a pane
        that is not already present in its saved layout. Rows, columns, and
        grids place their panes themselves and reject both arguments.

        Args:
            image: RGB or RGBA image with shape (height, width, 3|4). Floats
                are read as 0 to 1 and integers as 0 to 255.
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            format: Transport encoding. "auto" chooses PNG for RGBA and JPEG
                for RGB.
            jpeg_quality: JPEG encoder quality from 0 to 100; 85 by default.
            fit: Image sizing policy within the pane. By default the viewer's
                own "Image fit" setting decides; pass a value to override it.
            visible: Initial visibility.
            loading: Initial loading overlay. True shows the default indicator;
                a string shows that text alongside it.
            placement: Initial split edge relative to relative_to; "right" by
                default.
            relative_to: Visible pane used for initial placement; the latest
                visible pane by default.

        Returns:
            Handle for updating or removing the image pane.
        """
        return self._add(
            ImagePaneHandle,
            image,
            ImagePaneHandle._validate(format, jpeg_quality, fit),
            pane_id=pane_id,
            title=title,
            visible=visible,
            loading=loading,
            placement=placement,
            relative_to=relative_to,
        )

    def add_matplotlib(
        self,
        figure: Any,
        *,
        pane_id: str | None = None,
        title: str = "Figure",
        visible: bool = True,
        loading: PaneLoading = False,
        placement: Placement | None = None,
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

        Args:
            figure: matplotlib figure to display, e.g. from
                ``plt.subplots()``. Duck-typed on ``savefig``, so matplotlib
                is not a Leika dependency. Leika keeps the SVG and only a weak
                reference to the figure; keep your own reference if you want
                to read it back, mutate it, and assign it to the handle again
                to update the pane.
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            visible: Initial visibility.
            loading: Initial loading overlay. True shows the default indicator;
                a string shows that text alongside it.
            placement: Initial split edge relative to relative_to; see
                :meth:`add_image`.
            relative_to: Visible pane used for initial placement.

        Returns:
            Handle for updating or removing the matplotlib pane.
        """
        return self._add(
            MatplotlibPaneHandle,
            figure,
            {},
            pane_id=pane_id,
            title=title,
            visible=visible,
            loading=loading,
            placement=placement,
            relative_to=relative_to,
        )

    def add_plotly(
        self,
        figure: go.Figure,
        *,
        config: Mapping[str, Any] | None = None,
        pane_id: str | None = None,
        title: str = "Plotly",
        visible: bool = True,
        loading: PaneLoading = False,
        placement: Placement | None = None,
        relative_to: str | None = None,
    ) -> PlotlyPaneHandle:
        """Add a native interactive Plotly pane to the workspace.
        Requires the `plotly` package to be installed.

        The plot is dynamically sized: it always fills its pane, including
        when panes are resized in the browser.

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
                an independent copy from the serialized JSON. Assign that copy
                back to publish edits.
            config: Plotly config dict merged into the figure JSON. Controls
                display options like ``{"displayModeBar": False}``. Values
                must be JSON-serializable. See
                https://plotly.com/javascript/configuration-options/
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            visible: Initial visibility.
            loading: Initial loading overlay. True shows the default indicator;
                a string shows that text alongside it.
            placement: Initial split edge relative to relative_to; see
                :meth:`add_image`.
            relative_to: Visible pane used for initial placement.

        Returns:
            Handle for updating or removing the Plotly pane.
        """
        return self._add(
            PlotlyPaneHandle,
            figure,
            PlotlyPaneHandle._validate(config),
            pane_id=pane_id,
            title=title,
            visible=visible,
            loading=loading,
            placement=placement,
            relative_to=relative_to,
        )

    def add_video(
        self,
        source: Path | str,
        *,
        autoplay: bool = True,
        loop: bool = True,
        muted: bool = True,
        controls: bool = True,
        sync_group: str | None = None,
        fps: float | None = None,
        pane_id: str | None = None,
        title: str = "Video",
        visible: bool = True,
        loading: PaneLoading = False,
        placement: Placement | None = None,
        relative_to: str | None = None,
    ) -> VideoPaneHandle:
        """Add one native video player to the workspace.

        ``source`` is a local ``Path`` or an HTTP(S)/root-relative URL. Paths
        use :meth:`Server.register_http_asset` and its retention limits
        (64 MiB per file, 128 MiB total). Use external URLs for larger media.
        Browser codec support applies. Autoplay normally requires muted audio.
        Offscreen players pause automatically and preserve manual pause state.

        A shared ``sync_group`` gives videos on the displayed page one local
        timeline per browser. Add :meth:`GuiApi.add_video_controls` to control it
        from the dock. Grouped panes show fullscreen controls; in fullscreen
        they also show the shared timeline. The first pane sets initial autoplay
        and looping. The longest clip sets duration; shorter clips hold their
        last frame. Supply the same positive ``fps`` on every member to enable
        frame stepping. None leaves the rate unknown. Replacing a grouped source
        restarts the timeline while retaining the viewer's pause and speed.

        Compose multiple videos with :meth:`Panes.add_grid`, :meth:`Panes.add_row`,
        or :meth:`Panes.add_column`. Each video is an independently arranged
        pane. Placement works as in :meth:`add_image`.
        """
        return self._add(
            VideoPaneHandle,
            source,
            VideoPaneHandle._validate(autoplay, loop, muted, controls, sync_group, fps),
            pane_id=pane_id,
            title=title,
            visible=visible,
            loading=loading,
            placement=placement,
            relative_to=relative_to,
        )

    def add_viser(
        self,
        target: str | Any,
        *,
        pane_id: str | None = None,
        title: str = "viser",
        visible: bool = True,
        loading: PaneLoading = False,
        minimize_gui: bool = True,
        placement: Placement | None = None,
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

            viser_server = viser.ViserServer(host="127.0.0.1")
            server.panes.add_viser(viser_server)
            slider = server.gui.add_slider("Size", min=1, max=10, step=1, initial_value=3)

            @slider.on_update
            def _(_) -> None:
                viser_server.scene.add_icosphere("/ball", radius=slider.value)

        Server-object targets are proxied through Leika on the same origin.
        The login protects their assets and websocket, and a share tunnel or
        SSH forward needs only Leika's port. Bind Viser to ``127.0.0.1``;
        password-protected workspaces reject separately exposed listeners.
        Viser's independent share requests are blocked on this route.
        Leika owns the proxy route, while you still own and stop Viser itself.

        Explicit URL targets remain direct embeds with their own access
        policy. An ``http://`` URL cannot be embedded into an ``https://``
        Leika page because browsers block mixed content.

        The embedded client follows Leika's light/dark theme.

        Args:
            target: What to embed: a ``viser.ViserServer`` (any object with
                ``get_port()`` and ``get_host()`` methods), or an absolute
                http(s) URL of a viser client.
            pane_id: Stable identifier for browser layout persistence. By
                default a UUID is generated. Set this explicitly to restore a
                pane's position after a server restart.
            title: Pane corner-label title.
            visible: Initial visibility.
            loading: Initial loading overlay. True shows the default indicator;
                a string shows that text alongside it.
            minimize_gui: Dock viser's own control panel to the right edge
                and minimize it to a rail. Applies to server-object targets
                on viser versions with ``gui.main_panel``; ignored for URL
                targets, which Python cannot reach into.
            placement: Initial split edge relative to relative_to; see
                :meth:`add_image`.
            relative_to: Visible pane used for initial placement.

        Returns:
            Handle for re-pointing or removing the viser pane.
        """
        return self._add(
            ViserPaneHandle,
            target,
            ViserPaneHandle._validate(minimize_gui),
            pane_id=pane_id,
            title=title,
            visible=visible,
            loading=loading,
            placement=placement,
            relative_to=relative_to,
        )


class PaneGroup(_PaneAdder):
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
        panes: Panes,
        axis: Literal["row", "column"],
        placement: Placement,
        relative_to: str | None,
    ) -> None:
        self._panes = panes
        self._axis = axis
        self._placement: Placement = placement
        self._relative_to = (
            None if relative_to is None else validate_layout_id(relative_to, "relative_to")
        )
        self._members: list[weakref.ReferenceType[PaneHandle]] = []

    def _place(
        self, placement: Placement | None, relative_to: str | None
    ) -> tuple[Placement, str, tuple[str, ...]]:
        """Attach to the group's last visible member and equalize with the visible ones.

        Hidden and removed members cannot anchor placement, so with none
        visible the next pane falls back to the group's own placement, like a
        first pane. Membership is checked by handle identity, so an unrelated
        pane reusing a removed member's ID is not adopted.
        """
        if placement is not None or relative_to is not None:
            raise TypeError(
                "A row, column, or grid places its own panes; "
                "placement and relative_to apply only to Panes."
            )
        panes = self._panes
        members = [
            handle
            for reference in self._members
            if (handle := reference()) is not None
            and panes._handle_from_pane_id.get(handle.pane_id) is handle
        ]
        self._members = [weakref.ref(handle) for handle in members]
        visible = [handle.pane_id for handle in members if handle._props.visible]
        if not visible:
            # The group's own anchor may be hidden or removed as well (notably
            # a grid column whose top-row seed disappeared).
            anchor = self._relative_to if self._relative_to in panes._visible_pane_ids() else None
            return self._placement, panes._resolve_relative_to(anchor), ()
        return ("right" if self._axis == "row" else "bottom"), visible[-1], tuple(visible)

    def _placed(self, handle: PaneHandle) -> None:
        self._members.append(weakref.ref(handle))


class PaneGrid(_PaneAdder):
    """Adds panes to an equally divided grid.

    Returned by :meth:`Panes.add_grid`. Panes fill left to right, top
    to bottom: the first ``columns`` panes form the top row, and later panes
    wrap onto new rows beneath it, re-dividing their row and column equally
    on each addition. Like :class:`PaneGroup`, the grid only shapes
    creation-time placement; see it for details.
    """

    def __init__(self, panes: Panes, columns: int, relative_to: str | None) -> None:
        self._panes = panes
        self._columns = columns
        self._row = PaneGroup(panes, "row", "right", relative_to)
        self._column_groups: list[PaneGroup] = []
        self._count = 0

    def _next_group(self) -> PaneGroup:
        """The shared top row while it is still filling, then the column the
        next pane wraps onto."""
        if self._count < self._columns:
            return self._row
        return self._column_groups[self._count % self._columns]

    def _place(
        self, placement: Placement | None, relative_to: str | None
    ) -> tuple[Placement, str, tuple[str, ...]]:
        return self._next_group()._place(placement, relative_to)

    def _placed(self, handle: PaneHandle) -> None:
        group = self._next_group()
        group._placed(handle)
        if group is self._row:
            # A top-row pane seeds its column, so panes beneath it equalize
            # together with it into exact equal parts.
            column = PaneGroup(self._panes, "column", "bottom", handle.pane_id)
            column._placed(handle)
            self._column_groups.append(column)
        self._count += 1
        if self._count >= 2 * self._columns:
            self._count = self._columns


class Panes(_PaneAdder):
    """Declare image, matplotlib, Plotly, video, and viser panes on one page."""

    def __init__(self, owner: Server, page_id: str) -> None:
        self._owner = owner
        self._page_id = page_id
        self._panes = self
        self._lock = threading.RLock()
        self._websock_interface = owner._websock_server
        self._handle_from_pane_id: dict[str, PaneHandle] = {}

    def _place(
        self, placement: Placement | None, relative_to: str | None
    ) -> tuple[Placement, str, tuple[str, ...]]:
        placement = "right" if placement is None else placement
        if type(placement) is not str or placement not in ("left", "right", "top", "bottom"):
            raise ValueError("placement must be left, right, top, or bottom.")
        return placement, self._resolve_relative_to(relative_to), ()

    def _visible_pane_ids(self) -> set[str]:
        return {_ROOT_PANE_ID} | {
            pane_id
            for pane_id, handle in self._handle_from_pane_id.items()
            if handle._props.visible
        }

    def _resolve_relative_to(self, relative_to: str | None) -> str:
        """Resolve ``None`` placement to the latest visible pane. Lock held."""
        if relative_to is not None:
            relative_to = validate_layout_id(relative_to, "relative_to")
            if relative_to not in self._visible_pane_ids():
                raise ValueError(f"Unknown or hidden relative pane ID: {relative_to!r}.")
            return relative_to
        for pane_id, handle in reversed(self._handle_from_pane_id.items()):
            if handle._props.visible:
                return pane_id
        return _ROOT_PANE_ID

    def _snapshot_message(
        self, pane_ids: tuple[str, ...] | None = None
    ) -> _messages.ViewportPaneSnapshotMessage:
        """Build the authoritative pane-registry reconciliation message."""
        return _messages.ViewportPaneSnapshotMessage(
            page_id=self._page_id,
            pane_ids=tuple(self._handle_from_pane_id) if pane_ids is None else pane_ids,
        )

    def add_row(self, *, relative_to: str | None = None) -> PaneGroup:
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

    def add_column(self, *, relative_to: str | None = None) -> PaneGroup:
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

    def add_grid(self, *, columns: int = 2, relative_to: str | None = None) -> PaneGrid:
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

        validate_positive_integer(columns, "columns")
        return PaneGrid(self, columns, relative_to)
