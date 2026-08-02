from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

import leika
from leika._panes import _viser_embed_target, _wandb_embed_url


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
    )
    assert pane.pane_id == "camera"
    assert pane.title == "Camera"
    assert pane.visible is True
    assert pane.fit == "fill"
    np.testing.assert_array_equal(pane.image, original)

    next_frame = np.full((4, 6, 3), 127, dtype=np.uint8)
    pane.title = "Updated"
    pane.visible = False
    pane.fit = "fit"
    pane.update(next_frame)
    assert pane.title == "Updated"
    assert pane.visible is False
    assert pane.fit == "fit"
    np.testing.assert_array_equal(pane.image, next_frame)

    pane.remove()
    with pytest.raises(RuntimeError, match="removed"):
        pane.update(original)
    replacement = server.panes.add_image(original, pane_id="camera")
    assert replacement.pane_id == "camera"

    with pytest.raises(ValueError):
        server.panes.add_image(np.zeros((3, 3), dtype=np.uint8))
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
    with pytest.raises(ValueError):
        server.panes.add_image(frame, relative_to="missing")


@pytest.mark.plotly
def test_plotly_lifecycle(server: leika.Server) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    figure = go.Figure(go.Scatter(y=[1, 2, 1]))
    pane = server.panes.add_plotly(
        figure,
        pane_id="metrics",
        title="Metrics",
        config={"displayModeBar": False},
    )
    assert pane.pane_id == "metrics"
    assert pane.figure is figure
    replacement = go.Figure(go.Bar(y=[3, 1]))
    pane.update(replacement)
    assert pane.figure is replacement
    pane.visible = False
    assert pane.visible is False
    pane.remove()
    with pytest.raises(RuntimeError, match="removed"):
        pane.figure = go.Figure()


@pytest.mark.parametrize(
    ("target", "kwargs", "expected"),
    [
        # Bare projects are rewritten to the workspace, the one project view
        # W&B serves without frame-blocking headers.
        ("acme/proj", {}, "https://wandb.ai/acme/proj/workspace?jupyter=true"),
        ("/acme/proj/", {}, "https://wandb.ai/acme/proj/workspace?jupyter=true"),
        (
            "https://wandb.ai/acme/proj",
            {},
            "https://wandb.ai/acme/proj/workspace?jupyter=true",
        ),
        # Deeper routes pass through untouched.
        (
            "acme/proj/runs/abc123",
            {},
            "https://wandb.ai/acme/proj/runs/abc123?jupyter=true",
        ),
        (
            "acme/proj/sweeps/s1",
            {},
            "https://wandb.ai/acme/proj/sweeps/s1?jupyter=true",
        ),
        (
            "https://wandb.ai/acme/proj/groups/g1/workspace",
            {},
            "https://wandb.ai/acme/proj/groups/g1/workspace?jupyter=true",
        ),
        # View-only report links keep their access token, and an existing
        # jupyter parameter is not duplicated.
        (
            "https://wandb.ai/acme/proj/reports/My-Report--VmlldzoX?accessToken=tok",
            {},
            "https://wandb.ai/acme/proj/reports/My-Report--VmlldzoX?accessToken=tok&jupyter=true",
        ),
        (
            "acme/proj/runs/abc?jupyter=false",
            {},
            "https://wandb.ai/acme/proj/runs/abc?jupyter=false",
        ),
        # Panel selection opens W&B's fullscreen panel viewer.
        (
            "acme/proj",
            {"panel": "val loss", "panel_section": "eval"},
            "https://wandb.ai/acme/proj/workspace"
            "?panelDisplayName=val+loss&panelSectionName=eval&jupyter=true",
        ),
        # Self-hosted instances via base_url, as a path or a full URL.
        (
            "acme/proj",
            {"base_url": "http://localhost:8080/"},
            "http://localhost:8080/acme/proj/workspace?jupyter=true",
        ),
        (
            "http://localhost:8080/acme/proj/runs/r1",
            {"base_url": "http://localhost:8080"},
            "http://localhost:8080/acme/proj/runs/r1?jupyter=true",
        ),
    ],
)
def test_wandb_url_normalization(target: str, kwargs: dict[str, Any], expected: str) -> None:
    assert _wandb_embed_url(target, **kwargs) == expected


def test_wandb_url_accepts_objects_with_a_url_attribute() -> None:
    run = SimpleNamespace(url="https://wandb.ai/acme/proj/runs/r1")
    assert _wandb_embed_url(run) == "https://wandb.ai/acme/proj/runs/r1?jupyter=true"
    with pytest.raises(TypeError, match="url attribute"):
        _wandb_embed_url(object())
    with pytest.raises(TypeError, match="url attribute"):
        _wandb_embed_url(SimpleNamespace(url=""))


def test_wandb_url_rejects_malformed_targets() -> None:
    with pytest.raises(ValueError, match="missing a project"):
        _wandb_embed_url("acme")
    with pytest.raises(ValueError, match="base_url"):
        _wandb_embed_url("https://evil.example.com/acme/proj")
    with pytest.raises(ValueError, match="scheme"):
        _wandb_embed_url("ftp://wandb.ai/acme/proj")
    with pytest.raises(ValueError, match="base_url must be"):
        _wandb_embed_url("acme/proj", base_url="localhost:8080")
    with pytest.raises(ValueError, match="panel"):
        _wandb_embed_url("acme/proj/runs/r1", panel="loss")


def test_wandb_lifecycle(server: leika.Server) -> None:
    pane = server.panes.add_wandb(
        "acme/proj",
        base_url="http://localhost:9090",
        pane_id="wandb",
        title="Training",
    )
    assert pane.pane_id == "wandb"
    assert pane.title == "Training"
    assert pane.url == "http://localhost:9090/acme/proj/workspace?jupyter=true"

    # Re-pointing keeps the creation-time base URL.
    pane.url = "acme/proj/runs/abc"
    assert pane.url == "http://localhost:9090/acme/proj/runs/abc?jupyter=true"
    pane.update("acme/proj", panel="loss")
    assert (
        pane.url == "http://localhost:9090/acme/proj/workspace?panelDisplayName=loss&jupyter=true"
    )

    pane.visible = False
    assert pane.visible is False
    pane.remove()
    with pytest.raises(RuntimeError, match="removed"):
        pane.url = "acme/proj"

    with pytest.raises(ValueError, match="missing a project"):
        server.panes.add_wandb("acme")

    row = server.panes.add_row()
    first = row.add_wandb("acme/proj", pane_id="row-wandb")
    grid = server.panes.add_grid(columns=1, relative_to=first.pane_id)
    second = grid.add_wandb("acme/proj/runs/r2", pane_id="grid-wandb")
    assert [item.pane_id for item in (first, second)] == ["row-wandb", "grid-wandb"]
    with pytest.raises(ValueError):
        server.panes.add_wandb("acme/proj", pane_id="row-wandb")


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


def test_viser_lifecycle(server: leika.Server) -> None:
    fake = SimpleNamespace(get_port=lambda: 8123, get_host=lambda: "0.0.0.0")
    pane = server.panes.add_viser(fake, pane_id="viser", title="Scene")
    assert pane.pane_id == "viser"
    assert pane.title == "Scene"
    assert pane.url is None
    assert pane.port == 8123

    pane.update("http://viser.example.com:9000")
    assert pane.url == "http://viser.example.com:9000"
    assert pane.port is None
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
    for name in ("add_matplotlib", "add_url", "add_scene"):
        assert not hasattr(server.panes, name)
