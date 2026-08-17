from __future__ import annotations

import asyncio
import dataclasses
import gc
import inspect
import json
import sys
import threading
import time
import weakref
from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import leika
import leika._gui_api as gui_api_impl
import leika._gui_handles as gui_handles_impl
import leika._notification_handle as notification_impl
import leika._panes as panes_impl
from leika import _messages
from leika._server import ClientHandle
from leika.infra import ClientId


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


def test_internal_icon_and_hold_updates_roll_back_on_queue_failure(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    button = server.gui.add_button("Button")
    upload = server.gui.add_upload_button("Upload")
    command = server.gui.add_command("Command")

    def reject(_: _messages.Message) -> None:
        raise RuntimeError("queue rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    for handle in (button, upload, command):
        props_before = dataclasses.replace(handle._impl.props)
        with pytest.raises(RuntimeError, match="queue rejected"):
            handle.icon = leika.Icon.PLAY
        assert handle.icon is None
        assert handle._impl.props == props_before

    callback = lambda _: None
    hold_props = dataclasses.replace(button._impl.props)
    with pytest.raises(RuntimeError, match="queue rejected"):
        button.on_hold(callback, callback_hz=20.0)
    assert button._hold_cbs_from_freq == {}
    assert button._impl.props == hold_props

    monkeypatch.setattr(
        server.gui._websock_interface,
        "queue_message_or_raise",
        lambda _: None,
    )
    button.on_hold(callback, callback_hz=20.0)
    assert button._hold_cbs_from_freq == {20.0: [callback]}
    assert button._hold_callback_freqs == (20.0,)

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    props_before = dataclasses.replace(button._impl.props)
    with pytest.raises(RuntimeError, match="queue rejected"):
        button.remove_hold_callback(callback, callback_hz=20.0)
    assert button._hold_cbs_from_freq == {20.0: [callback]}
    assert button._impl.props == props_before


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
        await server.gui._dispatch_file_upload_completion(
            (
                ClientId(1),
                upload,
                leika.UploadedFile("file.bin", b"contents"),
                (upload_callback,),
            )
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
    assert sorted(seen) == ["dropdown", "form", "input", "text"]


def test_programmatic_callback_result_rejected_by_closed_loop_is_closed_and_reported(
    server: leika.Server,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def returned_coroutine() -> None:
        return None

    result = returned_coroutine()
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    gui_handles_impl._schedule_callback_result(closed_loop, server, result)

    assert inspect.getcoroutinestate(result) == inspect.CORO_CLOSED
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


def test_form_action_buttons_stay_below_fields_without_fallible_restamps(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actions use one finite terminal order; later children need no update."""
    with server.gui.add_form() as form:
        first = server.gui.add_text("Name", initial_value="Ada")
        last = server.gui.add_checkbox("Subscribe", initial_value=False)
    assert form.actions.order == sys.float_info.max
    assert form.actions.order > last.order > first.order

    buffer = server._websock_server.get_message_buffer()
    before_ids = set(buffer.message_from_id)
    before_count = server.gui._live_component_count
    before_resources = dict(server.gui._resource_from_gui_uuid)
    before_baselines = dict(server.gui._reset_baseline_resource_from_gui_uuid)
    original_queue = server.gui._websock_interface.queue_message_or_raise

    def reject_child(message: _messages.Message) -> None:
        if isinstance(message, _messages.GuiTextMessage):
            raise RuntimeError("child queue rejected")
        original_queue(message)

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject_child)
    with pytest.raises(RuntimeError, match="child queue rejected"):
        form.add_text("Rejected", initial_value="")
    assert not form._impl.removed
    assert server.gui._live_component_count == before_count
    assert server.gui._resource_from_gui_uuid == before_resources
    assert server.gui._reset_baseline_resource_from_gui_uuid == before_baselines
    assert set(buffer.message_from_id) == before_ids

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", original_queue)
    before_success = set(buffer.message_from_id)
    added = form.add_text("Nickname", initial_value="")
    published = [
        message
        for message_id, message in buffer.message_from_id.items()
        if message_id not in before_success
    ]
    assert not any(
        isinstance(message, _messages.GuiUpdateMessage)
        and message.uuid == form.actions.id
        and "order" in message.updates
        for message in published
    )
    assert form.actions.order == sys.float_info.max
    assert form.actions.order > added.order > last.order

    before_tie = buffer.message_from_id.copy()
    before_count = server.gui._live_component_count
    before_resources = dict(server.gui._resource_from_gui_uuid)
    with pytest.raises(ValueError, match="reserved for a form's Reset/Submit"):
        form.add_text("Tied", "", order=sys.float_info.max)
    assert buffer.message_from_id == before_tie
    assert server.gui._live_component_count == before_count
    assert server.gui._resource_from_gui_uuid == before_resources

    old_order = added.order
    with pytest.raises(ValueError, match="reserved for a form's Reset/Submit"):
        added.order = sys.float_info.max
    assert added.order == old_order
    assert buffer.message_from_id == before_tie

    outside = server.gui.add_text("Outside", "", order=sys.float_info.max)
    assert outside.order == sys.float_info.max

    action_props = dataclasses.replace(form.actions._impl.props)
    action_buffer = buffer.message_from_id.copy()
    action_resource = server.gui._resource_total
    with pytest.raises(ValueError, match="actions must keep their terminal order"):
        form.actions.order = 0.0
    assert form.actions._impl.props == action_props
    assert buffer.message_from_id == action_buffer
    assert server.gui._resource_total == action_resource

    with pytest.raises(ValueError, match="actions must keep their terminal order"):
        form.actions.update(order=0.0)
    assert form.actions._impl.props == action_props
    assert buffer.message_from_id == action_buffer
    assert server.gui._resource_total == action_resource

    with pytest.raises(TypeError, match="must be a number"):
        form.actions.update(order=None)
    with pytest.raises(ValueError, match="exactly Reset and Submit"):
        form.actions.options = ("Reset", "Cancel")
    with pytest.raises(ValueError, match="exactly Reset and Submit"):
        form.actions.update(options=("Reset", "Cancel"))
    assert form.actions._impl.props == action_props
    assert buffer.message_from_id == action_buffer
    assert server.gui._resource_total == action_resource


def test_add_form_action_creation_failure_leaves_no_form_ghost(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = server._websock_server.get_message_buffer()
    before_count = server.gui._live_component_count
    before_resources = dict(server.gui._resource_from_gui_uuid)
    before_baselines = dict(server.gui._reset_baseline_resource_from_gui_uuid)
    original_queue = server.gui._websock_interface.queue_message_or_raise
    form_uuid: list[str] = []

    def reject_actions(message: _messages.Message) -> None:
        if isinstance(message, _messages.GuiFormMessage):
            form_uuid.append(message.uuid)
            original_queue(message)
            return
        if isinstance(message, _messages.GuiButtonGroupMessage):
            raise RuntimeError("actions queue rejected")
        original_queue(message)

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject_actions)
    with pytest.raises(RuntimeError, match="actions queue rejected"):
        server.gui.add_form(label="Rejected")

    assert len(form_uuid) == 1
    assert form_uuid[0] not in server.gui._container_handle_from_uuid
    assert server.gui._get_container_uuid() == "root"
    assert server.gui._live_component_count == before_count
    assert server.gui._resource_from_gui_uuid == before_resources
    assert server.gui._reset_baseline_resource_from_gui_uuid == before_baselines
    assert not any(
        isinstance(message, _messages.GuiFormMessage) and message.uuid == form_uuid[0]
        for message in buffer.message_from_id.values()
    )


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

    # The mini renderer has one left-hand control cell. Sibling display rows
    # and nested containers are rejected before publication, even before its
    # one field is declared.
    with server.gui.add_mini_form() as strict:
        with pytest.raises(ValueError, match="direct editable field"):
            strict.add_text(
                None,
                "Ask away",
                editable=False,
                markdown=True,
                multiline=True,
            )
        with pytest.raises(ValueError, match="direct editable field"):
            strict.add_folder("Nested")
        strict.add_text("Query", initial_value="")


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


def test_gui_html_enforces_browser_utf16_limit_on_create_and_update(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_handles_impl, "_GUI_HTML_MAX_UTF16_CODE_UNITS", 2)

    handle = server.gui.add_html("😀")
    assert handle.content == "😀"
    with pytest.raises(ValueError, match="1 Mi-character"):
        handle.content = "😀x"
    assert handle.content == "😀"

    with pytest.raises(ValueError, match="1 Mi-character"):
        server.gui.add_html("😀x")
    with pytest.raises(TypeError, match="must be a string"):
        server.gui.add_html(123)  # type: ignore[arg-type]


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


def test_terminal_gui_handles_reject_state_reads_and_scrub_owned_payloads(
    server: leika.Server,
) -> None:
    frame = np.full((24, 32, 3), 127, dtype=np.uint8)
    image = server.gui.add_image(frame, label="Frame", format="png", jpeg_quality=73)
    download = server.gui.add_download_button("Save", b"payload" * 512, filename="capture.bin")
    command = server.gui.add_command(
        "Run",
        lambda: None,
        description="description" * 128,
        icon=leika.Icon.PLAY,
    )
    notification = server.gui.add_notification("Working", "body" * 256, auto_close_seconds=None)
    ids = (image.id, download.id, command.id, notification.id)

    for handle in (image, download, command, notification):
        handle.remove()

    for read in (
        lambda: image.image,
        lambda: image.label,
        lambda: download.content,
        lambda: download.value,
        lambda: command.label,
        lambda: command.icon,
        lambda: notification.title,
        lambda: notification.body,
    ):
        with pytest.raises(RuntimeError, match="removed"):
            read()

    assert (image.id, download.id, command.id, notification.id) == ids
    assert image._image.size == 0
    assert image._user_format == "auto"
    assert image._jpeg_quality is None
    assert image._impl.props._data == b""
    assert download._content == b""
    assert download._impl.value is None
    assert command._impl.icon is None
    assert command._impl.trigger_cb == []
    assert command._impl.props.label == ""
    assert command._impl.props.description in (None, "")
    assert command._impl.props._icon_html in (None, "")
    assert notification._impl.props.title == ""
    assert notification._impl.props.body == ""


def test_removing_root_components_unlinks_the_owner_registry(server: leika.Server) -> None:
    root = server.gui._container_handle_from_uuid["root"]
    children_before = dict(root._children)
    live_before = server.gui._live_component_count

    for index in range(4):
        handle = server.gui.add_button(f"Temporary {index}")
        assert root._children[handle.id] is handle

        handle.remove()

        assert handle.id not in root._children
        assert root._children == children_before
        assert server.gui._live_component_count == live_before


def test_caller_owned_path_and_primitive_subclasses_are_not_retained(
    server: leika.Server,
    tmp_path: Path,
) -> None:
    class Payload:
        pass

    class RichStr(str):
        pass

    class RichFloat(float):
        pass

    class RichInt(int):
        pass

    class RichBytes(bytes):
        pass

    class RichPath(type(Path())):
        pass

    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    path_payload = Payload()
    path_payload_ref = weakref.ref(path_payload)
    rich_path = RichPath(source)
    rich_path.payload = path_payload

    download = server.gui.add_download_button("Save", rich_path)
    assert download.content == source
    assert type(download.content) is type(Path())

    del rich_path, path_payload
    gc.collect()
    assert path_payload_ref() is None

    provider_path = RichPath(source)
    provider_path.payload = Payload()
    provider = server.gui.add_download_button("Provider", lambda _: provider_path)
    filename, resolved = provider._resolve(leika.GuiEvent(None, None, provider))
    assert filename == source.name
    assert resolved == source
    assert type(resolved) is type(Path())

    root_payload = Payload()
    root_payload_ref = weakref.ref(root_payload)
    rich_root = RichPath(tmp_path)
    rich_root.payload = root_payload
    text = server.gui.add_text("Text", "plain", image_root=rich_root)
    assert text._image_root == tmp_path
    assert type(text._image_root) is type(Path())
    del rich_root, root_payload
    gc.collect()
    assert root_payload_ref() is None
    text.remove()
    assert text._image_root is None

    with pytest.raises(TypeError, match="image_root"):
        server.gui.add_text("Bad root", "plain", image_root="not-a-path")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="filename"):
        server.gui.add_download_button(
            "Bad name",
            b"x",
            filename=RichStr("payload.bin"),
        )
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
    with pytest.raises(ValueError, match="one role per button"):
        server.gui.add_button("Run", color=RichStr("default"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="control_layout"):
        server.gui.configure_theme(control_layout=RichStr("left"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dark_mode"):
        server.gui.configure_theme(dark_mode=RichStr("auto"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="hotkey"):
        server.gui.add_command("Run", hotkey=RichStr("R"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="format"):
        server.gui.add_image(
            np.zeros((1, 1, 3), dtype=np.uint8),
            format=RichStr("png"),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="jpeg_quality"):
        server.gui.add_image(
            np.zeros((1, 1, 3), dtype=np.uint8),
            jpeg_quality=RichInt(80),
        )
    with pytest.raises(ValueError, match="max_bytes"):
        server.gui.add_preview_button(
            "Preview",
            b"x",
            filename="x.txt",
            max_bytes=RichInt(1),
        )


def test_equal_string_subclasses_are_canonicalized_to_declared_options(
    server: leika.Server,
) -> None:
    class RichStr(str):
        pass

    initial = RichStr("A")
    initial.payload = object()
    dropdown = server.gui.add_dropdown("Choice", ("A", "B"), initial_value=initial)
    assert dropdown.value is dropdown.options[0]
    assert type(dropdown.value) is str

    replacement = RichStr("B")
    replacement.payload = object()
    dropdown.value = replacement
    assert dropdown.value is dropdown.options[1]
    assert type(dropdown.value) is str

    buttons = server.gui.add_button(("A", "B"))
    button_value = RichStr("B")
    button_value.payload = object()
    buttons.value = button_value
    assert buttons.value is buttons.options[1]
    assert type(buttons.value) is str

    with server.gui.add_form() as form:
        field = server.gui.add_dropdown(
            "Form choice",
            ("A", "B"),
            initial_value=RichStr("A"),
        )
    assert field._impl.initial_value is field.options[0]
    field.value = RichStr("B")
    form.reset_form()
    assert field.value is field.options[0]
    assert type(field.value) is str


def test_failed_gui_terminal_removal_preserves_readable_payloads(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = np.full((8, 12, 3), 63, dtype=np.uint8)
    image = server.gui.add_image(frame, label="Frame")
    content = b"payload" * 64
    download = server.gui.add_download_button("Save", content, filename="capture.bin")
    command = server.gui.add_command("Run", description="Description", icon=leika.Icon.PLAY)
    notification = server.gui.add_notification("Working", "Still running", auto_close_seconds=None)
    image_data = image._impl.props._data
    command_props = dataclasses.replace(command._impl.props)
    notification_props = dataclasses.replace(notification._impl.props)

    def reject(_: _messages.Message) -> None:
        raise RuntimeError("closed")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    for handle in (image, download, command, notification):
        with pytest.raises(RuntimeError, match="closed"):
            handle.remove()

    np.testing.assert_array_equal(image.image, frame)
    assert image.label == "Frame"
    assert image._impl.props._data == image_data
    assert download.content == content
    assert download.value is False
    assert command.label == "Run"
    assert command.icon == leika.Icon.PLAY
    assert command._impl.props == command_props
    assert notification.title == "Working"
    assert notification.body == "Still running"
    assert notification._impl.props == notification_props
    assert not any(handle._impl.removed for handle in (image, download, command, notification))


@pytest.mark.plotly
def test_server_stop_scrubs_all_retained_gui_and_pane_owners(
    server: leika.Server,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")

    class Figure:
        def savefig(self, output: Any, *, format: str) -> None:
            assert format == "svg"
            output.write(b'<svg xmlns="http://www.w3.org/2000/svg"><text>large</text></svg>')

    text_handle = server.gui.add_text("Text", "value" * 128)
    with server.gui.add_form(label="Form") as form:
        form_field = server.gui.add_text("Baseline", "declaration" * 128)
    image = server.gui.add_image(np.zeros((16, 24, 3), dtype=np.uint8))
    plotly = server.gui.add_plotly(
        go.Figure(go.Scatter(y=[1, 2, 3])), config={"displayModeBar": False}
    )
    tabs = server.gui.add_tab_group()
    tab = tabs.add_tab("Tab label", icon=leika.Icon.PLAY)
    with tab:
        tab_text = server.gui.add_text("Nested", "payload" * 128)
    with server.gui.add_modal("Modal title") as modal:
        modal_text = server.gui.add_html("<strong>modal payload</strong>")
    command = server.gui.add_command(
        "Command", description="description" * 128, icon=leika.Icon.PLAY
    )
    notification = server.gui.add_notification(
        "Notification", "body" * 128, auto_close_seconds=None
    )

    pane_image = server.panes.add_image(np.zeros((16, 24, 3), dtype=np.uint8), pane_id="stop-image")
    pane_plotly = server.panes.add_plotly(go.Figure(go.Bar(y=[3, 2, 1])), pane_id="stop-plotly")
    pane_matplotlib = server.panes.add_matplotlib(Figure(), pane_id="stop-matplotlib")
    stable_ids = (
        text_handle.id,
        form.id,
        form_field.id,
        image.id,
        plotly.id,
        tab.id,
        modal.id,
        command.id,
        notification.id,
        pane_image.pane_id,
        pane_plotly.pane_id,
        pane_matplotlib.pane_id,
    )

    server.stop()

    for read in (
        lambda: text_handle.value,
        lambda: form_field.value,
        lambda: image.image,
        lambda: plotly.figure,
        lambda: tab.icon,
        lambda: tab_text.value,
        lambda: modal_text.content,
        lambda: command.label,
        lambda: notification.title,
        lambda: pane_image.image,
        lambda: pane_plotly.figure,
        lambda: pane_matplotlib.figure,
    ):
        with pytest.raises(RuntimeError, match="removed"):
            read()
    assert (
        text_handle.id,
        form.id,
        form_field.id,
        image.id,
        plotly.id,
        tab.id,
        modal.id,
        command.id,
        notification.id,
        pane_image.pane_id,
        pane_plotly.pane_id,
        pane_matplotlib.pane_id,
    ) == stable_ids

    assert form._impl.removed and form_field._impl.initial_value is None
    assert image._image.size == 0 and image._impl.props._data == b""
    assert plotly._impl.props._plotly_json_str == ""
    assert tab.removed and tab._label == "" and tab._icon is None
    assert modal.closed and modal._children == {} and modal._create_message is None
    assert command._impl.trigger_cb == [] and command._impl.icon is None
    assert notification._impl.props.title == "" and notification._impl.props.body == ""
    assert pane_image._impl.image.size == 0 and pane_image._impl.props._data == b""
    assert pane_plotly._impl.props._plotly_json_str == ""
    assert pane_matplotlib._impl.figure_ref is None
    assert pane_matplotlib._impl.props._svg == ""

    assert server.gui._resource_from_gui_uuid == {}
    assert server.gui._retained_extra_bytes_from_gui_uuid == {}
    assert server.gui._reset_baseline_resource_from_gui_uuid == {}
    assert server.gui._resource_total.collection_items == 0
    assert server.gui._resource_total.text_units == 0
    assert server.gui._resource_total.payload_bytes == 0
    assert server.gui._resource_total.decoded_pixels == 0
    assert server.panes._handle_from_pane_id == {}
    assert server.panes._resource_from_pane_id == {}
    assert server.panes._resource_total.text_units == 0
    assert server.panes._resource_total.payload_bytes == 0
    assert server.panes._resource_total.decoded_pixels == 0
    assert server._gui_retained_units_and_bytes == 0
    assert server._gui_decoded_pixels == 0
    assert server._page_global_decoded_pixels == 0


@pytest.mark.plotly
def test_gui_plotly_terminal_removal_scrubs_figure_config_and_json(
    server: leika.Server,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    figure = go.Figure(go.Scatter(y=[1, 3, 2]))
    handle = server.gui.add_plotly(figure, config={"displayModeBar": False}, aspect=2.0)
    handle_id = handle.id

    handle.remove()

    for read in (lambda: handle.figure, lambda: handle.aspect):
        with pytest.raises(RuntimeError, match="removed"):
            read()
    assert handle.id == handle_id
    assert handle._impl.props._plotly_json_str == ""


@pytest.mark.plotly
def test_failed_gui_plotly_removal_preserves_figure_config_and_json(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    figure = go.Figure(go.Bar(y=[2, 1]))
    handle = server.gui.add_plotly(figure, config={"displayModeBar": False}, aspect=2.0)
    json_before = handle._impl.props._plotly_json_str

    def reject(_: _messages.Message) -> None:
        raise RuntimeError("closed")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message_or_raise", reject)
    with pytest.raises(RuntimeError, match="closed"):
        handle.remove()

    assert handle.figure is not figure
    assert tuple(handle.figure.data[0].y) == (2, 1)
    assert handle.aspect == 2.0
    assert json.loads(handle._impl.props._plotly_json_str)["config"] == {"displayModeBar": False}
    assert handle._impl.props._plotly_json_str == json_before
    assert not handle._impl.removed


def test_theme_defaults_to_following_the_browser_color_scheme(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An app has to ask for a scheme; otherwise the viewer's OS decides.

    The wire value matters as much as the default: ``"auto"`` is what tells the
    client to read ``prefers-color-scheme`` rather than pin a scheme, so a
    bool sent in its place would silently override every viewer.
    """
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    server.gui.configure_theme()
    server.gui.configure_theme(dark_mode=True)
    server.gui.configure_theme(dark_mode=False)

    assert [message.dark_mode for message in sent] == ["auto", True, False]


def test_theme_rejects_unknown_wire_values(server: leika.Server) -> None:
    with pytest.raises(ValueError, match="control_layout"):
        server.gui.configure_theme(control_layout="wide")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dark_mode"):
        server.gui.configure_theme(dark_mode=1)  # type: ignore[arg-type]
    # The removed sidebar layouts fail with the replacement named, not as
    # anonymous typos: code written against 0.3.0 gets told where to go.
    with pytest.raises(ValueError, match="left"):
        server.gui.configure_theme(control_layout="fixed")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="left"):
        server.gui.configure_theme(control_layout="collapsible")  # type: ignore[arg-type]


def test_theme_sends_the_docked_edge_on_the_wire(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The layout is a starting position the client applies verbatim, so the
    wire value is the API value -- no mapping in between to drift."""
    sent: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    server.gui.configure_theme()
    server.gui.configure_theme(control_layout="left")
    server.gui.configure_theme(control_layout="right")

    assert [message.control_layout for message in sent] == ["floating", "left", "right"]


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
        add_a_button("Run", color="inverse")
        add_a_button("Run", color="default")
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
    row = server.gui.add_button(("Reset", "Submit"), color=("default", "inverse"))
    assert row.color == ("default", "inverse")
    # A single role still answers for the whole row, and reads back per button.
    plain = server.gui.add_toggle(("A", "B", "C"), color="default")
    assert plain.color == ("default", "default", "default")

    # Live, with the same latitude as the constructor.
    plain.color = ("inverse", "default", "inverse")
    assert plain.color == ("inverse", "default", "inverse")
    plain.color = "inverse"
    assert plain.color == ("inverse", "inverse", "inverse")

    with pytest.raises(ValueError, match="one role per button"):
        server.gui.add_button(("One", "Two"), color=("inverse",))
    with pytest.raises(ValueError, match="one role per toggle"):
        server.gui.add_toggle(("One", "Two"), color=("inverse", "inverse", "inverse"))
    with pytest.raises(ValueError, match="must be 'default' or 'inverse'"):
        server.gui.add_button(("One", "Two"), color=("inverse", "blue"))  # type: ignore[arg-type]
    # A single button is one button: the sequence form has nothing to spread.
    with pytest.raises(ValueError, match="a single button is one button"):
        server.gui.add_button("Solo", color=("inverse",))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="a single toggle is one toggle"):
        server.gui.add_toggle("Solo", color=("inverse",))  # type: ignore[arg-type]


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


def test_gui_image_format_preparation_is_two_phase_and_race_safe(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = np.zeros((3, 4, 3), dtype=np.uint8)
    image = server.gui.add_image(original, format="auto")
    real_encode = gui_handles_impl.encode_image_binary
    entered = threading.Event()
    release = threading.Event()

    def blocking_encode(
        value: np.ndarray, format: Any, jpeg_quality: int | None = None
    ) -> tuple[str, bytes]:
        if threading.current_thread().name.startswith("format-worker"):
            entered.set()
            assert release.wait(2)
        return real_encode(value, format, jpeg_quality=jpeg_quality)

    monkeypatch.setattr(gui_handles_impl, "encode_image_binary", blocking_encode)
    failures: list[BaseException] = []

    def change_format(target: Any) -> None:
        try:
            target.format = "png"
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=change_format, args=(image,), name="format-worker-replace")
    worker.start()
    assert entered.wait(1)
    replacement = np.full_like(original, 17)
    image.image = replacement
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures.pop(), RuntimeError)
    assert image.format == "auto"
    np.testing.assert_array_equal(image.image, replacement)

    entered.clear()
    release.clear()
    removed = server.gui.add_image(original, format="auto")
    worker = threading.Thread(target=change_format, args=(removed,), name="format-worker-remove")
    worker.start()
    assert entered.wait(1)
    removed.remove()
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures.pop(), RuntimeError)
    assert server._image_preparation_bytes == 0

    admitted = server.gui.add_image(original, format="auto")
    old_data = admitted._data

    def reject(_: object) -> None:
        raise RuntimeError("queue rejected")

    monkeypatch.setattr(admitted._impl.gui_api._websock_interface, "queue_message_or_raise", reject)
    with pytest.raises(RuntimeError, match="queue rejected"):
        admitted.format = "png"
    assert admitted.format == "auto"
    assert admitted._data == old_data
    assert server._image_preparation_bytes == 0


def test_tab_lifecycle_publishes_before_children_and_rolls_back(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = server._websock_server._broadcast_buffer
    tabs = server.gui.add_tab_group()
    group_create = next(
        message
        for message in buffer.message_from_id.values()
        if isinstance(message, _messages.GuiTabGroupMessage) and message.uuid == tabs.id
    )
    assert group_create.props._tabs == ()

    alpha = tabs.add_tab("Alpha")
    with alpha:
        alpha_child = server.gui.add_text("Alpha child", "a")
    alpha.icon = leika.Icon.PLAY
    beta = tabs.add_tab("Beta")
    with beta:
        beta_child = server.gui.add_text("Beta child", "b")

    forged = (_messages.GuiTab("Forged", None, "missing"),)
    with pytest.raises(AttributeError, match="internal state"):
        tabs._tabs = forged
    with pytest.raises(AttributeError, match="internal state"):
        tabs.update(_tabs=forged)

    messages = tuple(buffer.message_from_id.items())
    alpha_declaration_id = next(
        message_id
        for message_id, message in messages
        if isinstance(message, _messages.GuiTabMessage) and message.uuid == alpha.id
    )
    alpha_child_id = next(
        message_id
        for message_id, message in messages
        if isinstance(message, _messages.GuiTextMessage) and message.uuid == alpha_child.id
    )
    beta_declaration_id = next(
        message_id
        for message_id, message in messages
        if isinstance(message, _messages.GuiTabMessage) and message.uuid == beta.id
    )
    beta_child_id = next(
        message_id
        for message_id, message in messages
        if isinstance(message, _messages.GuiTextMessage) and message.uuid == beta_child.id
    )
    assert alpha_declaration_id < alpha_child_id < beta_declaration_id < beta_child_id
    alpha_update = next(
        message
        for message in buffer.message_from_id.values()
        if isinstance(message, _messages.GuiTabUpdateMessage) and message.uuid == alpha.id
    )
    assert alpha_update.icon_html is not None
    assert [descriptor.label for descriptor in tabs._tabs] == ["Alpha", "Beta"]

    alpha.remove()
    assert all(
        getattr(message, "uuid", None) not in {alpha.id, alpha_child.id}
        or isinstance(message, _messages.GuiRemoveMessage)
        for message in buffer.message_from_id.values()
    )
    assert [descriptor.container_id for descriptor in tabs._tabs] == [beta.id]

    old_icon = beta.icon
    old_tabs = tabs._tabs
    old_buffer = buffer.message_from_id.copy()

    def reject(_: Sequence[_messages.Message]) -> None:
        raise RuntimeError("tab lifecycle batch rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="tab lifecycle batch rejected"):
        beta.icon = leika.Icon.PLAY
    assert beta.icon == old_icon
    assert tabs._tabs == old_tabs
    assert buffer.message_from_id == old_buffer


def test_derived_protocol_props_are_internal_only(
    server: leika.Server,
) -> None:
    image = server.gui.add_image(np.zeros((2, 3, 3), dtype=np.uint8), format="png")
    button = server.gui.add_button("Button")
    download = server.gui.add_download_button("Download", b"x", filename="x.bin")
    preview = server.gui.add_preview_button("Preview", b"x", filename="x.txt")
    upload = server.gui.add_upload_button("Upload", icon=leika.Icon.PLAY)
    toggle = server.gui.add_toggle("Toggle", icon=leika.Icon.PLAY)
    command = server.gui.add_command("Command", icon=leika.Icon.PLAY)
    text = server.gui.add_text(None, "source", editable=False, markdown=True)
    tabs = server.gui.add_tab_group()
    tab = tabs.add_tab("Tab")

    attempts: tuple[tuple[Any, str, object], ...] = (
        (image, "_data", b"forged"),
        (image, "_format", "jpeg"),
        (button, "_icon_html", "<svg>forged</svg>"),
        (button, "_hold_callback_freqs", (60.0,)),
        (button, "_prefetch", True),
        (download, "_prefetch", True),
        (preview, "_prefetch", False),
        (upload, "_icon_html", None),
        (toggle, "_icon_html", None),
        (command, "_icon_html", None),
        (text, "_source", "forged"),
        (tabs, "_tabs", (_messages.GuiTab("Forged", None, "missing"),)),
    )
    buffer = server._websock_server._broadcast_buffer
    before_counter = buffer.message_counter
    before_values = {(id(handle), name): getattr(handle, name) for handle, name, _ in attempts}

    for handle, name, value in attempts:
        with pytest.raises(AttributeError, match="internal state"):
            setattr(handle, name, value)
        with pytest.raises(AttributeError, match="internal state"):
            handle.update(**{name: value})

    assert buffer.message_counter == before_counter
    for handle, name, _ in attempts:
        assert getattr(handle, name) == before_values[id(handle), name]
    assert [descriptor.container_id for descriptor in tabs._tabs] == [tab.id]

    # Canonical wire state with no separate backing registry remains mutable
    # through the existing validated transaction.
    row = server.gui.add_button(("One", "Two"))
    row._merge = (False,)
    assert row._merge == (False,)


@pytest.mark.plotly
def test_plotly_json_wire_prop_is_internal_only(server: leika.Server) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    handle = server.gui.add_plotly(go.Figure(go.Scatter(y=[1, 2])))
    before = handle._plotly_json_str
    counter = server._websock_server._broadcast_buffer.message_counter
    with pytest.raises(AttributeError, match="internal state"):
        handle._plotly_json_str = "{}"
    with pytest.raises(AttributeError, match="internal state"):
        handle.update(_plotly_json_str="{}")
    assert handle._plotly_json_str == before
    assert server._websock_server._broadcast_buffer.message_counter == counter


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
    # A fixed range remains valid, but must never emit a zero step.
    assert fixed.step == 0.1
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
            _websock_connection=SimpleNamespace(
                queue_message=acknowledgements[client_id].append,
                queue_message_or_raise=acknowledgements[client_id].append,
            )
        )
        for client_id in acknowledgements
    }
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(broadcast))
    monkeypatch.setattr(server.gui, "_resolve_client", clients.get)

    def start(client_id: int, *, transfer_uuid: str = "same", parts: int = 1) -> None:
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

    server.gui._handle_file_transfer_part(
        ClientId(1), _messages.FileTransferPart(upload.id, "same", 0, b"a")
    )
    assert upload.value.content == b"a"
    assert upload.value.name == "client-1.bin"
    assert len(server.gui._current_file_upload_states) == 1

    # The same transfer UUID from another client remains independent.
    server.gui._handle_file_transfer_part(
        ClientId(2), _messages.FileTransferPart(upload.id, "same", 0, b"c")
    )
    assert upload.value.content == b"c"
    assert server.gui._current_file_upload_states == {}
    assert not any(isinstance(message, _messages.FileTransferPartAck) for message in broadcast)
    assert {client_id: len(messages) for client_id, messages in acknowledgements.items()} == {
        1: 2,
        2: 2,
    }

    # Removing a button releases any incomplete transfer.
    start(1, transfer_uuid="pending", parts=1)
    upload.remove()
    assert server.gui._current_file_upload_states == {}


def test_final_upload_freeze_failure_aborts_without_ack_or_accounting_leak(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = server.gui.add_upload_button("Upload")
    queued: list[_messages.Message] = []
    client = SimpleNamespace(
        _websock_connection=SimpleNamespace(queue_message=_open_recorder(queued))
    )
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)
    server.gui._handle_file_transfer_start(
        ClientId(1),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid="memory",
            filename="data.bin",
            mime_type="application/octet-stream",
            part_count=1,
            size_bytes=1,
        ),
    )
    assert isinstance(queued.pop(), _messages.FileTransferPartAck)

    def fail_freeze(_: bytearray) -> bytes:
        raise MemoryError("simulated conversion pressure")

    monkeypatch.setattr("leika._gui_api._freeze_upload_content", fail_freeze)
    result = server.gui._handle_file_transfer_part(
        ClientId(1),
        _messages.FileTransferPart(upload.id, "memory", 0, b"x"),
    )

    assert result is None
    assert server.gui._current_file_upload_states == {}
    assert server._file_upload_bytes_reserved == 0
    assert upload.value == leika.UploadedFile("", b"")
    assert len(queued) == 1
    assert isinstance(queued[0], _messages.FileTransferAbort)
    assert not isinstance(queued[0], _messages.FileTransferPartAck)


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
    assert server.gui._file_upload_lock is server.gui._lock
    upload = server.gui.add_upload_button("Upload")
    ack_started = threading.Event()
    release_ack = threading.Event()

    def queue_message(message: Any) -> None:
        if isinstance(message, _messages.FileTransferPartAck) and message.transferred_bytes > 0:
            ack_started.set()
            assert release_ack.wait(2.0)

    client = SimpleNamespace(_websock_connection=SimpleNamespace(queue_message=queue_message))
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)
    server.gui._handle_file_transfer_start(
        ClientId(1),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid="race",
            filename="race.bin",
            mime_type="application/octet-stream",
            part_count=1,
            size_bytes=1,
        ),
    )
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
    # Nothing left behind for this context once every block has unwound.
    assert server.gui._container_stack.get() == ()


def test_full_component_graph_depth_is_bounded_transactionally(
    server: leika.Server,
) -> None:
    """Root and modal graphs accept depth 64 and reject every node at 65."""

    buffer = server._websock_server.get_message_buffer()

    def state() -> tuple[object, ...]:
        return (
            buffer.message_counter,
            dict(buffer.message_from_id),
            dict(buffer.id_from_redundancy_key),
            server.gui._live_component_count,
            server.gui._resource_total,
            dict(server.gui._resource_from_gui_uuid),
            dict(server.gui._reset_baseline_resource_from_gui_uuid),
            set(server.gui._gui_input_handle_from_uuid),
            set(server.gui._container_handle_from_uuid),
            dict(server.gui._container_depth_from_uuid),
            server._gui_retained_units_and_bytes,
            server._gui_decoded_pixels,
        )

    def check_graph_root(root: Any, prefix: str) -> None:
        parent = root
        for depth in range(1, 64):
            parent = parent.add_folder(f"{prefix} folder {depth}", order=float(depth))
            assert server.gui._container_depth_from_uuid[parent.id] == depth

        leaf = parent.add_text(f"{prefix} leaf", "", order=-3.0)
        tabs = parent.add_tab_group(order=-2.0)
        deepest_folder = parent.add_folder(f"{prefix} deepest", order=-1.0)
        assert server.gui._container_depth_from_uuid[tabs.id] == 64
        assert server.gui._container_depth_from_uuid[deepest_folder.id] == 64
        assert leaf.id in server.gui._gui_input_handle_from_uuid

        before = state()
        deepest_children = dict(deepest_folder._children)
        with pytest.raises(RuntimeError, match="graph depth cannot exceed 64"):
            deepest_folder.add_text("Too deep", "", order=0.0)
        assert state() == before
        assert deepest_folder._children == deepest_children

        with pytest.raises(RuntimeError, match="graph depth cannot exceed 64"):
            deepest_folder.add_tab_group(order=0.0)
        assert state() == before
        assert deepest_folder._children == deepest_children

        before_tabs = tuple(tabs._tab_handles)
        with pytest.raises(RuntimeError, match="graph depth cannot exceed 64"):
            tabs.add_tab("Too deep")
        assert state() == before
        assert tuple(tabs._tab_handles) == before_tabs

    check_graph_root(server.gui, "root")
    modal = server.gui.add_modal("Depth-root modal")
    assert server.gui._container_depth_from_uuid[modal.id] == 0
    check_graph_root(modal, "modal")


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
                # Give the first task a chance to add while this context is active.
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
    """No create-then-backfill: an image or plot arrives complete.

    The create message used to carry a placeholder that a property assignment
    immediately replaced, so every element cost a second message -- for images,
    a second copy of the encoded bytes.
    """
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


def test_plotly_bootstrap_is_owned_once_across_scopes_and_connections(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local, global, and pane APIs share one bootstrap per browser."""
    plotly = pytest.importorskip("plotly.graph_objects")
    bootstrap = "window.Plotly = {};"
    load_count = 0

    def load_plotly_js() -> str:
        nonlocal load_count
        load_count += 1
        return bootstrap

    monkeypatch.setattr("leika._server._load_plotly_js", load_plotly_js)

    def connect(client_id: int) -> tuple[ClientHandle, list[_messages.Message]]:
        queued: list[_messages.Message] = []
        connection = _client_connection_stub(server, ClientId(client_id), queued)
        client = ClientHandle(connection, server)  # type: ignore[arg-type]
        with server._client_lock:
            server._connected_clients[connection.client_id] = client
        return client, queued

    def bootstraps(messages: list[_messages.Message]) -> list[str]:
        return [
            message.source
            for message in messages
            if isinstance(message, _messages.RunJavascriptMessage)
        ]

    first, first_messages = connect(101)
    _, second_messages = connect(102)

    # A client-local figure initializes that client, not its peers.
    first.gui.add_plotly(plotly.Figure())
    assert bootstraps(first_messages) == [bootstrap]
    assert bootstraps(second_messages) == []

    # A later global figure fills only the missing recipient. A pane uses the
    # same global scope and must not enqueue the runtime again.
    server.gui.add_plotly(plotly.Figure())
    server.panes.add_plotly(plotly.Figure(), pane_id="plotly-bootstrap-test")
    assert bootstraps(first_messages) == [bootstrap]
    assert bootstraps(second_messages) == [bootstrap]

    # Once Plotly is globally required, each later connection is initialized
    # before its local GUI can enqueue a figure.
    late, late_messages = connect(103)
    server._initialize_plotly_connection(late._websock_connection)
    late.gui.add_plotly(plotly.Figure())
    assert bootstraps(late_messages) == [bootstrap]

    broadcast_messages = server._websock_server._broadcast_buffer.message_from_id.values()
    assert not any(
        isinstance(message, _messages.RunJavascriptMessage) for message in broadcast_messages
    )
    assert load_count == 1


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
    entries.on_update(lambda event: seen.append(event.value))
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


@pytest.mark.parametrize(
    ("factory", "initial", "bad"),
    [
        ("add_checkbox", True, "false"),
        ("add_toggle", True, "false"),
        ("add_text", "text", 123),
    ],
)
def test_scalar_value_assignment_rejects_silent_coercion(
    server: leika.Server,
    factory: str,
    initial: object,
    bad: object,
) -> None:
    if factory == "add_toggle":
        handle = server.gui.add_toggle("Strict", initial_value=initial)
    else:
        handle = getattr(server.gui, factory)("Strict", initial)
    with pytest.raises(TypeError):
        handle.value = bad
    assert handle.value == initial


def test_checklist_assignment_requires_exact_checked_bools(server: leika.Server) -> None:
    checklist = server.gui.add_checklist("Strict", [("one", False)])
    with pytest.raises(ValueError, match="checked state is a bool"):
        checklist.value = [("one", "false")]  # type: ignore[list-item]
    assert checklist.value == (("one", False),)


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
    asyncio.run(
        server.gui._handle_gui_updates(
            ClientId(1), _messages.GuiUpdateMessage(handle.id, {"value": bad})
        )
    )
    assert handle.value == 1.0


@pytest.mark.parametrize("factory", ["add_vector2", "add_vector3"])
@pytest.mark.parametrize(
    "bad",
    [
        (True, False),
        ("1", "2"),
    ],
)
def test_vectors_reject_boolean_and_string_components_at_every_boundary(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    factory: str,
    bad: tuple[object, object],
) -> None:
    length = 2 if factory == "add_vector2" else 3
    bad_value = bad if length == 2 else (*bad, 0.0)
    add = getattr(server.gui, factory)
    with pytest.raises(ValueError, match="real numbers"):
        add("Invalid", bad_value)

    handle = add("Vector", (0.0,) * length)
    with pytest.raises(ValueError, match="real numbers"):
        handle.value = bad_value

    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    asyncio.run(
        server.gui._handle_gui_updates(
            ClientId(1),
            _messages.GuiUpdateMessage(handle.id, {"value": list(bad_value)}),
        )
    )
    assert handle.value == (0.0,) * length


def test_assignable_props_reject_schema_invalid_primitives_and_literals(
    server: leika.Server,
) -> None:
    checkbox = server.gui.add_checkbox("Strict", True)
    with pytest.raises(TypeError, match="bool"):
        checkbox.disabled = "no"  # type: ignore[assignment]
    with pytest.raises(TypeError, match="does not match"):
        checkbox.label = 3  # type: ignore[assignment]
    assert checkbox.disabled is False
    assert checkbox.label == "Strict"

    button = server.gui.add_button("Action")
    with pytest.raises(ValueError, match="one of"):
        button.color = "danger"  # type: ignore[assignment]
    assert button.color == "default"


def test_assignable_props_validate_pep604_unions(server: leika.Server) -> None:
    checkbox = server.gui.add_checkbox("PEP 604", True)
    assert checkbox._cast_value_recursive(str | None, "valid") == "valid"
    assert checkbox._cast_value_recursive(str | None, None) is None
    with pytest.raises(TypeError, match="does not match"):
        checkbox._cast_value_recursive(str | None, 3)


def test_vector_live_props_normalize_one_dimensional_numpy_arrays(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector = server.gui.add_vector2("Point", (0.0, 0.0))
    queued: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(queued))

    vector.min = np.array([-1.0, -2.0])
    assert vector.min == (-1.0, -2.0)
    assert queued[-1].updates == {"min": (-1.0, -2.0)}
    with pytest.raises(TypeError, match="one-dimensional tuple"):
        vector.max = np.zeros((2, 1))


def test_color_values_are_length_bounded_before_conversion(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    rgb = server.gui.add_rgb("RGB", (1, 2, 3))
    rgba = server.gui.add_rgba("RGBA", (1, 2, 3, 4))
    messages: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(messages))
    huge_array = np.zeros(1_000_000, dtype=np.uint8)
    monkeypatch.setattr(
        gui_handles_impl.np,
        "asarray",
        lambda *_args, **_kwargs: pytest.fail("color admission called np.asarray"),
    )

    with pytest.raises(ValueError, match="3 color channels"):
        rgb.value = huge_array
    assert rgb.value == (1, 2, 3)
    assert messages == []

    yielded = 0

    def infinite() -> Any:
        nonlocal yielded
        while True:
            yielded += 1
            yield 1

    with pytest.raises(ValueError, match="3 color channels"):
        rgb.value = infinite()
    assert yielded == 4
    assert rgb.value == (1, 2, 3)
    assert messages == []

    class HugeSequence(Sequence[int]):
        touched = False

        def __len__(self) -> int:
            return 1_000_000

        def __getitem__(self, index: int) -> int:
            self.touched = True
            raise AssertionError(index)

    huge_sequence = HugeSequence()
    with pytest.raises(ValueError, match="4 color channels"):
        rgba.value = huge_sequence
    assert not huge_sequence.touched
    assert rgba.value == (1, 2, 3, 4)
    assert messages == []

    rgb.value = (0, 0.5, 300)
    rgba.value = [255, 1.0, -10, 128]
    assert rgb.value == (0, 127, 255)
    assert rgba.value == (255, 255, 0, 128)
    assert len(messages) == 2


def test_tuple_props_bound_ndarrays_before_python_scalar_materialization(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoListArray(np.ndarray):
        tolist_called = False

        def tolist(self) -> Any:
            self.tolist_called = True
            raise AssertionError("oversized ndarray was materialized")

    vector = server.gui.add_vector2("Vector", (0.0, 0.0))
    button_row = server.gui.add_button(("One", "Two"))
    messages: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(messages))

    wrong_fixed = np.zeros(3, dtype=np.float64).view(NoListArray)
    with pytest.raises(TypeError, match="does not match"):
        vector.min = wrong_fixed
    assert not wrong_fixed.tolist_called
    assert vector.min is None
    assert messages == []

    huge_variadic = np.zeros(4097, dtype=np.float64).view(NoListArray)
    with pytest.raises(TypeError, match="array subclasses"):
        button_row._merge = huge_variadic
    assert not huge_variadic.tolist_called
    assert button_row._merge == (True,)
    assert messages == []


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


def test_uploaded_file_is_immutable_and_public_assignment_is_accounted(
    server: leika.Server,
) -> None:
    upload = server.gui.add_upload_button("Upload")
    first = leika.UploadedFile("first.bin", b"abc")
    upload.value = first
    assert upload.value == first
    assert upload.value is not first
    assert server._file_upload_bytes_reserved == 3
    assert server.gui._retained_file_upload_bytes[upload.id] == 3
    with pytest.raises(dataclasses.FrozenInstanceError):
        upload.value.content = b"changed"  # type: ignore[misc]

    second = leika.UploadedFile("second.bin", b"12")
    upload.value = second
    assert upload.value == second
    assert upload.value is not second
    assert server._file_upload_bytes_reserved == 2
    assert server.gui._retained_file_upload_bytes[upload.id] == 2

    object.__setattr__(second, "content", b"external mutation")
    object.__setattr__(second, "extra", bytearray(1024))
    exposed = upload.value
    object.__setattr__(exposed, "content", b"getter mutation")
    object.__setattr__(exposed, "extra", bytearray(1024))
    assert upload.value == leika.UploadedFile("second.bin", b"12")
    assert server._file_upload_bytes_reserved == 2
    assert server.gui._retained_file_upload_bytes[upload.id] == 2

    class RichUpload(leika.UploadedFile):
        pass

    rich = RichUpload("rich.bin", b"x")
    object.__setattr__(rich, "extra", bytearray(1024))
    upload.value = rich
    assert type(upload.value) is leika.UploadedFile
    assert upload.value == leika.UploadedFile("rich.bin", b"x")
    assert upload.value is not rich
    assert server._file_upload_bytes_reserved == 1

    class RichBytes(bytes):
        pass

    with pytest.raises(TypeError, match="content must be bytes"):
        upload.value = leika.UploadedFile("bad.bin", RichBytes(b"x"))
    assert upload.value == leika.UploadedFile("rich.bin", b"x")
    assert server._file_upload_bytes_reserved == 1


def test_upload_assignment_capacity_rejection_queues_nothing(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = server.gui.add_upload_button("Upload")
    queued: list[Any] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(queued))
    monkeypatch.setattr("leika._server._FILE_UPLOAD_AGGREGATE_MAX_BYTES", 2)

    with pytest.raises(ValueError, match="memory limit"):
        upload.value = leika.UploadedFile("large.bin", b"abc")

    assert upload.value == leika.UploadedFile("", b"")
    assert queued == []
    assert server._file_upload_bytes_reserved == 0
    assert server.gui._retained_file_upload_bytes == {}


def test_upload_assignment_queue_failure_rolls_back_accounting_and_state(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = server.gui.add_upload_button("Upload")
    upload.value = leika.UploadedFile("old.bin", b"old")
    old_timestamp = upload.update_timestamp
    # Upload controls are buttons and ordinarily don't echo value assignments.
    # Exercise the shared transaction's queue-failure branch explicitly.
    upload._impl.is_button = False

    def fail(_: Any) -> None:
        raise RuntimeError("queue failed")

    monkeypatch.setattr(server.gui._websock_interface.get_message_buffer(), "push", fail)
    with pytest.raises(RuntimeError, match="queue failed"):
        upload.value = leika.UploadedFile("new.bin", b"new value")

    assert upload.value == leika.UploadedFile("old.bin", b"old")
    assert upload.update_timestamp == old_timestamp
    assert server._file_upload_bytes_reserved == 3
    assert server.gui._retained_file_upload_bytes[upload.id] == 3


def test_gui_creators_register_before_publication_and_roll_back_on_failure(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    gui = server.gui
    published: list[_messages.Message] = []

    def assert_registered(message: _messages.Message) -> bool:
        published.append(message)
        uuid = getattr(message, "uuid", None)
        if isinstance(message, _messages.GuiModalMessage):
            assert uuid in gui._container_handle_from_uuid
            assert uuid in gui._modal_handle_from_uuid
        elif hasattr(message, "container_uuid") and hasattr(message, "props"):
            container_uuid = getattr(message, "container_uuid")
            parent = gui._container_handle_from_uuid[container_uuid]
            assert uuid in parent._children
            if hasattr(message, "value"):
                assert uuid in gui._gui_input_handle_from_uuid
        return True

    monkeypatch.setattr(gui._websock_interface, "queue_message", assert_registered)
    gui.add_text("Text", "")
    gui.add_folder("Folder")
    gui.add_tab_group()
    gui.add_modal("Modal")
    gui.add_image(np.zeros((1, 1, 3), dtype=np.uint8))
    assert published

    parent = gui._container_handle_from_uuid["root"]
    children_before = set(parent._children)
    inputs_before = set(gui._gui_input_handle_from_uuid)
    containers_before = set(gui._container_handle_from_uuid)
    modals_before = set(gui._modal_handle_from_uuid)

    def fail(_: _messages.Message) -> bool:
        raise RuntimeError("publication failed")

    monkeypatch.setattr(gui._websock_interface, "queue_message", fail)
    with pytest.raises(RuntimeError, match="publication failed"):
        gui.add_text("Rejected", "")
    with pytest.raises(RuntimeError, match="publication failed"):
        gui.add_folder("Rejected")
    with pytest.raises(RuntimeError, match="publication failed"):
        gui.add_modal("Rejected")

    assert set(parent._children) == children_before
    assert set(gui._gui_input_handle_from_uuid) == inputs_before
    assert set(gui._container_handle_from_uuid) == containers_before
    assert set(gui._modal_handle_from_uuid) == modals_before


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


def test_container_lifecycle_queue_failures_are_transactional(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = server.gui.add_folder("Folder")
    child = folder.add_text("Child", "")
    tabs = server.gui.add_tab_group()
    tab = tabs.add_tab("Tab")
    modal = server.gui.add_modal("Modal")

    def fail(_: _messages.Message) -> bool:
        raise RuntimeError("queue failed")

    monkeypatch.setattr(server.gui._websock_interface, "queue_message", fail)
    monkeypatch.setattr(
        server.gui._websock_interface,
        "queue_messages_or_raise",
        lambda *_: fail(_messages.GuiRemoveMessage("unused")),
    )
    with pytest.raises(RuntimeError, match="queue failed"):
        folder.remove()
    assert not folder._impl.removed
    assert child.id in folder._children

    registry_before = set(server.gui._container_handle_from_uuid)
    with pytest.raises(RuntimeError, match="queue failed"):
        tabs.add_tab("Rejected")
    assert set(server.gui._container_handle_from_uuid) == registry_before
    assert [existing.id for existing in tabs._tab_handles] == [tab.id]

    with pytest.raises(RuntimeError, match="queue failed"):
        tabs.remove()
    assert not tabs._impl.removed
    assert not tab.removed
    with pytest.raises(RuntimeError, match="queue failed"):
        modal.close()
    assert not modal.closed


def test_container_removal_queues_once_and_retires_the_local_subtree(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = server.gui.add_folder("Folder")
    child = folder.add_text("Child", "")
    sent: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    folder.remove()

    assert len(sent) == 1
    assert isinstance(sent[0], _messages.GuiRemoveMessage)
    assert folder._impl.removed
    assert child._impl.removed
    assert folder.id not in server.gui._container_handle_from_uuid
    assert child.id not in server.gui._gui_input_handle_from_uuid


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
    remove_errors: list[BaseException] = []
    update_errors: list[BaseException] = []

    def remove() -> None:
        try:
            handle.remove()
        except BaseException as error:
            remove_errors.append(error)

    def update() -> None:
        try:
            handle.value = False
        except BaseException as error:
            update_errors.append(error)

    remove_thread = threading.Thread(target=remove)
    update_thread = threading.Thread(target=update)
    remove_thread.start()
    assert remove_queued.wait(2.0)
    update_thread.start()
    time.sleep(0.05)
    assert update_thread.is_alive()
    release_remove.set()
    remove_thread.join(2.0)
    update_thread.join(2.0)

    assert remove_errors == []
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
    errors: list[BaseException] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(sent))

    def remove() -> None:
        barrier.wait()
        try:
            handle.remove()
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=remove) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(2.0)

    assert errors == []
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
    assert handle.value is False
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
    with pytest.raises(RuntimeError, match="removed"):
        _ = notification.title
    assert notification._impl.props.title == ""
    assert notification._impl.props.body == ""
    assert [type(message) for message in sent] == [_messages.RemoveNotificationMessage]


@pytest.mark.plotly
def test_plotly_json_enforces_browser_utf16_limit_transactionally(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    initial = go.Figure(go.Scatter(y=[1, 2]))
    handle = server.gui.add_plotly(initial)
    old_json = handle._impl.props._plotly_json_str

    oversized = go.Figure(go.Scatter(text=["x" * 10_000], y=[1]))
    monkeypatch.setattr(gui_handles_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", 1000)
    with pytest.raises(ValueError, match="16 Mi-character"):
        handle.figure = oversized
    assert handle.figure is not initial
    assert tuple(handle.figure.data[0].y) == (1, 2)
    assert handle._impl.props._plotly_json_str == old_json

    with pytest.raises(ValueError, match="16 Mi-character"):
        server.gui.add_plotly(oversized)

    monkeypatch.setattr(gui_handles_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", 2)
    assert gui_handles_impl._validate_plotly_json_size("\U0001f600") == "\U0001f600"
    with pytest.raises(ValueError, match="16 Mi-character"):
        gui_handles_impl._validate_plotly_json_size("\U0001f600x")


def test_gui_image_rejects_decoded_pixel_overflow_before_encoding(
    server: leika.Server,
) -> None:
    backing = np.zeros((1, 1, 3), dtype=np.uint8)
    oversized = np.lib.stride_tricks.as_strided(
        backing, shape=(4_096, 8_193, 3), strides=(0, 0, 1), writeable=False
    )
    with pytest.raises(ValueError, match="decoded pixels"):
        server.gui.add_image(oversized)


def test_plotly_runtime_loader_is_bounded_and_requires_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    import leika._server as server_impl

    package = tmp_path / "plotly"
    runtime = package / "package_data" / "plotly.min.js"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"x" * 8)
    monkeypatch.setitem(
        sys.modules, "plotly", SimpleNamespace(__file__=str(package / "__init__.py"))
    )
    monkeypatch.setattr(server_impl, "_PLOTLY_JS_MAX_BYTES", 8)
    assert server_impl._load_plotly_js() == "x" * 8

    runtime.write_bytes(b"x" * 9)
    with pytest.raises(ValueError, match="byte limit"):
        server_impl._load_plotly_js()

    runtime.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="valid UTF-8"):
        server_impl._load_plotly_js()


def test_notification_expiry_mirrors_browser_updates_and_is_race_safe() -> None:
    from leika._notification_handle import (
        NotificationHandle,
        _NotificationHandleState,
    )

    class Timer:
        def __init__(self, delay: float, callback: Any) -> None:
            self.delay = delay
            self.callback = callback
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class Loop:
        def __init__(self) -> None:
            self.pending: list[tuple[Any, tuple[Any, ...]]] = []
            self.timers: list[Timer] = []

        def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
            self.pending.append((callback, args))

        def call_later(self, delay: float, callback: Any) -> Timer:
            timer = Timer(delay, callback)
            self.timers.append(timer)
            return timer

        def drain(self) -> None:
            while self.pending:
                callback, args = self.pending.pop(0)
                callback(*args)

    messages: list[_messages.Message] = []
    loop = Loop()
    handle = NotificationHandle(
        _NotificationHandleState(
            websock_interface=SimpleNamespace(queue_message_or_raise=messages.append),
            event_loop=loop,  # type: ignore[arg-type]
            uuid="toast",
            props=_messages.NotificationProps(
                title="Working",
                body="",
                loading=False,
                with_close_button=True,
                auto_close_seconds=5.0,
            ),
            state_lock=threading.RLock(),
        )
    )

    handle._show()
    loop.drain()
    initial_timer = loop.timers[-1]
    assert initial_timer.delay == 5.0

    # Every browser update restarts the deadline, even if it doesn't touch the
    # timeout. The stale callback is inert before its cancellation is installed.
    handle.title = "Still working"
    initial_timer.callback()
    assert not any(isinstance(message, _messages.RemoveNotificationMessage) for message in messages)
    loop.drain()
    restarted_timer = loop.timers[-1]
    assert initial_timer.cancelled

    # Loading suppresses expiry. Returning to a non-loading state starts it.
    handle.loading = True
    restarted_timer.callback()
    loop.drain()
    assert restarted_timer.cancelled
    timer_count = len(loop.timers)
    handle.loading = False
    loop.drain()
    assert len(loop.timers) == timer_count + 1

    # None and zero are both persistent; either can later become timed.
    active_timer = loop.timers[-1]
    handle.auto_close_seconds = None
    loop.drain()
    assert active_timer.cancelled
    timer_count = len(loop.timers)
    handle.auto_close_seconds = 5
    loop.drain()
    assert len(loop.timers) == timer_count + 1
    active_timer = loop.timers[-1]
    handle.auto_close_seconds = 0
    loop.drain()
    assert active_timer.cancelled
    assert len(loop.timers) == timer_count + 1

    prior_props = dataclasses.replace(handle._impl.props)
    prior_messages = list(messages)
    for invalid in (-1, float("nan"), float("inf"), True):
        with pytest.raises((TypeError, ValueError)):
            handle.auto_close_seconds = invalid  # type: ignore[assignment]
        assert handle._impl.props == prior_props
        assert messages == prior_messages

    # A timer racing explicit removal cannot publish a second tombstone.
    handle.auto_close_seconds = 1
    loop.drain()
    racing_timer = loop.timers[-1]
    handle.remove()
    remove_count = sum(
        isinstance(message, _messages.RemoveNotificationMessage) for message in messages
    )
    racing_timer.callback()
    loop.drain()
    assert racing_timer.cancelled
    assert (
        sum(isinstance(message, _messages.RemoveNotificationMessage) for message in messages)
        == remove_count
    )


def test_notification_expiry_scrubs_terminal_state_and_rejects_reads() -> None:
    from leika._notification_handle import (
        NotificationHandle,
        _NotificationHandleState,
    )

    class Timer:
        def __init__(self, callback: Any) -> None:
            self.callback = callback
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class Loop:
        def __init__(self) -> None:
            self.timer: Timer | None = None

        def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
            callback(*args)

        def call_later(self, delay: float, callback: Any) -> Timer:
            assert delay == 1.0
            self.timer = Timer(callback)
            return self.timer

    messages: list[_messages.Message] = []
    retired: list[str] = []
    loop = Loop()
    handle = NotificationHandle(
        _NotificationHandleState(
            websock_interface=SimpleNamespace(queue_message_or_raise=messages.append),
            event_loop=loop,  # type: ignore[arg-type]
            uuid="expiring-toast",
            props=_messages.NotificationProps(
                title="Working",
                body="large body" * 256,
                loading=False,
                with_close_button=True,
                auto_close_seconds=1.0,
            ),
            state_lock=threading.RLock(),
            on_terminal=retired.append,
        )
    )

    handle._show()
    assert loop.timer is not None
    loop.timer.callback()

    assert handle._impl.removed
    assert retired == ["expiring-toast"]
    assert isinstance(messages[-1], _messages.RemoveNotificationMessage)
    for read in (lambda: handle.title, lambda: handle.body):
        with pytest.raises(RuntimeError, match="removed"):
            read()
    assert handle._impl.props.title == ""
    assert handle._impl.props.body == ""
    assert handle._impl.expiry_handle is None


def test_notification_update_is_atomic_when_queue_admission_fails() -> None:
    from leika._notification_handle import (
        NotificationHandle,
        _NotificationHandleState,
    )

    class Loop:
        def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
            callback(*args)

        def call_later(self, delay: float, callback: Any) -> Any:
            return SimpleNamespace(cancel=lambda: None)

    def reject(_: _messages.Message) -> None:
        raise RuntimeError("closed")

    handle = NotificationHandle(
        _NotificationHandleState(
            websock_interface=SimpleNamespace(queue_message_or_raise=reject),
            event_loop=Loop(),  # type: ignore[arg-type]
            uuid="toast",
            props=_messages.NotificationProps(
                title="Original",
                body="",
                loading=False,
                with_close_button=True,
                auto_close_seconds=None,
            ),
            state_lock=threading.RLock(),
        )
    )
    before = dataclasses.replace(handle._impl.props)
    generation = handle._impl.expiry_generation

    with pytest.raises(RuntimeError, match="closed"):
        handle.update(title="Changed", loading=True)

    assert handle._impl.props == before
    assert handle._impl.expiry_generation == generation


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

    before = dataclasses.replace(slider._impl.props)
    messages.clear()
    for invalid in (
        {"step": 0},
        {"min": 0.6, "max": 0.5},
        {"precision": -1},
    ):
        with pytest.raises(ValueError):
            slider.update(**invalid)
        assert slider._impl.props == before
        assert messages == []

    command = server.gui.add_command("Run")
    command.update(hotkey="K", modifier="shift+cmd/ctrl")
    assert command.hotkey == "K"
    assert command.modifier == "cmd/ctrl+shift"
    command_before = dataclasses.replace(command._impl.props)
    messages.clear()
    with pytest.raises(ValueError, match="modifier requires hotkey"):
        command.hotkey = None
    assert command._impl.props == command_before
    assert messages == []

    text = server.gui.add_text("Notes", "", multiline=True)
    with pytest.raises(ValueError, match="positive integer"):
        text.rows = 0
    with pytest.raises(ValueError, match="read-only"):
        text.markdown = True
    assert (text.rows, text.markdown, text.editable) == (None, False, True)


def test_form_initial_values_are_captured_at_field_registration(
    server: leika.Server,
) -> None:
    with server.gui.add_form(label="Profile") as form:
        field = server.gui.add_text("Name", "Ada")
        field.value = "Changed before context exit"

    form.reset_form()
    assert field.value == "Ada"


def test_form_reset_baseline_is_charged_reused_and_released(
    server: leika.Server,
) -> None:
    with server.gui.add_form(label="Profile") as form:
        field = server.gui.add_text("Name", "Declared baseline")

    baseline = server.gui._reset_baseline_resource_from_gui_uuid[field.id]
    assert baseline == gui_handles_impl._gui_resource_cost("Declared baseline", None)
    assert server.gui._resource_from_gui_uuid[field.id] == (
        gui_handles_impl._gui_resource_cost(field.value, field._impl.props) + baseline
    )

    field.value = ""
    before_reset = server.gui._resource_total
    expected = (
        gui_handles_impl._gui_resource_cost(
            "Declared baseline",
            dataclasses.replace(field._impl.props, _source="Declared baseline"),
        )
        + baseline
    )
    form.reset_form()
    assert field.value == "Declared baseline"
    assert server.gui._resource_from_gui_uuid[field.id] == expected
    assert server.gui._resource_total.text_units > before_reset.text_units

    field.remove()
    assert field.id not in server.gui._resource_from_gui_uuid
    assert field.id not in server.gui._reset_baseline_resource_from_gui_uuid


def test_form_reset_resource_rejection_rolls_back_every_field(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_form(label="Profile") as form:
        first = server.gui.add_text("First", "A" * 64)
        second = server.gui.add_text("Second", "B" * 64)
    first.value = ""
    second.value = ""
    server.gui.add_text("Budget consumer", "C" * 64)

    before_total = server.gui._resource_total
    before_resources = dict(server.gui._resource_from_gui_uuid)
    before_props = (first._impl.props, second._impl.props)
    queued: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_messages_or_raise", queued.extend)
    monkeypatch.setattr(
        gui_api_impl,
        "_GUI_AGGREGATE_TEXT_MAX_UTF16_CODE_UNITS",
        before_total.text_units,
    )

    with pytest.raises(RuntimeError, match="text budget"):
        form.reset_form()
    assert (first.value, second.value) == ("", "")
    assert (first._impl.props, second._impl.props) == before_props
    assert server.gui._resource_total == before_total
    assert server.gui._resource_from_gui_uuid == before_resources
    assert queued == []


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


def test_mini_form_rejects_second_direct_or_nested_field_before_publication(
    server: leika.Server,
) -> None:
    with server.gui.add_mini_form() as mini:
        server.gui.add_text("Only", "")

    buffer = server._websock_server.get_message_buffer()
    before_messages = buffer.message_from_id.copy()
    before_count = server.gui._live_component_count
    before_resources = dict(server.gui._resource_from_gui_uuid)
    before_baselines = dict(server.gui._reset_baseline_resource_from_gui_uuid)
    with pytest.raises(ValueError, match="single field"):
        mini.add_text("Second", "")
    assert buffer.message_from_id == before_messages
    assert server.gui._live_component_count == before_count
    assert server.gui._resource_from_gui_uuid == before_resources
    assert server.gui._reset_baseline_resource_from_gui_uuid == before_baselines

    for add_incompatible in (
        lambda: mini.add_folder("Nested"),
        mini.add_tab_group,
        lambda: mini.add_html("<p>Sibling</p>"),
        lambda: mini.add_button("Sibling"),
    ):
        before_messages = buffer.message_from_id.copy()
        before_count = server.gui._live_component_count
        before_resources = dict(server.gui._resource_from_gui_uuid)
        before_baselines = dict(server.gui._reset_baseline_resource_from_gui_uuid)
        before_children = dict(mini._children)
        with pytest.raises(ValueError, match="direct editable field"):
            add_incompatible()
        assert buffer.message_from_id == before_messages
        assert server.gui._live_component_count == before_count
        assert server.gui._resource_from_gui_uuid == before_resources
        assert server.gui._reset_baseline_resource_from_gui_uuid == before_baselines
        assert mini._children == before_children


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
    assert form.id not in server.gui._container_handle_from_uuid
    assert child.id not in server.gui._gui_input_handle_from_uuid

    with pytest.raises(ValueError, match="single field"):
        with server.gui.add_mini_form() as empty:
            pass
    assert empty._impl.removed
    assert empty.id not in server.gui._container_handle_from_uuid

    first = second = None
    with pytest.raises(ValueError, match="single field"):
        with server.gui.add_mini_form() as invalid:
            first = server.gui.add_text("One", "")
            second = server.gui.add_text("Two", "")
    assert invalid._impl.removed
    assert first is not None and first._impl.removed
    assert second is None  # Rejected before publication or handle registration.


def test_form_reset_batch_failure_changes_no_field_or_callback(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_form(label="Profile") as form:
        name = server.gui.add_text("Name", "Ada")
        age = server.gui.add_number("Age", 36)
    name.value = "Grace"
    age.value = 45
    before_total = server.gui._resource_total
    before_resources = dict(server.gui._resource_from_gui_uuid)
    before_props = (name._impl.props, age._impl.props)
    callbacks: list[object] = []
    name.on_update(lambda event: callbacks.append(event.value))
    age.on_update(lambda event: callbacks.append(event.value))

    def reject(_: Any) -> None:
        raise RuntimeError("batch rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="batch rejected"):
        form.reset_form()

    assert (name.value, age.value) == ("Grace", 45)
    assert (name._impl.props, age._impl.props) == before_props
    assert server.gui._resource_total == before_total
    assert server.gui._resource_from_gui_uuid == before_resources
    assert callbacks == []


def test_client_array_controls_reject_mapping_payloads(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: SimpleNamespace())
    controls = (
        server.gui.add_list("List", ("one",)),
        server.gui.add_checklist("Checklist", (("one", False),)),
        server.gui.add_toggle(("one", "two"), multiple=True),
        server.gui.add_multi_slider("Range", (0.25, 0.75), min=0.0, max=1.0, step=0.1),
    )
    before = tuple(control.value for control in controls)

    for control in controls:
        asyncio.run(
            server.gui._handle_gui_updates(
                ClientId(12),
                _messages.GuiUpdateMessage(control.id, {"value": {"one": True}}),
            )
        )

    assert tuple(control.value for control in controls) == before


def test_disabled_or_hidden_controls_reject_stale_client_actions(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_messages: list[_messages.Message] = []
    client = SimpleNamespace(
        _websock_connection=SimpleNamespace(queue_message=client_messages.append)
    )
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)

    checkbox = server.gui.add_checkbox("Disabled", False, disabled=True)
    updates: list[bool] = []
    checkbox.on_update(lambda event: updates.append(event.value))
    asyncio.run(
        server.gui._handle_gui_updates(
            ClientId(1),
            _messages.GuiUpdateMessage(checkbox.id, {"value": True}),
        )
    )
    assert checkbox.value is False
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

    upload = server.gui.add_upload_button("Upload", disabled=True)
    server.gui._handle_file_transfer_start(
        ClientId(1),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid="disabled-upload",
            filename="file.bin",
            mime_type="application/octet-stream",
            part_count=1,
            size_bytes=1,
        ),
    )
    assert server.gui._current_file_upload_states == {}
    assert any(
        isinstance(message, _messages.FileTransferAbort)
        and message.transfer_uuid == "disabled-upload"
        for message in client_messages
    )

    warm_calls: list[object] = []
    preview = server.gui.add_preview_button("Preview", b"x", filename="x.txt", disabled=True)
    monkeypatch.setattr(preview, "_warm", warm_calls.append)
    asyncio.run(
        server.gui._handle_gui_preview_warm(
            ClientId(1), _messages.GuiPreviewWarmMessage(preview.id)
        )
    )
    assert warm_calls == []


def test_file_button_press_is_global_single_flight_and_preserves_manual_disable(
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

    # A second browser cannot enter the producer while the first owns it.
    second = threading.Thread(target=press, args=(2,))
    second.start()
    second.join(2.0)
    assert not second.is_alive()
    assert calls == [1]

    # Caller-owned disable during the transfer is not overwritten by cleanup.
    handle.disabled = True
    release.set()
    first.join(2.0)
    assert errors == []
    assert handle.disabled is True

    initially_disabled_calls: list[bool] = []
    blocked = server.gui.add_download_button(
        "Blocked",
        lambda _: initially_disabled_calls.append(True) or b"x",
        filename="x.bin",
        disabled=True,
    )
    asyncio.run(
        server.gui._handle_gui_updates(
            ClientId(3), _messages.GuiUpdateMessage(blocked.id, {"value": True})
        )
    )
    assert initially_disabled_calls == []
    assert blocked.disabled is True


def test_gui_reset_is_one_admission_before_local_retirement(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    with server.gui.add_folder("Folder") as folder:
        child = server.gui.add_checkbox("Child", True)
    with server.gui.add_modal("Modal") as modal:
        modal_child = server.gui.add_text("Text", "value")
    command = server.gui.add_command("Command")
    notification = server.gui.add_notification("Notice", auto_close_seconds=None)

    def reject(_: Any) -> None:
        raise RuntimeError("reset batch rejected")

    monkeypatch.setattr(server.gui._websock_interface, "queue_messages_or_raise", reject)
    with pytest.raises(RuntimeError, match="reset batch rejected"):
        server.gui.reset()
    assert not folder._impl.removed and not child._impl.removed
    assert not modal.closed and not modal_child._impl.removed
    assert not command._impl.removed and not notification._impl.removed

    batches: list[list[_messages.Message]] = []
    monkeypatch.setattr(
        server.gui._websock_interface,
        "queue_messages_or_raise",
        lambda messages: batches.append(list(messages)),
    )
    server.gui.reset()
    assert len(batches) == 1
    assert folder._impl.removed and child._impl.removed
    assert modal.closed and modal_child._impl.removed
    assert command._impl.removed and notification._impl.removed
    assert server.gui._live_component_count == 0
    assert server.gui._resource_total == gui_handles_impl._GuiResourceCost()
    assert server.gui._reset_baseline_resource_from_gui_uuid == {}
    assert server.gui._container_handle_from_uuid.keys() == {"root"}
    assert server.gui._command_handle_from_uuid == {}
    assert server.gui._modal_handle_from_uuid == {}
    assert server.gui._notification_handle_from_uuid == {}


def test_upload_resource_rejection_precedes_final_ack(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = server.gui.add_upload_button("Upload")
    queued: list[_messages.Message] = []
    client = SimpleNamespace(
        _websock_connection=SimpleNamespace(queue_message=_open_recorder(queued))
    )
    monkeypatch.setattr(server.gui, "_resolve_client", lambda _: client)
    server.gui._handle_file_transfer_start(
        ClientId(1),
        _messages.FileTransferStartUpload(
            source_component_uuid=upload.id,
            transfer_uuid="resource-limit",
            filename="data.bin",
            mime_type="application/octet-stream",
            part_count=1,
            size_bytes=1,
        ),
    )
    assert isinstance(queued.pop(), _messages.FileTransferPartAck)
    monkeypatch.setattr(
        gui_api_impl,
        "_GUI_AGGREGATE_PAYLOAD_MAX_BYTES",
        server.gui._resource_total.payload_bytes,
    )

    completion = server.gui._handle_file_transfer_part(
        ClientId(1),
        _messages.FileTransferPart(upload.id, "resource-limit", 0, b"x"),
    )

    assert completion is None
    assert not any(isinstance(message, _messages.FileTransferPartAck) for message in queued)
    assert any(isinstance(message, _messages.FileTransferAbort) for message in queued)
    assert upload.value == leika.UploadedFile("", b"")
    assert server.gui._current_file_upload_states == {}
    assert server._file_upload_bytes_reserved == 0


def test_public_collection_iterables_stop_after_limit_plus_one(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_handles_impl, "_GUI_COLLECTION_MAX", 2)
    yielded: list[int] = []

    def entries():
        index = 0
        while True:
            yielded.append(index)
            yield str(index)
            index += 1

    with pytest.raises(ValueError, match="more than 2"):
        server.gui.add_list("Bounded", entries())
    assert yielded == [0, 1, 2]
    assert server.gui.add_list("Exact", (str(i) for i in range(2))).value == ("0", "1")


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


@pytest.mark.plotly
def test_plotly_size_is_checked_before_config_json_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    from plotly.basedatatypes import BaseFigure

    monkeypatch.setattr(gui_handles_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", 2)
    monkeypatch.setattr(BaseFigure, "to_json", lambda self: "xxx")
    monkeypatch.setattr(gui_handles_impl, "_plotly_graph_json_upper_bound", lambda *roots: 0)
    monkeypatch.setattr(
        gui_handles_impl.json,
        "loads",
        lambda _: pytest.fail("oversized Plotly JSON was parsed"),
    )
    with pytest.raises(ValueError, match="Plotly figure exceeds"):
        gui_handles_impl._plotly_json_with_config(go.Figure(), {})


def test_live_multi_slider_values_are_bounded_before_materialization(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = server.gui.add_multi_slider(
        "Range",
        (0.25, 0.75),
        min=0.0,
        max=1.0,
        step=0.01,
    )
    messages: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(messages))

    exact = [0.5] * 4096
    handle.value = exact
    assert handle.value == tuple(exact)
    assert len(messages) == 1
    messages.clear()
    before = handle.value

    yielded = 0

    def infinite() -> Any:
        nonlocal yielded
        while True:
            yielded += 1
            yield 0.5

    with pytest.raises(ValueError, match="4096 items"):
        handle.value = infinite()
    assert yielded == 4097
    assert handle.value == before
    assert messages == []

    class LyingSequence(Sequence[float]):
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> float:
            if index < 0:
                raise IndexError
            return 0.5

        def __iter__(self) -> Any:
            yield from infinite()

    yielded = 0
    with pytest.raises(ValueError, match="4096 items"):
        handle.value = LyingSequence()
    assert yielded == 4097
    assert handle.value == before
    assert messages == []

    with pytest.raises(ValueError, match="4096 items"):
        handle.value = [0.5] * 4097
    assert handle.value == before
    assert messages == []


def test_slider_marks_are_bounded_and_transactionally_validated(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    exact_marks = tuple(float(index) for index in range(4096))
    slider = server.gui.add_slider(
        "Marked",
        0.0,
        min=0.0,
        max=4095.0,
        step=1.0,
        marks=exact_marks,
    )
    assert slider._marks is not None
    assert len(slider._marks) == 4096

    yielded = 0

    def too_many_marks() -> Any:
        nonlocal yielded
        for index in range(4097):
            yielded += 1
            yield float(index)

    live_before = server.gui._live_component_count
    with pytest.raises(ValueError, match="4096 items"):
        server.gui.add_slider(
            "Too many",
            0.0,
            min=0.0,
            max=4096.0,
            step=1.0,
            marks=too_many_marks(),  # type: ignore[arg-type]
        )
    assert yielded == 4097
    assert server.gui._live_component_count == live_before

    exact_label = "😀" * 8192
    labeled = server.gui.add_slider(
        "Labeled",
        0.0,
        min=0.0,
        max=1.0,
        step=1.0,
        marks=((0.0, exact_label),),
    )
    assert labeled._marks == (_messages.GuiSliderMark(0.0, exact_label),)
    with pytest.raises(ValueError, match="16384 UTF-16"):
        server.gui.add_slider(
            "Oversized label",
            0.0,
            min=0.0,
            max=1.0,
            step=1.0,
            marks=((0.0, exact_label + "x"),),
        )
    with pytest.raises(ValueError, match="finite"):
        server.gui.add_slider(
            "Nonfinite",
            0.0,
            min=0.0,
            max=1.0,
            step=1.0,
            marks=(float("nan"),),
        )

    messages: list[_messages.Message] = []
    monkeypatch.setattr(server.gui._websock_interface, "queue_message", _open_recorder(messages))
    before = dataclasses.replace(labeled._impl.props)
    invalid_live_marks: tuple[object, ...] = (
        (_messages.GuiSliderMark(float("inf"), None),),
        (_messages.GuiSliderMark(0.0, exact_label + "x"),),
        tuple(_messages.GuiSliderMark(float(index), None) for index in range(4097)),
        (object(),),
    )
    for marks in invalid_live_marks:
        with pytest.raises((TypeError, ValueError)):
            labeled._marks = marks  # type: ignore[assignment]
        assert labeled._impl.props == before
        assert messages == []

    def reject(_: _messages.Message) -> bool:
        return False

    monkeypatch.setattr(server.gui._websock_interface, "queue_message", reject)
    with pytest.raises(RuntimeError, match="closed"):
        labeled.update(_marks=(_messages.GuiSliderMark(1.0, "new"),))
    assert labeled._impl.props == before


def test_gui_image_encodes_and_retains_one_private_snapshot(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = np.zeros((2, 3, 3), dtype=np.uint8)
    encoded_snapshots: list[np.ndarray] = []

    def encode(snapshot: np.ndarray, *_: Any, **__: Any) -> tuple[str, bytes]:
        assert snapshot is not caller
        encoded_snapshots.append(snapshot)
        caller.fill(255)
        return "png", b"encoded"

    monkeypatch.setattr(gui_api_impl, "encode_image_binary", encode)
    monkeypatch.setattr(gui_handles_impl, "encode_image_binary", encode)
    handle = server.gui.add_image(caller)
    assert handle._image is encoded_snapshots[-1]
    assert np.count_nonzero(handle.image) == 0

    caller.fill(0)
    handle.image = caller
    assert np.count_nonzero(handle.image) == 0


def test_gui_text_constructor_matches_live_utf16_and_unicode_validation(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui_handles_impl, "_GUI_TEXT_MAX_UTF16_CODE_UNITS", 2)
    monkeypatch.setattr(gui_api_impl, "_GUI_TEXT_MAX_UTF16_CODE_UNITS", 2)
    handle = server.gui.add_text("Text", "😀")
    assert handle.value == "😀"
    with pytest.raises(ValueError, match="1 Mi-character"):
        server.gui.add_text("Too long", "😀x")
    with pytest.raises(ValueError, match="surrogate"):
        server.gui.add_text("Invalid", "\ud800")


def test_programmatic_callback_snapshot_budget_is_reported_post_commit(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    handle = server.gui.add_text("Value", "before")
    handle.on_update(lambda _: None)
    monkeypatch.setattr(gui_api_impl, "_GUI_PROGRAMMATIC_CALLBACK_RETAINED_MAX_BYTES", 1)

    handle.value = "after"

    assert handle.value == "after"
    assert server.gui._programmatic_callback_queue == deque()
    assert server.gui._programmatic_callback_retained_bytes == 0
    assert "callback queue exceeded" in capsys.readouterr().err


def test_programmatic_callback_snapshot_accounting_releases_on_terminal(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[object] = []
    with monkeypatch.context() as patch:
        patch.setattr(
            server.gui._event_loop,
            "call_soon_threadsafe",
            scheduled.append,
        )
        event = SimpleNamespace(value="retained")
        server.gui._schedule_programmatic_callbacks((lambda _: None,), event)
        assert scheduled
        assert server.gui._programmatic_callback_retained_bytes > 0
        assert len(server.gui._programmatic_callback_queue) == 1

    server.gui._retire_scope_without_queue()
    assert server.gui._programmatic_callback_queue == deque()
    assert server.gui._programmatic_callback_retained_bytes == 0


@pytest.mark.plotly
def test_plotly_preflight_bounds_normal_graphs_before_serializer_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    from plotly.basedatatypes import BaseFigure

    normal_array = np.arange(100_000, dtype=np.float64)
    normal = go.Figure(go.Scatter(x=normal_array, y=normal_array))
    json_str, _ = gui_handles_impl._plotly_json_and_config(normal, None)
    assert '"x"' in json_str and '"y"' in json_str

    normal_list = list(range(100_000))
    gui_handles_impl._plotly_graph_json_upper_bound(
        *gui_handles_impl._plotly_figure_raw_graph(
            go.Figure(go.Scatter(x=normal_list, y=normal_list))
        )
    )
    assert gui_handles_impl._plotly_graph_json_upper_bound(np.zeros((100, 100), dtype=np.uint8)) > 0

    reached_serializer = False

    def forbidden(_: object) -> str:
        nonlocal reached_serializer
        reached_serializer = True
        raise AssertionError("oversized Plotly graph reached serializer")

    monkeypatch.setattr(BaseFigure, "to_json", forbidden)
    oversized_list = go.Figure(go.Scatter(x=[0] * 500_001))
    oversized_array = go.Figure(go.Scatter(x=np.zeros(500_001, dtype=np.bool_)))
    oversized_frame = go.Figure(frames=[go.Frame(data=[go.Scatter(x=[0] * 500_001)])])
    nested = np.zeros((16_384,) + (1,) * 31, dtype=np.uint8)
    oversized_nested = go.Figure()
    object.__getattribute__(oversized_nested, "__dict__")["_data"] = [
        {"type": "scatter", "x": nested}
    ]
    for figure in (
        oversized_list,
        oversized_array,
        oversized_frame,
        oversized_nested,
    ):
        with pytest.raises(ValueError, match="too many values"):
            gui_handles_impl._plotly_json_with_config(figure, None)
    assert not reached_serializer


@pytest.mark.plotly
def test_plotly_preflight_rejects_dynamic_serialization_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    from plotly.graph_objs import Frame
    from plotly.graph_objs.layout import Template

    hook_calls = 0

    def hostile_hook() -> dict[str, Any]:
        nonlocal hook_calls
        hook_calls += 1
        raise AssertionError("dynamic Plotly hook ran")

    instance_shadow = go.Figure()
    instance_shadow.to_dict = hostile_hook
    with pytest.raises(TypeError, match="instance Plotly serialization overrides"):
        gui_handles_impl._plotly_json_with_config(instance_shadow, None)

    class HostileFigure(go.Figure):
        def __getattribute__(self, name: str) -> Any:
            if name in ("to_dict", "to_json"):
                hostile_hook()
            return super().__getattribute__(name)

    with pytest.raises(TypeError, match="exact plotly.graph_objects.Figure"):
        gui_handles_impl._plotly_json_with_config(HostileFigure(), None)

    class HostileMeta(type):
        def __getattribute__(cls, name: str) -> Any:
            if name in ("to_dict", "to_json", "__getattribute__"):
                hostile_hook()
            return super().__getattribute__(name)

    class HostileMetaFigure(go.Figure, metaclass=HostileMeta):
        pass

    with pytest.raises(TypeError, match="exact plotly.graph_objects.Figure"):
        gui_handles_impl._plotly_json_with_config(HostileMetaFigure(), None)

    class HostileFrame(Frame):
        def __getattribute__(self, name: str) -> Any:
            if name == "_props":
                hostile_hook()
            return super().__getattribute__(name)

    framed = go.Figure()
    object.__getattribute__(framed, "__dict__")["_frame_objs"] = [HostileFrame()]
    with pytest.raises(TypeError, match="custom Plotly frame"):
        gui_handles_impl._plotly_json_with_config(framed, None)

    class HostileTemplate(Template):
        def __getattribute__(self, name: str) -> Any:
            if name == "_props":
                hostile_hook()
            return super().__getattribute__(name)

    with pytest.raises(TypeError, match="exact stock Template"):
        panes_impl._bounded_plotly_template_dict(HostileTemplate())

    import datetime

    class HostileDate(datetime.date):
        def isoformat(self) -> str:
            hostile_hook()
            return ""

    with pytest.raises(TypeError, match="unsupported Plotly value"):
        gui_handles_impl._plotly_graph_json_upper_bound(HostileDate(2025, 1, 1))

    class HostileNumpyScalar(np.float64):
        def __getattribute__(self, name: str) -> Any:
            if name in ("dtype", "item", "tolist"):
                hostile_hook()
            return super().__getattribute__(name)

    with pytest.raises(TypeError, match="custom numpy scalar subclasses"):
        gui_handles_impl._plotly_graph_json_upper_bound(HostileNumpyScalar(1.0))
    assert hook_calls == 0

    # Normal exact stock templates still use the same raw property snapshot.
    pio = pytest.importorskip("plotly.io")
    stock = pio.templates["plotly_white"]
    expected = stock.to_plotly_json()
    assert panes_impl._bounded_plotly_template_dict(stock) == expected


@pytest.mark.plotly
def test_plotly_public_paths_reject_subclass_data_descriptors_without_hooks(
    server: leika.Server,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    hook_calls = 0

    class DescriptorFigure(go.Figure):
        @property
        def _data(self) -> Any:
            nonlocal hook_calls
            hook_calls += 1
            raise AssertionError("Plotly data descriptor ran")

    hostile = object.__new__(DescriptorFigure)
    gui = server.gui.add_plotly(go.Figure(go.Scatter(y=[1])))
    pane = server.panes.add_plotly(go.Figure(go.Scatter(y=[2])), pane_id="exact-figure")
    gui_json = gui._impl.props._plotly_json_str
    pane_json = pane._impl.props._plotly_json_str

    for operation in (
        lambda: server.gui.add_plotly(hostile),
        lambda: server.panes.add_plotly(hostile, pane_id="hostile-subclass"),
        lambda: setattr(gui, "figure", hostile),
        lambda: setattr(pane, "figure", hostile),
    ):
        with pytest.raises(TypeError, match="exact plotly.graph_objects.Figure"):
            operation()
    assert hook_calls == 0
    assert gui._impl.props._plotly_json_str == gui_json
    assert pane._impl.props._plotly_json_str == pane_json
    assert "hostile-subclass" not in server.panes._handle_from_pane_id


@pytest.mark.plotly
def test_plotly_config_snapshot_is_bounded_and_isolated_across_scopes(
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

    retained_configs = [
        json.loads(handle._impl.props._plotly_json_str).get("config") for handle in handles
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
def test_plotly_handles_retain_only_bounded_independent_json_snapshots(
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
    # assigned back, so it cannot expand retained state behind the ledger.
    gui_read.add_trace(go.Bar(y=[7]))
    pane_read.add_trace(go.Scatter(y=[6]))
    assert len(gui.figure.data) == 1
    assert len(pane.figure.data) == 1

    del gui_read, pane_read, gui_source, pane_source
    gc.collect()
    assert gui_ref() is None
    assert pane_ref() is None
    assert json.loads(gui._impl.props._plotly_json_str)["config"] == {"displayModeBar": False}
    assert json.loads(pane._impl.props._plotly_json_str)["config"] == {"displayModeBar": False}


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
    assert "template" not in json.loads(pane._impl.props._plotly_json_str)["layout"]

    template_name = "leika_oversized_getter_default"
    old_default = pio.templates.default
    pio.templates[template_name] = go.layout.Template(layout={"title": {"text": "global" * 2_000}})
    pio.templates.default = template_name
    monkeypatch.setattr(gui_handles_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", 500)
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
        assert "template" not in json.loads(pane._impl.props._plotly_json_str)["layout"]
    finally:
        pio.templates.default = old_default
        del pio.templates[template_name]


@pytest.mark.plotly
def test_plotly_config_materialization_and_renderer_reentry_are_bounded(
    server: leika.Server,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")

    class LyingMapping(Mapping[str, Any]):
        yielded = 0

        def __len__(self) -> int:
            return 1

        def __iter__(self) -> Iterator[str]:
            return iter(())

        def __getitem__(self, key: str) -> Any:
            raise KeyError(key)

        def items(self) -> Iterator[tuple[str, Any]]:
            while True:
                self.yielded += 1
                yield f"k{self.yielded}", False

    lying = LyingMapping()
    with pytest.raises(ValueError, match="length"):
        server.gui.add_plotly(go.Figure(), config=lying)
    assert lying.yielded == gui_handles_impl._PLOTLY_CONFIG_MAX_ITEMS + 1

    class ReentrantMapping(Mapping[str, Any]):
        def __len__(self) -> int:
            server.gui.add_plotly(go.Figure())
            return 0

        def __iter__(self) -> Iterator[str]:
            return iter(())

        def __getitem__(self, key: str) -> Any:
            raise KeyError(key)

    with pytest.raises(RuntimeError, match="cannot re-enter"):
        server.gui.add_plotly(go.Figure(), config=ReentrantMapping())

    class ReentrantFigure:
        def savefig(self, output: Any, *, format: str) -> None:
            del output, format
            server.panes.add_matplotlib(self)

    with pytest.raises(RuntimeError, match="cannot re-enter"):
        server.panes.add_matplotlib(ReentrantFigure(), pane_id="reentrant-renderer")

    # Every exceptional path releases ownership for later renderers.
    server.gui.add_plotly(go.Figure())


@pytest.mark.plotly
def test_plotly_raw_graph_rejects_injected_base_types_without_hooks(
    server: leika.Server,
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    called: list[str] = []

    class HostileScatter(go.Scatter):
        def __deepcopy__(self, memo: dict[int, object]) -> object:
            del memo
            called.append("trace")
            raise AssertionError("trace deepcopy hook ran")

    class HostileLayout(go.Layout):
        def __deepcopy__(self, memo: dict[int, object]) -> object:
            del memo
            called.append("layout")
            raise AssertionError("layout deepcopy hook ran")

    trace_figure = go.Figure()
    trace_figure.__dict__["_data"] = [HostileScatter(y=[1, 2])]
    with pytest.raises(TypeError, match="unsupported Plotly value"):
        server.gui.add_plotly(trace_figure)

    layout_figure = go.Figure()
    layout_figure.__dict__["_layout"] = HostileLayout(title="unsafe")
    with pytest.raises(TypeError, match="unsupported Plotly value"):
        server.panes.add_plotly(layout_figure)

    assert called == []


@pytest.mark.plotly
def test_plotly_global_templates_are_preflighted_before_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pio = pytest.importorskip("plotly.io")
    from plotly.basedatatypes import BasePlotlyType

    monkeypatch.setattr(panes_impl, "_theme_templates_json", None)
    monkeypatch.setattr(gui_handles_impl, "_PLOTLY_JSON_MAX_UTF16_CODE_UNITS", 100)
    huge = pio.templates["plotly_white"]
    monkeypatch.setitem(
        huge.__dict__["_orphan_props"],
        "oversized",
        "x" * 1000,
    )
    copied = False

    def forbidden(_: object) -> dict[str, Any]:
        nonlocal copied
        copied = True
        raise AssertionError("oversized template was copied")

    monkeypatch.setattr(BasePlotlyType, "to_plotly_json", forbidden)
    with pytest.raises(ValueError, match="16 Mi-character"):
        panes_impl._plotly_theme_templates_json()
    assert not copied


def test_image_and_renderer_preparation_admission_is_bounded_and_released(
    server: leika.Server,
) -> None:
    image_entered = threading.Event()
    image_release = threading.Event()
    image_second = threading.Event()

    def own_image() -> None:
        with server._reserve_image_preparation(128 * 1024 * 1024):
            image_entered.set()
            assert image_release.wait(2)

    def wait_image() -> None:
        with server._reserve_image_preparation(1):
            image_second.set()

    first = threading.Thread(target=own_image)
    second = threading.Thread(target=wait_image)
    first.start()
    assert image_entered.wait(1)
    assert server._image_preparation_bytes == 512 * 1024 * 1024
    second.start()
    assert not image_second.wait(0.05)
    image_release.set()
    first.join(2)
    second.join(2)
    assert image_second.is_set()
    assert server._image_preparation_bytes == 0
    with pytest.raises(RuntimeError, match="512 MiB"):
        with server._reserve_image_preparation(128 * 1024 * 1024 + 1):
            raise AssertionError("oversized image preparation was admitted")

    renderer_entered = threading.Event()
    renderer_release = threading.Event()
    renderer_second = threading.Event()

    def own_renderer() -> None:
        with server._reserve_renderer_preparation():
            renderer_entered.set()
            assert renderer_release.wait(2)

    def wait_renderer() -> None:
        with server._reserve_renderer_preparation():
            renderer_second.set()

    first = threading.Thread(target=own_renderer)
    second = threading.Thread(target=wait_renderer)
    first.start()
    assert renderer_entered.wait(1)
    second.start()
    assert not renderer_second.wait(0.05)
    renderer_release.set()
    first.join(2)
    second.join(2)
    assert renderer_second.is_set()
