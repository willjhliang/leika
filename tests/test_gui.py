from __future__ import annotations

import time
from typing import Any

import numpy as np
import pytest

import leika


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def test_controls_containers_and_callbacks(server: leika.Server) -> None:
    seen: list[tuple[str, bool]] = []
    with server.gui.add_folder("Inputs"):
        enabled = server.gui.add_checkbox("Enabled", initial_value=True)
        mode = server.gui.add_dropdown("Mode", options=("fast", "accurate"))
        slider = server.gui.add_slider("Gain", min=0.0, max=2.0, step=0.01, initial_value=1.0)
        multi = server.gui.add_multi_slider(
            "Range", min=0.0, max=1.0, step=0.05, initial_value=(0.2, 0.8)
        )

    @enabled.on_update
    def _(event: leika.GuiEvent[Any]) -> None:
        seen.append((event.target.label, event.value))

    enabled.value = False
    _wait_for(lambda: bool(seen))
    assert seen == [("Enabled", False)]
    assert mode.value == "fast"
    assert slider.value == 1.0
    assert multi.value == (0.2, 0.8)

    tabs = server.gui.add_tab_group()
    first = tabs.add_tab("First")
    with first:
        markdown = server.gui.add_markdown("**Hello**")
    second = tabs.add_tab("Second")
    second.remove()
    markdown.content = "## Updated"
    assert markdown.content == "## Updated"


def test_option_validation(server: leika.Server) -> None:
    with pytest.raises(ValueError, match="at least one option"):
        server.gui.add_dropdown("Empty", options=[])
    with pytest.raises(ValueError, match="at least one option"):
        server.gui.add_button_group("Empty", options=[])
    dropdown = server.gui.add_dropdown("Valid", options=("a", "b"))
    with pytest.raises(ValueError, match="at least one option"):
        dropdown.options = []
    assert dropdown.options == ("a", "b")


def test_form_compatibility_and_submission(server: leika.Server) -> None:
    with server.gui.add_form(submit_label="Save", label="Profile") as form:
        name = server.gui.add_text("Name", initial_value="Ada")
    assert form.submit.label == "Save"
    submitted: list[str] = []

    @form.on_submit
    def _(_) -> None:
        submitted.append(name.value)

    form.submit_form()
    _wait_for(lambda: submitted == ["Ada"])
    name.value = "Grace"
    form.submit_form()
    _wait_for(lambda: submitted == ["Ada", "Grace"])

    with server.gui.add_form(submit_label="Outer"):
        with pytest.raises(ValueError, match="Nested forms"):
            server.gui.add_form(submit_label="Inner")


def test_commands_notifications_and_modal(server: leika.Server) -> None:
    triggered: list[bool] = []
    command = server.gui.add_command(
        "Run",
        lambda *_: triggered.append(True),
        description="Run the action",
        hotkey="R",
        icon=leika.Icon.PLAY,
    )
    assert command.label == "Run"
    assert command.description == "Run the action"
    command.label = "Run now"
    command.disabled = True
    assert command.label == "Run now"
    assert command.disabled is True

    notification = server.gui.add_notification(
        "Working", "Please wait", loading=True, auto_close_seconds=None
    )
    notification.body = "Done"
    notification.loading = False
    notification.auto_close_seconds = 1.0
    notification.remove()

    with server.gui.add_modal("Details") as modal:
        server.gui.add_html("<strong>Content</strong>")
    modal.close()
    command.remove()


def test_removed_visual_customization_arguments_are_rejected(
    server: leika.Server,
) -> None:
    server.gui.configure_theme(
        control_layout="floating",
        control_width="large",
        dark_mode=True,
    )
    with pytest.raises(TypeError):
        server.gui.configure_theme(show_share_button=True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.configure_theme(brand_color=(80, 150, 255))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.add_button("Run", color="blue")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.add_upload_button("Upload", color="blue")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.add_progress_bar(50.0, color="blue")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.add_notification("Done", color="blue")  # type: ignore[call-arg]


def test_containers_mirror_every_container_scoped_add_method() -> None:
    """``folder.add_thing(...)`` exists because ``GuiApi.add_thing`` does.

    The mirror is derived, so this guards the two ways it can go wrong: an
    element that never reaches containers, and a non-container ``add_*`` (a
    notification, a command) that gets mirrored anyway and promises a
    containment it cannot honor.
    """
    from leika._gui_api import GuiApi
    from leika._gui_handles import GuiContainer

    api_methods = {name for name in dir(GuiApi) if name.startswith("add_")}
    opted_out = {
        name
        for name in api_methods
        if getattr(getattr(GuiApi, name), "_leika_container_scoped", True) is False
    }
    mirrored = {name for name in dir(GuiContainer) if name.startswith("add_")}

    assert opted_out == {"add_notification", "add_command"}
    assert mirrored == api_methods - opted_out


def test_containers_nest_and_unwind_to_where_they_started(server: leika.Server) -> None:
    """Entering the same container twice must not lose the outer target.

    Each container used to remember a single restore ID, so a re-entered
    ``with`` block overwrote it and the outer exit had nothing to go back to.
    """
    outer = server.gui.add_folder("Outer")
    with outer:
        inner = server.gui.add_folder("Inner")
        with outer:
            with inner:
                deep = server.gui.add_text("Deep", initial_value="")
            shallow = server.gui.add_text("Shallow", initial_value="")
        # Back inside `outer`, not stranded in `inner`.
        sibling = server.gui.add_text("Sibling", initial_value="")
    root = server.gui.add_text("Root", initial_value="")

    assert deep._impl.parent_container_id == inner.id
    assert shallow._impl.parent_container_id == outer.id
    assert sibling._impl.parent_container_id == outer.id
    assert root._impl.parent_container_id == "root"
    # Nothing left behind for this thread once every block has unwound.
    assert server.gui._container_stack_from_thread_id == {}


def test_media_elements_are_created_from_their_content(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No create-then-backfill: an image or plot arrives complete.

    The create message used to carry a placeholder that a property assignment
    immediately replaced, so every element cost a second message -- for images,
    a second copy of the encoded bytes.
    """
    plotly = pytest.importorskip("plotly.graph_objects")
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", sent.append)

    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    server.gui.add_image(frame, label="Frame")
    image_messages = [m for m in sent if type(m).__name__.startswith("GuiImage")]
    assert len(image_messages) == 1
    assert image_messages[0].props._data
    assert image_messages[0].props._format == "jpeg"

    sent.clear()
    server.gui.add_plotly(plotly.Figure(), aspect=2.0)
    plotly_messages = [m for m in sent if type(m).__name__.startswith("GuiPlotly")]
    assert len(plotly_messages) == 1
    assert plotly_messages[0].props.aspect == 2.0
    assert plotly_messages[0].props._plotly_json_str.startswith("{")
