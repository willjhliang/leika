from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

import leika
from leika import _messages
from leika import _pages as pages_impl
from leika import _panes as panes_impl
from leika.infra import ClientId


def _retained(server: leika.Server) -> tuple[_messages.Message, ...]:
    return tuple(server._websock_server.get_message_buffer().message_from_id.values())


def test_default_page_preserves_the_one_page_api_and_bootstrap_order(
    server: leika.Server,
) -> None:
    assert len(server.pages) == 1
    assert tuple(server.pages) == (server.pages.default,)
    assert server.pages.default.page_id == "default"
    assert server.pages.default.name == "Main"
    assert server.panes is server.pages.default.panes

    messages = _retained(server)
    workspace_index = next(
        index
        for index, message in enumerate(messages)
        if isinstance(message, _messages.WorkspaceConfigurationMessage)
    )
    page_index = next(
        index
        for index, message in enumerate(messages)
        if isinstance(message, _messages.PageCreateMessage)
    )
    snapshot_index = next(
        index
        for index, message in enumerate(messages)
        if isinstance(message, _messages.ViewportPaneSnapshotMessage)
    )
    assert workspace_index < page_index < snapshot_index
    assert messages[page_index] == _messages.PageCreateMessage(
        page_id="default",
        name="Main",
        is_default=True,
    )
    assert messages[snapshot_index] == _messages.ViewportPaneSnapshotMessage(
        page_id="default",
        pane_ids=(),
    )


def test_pages_scope_pane_ids_placement_updates_and_removal(
    server: leika.Server,
) -> None:
    frame = np.zeros((2, 3, 3), dtype=np.uint8)
    diagnostics = server.pages.add("Diagnostics", page_id="diagnostics")
    main_pane = server.panes.add_image(frame, pane_id="shared", title="Main")
    diagnostics_pane = diagnostics.panes.add_image(
        frame,
        pane_id="shared",
        title="Diagnostics",
    )

    assert main_pane.pane_id == diagnostics_pane.pane_id == "shared"
    with pytest.raises(ValueError, match="Unknown or hidden relative"):
        diagnostics.panes.add_image(frame, pane_id="bad", relative_to="main-only")

    main_only = server.panes.add_image(frame, pane_id="main-only")
    assert main_only.pane_id == "main-only"
    with pytest.raises(ValueError, match="Unknown or hidden relative"):
        diagnostics.panes.add_image(frame, pane_id="still-bad", relative_to="main-only")

    main_pane.title = "Renamed main"
    diagnostics_pane.title = "Renamed diagnostics"
    assert main_pane.title == "Renamed main"
    assert diagnostics_pane.title == "Renamed diagnostics"

    creates = [
        message
        for message in _retained(server)
        if isinstance(message, _messages.ViewportImageMessage) and message.pane_id == "shared"
    ]
    assert {message.page_id for message in creates} == {"default", "diagnostics"}
    assert creates[0].redundancy_key() != creates[1].redundancy_key()

    main_pane.remove()
    assert diagnostics.panes._handle_from_pane_id["shared"] is diagnostics_pane
    assert diagnostics_pane.title == "Renamed diagnostics"
    assert any(
        isinstance(message, _messages.ViewportImageMessage)
        and message.page_id == "diagnostics"
        and message.pane_id == "shared"
        for message in _retained(server)
    )


def test_page_names_are_stable_identity_updates_and_legacy_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    for label, expected in ((None, "Main"), ("", "Main"), ("Overview", "Overview")):
        server = leika.Server(
            host="127.0.0.1",
            port=0,
            label=label,
            verbose=False,
        )
        try:
            page = server.pages.default
            assert page.name == expected
            stable_id = page.page_id
            page.name = "Renamed"
            assert page.name == "Renamed"
            assert page.page_id == stable_id
            server.gui.set_panel_label(None)
            assert page.name == "Main"
            updates = [
                message
                for message in _retained(server)
                if isinstance(message, _messages.PageUpdateMessage)
            ]
            assert updates[-1] == _messages.PageUpdateMessage("default", "Main")
        finally:
            server.stop()


def test_client_local_panel_label_sends_a_default_page_update_only_to_that_client(
    server: leika.Server,
) -> None:
    queued: list[_messages.Message] = []
    connection = SimpleNamespace(
        client_id=ClientId(17),
        register_handler=lambda *_: None,
        queue_message=queued.append,
        queue_message_or_raise=queued.append,
        queue_messages_or_raise=queued.extend,
        get_message_buffer=lambda: SimpleNamespace(event_loop=server._event_loop),
    )
    client = leika.ClientHandle(cast(Any, connection), server)
    server.pages.default.name = "Global"

    client.gui.set_panel_label("")

    assert queued[-1] == _messages.PageUpdateMessage(page_id="default", name="Main")
    assert server.pages.default.name == "Global"


@pytest.mark.parametrize(
    ("name", "page_id", "error", "match"),
    [
        ("", "empty-name", ValueError, "must not be empty"),
        (cast(Any, 1), "bad-name", TypeError, "page name must be a string"),
        ("Bad id", "", ValueError, "must not be empty"),
        ("Bad id", cast(Any, True), TypeError, "Page ID must be a string"),
        ("Bad id", "constructor", ValueError, "reserved browser"),
        ("Bad id", "bad\ud800", ValueError, "surrogate"),
        ("Bad id", "😀" * 512 + "x", ValueError, "1024 UTF-16"),
    ],
)
def test_page_validation_is_transactional(
    server: leika.Server,
    name: Any,
    page_id: Any,
    error: type[Exception],
    match: str,
) -> None:
    before = tuple(server.pages)
    with pytest.raises(error, match=match):
        server.pages.add(name, page_id=page_id)
    assert tuple(server.pages) == before


def test_page_add_queue_failure_rolls_back_without_a_ghost(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_messages = _retained(server)

    def fail(_: object) -> None:
        raise RuntimeError("page batch failed")

    monkeypatch.setattr(server._websock_server, "queue_messages_or_raise", fail)
    with pytest.raises(RuntimeError, match="page batch failed"):
        server.pages.add("Rejected", page_id="rejected")

    assert len(server.pages) == 1
    assert "rejected" not in server.pages._page_from_page_id
    assert _retained(server) == before_messages
    assert server.pages._aggregate.live_panes == 0
    assert server.pages._aggregate.resource_total == panes_impl._PaneResourceCost()


def test_page_names_are_unique_and_failed_changes_are_transactional(
    server: leika.Server,
) -> None:
    analysis = server.pages.add("Analysis", page_id="analysis")
    before_messages = _retained(server)

    with pytest.raises(ValueError, match="Page name 'Analysis' already exists"):
        server.pages.add("Analysis", page_id="duplicate-name")
    with pytest.raises(ValueError, match="Page name 'Main' already exists"):
        analysis.name = "Main"

    assert tuple(page.name for page in server.pages) == ("Main", "Analysis")
    assert _retained(server) == before_messages


def test_pane_and_page_limits_remain_aggregate_across_pages(
    server: leika.Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    other = server.pages.add("Other", page_id="other")

    monkeypatch.setattr(panes_impl, "_PANE_MAX", 1)
    first = server.panes.add_image(frame, pane_id="same")
    with pytest.raises(RuntimeError, match="more than 1 panes"):
        other.panes.add_image(frame, pane_id="same")
    first.remove()
    replacement = other.panes.add_image(frame, pane_id="same")
    assert replacement.pane_id == "same"

    monkeypatch.setattr(pages_impl, "_PAGE_MAX", len(server.pages))
    with pytest.raises(RuntimeError, match="more than 2 pages"):
        server.pages.add("Overflow", page_id="overflow")


def test_stop_retires_every_pages_panes_and_releases_shared_ownership(
    server: leika.Server,
) -> None:
    frame = np.zeros((1, 1, 3), dtype=np.uint8)
    other = server.pages.add("Other", page_id="other")
    first = server.panes.add_image(frame, pane_id="first")
    second = other.panes.add_image(frame, pane_id="second")

    server.stop()

    assert first._impl.removed and second._impl.removed
    assert server.pages._aggregate.live_panes == 0
    assert server.pages._aggregate.live_viser_panes == 0
    assert server.pages._aggregate.resource_total == panes_impl._PaneResourceCost()
    assert server.panes._handle_from_pane_id == {}
    assert other.panes._handle_from_pane_id == {}
