from __future__ import annotations

import numpy as np
import pytest

import leika


def test_direct_container_syntax_and_exported_aliases(server: leika.Server) -> None:
    for name in ("GuiContainer", "GuiTabGroup", "PaneHandle", "PaneId"):
        assert hasattr(leika, name), name

    folder: leika.GuiContainer = server.gui.add_folder("Direct folder")
    slider = folder.add_slider("Direct slider", min=0.0, max=1.0, step=0.01, initial_value=0.5)
    assert slider.value == 0.5

    tabs: leika.GuiTabGroup = server.gui.add_tab_group()
    tab = tabs.add_tab("Direct tab")
    html = tab.add_html("<strong>Direct child</strong>")
    assert html.content == "<strong>Direct child</strong>"

    pane_id = leika.PaneId("direct-pane")
    pane: leika.PaneHandle = server.panes.add_image(
        np.zeros((2, 2, 3), dtype=np.uint8), pane_id=pane_id
    )
    assert pane.pane_id == pane_id


# One valid call per container-scoped `GuiApi.add_*`. Kept exhaustive on
# purpose: `test_containers_mirror_every_container_scoped_add_method` proves
# the mirror covers every element, and this proves each mirrored method
# actually places its element -- including the ones no example or other test
# happens to use.
_SAMPLE_CALLS: dict[str, tuple[tuple, dict]] = {
    "add_button": (("Button",), {}),
    "add_button_group": (("Group", ("a", "b")), {}),
    "add_checkbox": (("Checkbox", True), {}),
    "add_divider": ((), {}),
    "add_dropdown": (("Dropdown", ("a", "b")), {}),
    "add_folder": (("Folder",), {}),
    "add_form": ((), {}),
    "add_html": (("<b>html</b>",), {}),
    "add_image": ((np.zeros((2, 3, 3), dtype=np.uint8),), {}),
    "add_markdown": (("**markdown**",), {}),
    "add_modal": (("Modal",), {}),
    "add_multi_slider": (("Multi", 0.0, 1.0, 0.1), {"initial_value": (0.2, 0.8)}),
    "add_number": (("Number", 1.0), {}),
    "add_plotly": ((), {}),  # Filled in below; needs the optional dependency.
    "add_progress_bar": ((50.0,), {}),
    "add_rgb": (("Rgb", (10, 20, 30)), {}),
    "add_rgba": (("Rgba", (10, 20, 30, 40)), {}),
    "add_slider": (("Slider", 0.0, 1.0, 0.1, 0.5), {}),
    "add_tab_group": ((), {}),
    "add_text": (("Text", "value"), {}),
    "add_upload_button": (("Upload",), {}),
    "add_uplot": (
        (
            (np.linspace(0.0, 1.0, 4), np.zeros(4)),
            ({}, {"label": "y"}),
        ),
        {},
    ),
    "add_vector2": (("Vector2", (0.0, 0.0)), {}),
    "add_vector3": (("Vector3", (0.0, 0.0, 0.0)), {}),
}


def test_every_mirrored_add_method_places_its_element(server: leika.Server) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    calls = {**_SAMPLE_CALLS, "add_plotly": ((go.Figure(),), {})}

    mirrored = {name for name in dir(leika.GuiContainer) if name.startswith("add_")}
    assert calls.keys() == mirrored, "sample calls have drifted from the mirrored methods"

    folder = server.gui.add_folder("Everything")
    for name, (args, kwargs) in sorted(calls.items()):
        handle = getattr(folder, name)(*args, **kwargs)
        assert handle is not None, name
        # Modals are their own container rather than a child of one, so they
        # are the one element whose parent is not the folder.
        if name != "add_modal":
            assert folder._children.get(handle.id) is handle, name
