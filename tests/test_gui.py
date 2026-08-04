from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import numpy as np
import pytest

import leika
from leika import _messages
from leika.infra import ClientId


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
        markdown = server.gui.add_text(
            None, "**Hello**", editable=False, markdown=True, multiline=True
        )
    second = tabs.add_tab("Second")
    second.remove()
    markdown.value = "## Updated"
    assert markdown.value == "## Updated"


def test_a_multiline_text_input_is_the_height_it_asks_for(
    server: leika.Server,
) -> None:
    """``rows`` is a height, so it is fixed and it is assignable -- and it is a
    height in LINES, which starts at one. Left out it is None, and what that
    comes to is the field's business: three lines to type in, and as tall as
    the text when the text is only being read."""
    note = server.gui.add_text("Note", "", multiline=True)
    assert (note.multiline, note.rows) == (True, None)
    tall = server.gui.add_text("Body", "", multiline=True, rows=12)
    assert tall.rows == 12
    tall.rows = 6
    assert tall.rows == 6

    for bad in (0, -1):
        with pytest.raises(ValueError, match="height in lines"):
            server.gui.add_text("Bad", "", multiline=True, rows=bad)


def test_text_is_read_or_written_and_renders_markdown_when_read(
    server: leika.Server,
) -> None:
    """One element does both. What separates them is ``editable``: written, it
    is an input whose value is what was typed; read, it is that value shown,
    and drawn as markdown if it is asked to be."""
    written = server.gui.add_text("Name", "Ada")
    assert (written.editable, written.markdown) == (True, False)

    read = server.gui.add_text(None, "**Hello**", editable=False, markdown=True)
    assert (read.editable, read.markdown, read.label) == (False, True, None)
    assert read.value == "**Hello**"

    # The client renders the SOURCE: the value with its image paths resolved,
    # which the browser cannot do itself. It follows the value.
    assert read._source == "**Hello**"
    read.value = "## Updated"
    assert read._source == "## Updated"

    # And it follows a change of mind about rendering, so a field turned
    # read-only after the viewer typed in it renders what they typed rather
    # than what was there before.
    written.value = "# Typed"
    written.editable = False
    written.markdown = True
    assert written._source == "# Typed"


def test_option_validation(server: leika.Server) -> None:
    with pytest.raises(ValueError, match="at least one option"):
        server.gui.add_dropdown("Empty", options=[])
    with pytest.raises(ValueError, match="at least one option"):
        server.gui.add_button([], label="Empty")
    with pytest.raises(ValueError, match="one flag per gap"):
        server.gui.add_button(("a", "b", "c"), merge=(True,))
    with pytest.raises(ValueError, match="a single button"):
        server.gui.add_button("Solo", merge=(True,))  # type: ignore[call-overload]
    dropdown = server.gui.add_dropdown("Valid", options=("a", "b"))
    with pytest.raises(ValueError, match="at least one option"):
        dropdown.options = []
    assert dropdown.options == ("a", "b")

    for add in (
        lambda: server.gui.add_dropdown("Duplicate", ("same", "same")),
        lambda: server.gui.add_button(("same", "same")),
        lambda: server.gui.add_toggle(("same", "same")),
    ):
        with pytest.raises(ValueError, match="unique"):
            add()
    with pytest.raises(ValueError, match="strings"):
        server.gui.add_dropdown("Invalid", ("valid", 1))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="strings"):
        server.gui.add_button(("valid", None))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sequence"):
        server.gui.add_dropdown("Invalid", "not a sequence")
    with pytest.raises(ValueError, match="unique"):
        dropdown.options = ("same", "same")
    assert dropdown.options == ("a", "b")
    with pytest.raises(ValueError, match="must be one of"):
        dropdown.value = "missing"


def test_hold_frequency_is_positive_and_finite(server: leika.Server) -> None:
    button = server.gui.add_button("Hold")
    for frequency in (0, -1, float("inf"), float("nan"), True):
        with pytest.raises(ValueError, match="positive, finite"):
            button.on_hold(callback_hz=frequency)  # type: ignore[arg-type]

    callback = button.on_hold(callback_hz=20)(lambda _: None)
    assert callback is not None
    assert button._hold_callback_freqs == (20.0,)


def test_async_callbacks_are_scheduled_on_the_server_loop(server: leika.Server) -> None:
    checkbox = server.gui.add_checkbox("Async", True)
    called = threading.Event()

    @checkbox.on_update
    async def _(_: leika.GuiEvent[Any]) -> None:
        called.set()

    checkbox.value = False
    assert called.wait(2.0)


def test_handle_values_preserve_constructor_invariants(server: leika.Server) -> None:
    entries = server.gui.add_list("Entries", ("one",))
    with pytest.raises(ValueError, match="sequence of strings"):
        entries.value = "one"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="strings"):
        entries.value = ("one", None)  # type: ignore[assignment]

    toggles = server.gui.add_toggle(("A", "B"))
    with pytest.raises(ValueError, match="only one"):
        toggles.value = ("A", "B")
    with pytest.raises(ValueError, match="requires one"):
        toggles.value = ()

    color = server.gui.add_rgb("Color", (1, 2, 3))
    with pytest.raises(ValueError, match="3 color channels"):
        color.value = (1, 2)  # type: ignore[assignment]
    rgba = server.gui.add_rgba("Alpha", (1, 2, 3, 4))
    for handle, invalid in ((color, [1, 2]), (rgba, [1, 2, 3])):
        asyncio.run(
            server.gui._handle_gui_updates(
                ClientId(1),
                _messages.GuiUpdateMessage(handle.id, {"value": invalid}),
            )
        )
    assert color.value == (1, 2, 3)
    assert rgba.value == (1, 2, 3, 4)

    vector = server.gui.add_vector2("Point", (0.0, 0.0), min=(-1.0, -1.0), max=(1.0, 1.0))
    with pytest.raises(ValueError, match="shape"):
        vector.value = (0.0, 0.0, 0.0)  # type: ignore[assignment]
    with pytest.raises(ValueError, match="above max"):
        vector.value = (2.0, 0.0)

    asyncio.run(
        server.gui._handle_gui_updates(
            ClientId(1),
            _messages.GuiUpdateMessage(vector.id, {"value": [2.0, 0.0]}),
        )
    )
    assert vector.value == (0.0, 0.0)

    progress = server.gui.add_progress_bar(50)
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        progress.value = 101

    slider = server.gui.add_slider("Bounded", 0.5, min=0.0, max=1.0, step=0.1)
    with pytest.raises(ValueError, match="within"):
        slider.value = 2.0


def test_form_compatibility_and_submission(server: leika.Server) -> None:
    with server.gui.add_form(label="Profile") as form:
        name = server.gui.add_text("Name", initial_value="Ada")
    # One row holding the form's two ways out, and no row label of its own.
    assert (form.actions.options, form.actions.label) == (("Reset", "Submit"), None)
    submitted: list[str] = []

    @form.on_submit
    def _(_) -> None:
        submitted.append(name.value)

    form.submit_form()
    _wait_for(lambda: submitted == ["Ada"])
    name.value = "Grace"
    form.submit_form()
    _wait_for(lambda: submitted == ["Ada", "Grace"])

    with server.gui.add_form(label="Outer"):
        with pytest.raises(ValueError, match="Nested forms"):
            server.gui.add_form(label="Inner")


def test_form_action_buttons_stay_below_the_fields(server: leika.Server) -> None:
    """The action buttons are created with the form -- before any of the fields
    they act on -- so their order has to be re-stamped or they render above
    them."""
    with server.gui.add_form() as form:
        first = server.gui.add_text("Name", initial_value="Ada")
        last = server.gui.add_checkbox("Subscribe", initial_value=False)
    assert form.actions.order > last.order > first.order

    # Children added through the container's own methods arrive one at a time,
    # each after the buttons were last moved. Every one of them moves them again.
    added = form.add_text("Nickname", initial_value="")
    assert form.actions.order > added.order > last.order


def test_a_mini_form_holds_one_field_and_no_action_buttons(
    server: leika.Server,
) -> None:
    """A mini form is drawn as its field's own row with a send button, so it
    has no buttons of its own -- and nowhere to put a second field."""
    with server.gui.add_mini_form() as mini:
        field = server.gui.add_text("Search", initial_value="")
    assert not hasattr(mini, "actions")

    submitted: list[str] = []
    mini.on_submit(lambda _: submitted.append(field.value))
    field.value = "leika"
    mini.submit_form()
    _wait_for(lambda: submitted == ["leika"])

    # Reset works the same as any form's, on the one field it has.
    mini.reset_form()
    assert field.value == ""

    with pytest.raises(ValueError, match="single field"):
        with server.gui.add_mini_form():
            server.gui.add_text("One", initial_value="")
            server.gui.add_text("Two", initial_value="")

    # The rule is about fields, not rows: a form of one field plus something
    # that holds no value is still a mini form.
    with server.gui.add_mini_form():
        server.gui.add_text(None, "Ask away", editable=False, markdown=True, multiline=True)
        server.gui.add_text("Query", initial_value="")


def test_form_reset_restores_what_the_fields_were_declared_with(
    server: leika.Server,
) -> None:
    """Reset is the values Python declared, not the ones the browser last sent
    -- and it reaches fields nested in a folder inside the form."""
    with server.gui.add_form(label="Profile") as form:
        name = server.gui.add_text("Name", initial_value="Ada")
        with server.gui.add_folder("More"):
            age = server.gui.add_number("Age", initial_value=36)
            tags = server.gui.add_toggle(("A", "B"), label="Tags", multiple=True)
    late = form.add_text("Nickname", initial_value="Countess")

    name.value = "Grace"
    age.value = 45
    tags.value = ("A", "B")
    late.value = "Amazing"

    form.reset_form()
    assert (name.value, age.value, tags.value, late.value) == (
        "Ada",
        36,
        (),
        "Countess",
    )

    # A field removed since is skipped rather than resurrected.
    late.remove()
    form.reset_form()
    assert name.value == "Ada"


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


def test_theme_defaults_to_following_the_browser_color_scheme(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An app has to ask for a scheme; otherwise the viewer's OS decides.

    The wire value matters as much as the default: ``"auto"`` is what tells the
    client to read ``prefers-color-scheme`` rather than pin a scheme, so a
    bool sent in its place would silently override every viewer.
    """
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", sent.append)

    server.gui.configure_theme()
    server.gui.configure_theme(dark_mode=True)
    server.gui.configure_theme(dark_mode=False)

    assert [message.dark_mode for message in sent] == ["auto", True, False]


def test_theme_rejects_unknown_wire_values(server: leika.Server) -> None:
    with pytest.raises(ValueError, match="control_layout"):
        server.gui.configure_theme(control_layout="wide")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dark_mode"):
        server.gui.configure_theme(dark_mode=1)  # type: ignore[arg-type]


def test_removed_visual_customization_arguments_are_rejected(
    server: leika.Server,
) -> None:
    server.gui.configure_theme(
        control_layout="floating",
        dark_mode=True,
    )
    with pytest.raises(TypeError):
        server.gui.configure_theme(show_share_button=True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.configure_theme(control_width="large")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.configure_theme(brand_color=(80, 150, 255))  # type: ignore[call-arg]
    # Both buttons took `color` back, but as a role rather than a palette: the
    # two names they accept are all they accept, and an actual color still
    # fails. The other three below never regained it.
    for add_a_button in (server.gui.add_button, server.gui.add_upload_button):
        add_a_button("Run", color="primary")
        add_a_button("Run", color="secondary")
        with pytest.raises(ValueError):
            add_a_button("Run", color="blue")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        server.gui.add_progress_bar(50.0, color="blue")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        server.gui.add_notification("Done", color="blue")  # type: ignore[call-arg]


def test_a_row_can_take_one_role_per_button_or_toggle(server: leika.Server) -> None:
    """A row usually wants one weight throughout, and sometimes wants its accent
    behind one action only. Both are ``color=``; the wire always carries one
    role per element."""
    row = server.gui.add_button(("Reset", "Submit"), color=("secondary", "primary"))
    assert row.color == ("secondary", "primary")
    # A single role still answers for the whole row, and reads back per button.
    plain = server.gui.add_toggle(("A", "B", "C"), color="secondary")
    assert plain.color == ("secondary", "secondary", "secondary")

    # Live, with the same latitude as the constructor.
    plain.color = ("primary", "secondary", "primary")
    assert plain.color == ("primary", "secondary", "primary")
    plain.color = "primary"
    assert plain.color == ("primary", "primary", "primary")

    with pytest.raises(ValueError, match="one role per button"):
        server.gui.add_button(("One", "Two"), color=("primary",))
    with pytest.raises(ValueError, match="one role per toggle"):
        server.gui.add_toggle(("One", "Two"), color=("primary", "primary", "primary"))
    with pytest.raises(ValueError, match="must be 'primary' or 'secondary'"):
        server.gui.add_button(("One", "Two"), color=("primary", "blue"))  # type: ignore[arg-type]
    # A single button is one button: the sequence form has nothing to spread.
    with pytest.raises(ValueError, match="a single button is one button"):
        server.gui.add_button("Solo", color=("primary",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="a single toggle is one toggle"):
        server.gui.add_toggle("Solo", color=("primary",))  # type: ignore[arg-type]


def test_gui_images_always_span_the_panel(server: leika.Server) -> None:
    """A GUI image has one width -- the panel's -- so there is no knob for it."""
    frame = np.zeros((4, 6, 3), dtype=np.uint8)

    handle = server.gui.add_image(frame, label="Preview")
    assert not hasattr(handle, "fit_width")
    with pytest.raises(TypeError):
        server.gui.add_image(frame, fit_width=False)  # type: ignore[call-arg]


def test_gui_image_state_is_transactional_and_private(server: leika.Server) -> None:
    frame = np.zeros((2, 3, 3), dtype=np.uint8)
    image = server.gui.add_image(frame, format="png")

    frame[:] = 255
    assert np.all(image.image == 0)
    returned = image.image
    returned[:] = 255
    assert np.all(image.image == 0)

    old_data = image._data
    with pytest.raises(ValueError, match="format must be"):
        image.format = "gif"  # type: ignore[assignment]
    assert image.format == "png"
    assert image._data == old_data


def test_removed_containers_reject_new_actions(server: leika.Server) -> None:
    tabs = server.gui.add_tab_group()
    tab = tabs.add_tab("One")
    tab.remove()
    with pytest.raises(RuntimeError, match="removed tab"):
        tab.icon = leika.Icon.PLAY

    tabs.remove()
    with pytest.raises(RuntimeError, match="removed GuiTabGroupHandle"):
        tabs.add_tab("Too late")

    form = server.gui.add_mini_form()
    form.remove()
    with pytest.raises(RuntimeError, match="removed GuiFormHandle"):
        form.submit_form()


def test_numeric_constructors_reject_invalid_ranges(server: leika.Server) -> None:
    fixed = server.gui.add_slider("Fixed", 1.0, min=1.0, max=1.0, step=0.1)
    assert fixed.step == 0.0
    with pytest.raises(ValueError, match="at least min"):
        server.gui.add_slider("Backwards", 1.0, min=2.0, max=1.0, step=0.1)
    with pytest.raises(ValueError, match="greater than zero"):
        server.gui.add_number("Bad step", 1.0, step=0.0)
    with pytest.raises(ValueError, match="ascending"):
        server.gui.add_multi_slider("Order", (0.8, 0.2), min=0.0, max=1.0, step=0.1)
    with pytest.raises(ValueError, match="finite"):
        server.gui.add_progress_bar(float("nan"))

    preview = server.gui.add_preview_button("Empty", b"", filename="empty.txt", max_bytes=0)
    assert preview._max_bytes == 0


def test_uploads_are_isolated_and_validated_per_client(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = server.gui.add_upload_button("Upload")
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", sent.append)

    def start(client_id: int, *, transfer_uuid: str = "same", parts: int = 2) -> None:
        server.gui._handle_file_transfer_start(
            ClientId(client_id),
            _messages.FileTransferStartUpload(
                source_component_uuid=upload.id,
                transfer_uuid=transfer_uuid,
                filename=f"client-{client_id}.bin",
                mime_type="application/octet-stream",
                part_count=parts,
                size_bytes=parts,
            ),
        )

    start(1)
    start(2)
    assert len(server.gui._current_file_upload_states) == 2

    # A duplicate part neither double-counts bytes nor completes early.
    first = _messages.FileTransferPart(upload.id, "same", 0, b"a")
    server.gui._handle_file_transfer_part(ClientId(1), first)
    server.gui._handle_file_transfer_part(ClientId(1), first)
    assert upload.value.content == b""
    server.gui._handle_file_transfer_part(
        ClientId(1), _messages.FileTransferPart(upload.id, "same", 1, b"b")
    )
    assert upload.value.content == b"ab"
    assert upload.value.name == "client-1.bin"
    assert len(server.gui._current_file_upload_states) == 1

    # The same transfer UUID from another client remains independent.
    server.gui._handle_file_transfer_part(
        ClientId(2), _messages.FileTransferPart(upload.id, "same", 0, b"c")
    )
    server.gui._handle_file_transfer_part(
        ClientId(2), _messages.FileTransferPart(upload.id, "same", 1, b"d")
    )
    assert upload.value.content == b"cd"
    assert server.gui._current_file_upload_states == {}
    assert (
        len([message for message in sent if isinstance(message, _messages.FileTransferPartAck)])
        == 4
    )

    # Removing a button releases any incomplete transfer.
    start(1, transfer_uuid="pending", parts=1)
    upload.remove()
    assert server.gui._current_file_upload_states == {}


def test_malformed_upload_messages_are_dropped(server: leika.Server) -> None:
    upload = server.gui.add_upload_button("Upload")
    server.gui._handle_file_transfer_start(
        ClientId(1),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid="invalid",
            filename="bad.bin",
            mime_type="application/octet-stream",
            part_count=0,
            size_bytes=1,
        ),
    )
    assert server.gui._current_file_upload_states == {}

    server.gui._handle_file_transfer_start(
        ClientId(1),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid="oversize",
            filename="bad.bin",
            mime_type="application/octet-stream",
            part_count=1,
            size_bytes=1,
        ),
    )
    server.gui._handle_file_transfer_part(
        ClientId(1), _messages.FileTransferPart(upload.id, "oversize", 0, b"too long")
    )
    assert server.gui._current_file_upload_states == {}
    assert upload.value.content == b""


def test_upload_part_and_button_removal_are_serialized(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = server.gui.add_upload_button("Upload")
    server.gui._handle_file_transfer_start(
        ClientId(1),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid="race",
            filename="race.bin",
            mime_type="application/octet-stream",
            part_count=2,
            size_bytes=2,
        ),
    )

    ack_started = threading.Event()
    release_ack = threading.Event()

    def queue_message(message: Any) -> None:
        if isinstance(message, _messages.FileTransferPartAck):
            ack_started.set()
            assert release_ack.wait(2.0)

    monkeypatch.setattr(server.gui._websock_interface, "queue_message", queue_message)
    part_thread = threading.Thread(
        target=server.gui._handle_file_transfer_part,
        args=(ClientId(1), _messages.FileTransferPart(upload.id, "race", 0, b"a")),
    )
    part_thread.start()
    assert ack_started.wait(2.0)

    removed = threading.Event()

    def remove() -> None:
        upload.remove()
        removed.set()

    remove_thread = threading.Thread(target=remove)
    remove_thread.start()
    assert not removed.wait(0.1)
    release_ack.set()
    part_thread.join(timeout=2.0)
    remove_thread.join(timeout=2.0)

    assert not part_thread.is_alive()
    assert not remove_thread.is_alive()
    assert removed.is_set()
    assert server.gui._current_file_upload_states == {}


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

    assert opted_out == {"add_notification", "add_command", "add_modal"}
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


def test_toggle_initial_values_and_modes(server: leika.Server) -> None:
    """A toggle is a bool; a row of them is the tuple of options that are on."""
    single = server.gui.add_toggle("Bookmark", initial_value=True)
    assert single.value is True

    row = server.gui.add_toggle(("Bold", "Italic"), initial_value="Italic")
    assert row.value == ("Italic",)
    # One at a time is required by default, like a radio group, so a row left
    # without an initial value starts on its first option rather than empty.
    assert server.gui.add_toggle(("Bold", "Italic")).value == ("Bold",)
    assert server.gui.add_toggle(("Bold", "Italic"), required=False).value == ()
    # A tuple in both modes, and always in declaration order rather than the
    # order the caller named them in.
    many = server.gui.add_toggle(
        ("Bold", "Italic", "Under"), multiple=True, initial_value=("Under", "Bold")
    )
    assert many.value == ("Bold", "Under")
    # `multiple` is the other default pair, like checkboxes: optional, so empty.
    assert server.gui.add_toggle(("Grid", "Axes"), multiple=True).value == ()
    assert server.gui.add_toggle(("Grid", "Axes"), multiple=True, required=True).value == ("Grid",)

    with pytest.raises(ValueError, match="not among the options"):
        server.gui.add_toggle(("Bold", "Italic"), initial_value="Underline")
    with pytest.raises(ValueError, match="one at a time"):
        server.gui.add_toggle(("Bold", "Italic"), initial_value=("Bold", "Italic"))
    with pytest.raises(ValueError, match="an option or a sequence"):
        server.gui.add_toggle(("Bold", "Italic"), initial_value=True)  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="is a bool"):
        server.gui.add_toggle("Bookmark", initial_value="on")  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="cannot start empty"):
        server.gui.add_toggle(("Bold", "Italic"), initial_value=())
    with pytest.raises(ValueError, match="how many options in a ROW"):
        server.gui.add_toggle("Bookmark", multiple=True)  # type: ignore[call-overload]
    with pytest.raises(ValueError, match="at least one option"):
        server.gui.add_toggle([])


def test_a_list_holds_text_entries_and_can_be_frozen(server: leika.Server) -> None:
    """The value is the entries, in order: editing one, adding, removing, and
    reordering all read and write the same tuple."""
    entries = server.gui.add_list("Tags", ("alpha", "beta"))
    assert entries.value == ("alpha", "beta")
    assert entries.frozen is False

    seen: list[tuple[str, ...]] = []
    entries.on_update(lambda event: seen.append(event.target.value))
    entries.value = ("alpha", "beta", "gamma")  # Appended.
    entries.value = ("gamma", "alpha")  # Removed one and reordered the rest.
    _wait_for(lambda: seen == [("alpha", "beta", "gamma"), ("gamma", "alpha")])

    # An empty list is a list with nothing in it, and starts that way by
    # default -- the viewer's first Add is what fills it.
    assert server.gui.add_list().value == ()

    # Frozen fixes the length and the order, and says so on the wire; the
    # entries themselves are still editable, which `disabled` is for.
    fixed = server.gui.add_list("Fixed", ("read", "only"), frozen=True)
    assert fixed.frozen is True
    fixed.frozen = False
    assert fixed.frozen is False

    # Text entries, so anything else is a mistake worth naming rather than a
    # str() applied behind the caller's back.
    with pytest.raises(ValueError, match="sequence of strings"):
        server.gui.add_list("Bad", ("fine", 3))  # type: ignore[arg-type]


def test_a_checklist_pairs_each_entry_with_a_box(server: leika.Server) -> None:
    """The value is (text, checked) per item, so it reads back the way it is
    written -- and a bare string is an item nobody has ticked yet."""
    items = server.gui.add_checklist("Preflight", ["Fuel", ("Doors", True), "Lights"])
    assert items.value == (("Fuel", False), ("Doors", True), ("Lights", False))
    assert [text for text, _ in items.value] == ["Fuel", "Doors", "Lights"]
    assert items.checked == ("Doors",)
    assert items.frozen is False

    # Assigning takes the same latitude the constructor does, which is what
    # lets a bare string be appended to a list of pairs.
    items.value += ("Chocks",)
    assert items.value[-1] == ("Chocks", False)

    seen: list[tuple[tuple[str, bool], ...]] = []
    items.on_update(lambda event: seen.append(event.target.value))
    items.value = [("Fuel", True), ("Doors", True)]
    _wait_for(lambda: seen == [(("Fuel", True), ("Doors", True))])
    assert items.checked == ("Fuel", "Doors")

    # An empty checklist is one with nothing on it yet, and starts that way.
    assert server.gui.add_checklist().value == ()

    # Frozen fixes the items -- their words as well as their number and their
    # order, since what a checklist is asked for is the ticks.
    fixed = server.gui.add_checklist("Fixed", ("read", "only"), frozen=True)
    assert fixed.frozen is True
    fixed.frozen = False
    assert fixed.frozen is False

    # Pairs, so anything that is not one is a mistake worth naming.
    with pytest.raises(ValueError, match="strings or"):
        server.gui.add_checklist("Bad", [("fine", True), 3])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="item's text is a string"):
        server.gui.add_checklist("Bad", [(3, True)])  # type: ignore[list-item]
