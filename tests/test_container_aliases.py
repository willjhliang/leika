from __future__ import annotations

import numpy as np

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
