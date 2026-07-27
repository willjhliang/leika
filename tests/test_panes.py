from __future__ import annotations

from typing import Any, cast

import numpy as np
import pytest

import leika


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
        image_format="png",
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


def test_only_v1_pane_types_are_exposed(server: leika.Server) -> None:
    for name in ("add_matplotlib", "add_url", "add_scene"):
        assert not hasattr(server.panes, name)
