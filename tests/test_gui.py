from __future__ import annotations

import asyncio
import gc
import json
import threading
import time
import weakref
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import leika
import leika._notification_handle as notification_impl
from leika import _messages
from leika._server import ClientHandle
from leika._transport._websocket import ClientId


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _open_recorder(output: list[Any]):
    """Return a queue stub that records and reports an open connection."""

    def queue(message: Any) -> bool:
        output.append(message)
        return True

    return queue


def _queued(server: leika.Server) -> tuple[_messages.Message, ...]:
    """The messages the server retains for browsers that connect later."""
    return tuple(server._websock_server.get_message_buffer().message_from_id.values())


def _client_connection_stub(
    server: leika.Server,
    client_id: ClientId,
    queued: list[_messages.Message] | None = None,
) -> SimpleNamespace:
    """Minimal connection with the per-connection loop `ClientHandle` requires."""
    queued = [] if queued is None else queued
    message_buffer = SimpleNamespace(event_loop=server._event_loop)
    return SimpleNamespace(
        client_id=client_id,
        register_handler=lambda *_: None,
        delivery_scope=lambda: None,
        queue_message=queued.append,
        queue_message_or_raise=queued.append,
        queue_messages_or_raise=queued.extend,
        get_message_buffer=lambda: message_buffer,
    )


def _browser_update(server: leika.Server, handle: Any, value: object, client: int = 1) -> None:
    asyncio.run(
        server.gui._handle_gui_updates(
            ClientId(client), _messages.GuiUpdateMessage(handle.id, {"value": value})
        )
    )


def _start_upload(
    server: leika.Server, client_id: int, upload: Any, transfer_uuid: str, size: int
) -> Any:
    return server.gui._handle_file_transfer_start(
        ClientId(client_id),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid=transfer_uuid,
            filename=f"client-{client_id}.bin",
            mime_type="application/octet-stream",
            part_count=-(-size // (512 * 1024)),
            size_bytes=size,
        ),
    )


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


def test_implicit_order_is_shared_with_client_guis_but_isolated_between_servers(
    server: leika.Server,
) -> None:
    queued: list[_messages.Message] = []
    connection = _client_connection_stub(server, ClientId(7), queued)
    client = ClientHandle(connection, server)  # type: ignore[arg-type]
    other = leika.Server(host="127.0.0.1", port=0, verbose=False)
    try:
        first = server.gui.add_text("First", "")
        client_first = client.gui.add_text("Client first", "")
        second = server.gui.add_text("Second", "")
        other_first = other.gui.add_text("Other first", "")
        other_second = other.gui.add_text("Other second", "")

        assert (first.order, client_first.order, second.order) == (1, 2, 3)
        assert (other_first.order, other_second.order) == (1, 2)
    finally:
        other.stop()


def test_client_local_gui_resolves_only_its_live_owner(server: leika.Server) -> None:
    client_id = ClientId(7)

    def connection() -> SimpleNamespace:
        return _client_connection_stub(server, client_id)

    original = ClientHandle(connection(), server)  # type: ignore[arg-type]
    replacement = ClientHandle(connection(), server)  # type: ignore[arg-type]

    with server._client_lock:
        server._connected_clients[client_id] = original
    assert original.gui._resolve_client(client_id) is original
    assert original.gui._resolve_client(ClientId(8)) is None
    assert server.gui._resolve_client(client_id) is original

    # A stale queued handler on the previous connection must not resolve to
    # either the dead object or a newer client that reused the same ID.
    with server._client_lock:
        server._connected_clients[client_id] = replacement
    assert original.gui._resolve_client(client_id) is None
    assert replacement.gui._resolve_client(client_id) is replacement

    with server._client_lock:
        server._connected_clients.pop(client_id)
    assert replacement.gui._resolve_client(client_id) is None


def test_text_is_read_or_written_and_renders_markdown_when_read(
    server: leika.Server,
) -> None:
    """One element does both. What separates them is ``editable``: written, it
    is an input whose value is what was typed; read, it is that value shown,
    and drawn as markdown if it is asked to be."""
    written = server.gui.add_text("Name", "Ada")
    assert (written.editable, written.markdown) == (True, False)
    # Only rendered Markdown needs a source beside the value.
    assert written._source == ""

    read = server.gui.add_text(None, "**Hello**", editable=False, markdown=True)
    assert (read.editable, read.markdown, read.label) == (False, True, None)
    assert read.value == "**Hello**"
    assert read._source == "**Hello**"
    read.value = "## Updated"
    assert read._source == "## Updated"

    # It follows a change of mind about rendering, so a field turned read-only
    # after the viewer typed in it renders what they typed.
    written.value = "# Typed"
    written.update(editable=False, markdown=True)
    assert written._source == "# Typed"

    with pytest.raises(UnicodeEncodeError):
        server.gui.add_text("Invalid", "\ud800")


def test_updates_take_only_public_properties(server: leika.Server) -> None:
    text = server.gui.add_text("Text", "value")
    with pytest.raises(TypeError, match="no settable property '_source'"):
        text.update(_source="forged")
    with pytest.raises(AttributeError, match="derived internal state"):
        text._source = "forged"
    with pytest.raises(TypeError, match="no settable property 'lable'"):
        text.lable = "typo"  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        _ = text.lable  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="no settable property 'value'"):
        server.gui.add_folder("Folder").update(value=1)
    assert text._source == ""


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
    with pytest.raises(TypeError, match="strings"):
        server.gui.add_dropdown("Invalid", ("valid", 1))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="strings"):
        server.gui.add_button(("valid", None))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not one string"):
        server.gui.add_dropdown("Invalid", "not a sequence")
    with pytest.raises(ValueError, match="unique"):
        dropdown.options = ("same", "same")
    assert dropdown.options == ("a", "b")
    with pytest.raises(ValueError, match="must be one of"):
        dropdown.value = "missing"

    # Options without the current value select the first, and say so.
    seen: list[str] = []
    dropdown.on_update(lambda event: seen.append(event.value))
    dropdown.options = ("c", "d")
    assert dropdown.value == "c"
    _wait_for(lambda: seen == ["c"])


def test_hold_frequency_is_positive_and_finite(server: leika.Server) -> None:
    button = server.gui.add_button("Hold")
    for frequency in (0, -1, float("inf"), float("nan"), True, 61):
        with pytest.raises(ValueError, match="callback_hz"):
            button.on_hold(callback_hz=frequency)  # type: ignore[arg-type]

    callback = button.on_hold(callback_hz=20)(lambda _: None)
    assert callback is not None
    assert button._hold_callback_freqs == (20.0,)


def test_queue_failures_leave_icons_and_hold_callbacks_unchanged(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    button = server.gui.add_button("Button")
    upload = server.gui.add_upload_button("Upload")
    command = server.gui.add_command("Command")

    def reject(_: _messages.Message) -> None:
        raise RuntimeError("queue rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    for handle in (button, upload, command):
        props_before = handle._impl.props
        with pytest.raises(RuntimeError, match="queue rejected"):
            handle.icon = leika.Icon.PLAY
        assert handle.icon is None
        assert handle._impl.props is props_before

    callback = lambda _: None
    with pytest.raises(RuntimeError, match="queue rejected"):
        button.on_hold(callback, callback_hz=20.0)
    assert button._hold_callbacks == {}
    assert button._hold_callback_freqs == ()

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", lambda _: None)
    button.on_hold(callback, callback_hz=20.0)
    assert button._hold_callbacks == {20.0: [callback]}
    assert button._hold_callback_freqs == (20.0,)

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    with pytest.raises(RuntimeError, match="queue rejected"):
        button.remove_hold_callback(callback, callback_hz=20.0)
    assert button._hold_callbacks == {20.0: [callback]}
    assert button._hold_callback_freqs == (20.0,)


def test_async_callbacks_are_scheduled_on_the_server_loop(server: leika.Server) -> None:
    checkbox = server.gui.add_checkbox("Async", True)
    called = threading.Event()

    @checkbox.on_update
    async def _(_: leika.GuiEvent[Any]) -> None:
        called.set()

    checkbox.value = False
    assert called.wait(2.0)


def test_gui_event_value_is_stable_across_interleaved_client_updates(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkbox = server.gui.add_checkbox("Shared", True)
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", lambda _: True)
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    observed: list[tuple[bool, bool]] = []

    @checkbox.on_update
    async def observe(event: leika.GuiEvent[Any]) -> None:
        if event.value is False:
            first_entered.set()
            await release_first.wait()
            observed.append((event.value, event.target.value))

    async def run() -> None:
        first = asyncio.create_task(
            server.gui._handle_gui_updates(
                ClientId(1),
                _messages.GuiUpdateMessage(checkbox.id, {"value": False}),
            )
        )
        await first_entered.wait()
        await server.gui._handle_gui_updates(
            ClientId(2),
            _messages.GuiUpdateMessage(checkbox.id, {"value": True}),
        )
        release_first.set()
        await first

    asyncio.run(run())
    assert observed == [(False, True)]


def test_wire_callbacks_await_sync_returned_and_callable_object_awaitables(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", lambda _: True)
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    seen: list[str] = []

    class AsyncCallable:
        async def __call__(self, _: leika.GuiEvent[Any]) -> None:
            await asyncio.sleep(0)
            seen.append("input")

    checkbox = server.gui.add_checkbox("Input", True)
    checkbox.on_update(AsyncCallable())

    form = server.gui.add_form(label="Form")

    def form_callback(_: leika.GuiEvent[Any]) -> Any:
        async def finish() -> None:
            await asyncio.sleep(0)
            seen.append("form")

        return finish()

    form.on_submit(form_callback)

    command = server.gui.add_command("Command")

    def command_callback(_: leika.CommandEvent) -> Any:
        future: Future[None] = Future()
        seen.append("command")
        future.set_result(None)
        return future

    command.on_trigger(command_callback)

    upload = server.gui.add_upload_button("Upload")

    class CustomAwaitable:
        def __await__(self):
            async def finish() -> None:
                await asyncio.sleep(0)
                seen.append("upload")

            return finish().__await__()

    def upload_callback(_: leika.GuiEvent[Any]) -> CustomAwaitable:
        return CustomAwaitable()

    async def run() -> None:
        await server.gui._handle_gui_updates(
            ClientId(1),
            _messages.GuiUpdateMessage(checkbox.id, {"value": False}),
        )
        await server.gui._handle_gui_form_submit(
            ClientId(1), _messages.GuiFormSubmitMessage(form.id)
        )
        await server.gui._handle_command_trigger(
            ClientId(1), _messages.CommandTriggerMessage(command.id)
        )
        await server.gui._run_upload_callbacks(
            ClientId(1), upload, leika.UploadedFile("file.bin", b"contents"), (upload_callback,)
        )

    asyncio.run(run())
    assert seen == ["input", "form", "command", "upload"]


def test_programmatic_callbacks_schedule_every_awaitable_result(
    server: leika.Server,
) -> None:
    seen: list[str] = []
    completed = threading.Event()

    def callback(name: str):
        def run(_: leika.GuiEvent[Any]) -> Any:
            async def finish() -> None:
                await asyncio.sleep(0)
                seen.append(name)
                if len(seen) == 4:
                    completed.set()

            return finish()

        return run

    checkbox = server.gui.add_checkbox("Checkbox", True)
    checkbox.on_update(callback("input"))
    checkbox.value = False

    text = server.gui.add_text("Text", "before")
    text.on_update(callback("text"))
    text.value = "after"

    dropdown = server.gui.add_dropdown("Dropdown", ("a", "b"), initial_value="a")
    dropdown.on_update(callback("dropdown"))
    dropdown.options = ("b", "c")

    form = server.gui.add_form(label="Form")
    form.on_submit(callback("form"))
    form.submit_form()

    assert completed.wait(2.0)
    # Submitted in order, and run in that order.
    assert seen == ["input", "text", "dropdown", "form"]


def test_programmatic_callbacks_rejected_by_a_closed_loop_are_reported(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    monkeypatch.setattr(server.gui, "_event_loop", closed_loop)
    invoked: list[object] = []

    server.gui._schedule_callbacks((invoked.append,), SimpleNamespace(value="retained"))

    assert invoked == []
    assert not server.gui._callback_queue
    assert server.gui._callback_draining is False
    assert "RuntimeError: Event loop is closed" in capsys.readouterr().err


def test_raising_async_update_callback_cannot_skip_sync_or_later_callbacks(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    checkbox = server.gui.add_checkbox("Shared", True)
    queued: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(queued))
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())

    @checkbox.on_update
    async def fail(_: leika.GuiEvent[Any]) -> None:
        raise RuntimeError("update callback failed")

    continued: list[bool] = []

    @checkbox.on_update
    async def continue_dispatch(event: leika.GuiEvent[Any]) -> None:
        continued.append(event.value)

    client_id = ClientId(7)
    asyncio.run(
        server.gui._handle_gui_updates(
            client_id,
            _messages.GuiUpdateMessage(checkbox.id, {"value": False}),
        )
    )

    assert continued == [False]
    assert "RuntimeError: update callback failed" in capsys.readouterr().err
    sync_messages = [
        message for message in queued if isinstance(message, _messages.GuiUpdateMessage)
    ]
    assert len(sync_messages) == 1
    assert sync_messages[0].updates == {"value": False}
    assert sync_messages[0].excluded_self_client == client_id


def test_raising_async_submit_callback_cannot_skip_close_or_later_callbacks(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    form = server.gui.add_form(label="Shared form")
    queued: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(queued))
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())

    @form.on_submit
    async def fail(_: leika.GuiEvent[Any]) -> None:
        raise RuntimeError("submit callback failed")

    continued: list[bool] = []

    @form.on_submit
    async def continue_dispatch(_: leika.GuiEvent[Any]) -> None:
        continued.append(True)

    asyncio.run(
        server.gui._handle_gui_form_submit(
            ClientId(7),
            _messages.GuiFormSubmitMessage(form.id),
        )
    )

    assert continued == [True]
    assert "RuntimeError: submit callback failed" in capsys.readouterr().err
    close_messages = [
        message for message in queued if isinstance(message, _messages.GuiFormSubmitMessage)
    ]
    assert len(close_messages) == 1
    assert close_messages[0].uuid == form.id


def test_raising_async_hold_and_command_callbacks_do_not_skip_peers(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    continued: list[str] = []

    button = server.gui.add_button("Hold")

    @button.on_hold(callback_hz=10.0)
    async def fail_hold(_: leika.GuiEvent[Any]) -> None:
        raise RuntimeError("hold callback failed")

    @button.on_hold(callback_hz=10.0)
    async def continue_hold(_: leika.GuiEvent[Any]) -> None:
        continued.append("hold")

    asyncio.run(
        server.gui._handle_gui_button_hold(
            ClientId(7), _messages.GuiButtonHoldMessage(button.id, 10.0)
        )
    )

    command = server.gui.add_command("Run")

    @command.on_trigger
    async def fail_command(_: leika.CommandEvent) -> None:
        raise RuntimeError("command callback failed")

    @command.on_trigger
    async def continue_command(_: leika.CommandEvent) -> None:
        continued.append("command")

    asyncio.run(
        server.gui._handle_command_trigger(ClientId(7), _messages.CommandTriggerMessage(command.id))
    )

    assert continued == ["hold", "command"]
    errors = capsys.readouterr().err
    assert "RuntimeError: hold callback failed" in errors
    assert "RuntimeError: command callback failed" in errors


def test_handle_values_preserve_constructor_invariants(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    entries = server.gui.add_list("Entries", ("one",))
    with pytest.raises(ValueError, match="not one string"):
        entries.value = "one"  # type: ignore[assignment]
    with pytest.raises(ValueError, match="Rows are strings"):
        entries.value = ("one", None)  # type: ignore[assignment]

    toggles = server.gui.add_toggle(("A", "B"))
    with pytest.raises(ValueError, match="one at a"):
        toggles.value = ("A", "B")
    with pytest.raises(ValueError, match="cannot be empty"):
        toggles.value = ()
    # One option's text names that option alone.
    toggles.value = "B"
    assert toggles.value == ("B",)

    color = server.gui.add_color("Color", (1, 2, 3))
    with pytest.raises(ValueError, match="3 color channels"):
        color.value = (1, 2)  # type: ignore[assignment]
    rgba = server.gui.add_color("Alpha", (1, 2, 3, 4))
    # A browser sends exact integer channels; Python may also give floats.
    for handle, invalid in (
        (color, [1, 2]),
        (rgba, [1, 2, 3]),
        (color, [0.5, 0.5, 0.5]),
        (color, [1, 2, 300]),
    ):
        _browser_update(server, handle, invalid)
    assert color.value == (1, 2, 3)
    assert rgba.value == (1, 2, 3, 4)
    color.value = (0, 0.5, 300)
    assert color.value == (0, 127, 255)
    with pytest.raises(ValueError, match="3 \\(RGB\\) or 4 \\(RGBA\\)"):
        server.gui.add_color("Gray", (1, 2))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="2 or 3 components"):
        server.gui.add_vector("Point", (1.0, 2.0, 3.0, 4.0), step=0.1)  # type: ignore[arg-type]

    vector = server.gui.add_vector("Point", (0.0, 0.0), min=(-1.0, -1.0), max=(1.0, 1.0))
    with pytest.raises(ValueError, match="2 components"):
        vector.value = (0.0, 0.0, 0.0)  # type: ignore[assignment]
    with pytest.raises(ValueError, match="above max"):
        vector.value = (2.0, 0.0)
    _browser_update(server, vector, [2.0, 0.0])
    assert vector.value == (0.0, 0.0)
    vector.value = np.array([0.5, -0.5])
    assert vector.value == (0.5, -0.5)

    progress = server.gui.add_progress_bar(50)
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        progress.value = 101
    assert progress.value == 50

    slider = server.gui.add_slider("Bounded", 0.5, min=0.0, max=1.0, step=0.1)
    with pytest.raises(ValueError, match="outside"):
        slider.value = 2.0


def test_progress_bar_is_display_only(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    progress = server.gui.add_progress_bar(10, animated=True)
    assert not isinstance(progress, leika.GuiInputHandle)
    _browser_update(server, progress, 90)
    assert progress.value == 10
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))
    progress.value = 40
    assert sent[-1].updates == {"value": 40}


def test_a_popup_folder_opens_its_children_from_one_row(server: leika.Server) -> None:
    with server.gui.add_folder("Display details", popup=True, order=7.0) as popup:
        enabled = server.gui.add_checkbox("Enabled", initial_value=True)
        with server.gui.add_folder("Advanced") as folder:
            gain = server.gui.add_number("Gain", initial_value=1.0)

    assert isinstance(popup, leika.GuiFolderHandle)
    assert (popup.label, popup.popup, popup.order) == ("Display details", True, 7.0)
    assert enabled._impl.parent_container_id == popup.id
    assert folder._impl.parent_container_id == popup.id
    assert gain._impl.parent_container_id == folder.id
    assert any(
        isinstance(message, _messages.GuiFolderMessage)
        and message.uuid == popup.id
        and message.props.popup
        for message in _queued(server)
    )

    popup.update(label="Rendering", visible=False, order=8.0)
    assert (popup.label, popup.visible, popup.order) == ("Rendering", False, 8.0)
    with pytest.raises(ValueError, match="needs a label"):
        popup.label = None
    with pytest.raises(ValueError, match="needs a label"):
        server.gui.add_folder(None, popup=True)

    popup.remove()
    assert popup._impl.removed
    assert enabled._impl.removed
    assert folder._impl.removed
    assert gain._impl.removed
    with pytest.raises(RuntimeError, match="removed GuiFolderHandle"):
        with popup:
            pass


def test_form_submission_and_its_browser_reset(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_form(label="Profile") as form:
        name = server.gui.add_text("Name", initial_value="Ada")
    # Reset and Submit are the browser's, not children of the form.
    assert list(form._impl.children.values()) == [name]
    submitted: list[str] = []

    @form.on_submit
    def _(_) -> None:
        submitted.append(name.value)

    form.submit_form()
    _wait_for(lambda: submitted == ["Ada"])
    name.value = "Grace"
    form.submit_form()
    _wait_for(lambda: submitted == ["Ada", "Grace"])

    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())

    def browser_reset(target: leika.GuiFormHandle) -> None:
        reset = _messages.GuiFormResetMessage(target.id)
        asyncio.run(server.gui._handle_gui_form_reset(ClientId(1), reset))

    browser_reset(form)
    assert name.value == "Ada"
    assert submitted == ["Ada", "Grace"]

    # Only a visible regular form draws a Reset to press.
    name.value = "Grace"
    form.visible = False
    browser_reset(form)
    assert name.value == "Grace"
    with server.gui.add_form(mini=True) as mini:
        query = server.gui.add_text("Query", "")
    query.value = "typed"
    browser_reset(mini)
    assert query.value == "typed"

    # A form keeps its kind, so the mini form's one-field rule holds.
    with pytest.raises(ValueError, match="cannot change between mini and regular"):
        form.mini = True

    # Any order is a child's to use.
    with form:
        last = server.gui.add_text("Last", "", order=float.fromhex("0x1.fffffffffffffp+1023"))
    assert last.order > name.order

    with server.gui.add_form(label="Outer"):
        with pytest.raises(ValueError, match="Nested forms"):
            server.gui.add_form(label="Inner")


def test_a_mini_form_holds_one_field(server: leika.Server) -> None:
    """A mini form is drawn as its field's own row with a send button, so it
    has nowhere to put a second field or another row."""
    with server.gui.add_form(mini=True) as mini:
        field = server.gui.add_text("Search", initial_value="")

    submitted: list[str] = []
    mini.on_submit(lambda _: submitted.append(field.value))
    field.value = "leika"
    mini.submit_form()
    _wait_for(lambda: submitted == ["leika"])

    # Reset works the same as any form's, on the one field it has.
    mini.reset_form()
    assert field.value == ""

    with pytest.raises(ValueError, match="single field"):
        with server.gui.add_form(mini=True):
            server.gui.add_text("One", initial_value="")
            server.gui.add_text("Two", initial_value="")

    with server.gui.add_form(mini=True) as strict:
        for add_incompatible in (
            lambda: server.gui.add_text(None, "Ask away", editable=False, markdown=True),
            lambda: server.gui.add_folder("Nested"),
            server.gui.add_tab_group,
            lambda: server.gui.add_html("<p>Sibling</p>"),
            lambda: server.gui.add_button("Sibling"),
        ):
            before = dict(strict._impl.children)
            with pytest.raises(ValueError, match="direct editable field"):
                add_incompatible()
            assert strict._impl.children == before
        server.gui.add_text("Query", initial_value="")
        with pytest.raises(ValueError, match="single field"):
            server.gui.add_text("Second", initial_value="")
    assert len(strict._impl.children) == 1


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
        name.value = "Changed before the context exits"
    with form:
        late = server.gui.add_text("Nickname", initial_value="Countess")

    name.value = "Grace"
    age.value = 45
    tags.value = ("A", "B")
    late.value = "Amazing"

    form.reset_form()
    assert (name.value, age.value, tags.value, late.value) == ("Ada", 36, (), "Countess")

    # A field removed since is skipped rather than resurrected.
    late.remove()
    form.reset_form()
    assert name.value == "Ada"


def test_form_reset_rebuilds_markdown_source_for_the_current_mode(
    server: leika.Server, tmp_path: Path
) -> None:
    image = tmp_path / "dot.png"
    ihdr = (1).to_bytes(4, "big") * 2 + b"\x08\x02\x00\x00\x00"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + len(ihdr).to_bytes(4, "big")
        + b"IHDR"
        + ihdr
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IDAT\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00"
    )
    declared = "![dot](dot.png)"
    with server.gui.add_form(label="Profile") as form:
        field = server.gui.add_text("Body", declared, image_root=tmp_path)

    field.update(editable=False, markdown=True)
    field.value = "changed"
    form.reset_form()

    assert field.value == declared
    assert "/leika-assets/" in field._source
    assert field._source != declared


def test_form_reset_batch_failure_changes_no_field_or_callback(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_form(label="Profile") as form:
        name = server.gui.add_text("Name", "Ada")
        age = server.gui.add_number("Age", 36)
    name.value = "Grace"
    age.value = 45
    callbacks: list[object] = []
    name.on_update(lambda event: callbacks.append(event.value))
    age.on_update(lambda event: callbacks.append(event.value))

    def reject(_: Any) -> None:
        raise RuntimeError("batch rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="batch rejected"):
        form.reset_form()

    assert (name.value, age.value) == ("Grace", 45)
    time.sleep(0.05)
    assert callbacks == []


def test_failed_and_invalid_form_contexts_retire_the_whole_subtree(
    server: leika.Server,
) -> None:
    form = None
    child = None
    with pytest.raises(RuntimeError, match="construction failed"):
        with server.gui.add_form(label="Broken") as form:
            child = server.gui.add_text("Partial", "")
            raise RuntimeError("construction failed")
    assert form is not None and form._impl.removed
    assert child is not None and child._impl.removed
    assert form.id not in server.gui._handles
    assert child.id not in server.gui._handles

    with pytest.raises(ValueError, match="single field"):
        with server.gui.add_form(mini=True) as empty:
            pass
    assert empty._impl.removed
    assert empty.id not in server.gui._handles

    first = second = None
    with pytest.raises(ValueError, match="single field"):
        with server.gui.add_form(mini=True) as invalid:
            first = server.gui.add_text("One", "")
            second = server.gui.add_text("Two", "")
    assert invalid._impl.removed
    assert first is not None and first._impl.removed
    assert second is None  # Rejected before publication or registration.


def test_removed_handles_keep_their_last_state_and_refuse_changes(
    server: leika.Server,
) -> None:
    frame = np.full((24, 32, 3), 127, dtype=np.uint8)
    image = server.gui.add_image(frame, label="Frame", format="png")
    download = server.gui.add_download_button("Save", b"payload", filename="capture.bin")
    command = server.gui.add_command("Run", lambda: None, icon=leika.Icon.PLAY)
    notification = server.gui.add_notification("Working", "body", auto_close_seconds=None)
    checkbox = server.gui.add_checkbox("Check", True)

    for handle in (image, download, command, notification, checkbox):
        handle.remove()

    np.testing.assert_array_equal(image.image, frame)
    assert image.label == "Frame"
    assert download.content == b"payload"
    assert (command.label, command.icon) == ("Run", leika.Icon.PLAY)
    assert notification.title == "Working"
    assert checkbox.value is True

    for change in (
        lambda: setattr(image, "image", frame),
        lambda: setattr(download, "content", b"other"),
        lambda: setattr(command, "label", "Other"),
        lambda: setattr(notification, "title", "Other"),
        lambda: setattr(checkbox, "value", False),
        lambda: checkbox.on_update(lambda _: None),
    ):
        with pytest.raises(RuntimeError, match="removed"):
            change()

    with pytest.warns(UserWarning, match="already removed"):
        checkbox.remove()


def test_removed_control_can_be_collected_while_server_is_alive(server: leika.Server) -> None:
    handle = server.gui.add_button("Temporary")
    reference = weakref.ref(handle)
    handle.remove()
    del handle
    gc.collect()
    assert reference() is None


def test_caller_owned_path_and_primitive_subclasses(
    server: leika.Server,
    tmp_path: Path,
) -> None:
    class RichStr(str):
        pass

    class RichFloat(float):
        pass

    class RichInt(int):
        pass

    class RichBytes(bytes):
        pass

    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    provider = server.gui.add_download_button("Provider", lambda _: source)
    filename, resolved = provider._resolve(leika.GuiEvent(None, None, provider))
    assert (filename, resolved) == (source.name, source)

    with pytest.raises(TypeError, match="image_root"):
        server.gui.add_text("Bad root", "plain", image_root="not-a-path")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="filename"):
        server.gui.add_download_button("Bad name", b"x", filename=RichStr("payload.bin"))
    with pytest.raises(TypeError, match="content"):
        server.gui.add_download_button(
            "Bad bytes",
            RichBytes(b"x"),  # type: ignore[arg-type]
            filename="payload.bin",
        )

    with pytest.raises(ValueError, match="number"):
        server.gui.add_number("Number", RichFloat(1.0))
    with pytest.raises(ValueError, match="positive integer"):
        server.gui.add_text("Rows", "", multiline=True, rows=RichInt(2))
    with pytest.raises(ValueError, match="'default' or 'inverse'"):
        server.gui.add_button("Run", color=RichStr("default"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="control_layout"):
        server.gui.configure_theme(control_layout=RichStr("left"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="theme"):
        server.gui.configure_theme(theme=RichStr("auto"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="hotkey"):
        server.gui.add_command("Run", hotkey=RichStr("R"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="format"):
        server.gui.add_image(
            np.zeros((1, 1, 3), dtype=np.uint8),
            format=RichStr("png"),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="jpeg_quality"):
        server.gui.add_image(np.zeros((1, 1, 3), dtype=np.uint8), jpeg_quality=RichInt(80))
    with pytest.raises(ValueError, match="max_bytes"):
        server.gui.add_preview_button("Preview", b"x", filename="x.txt", max_bytes=RichInt(1))


def test_equal_string_subclasses_are_canonicalized_to_declared_options(
    server: leika.Server,
) -> None:
    class RichStr(str):
        pass

    initial = RichStr("A")
    dropdown = server.gui.add_dropdown("Choice", ("A", "B"), initial_value=initial)
    assert dropdown.value is dropdown.options[0]
    assert type(dropdown.value) is str

    dropdown.value = RichStr("B")
    assert dropdown.value is dropdown.options[1]

    buttons = server.gui.add_button(("A", "B"))
    buttons.value = RichStr("B")
    assert buttons.value is buttons.options[1]

    with server.gui.add_form() as form:
        field = server.gui.add_dropdown("Form choice", ("A", "B"), initial_value=RichStr("A"))
    assert field._impl.initial_value is field.options[0]
    field.value = RichStr("B")
    form.reset_form()
    assert field.value is field.options[0]


def test_failed_removal_preserves_the_handle(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = np.full((8, 12, 3), 63, dtype=np.uint8)
    image = server.gui.add_image(frame, label="Frame")
    download = server.gui.add_download_button("Save", b"payload", filename="capture.bin")
    command = server.gui.add_command("Run", description="Description", icon=leika.Icon.PLAY)
    notification = server.gui.add_notification("Working", "Still running", auto_close_seconds=None)
    with server.gui.add_folder("Folder") as folder:
        child = server.gui.add_text("Child", "")

    def reject(_: _messages.Message) -> None:
        raise RuntimeError("closed")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    for handle in (image, download, command, notification, folder):
        with pytest.raises(RuntimeError, match="closed"):
            handle.remove()

    assert not any(
        handle._impl.removed for handle in (image, download, command, notification, folder, child)
    )
    assert child.id in folder._impl.children
    assert set(server.gui._handles) >= {image.id, command.id, folder.id, child.id}


def test_server_stop_retires_every_handle(server: leika.Server) -> None:
    with server.gui.add_form(label="Form") as form:
        field = server.gui.add_text("Field", "value")
    tabs = server.gui.add_tab_group()
    tab = tabs.add_tab("Tab", icon=leika.Icon.PLAY)
    with server.gui.add_modal("Modal") as modal:
        modal_text = server.gui.add_html("<strong>modal</strong>")
    command = server.gui.add_command("Command")
    notification = server.gui.add_notification("Notification", auto_close_seconds=None)
    handles = (form, field, tabs, tab, modal, modal_text, command, notification)

    server.stop()

    assert all(handle._impl.removed for handle in handles)
    assert server.gui._handles == {} and server.gui._root_children == {}
    assert field.value == "value" and tab.icon == leika.Icon.PLAY
    with pytest.raises(RuntimeError, match="no longer active"):
        server.gui.add_text("Late", "")


def test_theme_defaults_to_following_the_browser_color_scheme(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An app has to ask for a scheme; otherwise the viewer's OS decides."""
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    server.gui.configure_theme()
    server.gui.configure_theme(theme=None)
    server.gui.configure_theme(theme="auto")
    server.gui.configure_theme(theme="light")
    server.gui.configure_theme(theme="dark")
    server.gui.configure_theme(control_layout="left")
    server.gui.configure_theme(control_layout="right")

    assert [message.theme for message in sent] == ["auto"] * 3 + ["light", "dark", "auto", "auto"]
    assert [message.control_layout for message in sent][-2:] == ["left", "right"]


def test_theme_rejects_unknown_wire_values(server: leika.Server) -> None:
    for layout in ("wide", "fixed", "collapsible"):
        with pytest.raises(ValueError, match="'floating', 'left', or 'right'"):
            server.gui.configure_theme(control_layout=layout)  # type: ignore[arg-type]
    for invalid in (True, False, 1, "system", "Dark", "", [], {}):
        with pytest.raises(ValueError, match="theme"):
            server.gui.configure_theme(theme=invalid)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="dark_mode"):
        server.gui.configure_theme(dark_mode=True)  # type: ignore[call-arg]


def test_a_row_can_take_one_role_per_button_or_toggle(server: leika.Server) -> None:
    """A row usually wants one weight throughout, and sometimes wants its accent
    behind one action only. Both are ``color=``; the wire always carries one
    role per element."""
    row = server.gui.add_button(("Reset", "Submit"), color=("default", "inverse"))
    assert row.color == ("default", "inverse")
    plain = server.gui.add_toggle(("A", "B", "C"), color="default")
    assert plain.color == ("default", "default", "default")

    # Live, with the same latitude as the constructor.
    plain.color = ("inverse", "default", "inverse")
    assert plain.color == ("inverse", "default", "inverse")
    plain.color = "inverse"  # type: ignore[assignment]
    assert plain.color == ("inverse", "inverse", "inverse")

    with pytest.raises(ValueError, match="one role per option"):
        server.gui.add_button(("One", "Two"), color=("inverse",))
    with pytest.raises(ValueError, match="one role per option"):
        server.gui.add_toggle(("One", "Two"), color=("inverse", "inverse", "inverse"))
    with pytest.raises(ValueError, match="must be 'default' or 'inverse'"):
        server.gui.add_button(("One", "Two"), color=("inverse", "blue"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="a single button"):
        server.gui.add_button("Solo", color=("inverse",))  # type: ignore[arg-type]


def test_gui_image_state_is_private_and_unchanged_by_failures(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    def reject(_: object) -> None:
        raise RuntimeError("queue rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    with pytest.raises(RuntimeError, match="queue rejected"):
        image.format = "jpeg"
    with pytest.raises(RuntimeError, match="queue rejected"):
        image.image = np.full((2, 3, 3), 9, dtype=np.uint8)
    assert image.format == "png"
    assert image._data == old_data
    assert np.all(image.image == 0)


def test_tabs_publish_before_their_children_and_remove_with_them(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    tabs = server.gui.add_tab_group()
    alpha = tabs.add_tab("Alpha")
    with alpha:
        alpha_child = server.gui.add_text("Alpha child", "a")
    alpha.icon = leika.Icon.PLAY
    beta = tabs.add_tab("Beta")
    with beta:
        beta_child = server.gui.add_text("Beta child", "b")

    messages = _queued(server)
    order = [
        index
        for uuid in (alpha.id, alpha_child.id, beta.id, beta_child.id)
        for index, message in enumerate(messages)
        if getattr(message, "uuid", None) == uuid
        and not isinstance(message, (_messages.GuiUpdateMessage, _messages.GuiTabUpdateMessage))
    ]
    assert order == sorted(order) and len(order) == 4
    alpha_update = next(
        message
        for message in messages
        if isinstance(message, _messages.GuiTabUpdateMessage) and message.uuid == alpha.id
    )
    assert alpha_update.props._icon_html is not None
    assert list(tabs._impl.children) == [alpha.id, beta.id]
    beta.label = "Renamed"
    assert beta.label == "Renamed"

    alpha.remove()
    assert list(tabs._impl.children) == [beta.id]
    assert alpha_child._impl.removed

    def reject(_: _messages.Message) -> None:
        raise RuntimeError("tab update rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    with pytest.raises(RuntimeError, match="tab update rejected"):
        beta.icon = leika.Icon.PLAY
    assert beta.icon is None

    sent: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", sent.append)
    tabs.remove()
    assert sent == [_messages.GuiRemoveMessage(tabs.id, (beta.id, beta_child.id))]


def test_removed_containers_reject_new_actions(server: leika.Server) -> None:
    tabs = server.gui.add_tab_group()
    tab = tabs.add_tab("One")
    tab.remove()
    with pytest.raises(RuntimeError, match="removed GuiTabHandle"):
        tab.icon = leika.Icon.PLAY

    tabs.remove()
    with pytest.raises(RuntimeError, match="has been removed"):
        tabs.add_tab("Too late")

    form = server.gui.add_form()
    form.remove()
    with pytest.raises(RuntimeError, match="removed GuiFormHandle"):
        form.submit_form()


def test_numeric_constructors_reject_invalid_ranges(server: leika.Server) -> None:
    fixed = server.gui.add_slider("Fixed", 1.0, min=1.0, max=1.0, step=0.1)
    # A fixed range remains valid, but must never emit a zero step.
    assert fixed.step == 0.1
    # A step wider than the range is clamped to it.
    assert server.gui.add_slider("Narrow", 0, min=0, max=2, step=5).step == 2
    with pytest.raises(ValueError, match="at least min"):
        server.gui.add_slider("Backwards", 1.0, min=2.0, max=1.0, step=0.1)
    with pytest.raises(ValueError, match="greater than zero"):
        server.gui.add_number("Bad step", 1.0, step=0.0)
    with pytest.raises(ValueError, match="ascending"):
        server.gui.add_multi_slider("Order", (0.8, 0.2), min=0.0, max=1.0, step=0.1)
    with pytest.raises(ValueError, match="finite"):
        server.gui.add_progress_bar(float("nan"))
    with pytest.raises(ValueError, match="finite"):
        server.gui.add_number("Huge", 10**1000)

    preview = server.gui.add_preview_button("Empty", b"", filename="empty.txt", max_bytes=0)
    assert preview._max_bytes == 0


def test_uploads_are_isolated_and_validated_per_client(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = server.gui.add_upload_button("Upload")
    broadcast: list[Any] = []
    acknowledgements: dict[int, list[Any]] = {1: [], 2: []}
    clients = {
        client_id: SimpleNamespace(
            _websock_connection=SimpleNamespace(queue_message=_open_recorder(messages))
        )
        for client_id, messages in acknowledgements.items()
    }
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(broadcast))
    monkeypatch.setattr(server.gui, "_resolve_client", clients.get)
    uploaded: list[tuple[str, bytes]] = []
    upload.on_upload(lambda event: uploaded.append((event.value.name, event.value.content)))

    _start_upload(server, 1, upload, "same", 1)
    _start_upload(server, 2, upload, "same", 1)
    assert len(server.gui._uploads) == 2

    completion = server.gui._handle_file_transfer_part(
        ClientId(1), _messages.FileTransferPart(upload.id, "same", 0, b"a")
    )
    assert upload.value == leika.UploadedFile("client-1.bin", b"a")
    assert len(server.gui._uploads) == 1
    assert completion is not None
    asyncio.run(completion)
    assert uploaded == [("client-1.bin", b"a")]

    # The same transfer UUID from another client remains independent.
    server.gui._handle_file_transfer_part(
        ClientId(2), _messages.FileTransferPart(upload.id, "same", 0, b"c")
    )
    assert upload.value.content == b"c"
    assert server.gui._uploads == {}
    assert not any(isinstance(message, _messages.FileTransferPartAck) for message in broadcast)
    assert {client_id: len(messages) for client_id, messages in acknowledgements.items()} == {
        1: 2,
        2: 2,
    }

    # Assignments from Python are validated like any other value.
    upload.value = leika.UploadedFile("python.bin", b"x")
    with pytest.raises(TypeError, match="content must be bytes"):
        upload.value = leika.UploadedFile("bad.bin", bytearray(b"x"))  # type: ignore[arg-type]
    assert upload.value == leika.UploadedFile("python.bin", b"x")

    # Removing a button releases any incomplete transfer.
    _start_upload(server, 1, upload, "pending", 1)
    upload.remove()
    assert server.gui._uploads == {}


def test_malformed_or_unavailable_uploads_are_aborted(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[Any] = []
    client = SimpleNamespace(_websock_connection=SimpleNamespace(queue_message=messages.append))
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)
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
    _start_upload(server, 1, upload, "oversize", 64 * 1024 * 1024 + 1)
    _start_upload(server, 1, upload, "wrong-size", 1)
    server.gui._handle_file_transfer_part(
        ClientId(1), _messages.FileTransferPart(upload.id, "wrong-size", 0, b"too long")
    )
    assert server.gui._uploads == {}
    assert upload.value.content == b""
    assert [message.reason for message in messages if hasattr(message, "reason")] == [
        "Invalid upload metadata.",
        "Upload exceeds the 64 MiB limit.",
        "Invalid upload part.",
    ]

    upload.disabled = True
    _start_upload(server, 1, upload, "disabled", 1)
    assert server.gui._uploads == {}
    assert messages[-1].reason == "Upload target unavailable."

    # A repeated start does not cancel the transfer already under way.
    upload.disabled = False
    _start_upload(server, 1, upload, "active", 1)
    _start_upload(server, 1, upload, "active", 1)
    assert messages[-1].reason == "An upload is already active for this control."
    assert (ClientId(1), "active") in server.gui._uploads


def test_upload_part_and_button_removal_are_serialized(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = server.gui.add_upload_button("Upload")
    ack_started = threading.Event()
    release_ack = threading.Event()

    def queue_message(message: Any) -> None:
        if isinstance(message, _messages.FileTransferPartAck) and message.transferred_bytes > 0:
            ack_started.set()
            assert release_ack.wait(2.0)

    client = SimpleNamespace(_websock_connection=SimpleNamespace(queue_message=queue_message))
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)
    _start_upload(server, 1, upload, "race", 1)
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
    assert server.gui._uploads == {}


def test_containers_nest_and_unwind_to_where_they_started(server: leika.Server) -> None:
    """Entering the same container twice must not lose the outer target."""
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
    assert server.gui._container_stack.get() == ()


def test_container_targets_are_isolated_between_async_tasks(server: leika.Server) -> None:
    """Interleaved builders share an event-loop thread but not a container target."""

    first = server.gui.add_folder("First")
    second = server.gui.add_folder("Second")

    async def build() -> tuple[leika.GuiCheckboxHandle, leika.GuiCheckboxHandle]:
        first_entered = asyncio.Event()
        second_entered = asyncio.Event()

        async def build_first() -> leika.GuiCheckboxHandle:
            with first:
                first_entered.set()
                await second_entered.wait()
                return server.gui.add_checkbox("First child", True)

        async def build_second() -> leika.GuiCheckboxHandle:
            await first_entered.wait()
            with second:
                second_entered.set()
                await asyncio.sleep(0)
                return server.gui.add_checkbox("Second child", True)

        first_child, second_child = await asyncio.gather(build_first(), build_second())
        return first_child, second_child

    first_child, second_child = asyncio.run(build())
    assert first_child._impl.parent_container_id == first.id
    assert second_child._impl.parent_container_id == second.id
    assert server.gui._container_stack.get() == ()


def test_media_elements_are_created_from_their_content(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No create-then-backfill: an image or plot arrives complete."""
    plotly = pytest.importorskip("plotly.graph_objects")
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

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


def test_plotly_runtime_is_queued_once_for_every_scope(server: leika.Server) -> None:
    """Local, global, and pane plots share one replayed runtime."""
    plotly = pytest.importorskip("plotly.graph_objects")
    queued: list[_messages.Message] = []
    connection = _client_connection_stub(server, ClientId(101), queued)
    client = ClientHandle(connection, server)  # type: ignore[arg-type]

    def runtimes() -> list[_messages.Message]:
        return [m for m in _queued(server) if isinstance(m, _messages.RunJavascriptMessage)]

    assert runtimes() == []
    client.gui.add_plotly(plotly.Figure())
    server.gui.add_plotly(plotly.Figure())
    server.panes.add_plotly(plotly.Figure(), pane_id="plotly-runtime-test")
    assert len(runtimes()) == 1
    assert "Plotly" in runtimes()[0].source
    assert not any(isinstance(m, _messages.RunJavascriptMessage) for m in queued)


def test_toggle_initial_values_and_modes(server: leika.Server) -> None:
    """A row of toggles holds the tuple of options that are on."""
    row = server.gui.add_toggle(("Bold", "Italic"), initial_value="Italic")
    assert row.value == ("Italic",)
    # One at a time is required by default, like a radio group, so a row left
    # without an initial value starts on its first option rather than empty.
    assert server.gui.add_toggle(("Bold", "Italic")).value == ("Bold",)
    assert server.gui.add_toggle(("Bold", "Italic"), required=False).value == ()
    many = server.gui.add_toggle(
        ("Bold", "Italic", "Under"), multiple=True, initial_value=("Under", "Bold")
    )
    assert many.value == ("Bold", "Under")
    assert server.gui.add_toggle(("Grid", "Axes"), multiple=True).value == ()
    assert server.gui.add_toggle(("Grid", "Axes"), multiple=True, required=True).value == ("Grid",)

    with pytest.raises(ValueError, match="Unknown toggle option"):
        server.gui.add_toggle(("Bold", "Italic"), initial_value="Underline")
    with pytest.raises(ValueError, match="one at a"):
        server.gui.add_toggle(("Bold", "Italic"), initial_value=("Bold", "Italic"))
    with pytest.raises(TypeError):
        server.gui.add_toggle(("Bold", "Italic"), initial_value=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot be empty"):
        server.gui.add_toggle(("Bold", "Italic"), initial_value=())
    with pytest.raises(ValueError, match="use add_checkbox"):
        server.gui.add_toggle("Bookmark")
    with pytest.raises(ValueError, match="at least one option"):
        server.gui.add_toggle([])


def test_a_list_holds_text_entries_and_can_be_frozen(server: leika.Server) -> None:
    """The value is the entries, in order: editing one, adding, removing, and
    reordering all read and write the same tuple."""
    entries = server.gui.add_list("Tags", ("alpha", "beta"))
    assert entries.value == ("alpha", "beta")
    assert entries.frozen is False

    seen: list[tuple[str, ...]] = []
    entries.on_update(lambda event: seen.append(event.value))
    entries.value = ("alpha", "beta", "gamma")
    entries.value = ("gamma", "alpha")
    _wait_for(lambda: seen == [("alpha", "beta", "gamma"), ("gamma", "alpha")])

    assert server.gui.add_list().value == ()

    fixed = server.gui.add_list("Fixed", ("read", "only"), frozen=True)
    assert fixed.frozen is True
    fixed.frozen = False
    assert fixed.frozen is False

    with pytest.raises(ValueError, match="Rows are strings"):
        server.gui.add_list("Bad", ("fine", 3))  # type: ignore[arg-type]


def test_a_checked_list_pairs_each_row_with_a_box(server: leika.Server) -> None:
    """With a mark, the value is (text, marked) per row, and a bare string is
    a row nobody has marked yet."""
    items = server.gui.add_list("Preflight", ["Fuel", ("Doors", True), "Lights"], mark="check")
    assert items.value == (("Fuel", False), ("Doors", True), ("Lights", False))
    assert items.marked == ("Doors",)

    items.value += ("Chocks",)
    assert items.value[-1] == ("Chocks", False)

    seen: list[tuple[tuple[str, bool], ...]] = []
    items.on_update(lambda event: seen.append(event.target.value))
    items.value = [("Fuel", True), ("Doors", True)]
    _wait_for(lambda: seen == [(("Fuel", True), ("Doors", True))])
    assert items.marked == ("Fuel", "Doors")

    assert server.gui.add_list(mark="check").value == ()

    with pytest.raises(ValueError, match="strings or"):
        server.gui.add_list("Bad", [("fine", True), 3], mark="check")  # type: ignore[list-item]
    with pytest.raises(TypeError, match="strings or"):
        server.gui.add_list("Bad", [(3, True)], mark="check")  # type: ignore[list-item]
    with pytest.raises(TypeError, match="strings or"):
        items.value = [("one", "false")]  # type: ignore[list-item]
    assert items.marked == ("Fuel", "Doors")
    with pytest.raises(ValueError, match="mark must be"):
        server.gui.add_list("Bad", mark="star")  # type: ignore[arg-type]

    # The mark can change; without one, rows keep only their words.
    items.mark = None
    assert items.value == ("Fuel", "Doors")
    assert items.marked == ()
    items.mark = "radio"
    assert items.value == (("Fuel", False), ("Doors", False))


def test_a_radio_list_has_at_most_one_selected_row(server: leika.Server) -> None:
    choices = server.gui.add_list(
        "Density", ["Default", ("Comfortable", True), "Compact"], mark="radio"
    )
    assert choices.marked == ("Comfortable",)

    choices.value += ("Spacious",)
    assert choices.value[-1] == ("Spacious", False)

    choices.value = [("Default", True), "Comfortable", "Compact"]
    assert choices.marked == ("Default",)
    assert server.gui.add_list(mark="radio").marked == ()

    with pytest.raises(ValueError, match="at most one selected"):
        server.gui.add_list("Invalid", [("one", True), ("two", True)], mark="radio")

    before = choices.value
    with pytest.raises(ValueError, match="at most one selected"):
        choices.value = [("one", True), ("two", True)]
    assert choices.value == before


@pytest.mark.parametrize("mark", ["check", "radio"])
def test_frozen_marked_lists_only_accept_client_mark_changes(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    mark: str,
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    handle = server.gui.add_list(
        "Frozen",
        [("First", False), ("Second", True)],
        mark=mark,  # type: ignore[arg-type]
        frozen=True,
    )

    _browser_update(server, handle, [["First", True], ["Second", False]])
    expected = (("First", True), ("Second", False))
    assert handle.value == expected

    for tampered in (
        [["Renamed", True], ["Second", False]],
        [["First", True]],
        [["First", True], ["Second", False], ["Third", False]],
        [["Second", False], ["First", True]],
    ):
        _browser_update(server, handle, tampered)
        assert handle.value == expected


def test_a_frozen_list_keeps_its_count_but_not_its_words(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    handle = server.gui.add_list("Frozen", ["one", "two"], frozen=True)
    _browser_update(server, handle, ["uno", "two"])
    assert handle.value == ("uno", "two")
    _browser_update(server, handle, ["uno", "two", "three"])
    assert handle.value == ("uno", "two")


def test_radio_list_rejects_multiple_client_selections(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    choices = server.gui.add_list("Density", [("Default", True), "Compact"], mark="radio")
    _browser_update(server, choices, [["Default", True], ["Compact", True]])
    assert choices.value == (("Default", True), ("Compact", False))


@pytest.mark.parametrize(
    ("factory", "initial", "bad"),
    [
        ("add_checkbox", True, "false"),
        ("add_text", "text", 123),
    ],
)
def test_scalar_value_assignment_rejects_silent_coercion(
    server: leika.Server,
    factory: str,
    initial: object,
    bad: object,
) -> None:
    handle = getattr(server.gui, factory)("Strict", initial)
    with pytest.raises(TypeError):
        handle.value = bad
    assert handle.value == initial


@pytest.mark.parametrize("factory", ["add_number", "add_slider"])
@pytest.mark.parametrize("bad", [True, "1"])
def test_numeric_client_updates_reject_bool_and_string(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    factory: str,
    bad: object,
) -> None:
    if factory == "add_number":
        handle = server.gui.add_number("Number", 1.0)
    else:
        handle = server.gui.add_slider("Slider", 1.0, min=0.0, max=2.0, step=0.1)
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    _browser_update(server, handle, bad)
    assert handle.value == 1.0


@pytest.mark.parametrize("length", [2, 3])
@pytest.mark.parametrize("bad", [(True, False), ("1", "2")])
def test_vectors_reject_boolean_and_string_components_at_every_boundary(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    length: int,
    bad: tuple[object, object],
) -> None:
    bad_value = bad if length == 2 else (*bad, 0.0)
    with pytest.raises(TypeError, match="real numbers"):
        server.gui.add_vector("Invalid", bad_value, step=0.1)  # type: ignore[arg-type]

    handle = server.gui.add_vector("Vector", (0.0,) * length)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="real numbers"):
        handle.value = bad_value  # type: ignore[assignment]

    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    _browser_update(server, handle, list(bad_value))
    assert handle.value == (0.0,) * length


def test_props_are_checked_against_their_wire_types(server: leika.Server) -> None:
    checkbox = server.gui.add_checkbox("Strict", True)
    with pytest.raises(TypeError, match="disabled"):
        checkbox.disabled = "no"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="label"):
        checkbox.label = 3  # type: ignore[assignment]
    assert checkbox.disabled is False
    assert checkbox.label == "Strict"

    button = server.gui.add_button("Action")
    with pytest.raises(ValueError, match="'default' or 'inverse'"):
        button.color = "danger"  # type: ignore[assignment]
    assert button.color == "default"

    vector = server.gui.add_vector("Point", (0.0, 0.0))
    vector.min = np.array([-1.0, -2.0])  # type: ignore[assignment]
    assert vector.min == (-1.0, -2.0)
    with pytest.raises(ValueError, match="vector of 2"):
        vector.max = np.zeros((2, 1))  # type: ignore[assignment]


def test_client_array_controls_reject_mapping_payloads(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    controls = (
        server.gui.add_list("List", ("one",)),
        server.gui.add_list("Checklist", (("one", False),), mark="check"),
        server.gui.add_list("Radio list", (("one", False),), mark="radio"),
        server.gui.add_toggle(("one", "two"), multiple=True),
        server.gui.add_multi_slider("Range", (0.25, 0.75), min=0.0, max=1.0, step=0.1),
        server.gui.add_vector("Vector", (0.0, 0.0)),
    )
    before = tuple(control.value for control in controls)
    for control in controls:
        _browser_update(server, control, {"one": True})
    assert tuple(control.value for control in controls) == before


def test_public_value_callbacks_use_a_stable_snapshot(server: leika.Server) -> None:
    checkbox = server.gui.add_checkbox("Stable", False)
    calls: list[str] = []

    def first(_: leika.GuiEvent[Any]) -> None:
        calls.append("first")
        checkbox.remove_update_callback(second)
        checkbox.on_update(lambda _: calls.append("late"))

    def second(_: leika.GuiEvent[Any]) -> None:
        calls.append("second")

    checkbox.on_update(first)
    checkbox.on_update(second)
    checkbox.value = True
    _wait_for(lambda: calls == ["first", "second"])

    checkbox.value = False
    _wait_for(lambda: calls == ["first", "second", "first", "late"])


def test_gui_creators_register_at_publication_and_leave_nothing_on_failure(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    gui = server.gui
    published: list[_messages.Message] = []
    monkeypatch.setattr(gui._websock_interface, "queue_message", _open_recorder(published))
    gui.add_text("Text", "")
    gui.add_folder("Folder")
    gui.add_tab_group()
    gui.add_modal("Modal")
    gui.add_image(np.zeros((1, 1, 3), dtype=np.uint8))
    assert len(published) == 5
    assert set(gui._handles) == {getattr(message, "uuid") for message in published}

    handles_before = set(gui._handles)
    children_before = set(gui._root_children)

    def fail(_: _messages.Message) -> bool:
        raise RuntimeError("publication failed")

    monkeypatch.setattr(gui._websock_interface, "queue_message", fail)
    for add in (
        lambda: gui.add_text("Rejected", ""),
        lambda: gui.add_folder("Rejected"),
        lambda: gui.add_modal("Rejected"),
    ):
        with pytest.raises(RuntimeError, match="publication failed"):
            add()
    assert set(gui._handles) == handles_before
    assert set(gui._root_children) == children_before


def test_disconnected_gui_update_and_sync_failure_leave_state_unchanged(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkbox = server.gui.add_checkbox("Shared", True)
    timestamp = checkbox.update_timestamp
    message = _messages.GuiUpdateMessage(checkbox.id, {"value": False})

    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: None)
    asyncio.run(server.gui._handle_gui_updates(ClientId(10), message))
    assert checkbox.value is True
    assert checkbox.update_timestamp == timestamp

    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())

    def fail(_: _messages.Message) -> bool:
        raise RuntimeError("sync failed")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message", fail)
    with pytest.raises(RuntimeError, match="sync failed"):
        asyncio.run(server.gui._handle_gui_updates(ClientId(10), message))
    assert checkbox.value is True
    assert checkbox.update_timestamp == timestamp


def test_container_lifecycle_queue_failures_change_nothing(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_folder("Folder") as folder:
        child = server.gui.add_text("Child", "")
    tabs = server.gui.add_tab_group()
    tab = tabs.add_tab("Tab")
    modal = server.gui.add_modal("Modal")

    def fail(_: _messages.Message) -> bool:
        raise RuntimeError("queue failed")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message", fail)
    with pytest.raises(RuntimeError, match="queue failed"):
        folder.remove()
    assert not folder._impl.removed
    assert child.id in folder._impl.children

    with pytest.raises(RuntimeError, match="queue failed"):
        tabs.add_tab("Rejected")
    assert list(tabs._impl.children) == [tab.id]

    with pytest.raises(RuntimeError, match="queue failed"):
        tabs.remove()
    assert not tabs._impl.removed and not tab._impl.removed
    with pytest.raises(RuntimeError, match="queue failed"):
        modal.close()
    assert not modal._impl.removed


def test_container_removal_queues_once_and_retires_the_local_subtree(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_folder("Folder") as folder:
        child = server.gui.add_text("Child", "")
        with server.gui.add_folder("Inner") as inner:
            leaf = server.gui.add_checkbox("Leaf", True)
    sent: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    folder.remove()

    assert sent == [_messages.GuiRemoveMessage(folder.id, (child.id, inner.id, leaf.id))]
    assert all(handle._impl.removed for handle in (folder, child, inner, leaf))
    assert server.gui._handles == {}
    assert server.gui._root_children == {}


def test_gui_remove_and_update_are_linearized(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = server.gui.add_checkbox("Concurrent", True)
    remove_queued = threading.Event()
    release_remove = threading.Event()
    sent: list[_messages.Message] = []

    def queue(message: _messages.Message) -> bool:
        sent.append(message)
        if isinstance(message, _messages.GuiRemoveMessage):
            remove_queued.set()
            assert release_remove.wait(2.0)
        return True

    monkeypatch.setattr(server.gui._websock_interface, "queue_message", queue)
    update_errors: list[BaseException] = []

    def update() -> None:
        try:
            handle.value = False
        except BaseException as error:
            update_errors.append(error)

    remove_thread = threading.Thread(target=handle.remove)
    update_thread = threading.Thread(target=update)
    remove_thread.start()
    assert remove_queued.wait(2.0)
    update_thread.start()
    time.sleep(0.05)
    assert update_thread.is_alive()
    release_remove.set()
    remove_thread.join(2.0)
    update_thread.join(2.0)

    assert len(update_errors) == 1
    assert isinstance(update_errors[0], RuntimeError)
    assert [type(message) for message in sent] == [_messages.GuiRemoveMessage]
    assert handle._impl.removed


def test_concurrent_double_remove_queues_one_lifecycle_message(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = server.gui.add_checkbox("Concurrent", True)
    barrier = threading.Barrier(3)
    sent: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    def remove() -> None:
        barrier.wait()
        handle.remove()  # The later of the two warns and does nothing else.

    threads = [threading.Thread(target=remove) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(2.0)

    assert sum(isinstance(message, _messages.GuiRemoveMessage) for message in sent) == 1
    assert handle._impl.removed


def test_programmatic_callback_failure_does_not_escape_or_suppress_peers(
    server: leika.Server, capsys: pytest.CaptureFixture[str]
) -> None:
    handle = server.gui.add_checkbox("Callbacks", True)
    seen: list[bool] = []

    @handle.on_update
    def fail(_: leika.GuiEvent[Any]) -> None:
        raise RuntimeError("programmatic callback failed")

    @handle.on_update
    def continue_dispatch(event: leika.GuiEvent[Any]) -> None:
        seen.append(event.value)

    handle.value = False

    _wait_for(lambda: seen == [False])
    output = ""
    deadline = time.monotonic() + 2.0
    while "RuntimeError: programmatic callback failed" not in output:
        output += capsys.readouterr().err
        if time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    assert "RuntimeError: programmatic callback failed" in output


def test_notification_update_and_remove_are_linearized(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    notification = server.gui.add_notification("Initial", auto_close_seconds=None)
    remove_queued = threading.Event()
    release_remove = threading.Event()
    sent: list[_messages.Message] = []

    def queue(message: _messages.Message) -> bool:
        sent.append(message)
        if isinstance(message, _messages.RemoveNotificationMessage):
            remove_queued.set()
            assert release_remove.wait(2.0)
        return True

    monkeypatch.setattr(server.gui._websock_interface, "queue_message", queue)
    update_errors: list[BaseException] = []
    remove_thread = threading.Thread(target=notification.remove)

    def update() -> None:
        try:
            notification.title = "Too late"
        except BaseException as error:
            update_errors.append(error)

    remove_thread.start()
    assert remove_queued.wait(2.0)
    update_thread = threading.Thread(target=update)
    update_thread.start()
    assert update_thread.is_alive()
    release_remove.set()
    remove_thread.join(2.0)
    update_thread.join(2.0)

    assert len(update_errors) == 1
    assert isinstance(update_errors[0], RuntimeError)
    assert notification.title == "Initial"
    assert [type(message) for message in sent] == [_messages.RemoveNotificationMessage]


class _FakeTimer:
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class _FakeLoop:
    """Runs scheduled work on demand, so expiry can be stepped through."""

    def __init__(self) -> None:
        self.pending: list[tuple[Any, tuple[Any, ...]]] = []
        self.timers: list[tuple[float, Any]] = []
        self.handles: list[_FakeTimer] = []

    def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
        self.pending.append((callback, args))

    def call_later(self, delay: float, callback: Any) -> _FakeTimer:
        self.timers.append((delay, callback))
        self.handles.append(_FakeTimer())
        return self.handles[-1]

    def live(self) -> int:
        return sum(not handle.cancelled for handle in self.handles)

    def drain(self) -> None:
        while self.pending:
            callback, args = self.pending.pop(0)
            callback(*args)


def test_notification_expiry_mirrors_browser_updates(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _FakeLoop()
    monkeypatch.setattr(server.gui, "_event_loop", loop)
    sent: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    def removals() -> int:
        return sum(isinstance(message, _messages.RemoveNotificationMessage) for message in sent)

    handle = server.gui.add_notification("Working", auto_close_seconds=5.0)
    loop.drain()
    delay, initial = loop.timers[-1]
    assert delay == 5.0

    # Every update restarts the deadline, even one that changes nothing, and
    # the replaced deadline is cancelled.
    handle.title = "Still working"
    initial()
    assert removals() == 0
    loop.drain()
    published = len(sent)
    handle.title = "Still working"
    loop.drain()
    assert len(sent) == published + 1
    assert loop.live() == 1
    restarted = loop.timers[-1][1]

    # Loading suppresses expiry; None and zero are persistent.
    for persistent in ({"loading": True}, {"loading": False, "auto_close_seconds": None}):
        timers = len(loop.timers)
        handle.update(**persistent)
        loop.drain()
        assert len(loop.timers) == timers
    restarted()
    assert removals() == 0
    handle.auto_close_seconds = 0
    loop.drain()

    props = handle._impl.props
    for invalid in (-1, float("nan"), float("inf"), True, 2_147_483.648):
        with pytest.raises((TypeError, ValueError)):
            handle.auto_close_seconds = invalid  # type: ignore[assignment]
        assert handle._impl.props is props

    # The deadline removes the notification, once, and unregisters it.
    handle.auto_close_seconds = 1
    loop.drain()
    expire = loop.timers[-1][1]
    expire()
    assert handle._impl.removed and handle.id not in server.gui._handles
    expire()
    assert removals() == 1

    # A timer racing an explicit removal publishes nothing more.
    racing = server.gui.add_notification("Racing", auto_close_seconds=1)
    loop.drain()
    racing.remove()
    loop.drain()
    assert loop.live() == 0
    loop.timers[-1][1]()
    assert removals() == 2


def test_notification_timeout_matches_javascript_timer_range(
    server: leika.Server,
) -> None:
    maximum = notification_impl._MAX_AUTO_CLOSE_SECONDS
    notification = server.gui.add_notification("Timer", auto_close_seconds=maximum, loading=True)
    assert notification.auto_close_seconds == maximum
    with pytest.raises(ValueError, match="2147483.647"):
        notification.auto_close_seconds = maximum + 0.001
    assert notification.auto_close_seconds == maximum
    with pytest.raises(ValueError, match="2147483.647"):
        server.gui.add_notification("Too long", auto_close_seconds=maximum + 0.001)


def test_live_props_preserve_semantic_invariants_and_update_atomically(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    slider = server.gui.add_slider("Range", 0.5, min=0.0, max=1.0, step=0.1)
    messages: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(messages))

    slider.update(min=0.25, max=0.75, step=0.05)
    assert (slider.min, slider.max, slider.step) == (0.25, 0.75, 0.05)
    assert len(messages) == 1
    update = messages[-1]
    assert isinstance(update, _messages.GuiUpdateMessage)
    assert update.updates == {"min": 0.25, "max": 0.75, "step": 0.05}

    before = slider._impl.props
    messages.clear()
    for invalid in ({"step": 0}, {"min": 0.6, "max": 0.5}, {"max": 0.4}):
        with pytest.raises(ValueError):
            slider.update(**invalid)
        assert slider._impl.props is before
        assert messages == []

    slider.marks = (0.25, (0.75, "high"))  # type: ignore[assignment]
    assert slider.marks == (
        _messages.GuiSliderMark(0.25, None),
        _messages.GuiSliderMark(0.75, "high"),
    )
    marked = slider._impl.props
    for marks in ((float("inf"),), ((0.0, 1),), (object(),)):
        with pytest.raises((TypeError, ValueError)):
            slider.marks = marks  # type: ignore[assignment]
        assert slider._impl.props is marked

    command = server.gui.add_command("Run")
    command.update(hotkey="K", modifier="shift+cmd/ctrl")  # type: ignore[arg-type]
    assert command.hotkey == "K"
    assert command.modifier == "cmd/ctrl+shift"
    command_before = command._impl.props
    messages.clear()
    with pytest.raises(ValueError, match="modifier requires hotkey"):
        command.hotkey = None
    assert command._impl.props is command_before
    assert messages == []

    text = server.gui.add_text("Notes", "", multiline=True)
    with pytest.raises(ValueError, match="positive integer"):
        text.rows = 0
    with pytest.raises(ValueError, match="read-only"):
        text.markdown = True
    assert (text.rows, text.markdown, text.editable) == (None, False, True)


def test_disabled_or_hidden_controls_reject_stale_client_actions(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_messages: list[_messages.Message] = []
    client = SimpleNamespace(
        _websock_connection=SimpleNamespace(queue_message=client_messages.append)
    )
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)

    checkbox = server.gui.add_checkbox("Disabled", False, disabled=True)
    hidden = server.gui.add_checkbox("Hidden", False, visible=False)
    read_only = server.gui.add_text("Read only", "fixed", editable=False)
    updates: list[bool] = []
    checkbox.on_update(lambda event: updates.append(event.value))
    _browser_update(server, checkbox, True)
    _browser_update(server, hidden, True)
    _browser_update(server, read_only, "forged")
    assert (checkbox.value, hidden.value, read_only.value) == (False, False, "fixed")
    assert updates == []

    button = server.gui.add_button("Hold", disabled=True)
    holds: list[bool] = []
    button.on_hold(lambda event: holds.append(True))
    asyncio.run(
        server.gui._handle_gui_button_hold(
            ClientId(1), _messages.GuiButtonHoldMessage(button.id, 10.0)
        )
    )
    assert holds == []

    warm_calls: list[object] = []
    preview = server.gui.add_preview_button("Preview", b"x", filename="x.txt", disabled=True)
    monkeypatch.setattr(preview, "_warm", warm_calls.append)
    asyncio.run(
        server.gui._handle_gui_preview_warm(
            ClientId(1), _messages.GuiPreviewWarmMessage(preview.id)
        )
    )
    assert warm_calls == []


def test_file_button_press_is_single_flight_and_preserves_manual_disable(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def content(_: leika.GuiEvent[Any]) -> bytes:
        calls.append(1)
        started.set()
        assert release.wait(2.0)
        return b"payload"

    client = SimpleNamespace(send_file_download=lambda *args, **kwargs: None)
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)
    handle = server.gui.add_download_button("Export", content, filename="payload.bin")
    message = _messages.GuiUpdateMessage(handle.id, {"value": True})
    errors: list[BaseException] = []

    def press(client_id: int) -> None:
        try:
            asyncio.run(server.gui._handle_gui_updates(ClientId(client_id), message))
        except BaseException as error:
            errors.append(error)

    first = threading.Thread(target=press, args=(1,))
    first.start()
    assert started.wait(2.0)
    assert handle._busy is True

    # A second browser cannot enter the producer while the first owns it.
    second = threading.Thread(target=press, args=(2,))
    second.start()
    second.join(2.0)
    assert not second.is_alive()
    assert calls == [1]

    # Busy is not `disabled`, so the caller's own setting survives the press.
    handle.disabled = True
    release.set()
    first.join(2.0)
    assert errors == []
    assert handle._busy is False
    assert handle.disabled is True

    blocked_calls: list[bool] = []
    blocked = server.gui.add_download_button(
        "Blocked",
        lambda _: blocked_calls.append(True) or b"x",
        filename="x.bin",
        disabled=True,
    )
    _browser_update(server, blocked, True, client=3)
    assert blocked_calls == []


def test_gui_reset_is_one_admission_before_local_retirement(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_folder("Folder") as folder:
        child = server.gui.add_checkbox("Child", True)
    with server.gui.add_modal("Modal") as modal:
        modal_child = server.gui.add_text("Text", "value")
    command = server.gui.add_command("Command")
    notification = server.gui.add_notification("Notice", auto_close_seconds=None)
    handles = (folder, child, modal, modal_child, command, notification)

    def reject(_: Any) -> None:
        raise RuntimeError("reset batch rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="reset batch rejected"):
        server.gui.reset()
    assert not any(handle._impl.removed for handle in handles)

    batches: list[list[_messages.Message]] = []
    monkeypatch.setattr(
        server.gui._websock_interface,
        "queue_messages_or_raise",
        lambda messages: batches.append(list(messages)),
    )
    server.gui.reset()
    assert batches == [
        [
            _messages.GuiRemoveMessage(folder.id, (child.id,)),
            _messages.GuiCloseModalMessage(modal.id, (modal_child.id,)),
            _messages.RemoveCommandMessage(command.id),
            _messages.RemoveNotificationMessage(notification.id),
        ]
    ]
    assert all(handle._impl.removed for handle in handles)
    assert server.gui._handles == {} and server.gui._root_children == {}


def test_command_shorthand_and_hotkey_rules(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran = threading.Event()
    command = server.gui.add_command("Run", ran.set, hotkey="R", icon=leika.Icon.PLAY)
    assert str(command) == command.id
    assert command._icon_html is not None
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    trigger = _messages.CommandTriggerMessage(command.id)
    asyncio.run(server.gui._handle_command_trigger(ClientId(1), trigger))
    assert ran.wait(2.0)
    command.disabled = True
    ran.clear()
    asyncio.run(server.gui._handle_command_trigger(ClientId(1), trigger))
    assert not ran.is_set()
    with pytest.raises(ValueError, match="modifier requires hotkey"):
        server.gui.add_command("Bad", modifier="shift")
    with pytest.raises(ValueError, match="Unknown modifier"):
        command.modifier = "meta"  # type: ignore[assignment]
    command.icon = None
    assert command._icon_html is None


def test_plotly_config_snapshot_is_isolated_across_scopes(
    server: leika.Server,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    config: dict[str, Any] = {
        "displayModeBar": False,
        "modeBarButtonsToRemove": ["zoom"],
    }
    handles = (
        server.gui.add_plotly(go.Figure(), config=config),
        server.panes.add_plotly(go.Figure(), config=config, pane_id="direct-config"),
        server.panes.add_row().add_plotly(go.Figure(), config=config, pane_id="group-config"),
        server.panes.add_grid(columns=1).add_plotly(
            go.Figure(), config=config, pane_id="grid-config"
        ),
    )
    config["displayModeBar"] = True
    config["modeBarButtonsToRemove"].append("pan")

    gui, *panes = handles
    retained_configs = [
        json.loads(props._plotly_json_str).get("config")
        for props in (gui._impl.props, *(pane._props for pane in panes))
    ]
    assert all(
        retained
        == {
            "displayModeBar": False,
            "modeBarButtonsToRemove": ["zoom"],
        }
        for retained in retained_configs
    )
    for handle in handles:
        handle.figure = go.Figure(go.Scatter(y=[1, 2]))


@pytest.mark.plotly
def test_plotly_handles_retain_only_independent_json_snapshots(
    server: leika.Server,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    gui_source = go.Figure(go.Scatter(y=[1, 2]))
    pane_source = go.Figure(go.Bar(y=[3, 4]))
    gui_ref = weakref.ref(gui_source)
    pane_ref = weakref.ref(pane_source)
    gui = server.gui.add_plotly(gui_source, config={"displayModeBar": False})
    pane = server.panes.add_plotly(
        pane_source,
        config={"displayModeBar": False},
        pane_id="plotly-owned-json",
    )

    gui_source.add_trace(go.Bar(y=[9]))
    pane_source.add_trace(go.Scatter(y=[8]))
    gui_read = gui.figure
    pane_read = pane.figure
    assert gui_read is not gui_source and len(gui_read.data) == 1
    assert pane_read is not pane_source and len(pane_read.data) == 1

    # Mutating a getter result is also caller-local until it is explicitly
    # assigned back.
    gui_read.add_trace(go.Bar(y=[7]))
    pane_read.add_trace(go.Scatter(y=[6]))
    assert len(gui.figure.data) == 1
    assert len(pane.figure.data) == 1

    del gui_read, pane_read, gui_source, pane_source
    gc.collect()
    assert gui_ref() is None
    assert pane_ref() is None
    assert json.loads(gui._impl.props._plotly_json_str)["config"] == {"displayModeBar": False}
    assert json.loads(pane._props._plotly_json_str)["config"] == {"displayModeBar": False}


@pytest.mark.plotly
def test_plotly_snapshot_getters_ignore_mutable_global_default_template(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    pio = pytest.importorskip("plotly.io")
    source = go.Figure(go.Scatter(y=[1, 2]))
    source.layout.template = None
    gui = server.gui.add_plotly(source)
    pane = server.panes.add_plotly(source, pane_id="template-free-getter")
    assert "template" not in json.loads(gui._impl.props._plotly_json_str)["layout"]
    assert "template" not in json.loads(pane._props._plotly_json_str)["layout"]

    template_name = "leika_oversized_getter_default"
    old_default = pio.templates.default
    pio.templates[template_name] = go.layout.Template(layout={"title": {"text": "global" * 2_000}})
    pio.templates.default = template_name
    try:
        gui_read = gui.figure
        pane_read = pane.figure
        assert "template" not in gui_read.to_dict()["layout"]
        assert "template" not in pane_read.to_dict()["layout"]

        gui_read.data[0].y = [3, 4]
        pane_read.data[0].y = [5, 6]
        gui.figure = gui_read
        pane.figure = pane_read
        assert "template" not in json.loads(gui._impl.props._plotly_json_str)["layout"]
        assert "template" not in json.loads(pane._props._plotly_json_str)["layout"]
    finally:
        pio.templates.default = old_default
        del pio.templates[template_name]


def test_refresh_bindings_acknowledge_same_value_and_bound_client_history(server):
    control = server.gui.add_slider("Frame", initial_value=0, min=0, max=10, step=1)
    pane = server.panes.add_image(np.full((8, 8, 3), 80, np.uint8))
    pane.invalidate_on(control)
    connection = _client_connection_stub(server, ClientId(12))
    client = ClientHandle(connection, server)
    server._connected_clients[12] = client
    seen = []

    @control.on_update
    def changed(event):
        seen.append(event.value)
        pane.update(np.zeros((8, 8, 3), np.uint8), loading=True)

    def request(value, request_id):
        asyncio.run(
            server.gui._handle_gui_refresh(
                ClientId(12),
                _messages.GuiRefreshMessage(control._impl.uuid, {"value": value}, request_id),
            )
        )
        buffer = server._websock_server.get_message_buffer()
        updates = [
            m
            for m in buffer.message_from_id.values()
            if isinstance(m, _messages.ViewportPaneUpdateMessage) and m.pane_id == pane.pane_id
        ]
        return updates[-1].updates

    first = request(1, "first")
    assert first["_refresh_controls"] == (control._impl.uuid,)
    assert first["_refresh_requests"] == ("first",)
    assert first["loading"] is True
    assert first["_data"] == pane._props._data
    second = request(1, "same-value")
    assert second["_refresh_revision"] > first["_refresh_revision"]
    assert second["_refresh_requests"] == ("same-value",)
    assert seen == [1]
    for i in range(100):
        request(1, f"repeat-{i}")
    assert len(pane._refresh_requests) == 1
    assert (
        len(
            [
                m
                for m in server._websock_server.get_message_buffer().message_from_id.values()
                if isinstance(m, _messages.ViewportPaneUpdateMessage) and m.pane_id == pane.pane_id
            ]
        )
        <= 3
    )
    server._connected_clients.clear()
    server._connected_clients[13] = ClientHandle(
        _client_connection_stub(server, ClientId(13)), server
    )
    pane._ack_refresh(control._impl.uuid, "reconnected", 13)
    assert pane._refresh_requests == {13: "reconnected"}


def test_refresh_binding_rejects_removed_or_private_control_and_prunes_old(server):
    pane = server.panes.add_image(np.zeros((8, 8, 3), np.uint8))
    first = server.gui.add_button("First")
    pane.invalidate_on(first)
    first.remove()
    with pytest.raises(ValueError):
        pane.invalidate_on(first)
    second = server.gui.add_button("Second")
    pane.invalidate_on(second)
    assert tuple(pane._refresh_controls) == (second._impl.uuid,)
    client = ClientHandle(_client_connection_stub(server, ClientId(1)), server)
    private = client.gui.add_button("Private")
    with pytest.raises(ValueError):
        pane.invalidate_on(private)
    with pytest.raises(TypeError):
        pane.invalidate_on(object())


def test_pane_size_feedback_ignores_invalid_dimensions_and_other_pages(server):
    pane = server.panes.add_image(np.zeros((8, 8, 3), np.uint8))
    page_id = pane._panes._page_id
    connection = _client_connection_stub(server, ClientId(12))
    connection.delivery_scope = lambda: page_id
    client = ClientHandle(connection, server)
    server._connected_clients[12] = client
    assert client.pane_size(pane) is None
    server._handle_pane_viewport(
        ClientId(12), _messages.PaneViewportMessage(page_id, pane.pane_id, 640, 480)
    )
    assert client.pane_size(pane) == (640, 480)
    server._handle_pane_viewport(
        ClientId(12), _messages.PaneViewportMessage(page_id, pane.pane_id, -1, 480)
    )
    server._handle_pane_viewport(
        ClientId(12), _messages.PaneViewportMessage("other", pane.pane_id, 320, 240)
    )
    assert client.pane_size(pane) == (640, 480)
    connection.delivery_scope = lambda: "other"
    assert client.pane_size(pane) == (0, 0)


def test_per_frame_jpeg_quality_changes_only_display_encoding(server):
    image = np.random.default_rng(2).integers(0, 255, (240, 320, 3), dtype=np.uint8)
    pane = server.panes.add_image(image, format="jpeg", jpeg_quality=90)
    original_bytes = pane._props._data
    pane.update(image, jpeg_quality=30)
    assert len(pane._props._data) < len(original_bytes) / 2
    np.testing.assert_array_equal(pane.image, image)
    pane.update(image)
    assert pane._props._data == original_bytes
    with pytest.raises(ValueError):
        pane.update(image, jpeg_quality=101)
