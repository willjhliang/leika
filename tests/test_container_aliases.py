from __future__ import annotations

import numpy as np
import pytest

import leika

# Exercise direct container creation for each supported control.
_SAMPLE_CALLS: dict[str, tuple[tuple, dict]] = {
    "add_button": (("Button",), {}),
    "add_checkbox": (("Checkbox", True), {}),
    "add_checklist": (("Checklist", ("one", ("two", True))), {}),
    "add_radio_list": (("Radio list", ("one", ("two", True))), {}),
    "add_divider": ((), {}),
    "add_video_controls": (("Playback",), {"sync_group": "episode"}),
    "add_download_button": (("Download", b"contents"), {"filename": "file.txt"}),
    "add_dropdown": (("Dropdown", ("a", "b")), {}),
    "add_folder": (("Folder",), {}),
    "add_form": ((), {}),
    "add_html": (("<b>html</b>",), {}),
    "add_image": ((np.zeros((2, 3, 3), dtype=np.uint8),), {}),
    "add_list": (("List", ("one", "two")), {}),
    "add_mini_form": ((), {}),
    "add_multi_slider": (("Multi", (0.2, 0.8)), {"min": 0.0, "max": 1.0, "step": 0.1}),
    "add_number": (("Number", 1.0), {}),
    "add_plotly": ((), {}),  # Filled in below; needs the optional dependency.
    "add_popup": (("Popup",), {}),
    "add_preview_button": (("Preview", b"contents"), {"filename": "file.txt"}),
    "add_progress_bar": ((50.0,), {}),
    "add_rgb": (("Rgb", (10, 20, 30)), {}),
    "add_rgba": (("Rgba", (10, 20, 30, 40)), {}),
    "add_slider": (("Slider", 0.5), {"min": 0.0, "max": 1.0, "step": 0.1}),
    "add_tab_group": ((), {}),
    "add_text": (("Text", "value"), {}),
    "add_toggle": (("Toggle",), {}),
    "add_upload_button": (("Upload",), {}),
    "add_vector2": (("Vector2", (0.0, 0.0)), {}),
    "add_vector3": (("Vector3", (0.0, 0.0, 0.0)), {}),
}


def test_direct_container_methods_publish_children_in_the_folder(server: leika.Server) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    calls = {**_SAMPLE_CALLS, "add_plotly": ((go.Figure(),), {})}

    folder = server.gui.add_folder("Everything")
    for name, (args, kwargs) in sorted(calls.items()):
        handle = getattr(folder, name)(*args, **kwargs)
        assert any(
            getattr(message, "uuid", None) == handle.id
            and getattr(message, "container_uuid", None) == folder.id
            for message in server._websock_server.get_message_buffer().message_from_id.values()
        ), name
