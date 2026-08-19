from __future__ import annotations

import gc
import json
import threading
import weakref
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

import leika
import leika._messages as messages
import leika._panes as panes_impl
from leika._panes import _viser_embed_target


def test_image_fit_defers_to_the_viewer_until_python_names_one(
    server: leika.Server,
) -> None:
    """`fit` is the app's override, not its obligation: left alone it stays
    None and the browser applies whatever the viewer chose."""
    frame = np.zeros((4, 6, 3), dtype=np.uint8)

    deferred = server.panes.add_image(frame, pane_id="deferred")
    assert deferred.fit is None

    explicit = server.panes.add_image(frame, pane_id="explicit", fit="fill")
    assert explicit.fit == "fill"

    # And it can be handed back after the fact.
    explicit.fit = None
    assert explicit.fit is None
    deferred.fit = "stretch"
    assert deferred.fit == "stretch"

    with pytest.raises(ValueError, match="fit must be"):
        server.panes.add_image(frame, pane_id="bad", fit="cover")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="fit must be"):
        deferred.fit = "cover"  # type: ignore[assignment]


def test_image_lifecycle_and_validation(server: leika.Server) -> None:
    original = np.zeros((8, 12, 4), dtype=np.uint8)
    pane = server.panes.add_image(
        original,
        pane_id="camera",
        title="Camera",
        fit="fill",
        format="png",
        loading="Loading camera",
    )
    assert pane.pane_id == "camera"
    assert pane.title == "Camera"
    assert pane.visible is True
    assert pane.loading == "Loading camera"
    assert pane.fit == "fill"
    np.testing.assert_array_equal(pane.image, original)
    original[:] = 255
    assert np.all(pane.image == 0)
    returned = pane.image
    returned[:] = 255
    assert np.all(pane.image == 0)
    pane.loading = True
    assert pane.loading is True

    next_frame = np.full((4, 6, 3), 127, dtype=np.uint8)
    pane.title = "Updated"
    pane.visible = False
    pane.fit = "fit"
    pane.update(next_frame, loading=False)
    assert pane.title == "Updated"
    assert pane.visible is False
    assert pane.fit == "fit"
    assert pane.loading is False
    np.testing.assert_array_equal(pane.image, next_frame)

    pane.remove()
    for read in (
        lambda: pane.image,
        lambda: pane.title,
        lambda: pane.visible,
        lambda: pane.loading,
        lambda: pane.fit,
    ):
        with pytest.raises(RuntimeError, match="removed"):
            read()
    assert pane._impl.image.size == 0
    assert pane._impl.props._data == b""
    with pytest.raises(RuntimeError, match="removed"):
        pane.update(original)
    replacement = server.panes.add_image(original, pane_id="camera")
    assert replacement.pane_id == "camera"

    with pytest.raises(ValueError):
        server.panes.add_image(np.zeros((3, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="positive height and width"):
        server.panes.add_image(np.zeros((0, 3, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="positive height and width"):
        server.panes.add_image(np.zeros((3, 0, 4), dtype=np.uint8))
    with pytest.raises((TypeError, ValueError)):
        server.panes.add_image(np.zeros((3, 3, 3), dtype=np.bool_))
    with pytest.raises(ValueError):
        server.panes.add_image(original, pane_id="camera")
    with pytest.raises((TypeError, ValueError)):
        server.panes.add_image(original, pane_id=cast(Any, 4))


def test_row_column_and_grid_helpers(server: leika.Server) -> None:
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    row = server.panes.add_row()
    first = row.add_image(frame, pane_id="row-a")
    second = row.add_image(frame, pane_id="row-b")
    column = server.panes.add_column(relative_to=second.pane_id)
    third = column.add_image(frame, pane_id="column-a")
    grid = server.panes.add_grid(columns=2, relative_to=third.pane_id)
    fourth = grid.add_image(frame, pane_id="grid-a")
    fifth = grid.add_image(frame, pane_id="grid-b")
    assert [item.pane_id for item in (first, second, third, fourth, fifth)] == [
        "row-a",
        "row-b",
        "column-a",
        "grid-a",
        "grid-b",
    ]

    with pytest.raises(ValueError):
        server.panes.add_grid(columns=0)
    for columns in (True, 1.5):
        with pytest.raises(ValueError, match="positive integer"):
            server.panes.add_grid(columns=cast(Any, columns))
    with pytest.raises(ValueError):
        server.panes.add_image(frame, relative_to="missing")


def test_image_update_can_change_loading_in_one_message(server: leika.Server) -> None:
    original = np.zeros((2, 3, 3), dtype=np.uint8)
    pane = server.panes.add_image(original, pane_id="coupled", loading=True)
    buffer = server._websock_server.get_message_buffer()
    before_ids = set(buffer.message_from_id)

    replacement = np.full((3, 4, 3), 127, dtype=np.uint8)
    pane.update(replacement, loading=False)

    queued = [
        message
        for message_id, message in buffer.message_from_id.items()
        if message_id not in before_ids
    ]
    assert len(queued) == 1
    assert isinstance(queued[0], messages.ViewportPaneUpdateMessage)
    assert set(queued[0].updates) == {"_data", "_format", "loading"}
    assert queued[0].updates["loading"] is False
    assert pane.loading is False
    np.testing.assert_array_equal(pane.image, replacement)


def test_coupled_image_loading_update_rolls_back_on_queue_failure(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = np.zeros((2, 3, 3), dtype=np.uint8)
    pane = server.panes.add_image(original, pane_id="rollback", loading="Preparing")
    before_resources = server.panes._resource_total

    def fail(_: object) -> None:
        raise RuntimeError("update failed")

    monkeypatch.setattr(server.panes._websock_interface, "queue_message_or_raise", fail)
    with pytest.raises(RuntimeError, match="update failed"):
        pane.update(np.ones((4, 5, 3), dtype=np.uint8), loading=False)

    assert pane.loading == "Preparing"
    np.testing.assert_array_equal(pane.image, original)
    assert server.panes._resource_total == before_resources


@pytest.mark.parametrize("retire", ["hide", "remove"])
def test_grid_wrap_falls_back_when_top_column_anchor_is_not_visible(
    server: leika.Server, retire: str
) -> None:
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    fallback = server.panes.add_image(frame, pane_id=f"fallback-{retire}")
    grid = server.panes.add_grid(columns=1, relative_to=fallback.pane_id)
    top = grid.add_image(frame, pane_id=f"top-{retire}")

    if retire == "hide":
        top.visible = False
    else:
        top.remove()

    wrapped = grid.add_image(frame, pane_id=f"wrapped-{retire}")
    assert wrapped.pane_id == f"wrapped-{retire}"
    assert server.panes._handle_from_pane_id[wrapped.pane_id] is wrapped


@pytest.mark.plotly
def test_plotly_lifecycle(server: leika.Server) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    figure = go.Figure(go.Scatter(y=[1, 2, 1]))
    pane = server.panes.add_plotly(
        figure,
        pane_id="metrics",
        title="Metrics",
        config={"displayModeBar": False},
        loading=True,
    )
    assert pane.pane_id == "metrics"
    assert pane.figure is not figure
    assert tuple(pane.figure.data[0].y) == (1, 2, 1)
    replacement = go.Figure(go.Bar(y=[3, 1]))
    pane.update(replacement, loading="Drawing chart")
    assert pane.figure is not replacement
    assert tuple(pane.figure.data[0].y) == (3, 1)
    assert pane.loading == "Drawing chart"
    pane.visible = False
    assert pane.visible is False
    pane.remove()
    for read in (
        lambda: pane.figure,
        lambda: pane.title,
        lambda: pane.visible,
        lambda: pane.loading,
    ):
        with pytest.raises(RuntimeError, match="removed"):
            read()
    assert pane._impl.props._plotly_json_str == ""
    assert pane._impl.props._theme_templates == ""
    with pytest.raises(RuntimeError, match="removed"):
        pane.figure = go.Figure()


@pytest.mark.matplotlib
def test_matplotlib_lifecycle(server: leika.Server) -> None:
    plt = pytest.importorskip("matplotlib.pyplot")
    figure, axes = plt.subplots()
    axes.plot([0, 1, 2], [1, 3, 2], label="signal")
    try:
        pane = server.panes.add_matplotlib(figure, pane_id="figure", title="Signal", loading=True)
        assert pane.pane_id == "figure"
        assert pane.title == "Signal"
        assert pane.figure is figure
        # Relayed as SVG source, so the pane can rescale it without a redraw.
        assert pane._impl.props._svg.lstrip().startswith(("<?xml", "<svg"))
        assert "<svg" in pane._impl.props._svg

        # matplotlib mutates figures in place, so re-passing one is normal.
        axes.set_title("Updated")
        pane.update(figure, loading="Drawing figure")
        assert "Updated" in pane._impl.props._svg
        assert pane.loading == "Drawing figure"

        pane.visible = False
        assert pane.visible is False
        pane.remove()
        for read in (
            lambda: pane.figure,
            lambda: pane.title,
            lambda: pane.visible,
            lambda: pane.loading,
        ):
            with pytest.raises(RuntimeError, match="removed"):
                read()
        assert pane._impl.figure_ref is None
        assert pane._impl.props._svg == ""
        with pytest.raises(RuntimeError, match="removed"):
            pane.update(figure)
    finally:
        plt.close(figure)

    with pytest.raises(TypeError, match="savefig"):
        server.panes.add_matplotlib(object())


def test_matplotlib_sources_must_support_weak_references_transactionally(
    server: leika.Server,
) -> None:
    class NonWeakFigure:
        __slots__ = ()

        def savefig(self, output: Any, *, format: str) -> None:
            raise AssertionError("non-weak source reached renderer")

    buffer = server._websock_server.get_message_buffer()
    before_messages = buffer.message_from_id.copy()
    before_resources = server.panes._resource_total
    with pytest.raises(TypeError, match="must support weak references"):
        server.panes.add_matplotlib(NonWeakFigure(), pane_id="non-weak")
    assert "non-weak" not in server.panes._handle_from_pane_id
    assert buffer.message_from_id == before_messages
    assert server.panes._resource_total == before_resources

    class Figure:
        def savefig(self, output: Any, *, format: str) -> None:
            assert format == "svg"
            output.write(b'<svg xmlns="http://www.w3.org/2000/svg"/>')

    source = Figure()
    pane = server.panes.add_matplotlib(source, pane_id="weak-source")
    before_messages = buffer.message_from_id.copy()
    before_resources = server.panes._resource_total
    before_svg = pane._impl.props._svg
    with pytest.raises(TypeError, match="must support weak references"):
        pane.figure = NonWeakFigure()
    assert pane.figure is source
    assert pane._impl.props._svg == before_svg
    assert buffer.message_from_id == before_messages
    assert server.panes._resource_total == before_resources


def test_matplotlib_pane_does_not_retain_the_caller_figure(
    server: leika.Server,
) -> None:
    class Figure:
        def savefig(self, output: Any, *, format: str) -> None:
            assert format == "svg"
            output.write(b'<svg xmlns="http://www.w3.org/2000/svg"/>')

    figure = Figure()
    reference = weakref.ref(figure)
    pane = server.panes.add_matplotlib(figure, pane_id="weak-matplotlib")
    assert pane.figure is figure
    assert pane._impl.props._svg

    del figure
    gc.collect()
    assert reference() is None
    with pytest.raises(RuntimeError, match="no longer available"):
        _ = pane.figure
    assert pane._impl.props._svg


def test_matplotlib_svg_enforces_browser_utf16_limit_transactionally(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Figure:
        def __init__(self, source: str) -> None:
            self.source = source

        def savefig(self, output: Any, *, format: str) -> None:
            assert format == "svg"
            output.write(self.source.encode("utf-8"))

    monkeypatch.setattr(panes_impl, "_MATPLOTLIB_SVG_MAX_UTF16_CODE_UNITS", 2)
    pane = server.panes.add_matplotlib(Figure("😀"), pane_id="svg")
    assert pane._impl.props._svg == "😀"

    with pytest.raises(ValueError, match="16 Mi-character"):
        pane.figure = Figure("😀x")
    assert pane._impl.props._svg == "😀"

    with pytest.raises(ValueError, match="16 Mi-character"):
        server.panes.add_matplotlib(Figure("😀x"), pane_id="too-large")
    assert "too-large" not in server.panes._handle_from_pane_id


def test_viser_target_normalization() -> None:
    assert _viser_embed_target("http://viser.example.com:8080") == (
        "http://viser.example.com:8080",
        None,
    )
    assert _viser_embed_target("https://tunnel.example.com/scene") == (
        "https://tunnel.example.com/scene",
        None,
    )

    # ViserServer duck type: only the port is kept, since viser binds 0.0.0.0
    # and the browser derives the host from the page's own hostname.
    fake = SimpleNamespace(get_port=lambda: 8080, get_host=lambda: "0.0.0.0")
    assert _viser_embed_target(fake) == (None, 8080)

    with pytest.raises(ValueError, match="absolute http"):
        _viser_embed_target("localhost:8080")
    with pytest.raises(ValueError, match="absolute http"):
        _viser_embed_target("ftp://viser.example.com")
    with pytest.raises(ValueError, match="absolute http"):
        _viser_embed_target("")
    for malformed in (
        "http://viser.example.com/a b",
        "http://viser.example.com/a\tb",
        "http://viser.example.com/a\x7fb",
    ):
        with pytest.raises(ValueError, match="malformed"):
            _viser_embed_target(malformed)
    # Released viser reports 0 for ViserServer(port=0); the error explains it.
    with pytest.raises(ValueError, match="port 0"):
        _viser_embed_target(SimpleNamespace(get_port=lambda: 0, get_host=lambda: "0.0.0.0"))
    with pytest.raises(ValueError, match="invalid port"):
        _viser_embed_target(SimpleNamespace(get_port=lambda: 70_000, get_host=lambda: "0.0.0.0"))
    with pytest.raises(TypeError, match="ViserServer"):
        _viser_embed_target(object())
    with pytest.raises(TypeError, match="ViserServer"):
        _viser_embed_target(SimpleNamespace(get_port=8080, get_host=lambda: "0.0.0.0"))


def _fake_viser_server(port: int = 8123) -> SimpleNamespace:
    """Duck-typed stand-in for a viser server with the main_panel API,
    recording the placement calls add_viser makes."""

    calls: list[str] = []
    main_panel = SimpleNamespace(
        dock_right=lambda: calls.append("dock_right"),
        minimize=lambda: calls.append("minimize"),
    )
    return SimpleNamespace(
        get_port=lambda: port,
        get_host=lambda: "0.0.0.0",
        gui=SimpleNamespace(main_panel=main_panel),
        calls=calls,
    )


def test_viser_gui_is_minimized_by_default(server: leika.Server) -> None:
    fake = _fake_viser_server()
    pane = server.panes.add_viser(fake, pane_id="minimized")
    assert fake.calls == ["dock_right", "minimize"]

    # Re-applying with the same server re-minimizes a viewer-expanded panel.
    pane.update(fake)
    assert fake.calls == ["dock_right", "minimize", "dock_right", "minimize"]

    # URL targets are unreachable from Python, so nothing more is queued.
    pane.update("http://viser.example.com:9000")
    assert len(fake.calls) == 4

    # Opting out leaves the viser server untouched, on add and on update.
    untouched = _fake_viser_server(port=8200)
    hands_off = server.panes.add_viser(untouched, pane_id="expanded", minimize_gui=False)
    hands_off.update(untouched)
    assert untouched.calls == []

    # Servers without the main_panel API (viser <= 1.0.30) are a silent no-op.
    old = SimpleNamespace(get_port=lambda: 8300, get_host=lambda: "0.0.0.0")
    server.panes.add_viser(old, pane_id="old-viser")

    # A failed add leaves the user's viser server untouched.
    rejected = _fake_viser_server(port=8400)
    with pytest.raises(ValueError, match="already exists"):
        server.panes.add_viser(rejected, pane_id="minimized")
    assert rejected.calls == []


def test_viser_minimize_hook_failures_are_nonfatal(
    server: leika.Server,
) -> None:
    def fail() -> None:
        raise RuntimeError("viser panel unavailable")

    target = SimpleNamespace(
        get_port=lambda: 8500,
        get_host=lambda: "0.0.0.0",
        gui=SimpleNamespace(main_panel=SimpleNamespace(dock_right=fail, minimize=lambda: None)),
    )
    with pytest.warns(RuntimeWarning, match="viser panel unavailable"):
        pane = server.panes.add_viser(target, pane_id="hook-failure")
    assert pane.pane_id == "hook-failure"
    assert server.panes._handle_from_pane_id["hook-failure"] is pane

    with pytest.warns(RuntimeWarning, match="viser panel unavailable"):
        pane.update(target)
    assert pane.port == 8500


def test_viser_lifecycle(server: leika.Server) -> None:
    fake = SimpleNamespace(get_port=lambda: 8123, get_host=lambda: "0.0.0.0")
    pane = server.panes.add_viser(fake, pane_id="viser", title="Scene", loading=True)
    assert pane.pane_id == "viser"
    assert pane.title == "Scene"
    assert pane.url is None
    assert pane.port == 8123

    pane.update("http://viser.example.com:9000", loading="Connecting")
    assert pane.url == "http://viser.example.com:9000"
    assert pane.port is None
    assert pane.loading == "Connecting"
    pane.update(SimpleNamespace(get_port=lambda: 8124, get_host=lambda: "0.0.0.0"))
    assert pane.url is None
    assert pane.port == 8124

    pane.visible = False
    assert pane.visible is False
    pane.remove()
    with pytest.raises(RuntimeError, match="removed"):
        pane.update(fake)

    with pytest.raises(TypeError, match="ViserServer"):
        server.panes.add_viser(object())

    row = server.panes.add_row()
    first = row.add_viser(fake, pane_id="row-viser")
    grid = server.panes.add_grid(columns=1, relative_to=first.pane_id)
    second = grid.add_viser("http://viser.example.com:9000", pane_id="grid-viser")
    assert [item.pane_id for item in (first, second)] == ["row-viser", "grid-viser"]
    with pytest.raises(ValueError):
        server.panes.add_viser(fake, pane_id="row-viser")


def test_only_v1_pane_types_are_exposed(server: leika.Server) -> None:
    # add_matplotlib relays a figure the caller composed, which is what panes
    # are for. A generic URL pane would make Leika a frame host for arbitrary
    # pages, and a scene API would make it a 3D engine; both stay out.
    for name in ("add_url", "add_scene"):
        assert not hasattr(server.panes, name)


@pytest.mark.parametrize("factory", ["direct", "group", "grid"])
@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("title", 123, "title must be a string"),
        ("visible", "false", "visible must be a bool"),
        ("loading", 1, "loading must be a bool or string"),
    ],
)
def test_pane_creation_rejects_primitive_coercion(
    server: leika.Server,
    factory: str,
    keyword: str,
    value: object,
    message: str,
) -> None:
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    if factory == "direct":
        add = server.panes.add_image
    elif factory == "group":
        add = server.panes.add_row().add_image
    else:
        add = server.panes.add_grid(columns=1).add_image
    with pytest.raises(TypeError, match=message):
        add(frame, **{keyword: value})


def test_pane_setters_reject_primitive_coercion(server: leika.Server) -> None:
    pane = server.panes.add_image(np.zeros((2, 2, 3), dtype=np.uint8))
    with pytest.raises(TypeError, match="title must be a string"):
        pane.title = 123  # type: ignore[assignment]
    with pytest.raises(TypeError, match="visible must be a bool"):
        pane.visible = "false"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="loading must be a bool or string"):
        pane.loading = 1  # type: ignore[assignment]
    assert pane.title == "Image"
    assert pane.visible is True
    assert pane.loading is False


def test_pane_encoding_and_layout_options_reject_builtin_subclasses_transactionally(
    server: leika.Server,
) -> None:
    class String(str):
        pass

    class Integer(int):
        pass

    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    anchor = server.panes.add_image(frame, pane_id="boundary-anchor", fit="fill")
    buffer = server._websock_server.get_message_buffer()
    before_handles = server.panes._handle_from_pane_id.copy()
    before_messages = buffer.message_from_id.copy()
    before_resources = server.panes._resource_total

    with pytest.raises(ValueError, match="format must be"):
        server.panes.add_image(frame, pane_id="subclass-format", format=cast(Any, String("png")))
    with pytest.raises(ValueError, match="jpeg_quality must be"):
        server.panes.add_image(
            frame, pane_id="subclass-quality", jpeg_quality=cast(Any, Integer(85))
        )
    with pytest.raises(ValueError, match="fit must be"):
        server.panes.add_image(frame, pane_id="subclass-fit", fit=cast(Any, String("fit")))
    with pytest.raises(ValueError, match="placement must be"):
        server.panes.add_image(
            frame, pane_id="subclass-placement", placement=cast(Any, String("right"))
        )
    with pytest.raises(TypeError, match="relative_to must be a string"):
        server.panes.add_image(
            frame,
            pane_id="subclass-relative",
            relative_to=cast(Any, String(anchor.pane_id)),
        )
    with pytest.raises(TypeError, match="relative_to must be a string"):
        server.panes.add_row(relative_to=cast(Any, String(anchor.pane_id)))
    with pytest.raises(ValueError, match="columns must be a positive integer"):
        server.panes.add_grid(columns=cast(Any, Integer(2)))
    with pytest.raises(ValueError, match="fit must be"):
        anchor.fit = cast(Any, String("stretch"))

    assert anchor.fit == "fill"
    assert server.panes._handle_from_pane_id == before_handles
    assert buffer.message_from_id == before_messages
    assert server.panes._resource_total == before_resources


def test_removed_image_pane_scrubs_private_encoding_state(server: leika.Server) -> None:
    pane = server.panes.add_image(
        np.zeros((2, 2, 3), dtype=np.uint8),
        pane_id="scrubbed-image",
        title="Sensitive title",
        format="jpeg",
        jpeg_quality=73,
    )
    assert pane._impl.requested_format == "jpeg"
    assert pane._impl.jpeg_quality == 73

    pane.remove()

    assert pane._impl.image.size == 0
    assert pane._impl.requested_format == "auto"
    assert pane._impl.jpeg_quality is None
    assert pane._impl.props._data == b""
    assert pane._impl.props.title == ""


def test_viser_minimize_and_reported_port_are_strict(server: leika.Server) -> None:
    with pytest.raises(TypeError, match="minimize_gui must be a bool"):
        server.panes.add_viser(
            "http://127.0.0.1:8080",
            minimize_gui="false",  # type: ignore[arg-type]
        )

    class Target:
        def get_port(self) -> str:
            return "8080"

        def get_host(self) -> str:
            return "127.0.0.1"

    with pytest.raises(TypeError, match="non-integer port"):
        _viser_embed_target(Target())


def test_relative_anchor_resolution_holds_the_registry_lock(
    server: leika.Server,
) -> None:
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    first = server.panes.add_image(frame, pane_id="first")
    entered = threading.Event()
    release = threading.Event()
    resolved: list[str] = []

    def resolve() -> None:
        with server.panes._lock:
            entered.set()
            assert release.wait(2)
            resolved.append(server.panes._resolve_relative_to(None))

    resolver = threading.Thread(target=resolve)
    resolver.start()
    assert entered.wait(1)
    removed = threading.Event()
    remover = threading.Thread(target=lambda: (first.remove(), removed.set()))
    remover.start()
    assert not removed.wait(0.05)
    release.set()
    resolver.join(timeout=1)
    remover.join(timeout=1)

    assert resolved == ["first"]
    assert removed.is_set()
    assert not resolver.is_alive() and not remover.is_alive()


def test_pane_lifecycle_batch_failure_leaves_no_ghost_or_partial_removal(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = np.zeros((1, 1, 3), dtype=np.uint8)

    def fail(_: object) -> None:
        raise RuntimeError("batch failed")

    monkeypatch.setattr(server.panes._websock_interface, "queue_messages_or_raise", fail)
    with pytest.raises(RuntimeError, match="batch failed"):
        server.panes.add_image(frame, pane_id="rejected")
    assert "rejected" not in server.panes._handle_from_pane_id

    monkeypatch.undo()
    pane = server.panes.add_image(frame, pane_id="live")
    monkeypatch.setattr(server.panes._websock_interface, "queue_messages_or_raise", fail)
    with pytest.raises(RuntimeError, match="batch failed"):
        pane.remove()
    assert not pane._impl.removed
    assert server.panes._handle_from_pane_id["live"] is pane
    np.testing.assert_array_equal(pane.image, frame)
    assert pane.title == "Image"
    assert pane._impl.props._data


@pytest.mark.plotly
def test_failed_plotly_pane_removal_preserves_figure_and_props(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    figure = go.Figure(go.Scatter(y=[1, 3, 2]))
    pane = server.panes.add_plotly(
        figure,
        pane_id="failed-plotly-remove",
        title="Metrics",
        config={"displayModeBar": False},
    )
    json_before = pane._impl.props._plotly_json_str

    def reject(_: object) -> None:
        raise RuntimeError("batch failed")

    monkeypatch.setattr(server.panes._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="batch failed"):
        pane.remove()

    assert pane.figure is not figure
    assert tuple(pane.figure.data[0].y) == (1, 3, 2)
    assert pane.title == "Metrics"
    assert json.loads(pane._impl.props._plotly_json_str)["config"] == {"displayModeBar": False}
    assert pane._impl.props._plotly_json_str == json_before


def test_failed_matplotlib_pane_removal_preserves_figure_and_svg(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Figure:
        def savefig(self, output: Any, *, format: str) -> None:
            assert format == "svg"
            output.write(b'<svg xmlns="http://www.w3.org/2000/svg"><text>large</text></svg>')

    figure = Figure()
    pane = server.panes.add_matplotlib(
        figure,
        pane_id="failed-matplotlib-remove",
        title="Signal",
    )
    svg_before = pane._impl.props._svg

    def reject(_: object) -> None:
        raise RuntimeError("batch failed")

    monkeypatch.setattr(server.panes._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="batch failed"):
        pane.remove()

    assert pane.figure is figure
    assert pane.title == "Signal"
    assert pane._impl.props._svg == svg_before


def test_pane_image_rejects_decoded_pixel_overflow_before_encoding(
    server: leika.Server,
) -> None:
    backing = np.zeros((1, 1, 3), dtype=np.uint8)
    oversized = np.lib.stride_tricks.as_strided(
        backing, shape=(4_096, 8_193, 3), strides=(0, 0, 1), writeable=False
    )
    with pytest.raises(ValueError, match="decoded pixels"):
        server.panes.add_image(oversized)


def test_pane_id_obeys_browser_utf16_layout_limit(server: leika.Server) -> None:
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    exact = "😀" * 512
    pane = server.panes.add_image(frame, pane_id=exact)
    assert pane.pane_id == exact

    with pytest.raises(ValueError, match="1024 UTF-16"):
        server.panes.add_image(frame, pane_id=exact + "x")
    with pytest.raises(ValueError, match="surrogate"):
        server.panes.add_image(frame, pane_id="bad\ud800")
    for reserved in ("__proto__", "prototype", "constructor"):
        with pytest.raises(ValueError, match="reserved browser"):
            server.panes.add_image(frame, pane_id=reserved)


def test_pane_image_encodes_and_retains_one_private_snapshot(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = np.zeros((2, 3, 3), dtype=np.uint8)
    encoded_snapshots: list[np.ndarray] = []

    def encode(snapshot: np.ndarray, *_: object, **__: object) -> tuple[str, bytes]:
        assert snapshot is not caller
        encoded_snapshots.append(snapshot)
        caller.fill(255)
        return "png", b"encoded"

    monkeypatch.setattr(panes_impl, "encode_image_binary", encode)
    handle = server.panes.add_image(caller, pane_id="snapshot-image")
    assert handle._impl.image is encoded_snapshots[-1]
    assert np.count_nonzero(handle.image) == 0

    caller.fill(0)
    handle.image = caller
    assert np.count_nonzero(handle.image) == 0
