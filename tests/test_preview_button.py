"""What a preview button does with a press.

It is the download button's twin -- both are ``_GuiFileButtonHandle``, so
resolving the contents, defaulting the name and holding the button shut while
the file goes out are pinned once, in ``test_download_button.py``. What is
tested here is what only the preview does: show rather than save, and refuse a
file too large to hold in a tab.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import re
import threading
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Tuple
from unittest import mock

import pytest

import leika
from leika import _gui_api as gui_api_impl
from leika import _messages
from leika._gui_handles import GuiEvent, GuiPreviewButtonHandle
from leika.infra import ClientId
from leika.infra import _infra as infra_impl


class _Client:
    """A client that records what it was asked to show.

    Carries the real server when a test needs one: delivering a path-backed
    markdown file registers its images with ``client._server``.
    """

    def __init__(self, server: leika.Server | None = None) -> None:
        self._server = server
        #: Every file sent to a dialog, in order: disposition, name, contents,
        #: size limit, the component it came from and the stamp it went out
        #: with. The last two are what let the dialog ask for it again.
        self.shown: List[Tuple[str, str, Any, int, str | None, str | None]] = []
        self.downloaded: List[Tuple[str, Any]] = []
        self.warmed: List[Tuple[str, Any, str | None, str | None]] = []

    def _cancel_all_outgoing_file_transfers(self) -> None:
        """Production-shaped disconnect cleanup; this fake has no transfers."""

    @property
    def previewed(self) -> List[Tuple[str, Any, int]]:
        """The files that opened a dialog."""
        return [
            (name, content, limit) for d, name, content, limit, _, _ in self.shown if d == "preview"
        ]

    @property
    def reloaded(self) -> List[Tuple[str, Any, int]]:
        """The files that landed in a dialog already open."""
        return [
            (name, content, limit) for d, name, content, limit, _, _ in self.shown if d == "reload"
        ]

    def _send_file(
        self, filename: str, content: Any, chunk_size: int, disposition: str, **kwargs: Any
    ) -> int | None:
        assert disposition == "warm"
        size = len(content) if isinstance(content, bytes) else content.stat().st_size
        max_bytes = kwargs.get("max_bytes")
        if max_bytes is not None and size > max_bytes:
            return size
        self.warmed.append(
            (
                filename,
                content,
                kwargs.get("source_uuid"),
                kwargs.get("source_version"),
            )
        )
        return None

    def _send_preview(
        self,
        filename: str,
        content: Any,
        *,
        chunk_size: int = 0,
        max_bytes: int = 0,
        disposition: str = "preview",
        source_uuid: str | None = None,
        source_version: str | None = None,
    ) -> None:
        self.shown.append((disposition, filename, content, max_bytes, source_uuid, source_version))

    def send_file_download(self, filename: str, content: Any, **kwargs: Any) -> None:
        self.downloaded.append((filename, content))


def _press(handle: GuiPreviewButtonHandle, server: leika.Server | None = None) -> _Client:
    client = _Client(server)
    handle._send(GuiEvent(client, 0, handle))  # type: ignore[arg-type]
    return client


def test_a_press_shows_the_file_rather_than_saving_it(server: leika.Server) -> None:
    handle = server.gui.add_preview_button("Look", b"# Title\n", filename="notes.md")
    client = _press(handle)

    assert client.previewed == [("notes.md", b"# Title\n", leika._gui_handles.PREVIEW_MAX_BYTES)]
    assert client.downloaded == []


def test_the_size_limit_reaches_the_client(server: leika.Server) -> None:
    handle = server.gui.add_preview_button("Look", b"data", filename="capture.bin", max_bytes=2048)
    assert _press(handle).previewed[0][2] == 2048


def test_contents_can_be_bytes_a_path_or_a_function(server: leika.Server, tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-")

    from_path = server.gui.add_preview_button("A", path)
    from_call = server.gui.add_preview_button("B", lambda _: path)

    assert _press(from_path).previewed[0][:2] == ("paper.pdf", path)
    assert _press(from_call).previewed[0][:2] == ("paper.pdf", path)


def _one_pixel_png() -> bytes:
    """A valid PNG, one pixel square, which its header declares."""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def _asset_url(document: bytes) -> str:
    """The bare asset path a document's first figure points at."""
    found = re.search(r"\(/leika-assets/[^?)]*", document.decode())
    assert found is not None
    return found.group(0)[1:]


def test_a_path_backed_markdown_preview_links_relative_images(
    server: leika.Server, tmp_path: Path
) -> None:
    docs = tmp_path / "docs"
    figures = docs / "figures"
    figures.mkdir(parents=True)
    # A valid one-pixel PNG. The exact image data is immaterial; the assertion
    # is that the path is resolved beside the markdown, registered with the
    # server, and the document sent on with the URL in its place -- the text
    # crosses the wire at its own size, and the browser fetches the images.
    png = _one_pixel_png()
    figures.joinpath("plot.png").write_bytes(png)
    document = docs / "notes.md"
    document.write_text(
        "# Results\n\n![plot](figures/plot.png)\n\n"
        "Text with (parentheses) between figures.\n\n"
        "![plot again](figures/plot.png)\n"
    )

    handle = server.gui.add_preview_button("Look", document)
    filename, content, _ = _press(handle, server).previewed[0]

    assert filename == "notes.md"
    assert isinstance(content, bytes)
    urls = re.findall(r"!\[[^]]*\]\(([^)]*)\)", content.decode())
    # The same file is the same content, so both references share one URL.
    assert len(urls) == 2 and urls[0] == urls[1]
    # The size the header declares rides along with the address -- the PNG
    # above is one pixel square -- so the browser can leave the right room for
    # the figure before it has arrived. Serving ignores the query, so this is
    # still one file; the renderer turns it back into width and height.
    assert urls[0] == f"{_asset_url(content)}?w=1&h=1"
    assert _asset_url(content).startswith("/leika-assets/")
    assert _asset_url(content).endswith(".png")
    assert b"figures/plot.png" not in content
    assert b"base64" not in content

    # The URL the document now points at answers with the image itself, query
    # and all -- the size is for the browser's layout, not for the lookup.
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{urls[0]}") as response:
        assert response.read() == png
        assert response.headers["Content-Type"] == "image/png"


def test_oversized_path_markdown_is_not_read_before_preview_rejection(
    server: leika.Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "notes.md"
    document.write_bytes(b"12345")
    handle = server.gui.add_preview_button("Look", document, max_bytes=4)

    def forbidden_read(self: Path) -> bytes:
        raise AssertionError("oversized Markdown was read before its size gate")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    client = _press(handle, server)

    assert client.previewed == [("notes.md", document, 4)]


def test_an_image_that_cannot_be_read_keeps_its_reference(
    server: leika.Server, tmp_path: Path
) -> None:
    # The document still shows, with the same broken figure it would show
    # anywhere else, rather than the preview failing over one lost file.
    document = tmp_path / "notes.md"
    document.write_text("# Results\n\n![gone](figures/missing.png)\n")

    handle = server.gui.add_preview_button("Look", document)
    with pytest.warns(UserWarning, match="missing.png"):
        client = _press(handle, server)

    assert b"![gone](figures/missing.png)" in client.previewed[0][1]


def test_scrolling_into_view_warms_a_static_preview(server: leika.Server, tmp_path: Path) -> None:
    # The warm is the press's transfer sent early, under a disposition the
    # browser holds rather than shows -- so nothing lands in `previewed`.
    document = tmp_path / "notes.md"
    document.write_text("# hi\n")

    handle = server.gui.add_preview_button("Look", document)
    client = _Client(server)
    handle._warm(client)  # type: ignore[arg-type]

    assert len(client.warmed) == 1
    filename, content, source_uuid, version = client.warmed[0]
    assert (filename, content, source_uuid) == ("notes.md", b"# hi\n", handle._impl.uuid)
    assert version is not None
    assert client.previewed == []


def _version(client: _Client) -> str | None:
    """The stamp the last file went out under."""
    return client.shown[-1][5]


def _watch(handle: GuiPreviewButtonHandle, version: str | None) -> _Client:
    client = _Client()
    handle._watch(client, version)  # type: ignore[arg-type]
    return client


def test_a_press_says_which_button_its_file_came_out_of(
    server: leika.Server, tmp_path: Path
) -> None:
    # The transfer is the only thing the dialog is given, so what it needs to
    # ask for the file again has to travel on it: which component to ask, and
    # what it is already holding.
    document = tmp_path / "notes.txt"
    document.write_text("# hi\n")
    handle = server.gui.add_preview_button("Look", document)

    disposition, _, _, _, source_uuid, version = _press(handle).shown[0]
    assert disposition == "preview"
    assert source_uuid == handle._impl.uuid
    assert version is not None


def test_only_a_file_on_disk_is_stamped(server: leika.Server, tmp_path: Path) -> None:
    # No stamp means no watching, and the two sources that cannot be watched
    # say so this way: bytes handed over once are not a file and cannot change
    # behind the reader, and what a function would return next time is not
    # knowable without running it.
    path = tmp_path / "notes.txt"
    path.write_text("# hi\n")

    assert _version(_press(server.gui.add_preview_button("A", b"x", filename="a.txt"))) is None
    assert _version(_press(server.gui.add_preview_button("B", lambda _: path))) is None
    assert _version(_press(server.gui.add_preview_button("C", path))) is not None


def test_the_stamp_moves_when_the_file_does(server: leika.Server, tmp_path: Path) -> None:
    document = tmp_path / "notes.txt"
    document.write_text("# hi\n")
    handle = server.gui.add_preview_button("Look", document)

    first = _version(_press(handle))
    document.write_text("# hi\n\nAnd more.\n")
    assert _version(_press(handle)) != first


def test_a_watch_sends_nothing_while_the_file_is_the_one_being_read(
    server: leika.Server, tmp_path: Path
) -> None:
    # The common case, and the one that has to cost nothing: a dialog left
    # open on a file nobody is writing asks once a second and is told nothing
    # each time.
    document = tmp_path / "notes.txt"
    document.write_text("# hi\n")
    handle = server.gui.add_preview_button("Look", document)
    version = _version(_press(handle))

    assert _watch(handle, version).shown == []


def test_a_watch_sends_the_file_again_once_it_has_changed(
    server: leika.Server, tmp_path: Path
) -> None:
    document = tmp_path / "notes.txt"
    document.write_text("# hi\n")
    handle = server.gui.add_preview_button("Look", document)
    version = _version(_press(handle))

    document.write_text("# hi\n\nRewritten.\n")
    client = _watch(handle, version)

    # Into the dialog that is open, rather than opening another. The file
    # itself goes, as a path streamed a chunk at a time, exactly as the press
    # would have sent it.
    assert client.reloaded == [("notes.txt", document, leika._gui_handles.PREVIEW_MAX_BYTES)]
    assert client.previewed == []
    # Stamped with what it is now, so the next watch asks about the right one.
    assert _version(client) not in (None, version)


def test_a_watch_never_runs_a_callable(server: leika.Server, tmp_path: Path) -> None:
    # The same rule warming follows, for the same reason: a function is the
    # caller's code, with whatever cost and side effects they gave it, and
    # leaving a dialog open is not a decision to run it once a second forever.
    ran: List[Any] = []

    def content(event: Any) -> bytes:
        ran.append(event)
        return b"# hi\n"

    handle = server.gui.add_preview_button("Look", content, filename="notes.txt")
    client = _watch(handle, None)

    assert client.shown == [] and ran == []


def test_a_watch_says_nothing_about_a_file_that_has_gone(
    server: leika.Server, tmp_path: Path
) -> None:
    # A file being rewritten in place is briefly not there. A preview that
    # emptied itself for that moment and filled back in would be worse than
    # one that waited for the next tick.
    document = tmp_path / "notes.txt"
    document.write_text("# hi\n")
    handle = server.gui.add_preview_button("Look", document)
    version = _version(_press(handle))

    document.unlink()
    assert _watch(handle, version).shown == []


def test_a_watch_stops_at_the_size_limit_without_saying_so(
    server: leika.Server, tmp_path: Path
) -> None:
    # A press over the limit answers with a notification, because somebody
    # asked. A watch asking every second must not raise one every second, so
    # it simply stops sending.
    document = tmp_path / "notes.txt"
    document.write_text("# hi\n")
    handle = server.gui.add_preview_button("Look", document, max_bytes=16)
    version = _version(_press(handle))

    document.write_text("# hi\n" + "x" * 64)
    assert _watch(handle, version).shown == []


def test_a_reload_press_asks_the_contents_afresh(server: leika.Server) -> None:
    # Unlike a watch: pressing reload is asking what the file says now, and
    # for contents that are computed the only way to answer is to compute
    # them. It lands in the open dialog rather than opening a second one.
    answers = iter([b"# first\n", b"# second\n"])

    handle = server.gui.add_preview_button("Look", lambda _: next(answers), filename="notes.txt")
    client = _Client()
    handle._send(GuiEvent(client, 0, handle))  # type: ignore[arg-type]
    handle._reload(GuiEvent(client, 0, handle))  # type: ignore[arg-type]

    assert client.previewed == [("notes.txt", b"# first\n", leika._gui_handles.PREVIEW_MAX_BYTES)]
    assert client.reloaded == [("notes.txt", b"# second\n", leika._gui_handles.PREVIEW_MAX_BYTES)]


def test_a_callable_preview_never_runs_for_a_warm(server: leika.Server) -> None:
    # A callable is the caller's code, run on a press; a button scrolling
    # past is not a press, so the callable must not fire for one.
    ran: List[Any] = []

    def content(event: Any) -> bytes:
        ran.append(event)
        return b"# hi\n"

    handle = server.gui.add_preview_button("Look", content, filename="notes.md")
    client = _Client(server)
    handle._warm(client)  # type: ignore[arg-type]

    assert client.warmed == [] and ran == []


def test_a_warm_that_cannot_deliver_stays_silent(server: leika.Server, tmp_path: Path) -> None:
    # Warming shows nobody anything, so there is nobody to tell: a file over
    # the size limit, or gone from disk, simply does not warm. (The fake
    # client has no `add_notification`, so telling would raise here.)
    oversized = server.gui.add_preview_button("Big", b"x" * 100, filename="big.bin", max_bytes=10)
    missing = server.gui.add_preview_button("Gone", tmp_path / "gone.md")

    client = _Client(server)
    oversized._warm(client)  # type: ignore[arg-type]
    missing._warm(client)  # type: ignore[arg-type]

    assert client.warmed == []


def test_an_unchanged_file_keeps_its_asset_url_and_a_changed_one_moves(
    server: leika.Server, tmp_path: Path
) -> None:
    # The URL is the content's hash: unchanged bytes produce the same URL,
    # while changed bytes produce a new one regardless of filesystem metadata.
    asset = tmp_path / "plot.png"
    asset.write_bytes(b"one")

    first = server.register_http_asset(asset)
    assert server.register_http_asset(asset) == first

    asset.write_bytes(b"two, longer")
    assert server.register_http_asset(asset) != first


def test_a_pictures_size_is_learned_from_the_bytes_used_for_its_digest(
    server: leika.Server, tmp_path: Path
) -> None:
    # Each registration reads once to uphold the content-addressed URL. The
    # picture size comes from those bytes rather than causing another read.
    asset = tmp_path / "plot.png"
    asset.write_bytes(_one_pixel_png())

    reads: List[Any] = []
    original = infra_impl._read_bounded_file

    def counted(path: Path, max_bytes: int, **kwargs: object) -> bytes:
        if path == asset:
            reads.append(path)
        return original(path, max_bytes, **kwargs)

    with mock.patch.object(infra_impl, "_read_bounded_file", counted):
        first = server._register_http_image(asset)
        again = server._register_http_image(asset)

    assert first.pixel_size == (1, 1)
    assert again == first
    assert len(reads) == 2, "pixel-size detection performed an extra file read"


def test_bytes_without_a_filename_are_rejected_at_creation(server: leika.Server) -> None:
    # The name is what the dialog titles itself with, and what its extension
    # picks a viewer from, so a preview needs one at least as much as a
    # download does.
    with pytest.raises(ValueError, match="add_preview_button"):
        server.gui.add_preview_button("Look", b"# Title\n")


def test_the_error_names_the_method_that_was_called(server: leika.Server) -> None:
    # The two buttons share their resolution, so the complaint has to point
    # back at whichever one the caller reached for.
    handle = server.gui.add_preview_button("Look", lambda _: b"# Title\n")
    with pytest.raises(ValueError, match="A preview of bytes has no name"):
        _press(handle)


def test_a_str_is_refused_at_creation(server: leika.Server) -> None:
    with pytest.raises(TypeError, match="bytes, a Path"):
        server.gui.add_preview_button("Look", "notes.md")  # type: ignore[arg-type]


def test_file_sources_reject_unsupported_and_async_providers_before_commit(
    server: leika.Server,
) -> None:
    async def async_provider(_: GuiEvent[Any]) -> bytes:
        return b"async"

    class AsyncCallable:
        async def __call__(self, _: GuiEvent[Any]) -> bytes:
            return b"async"

    for invalid in (object(), async_provider, AsyncCallable()):
        with pytest.raises(TypeError, match="bytes, a Path|synchronous"):
            server.gui.add_preview_button(
                "Look",
                invalid,  # type: ignore[arg-type]
                filename="notes.txt",
            )
        with pytest.raises(TypeError, match="bytes, a Path|synchronous"):
            server.gui.add_download_button(
                "Save",
                invalid,  # type: ignore[arg-type]
                filename="notes.txt",
            )

    handle = server.gui.add_preview_button("Look", b"old", filename="notes.txt")
    with pytest.raises(TypeError, match="bytes, a Path"):
        handle.content = object()  # type: ignore[assignment]
    assert handle.content == b"old"


def test_file_provider_result_is_exact_and_unexpected_coroutine_is_closed(
    server: leika.Server,
) -> None:
    invalid = server.gui.add_preview_button(
        "Invalid",
        lambda _: object(),
        filename="notes.txt",  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError, match="must return bytes or a Path"):
        _press(invalid)
    assert invalid.disabled is False

    async def produced() -> bytes:
        return b"late"

    coroutine = produced()
    unexpected_async = server.gui.add_preview_button(
        "Async",
        lambda _: coroutine,
        filename="notes.txt",  # type: ignore[arg-type]
    )
    with pytest.raises(TypeError, match="async providers are not supported"):
        _press(unexpected_async)
    assert coroutine.cr_frame is None
    assert unexpected_async.disabled is False


def test_direct_file_bytes_are_transactionally_charged_and_released(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    handle = server.gui.add_preview_button("Look", b"old", filename="notes.txt")
    assert server.gui._retained_extra_bytes_from_gui_uuid[handle.id] == 3

    old_total = server.gui._resource_total.payload_bytes
    monkeypatch.setattr(
        gui_api_impl,
        "_GUI_AGGREGATE_PAYLOAD_MAX_BYTES",
        old_total + 1,
    )
    with pytest.raises(RuntimeError, match="retained payload"):
        handle.content = b"replacement"
    assert handle.content == b"old"
    assert server.gui._retained_extra_bytes_from_gui_uuid[handle.id] == 3

    path = tmp_path / "notes.txt"
    path.write_bytes(b"path-backed")
    handle.content = path
    assert handle.content == path
    assert handle.id not in server.gui._retained_extra_bytes_from_gui_uuid

    handle.remove()
    with pytest.raises(RuntimeError, match="removed file button"):
        _ = handle.content
    assert handle._content == b""
    assert handle.id not in server.gui._resource_from_gui_uuid


def test_preview_work_for_one_client_and_source_is_fifo(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow old operation cannot land after a newer user request."""
    handle = server.gui.add_preview_button("Look", b"x", filename="x.txt")
    client = _Client(server)
    client_id = ClientId(17)
    monkeypatch.setattr(
        server.gui,
        "_resolve_client",
        lambda requested: client if requested == client_id else None,
    )
    warm_started = threading.Event()
    release_warm = threading.Event()
    second_reload_finished = threading.Event()
    events: list[str] = []
    reload_count = 0

    def warm(requesting_client: Any) -> None:
        assert requesting_client is client
        events.append("warm:start")
        warm_started.set()
        if not release_warm.wait(5.0):
            raise AssertionError("test did not release the warm operation")
        events.append("warm:end")

    def preview(event: GuiEvent[Any]) -> None:
        assert event.client is client
        events.append("preview")

    def reload(event: GuiEvent[Any]) -> None:
        nonlocal reload_count
        assert event.client is client
        reload_count += 1
        events.append(f"reload:{reload_count}")
        if reload_count == 2:
            second_reload_finished.set()

    def watch(requesting_client: Any, version: str | None) -> None:
        events.append("watch")

    monkeypatch.setattr(handle, "_warm", warm)
    monkeypatch.setattr(handle, "_send", preview)
    monkeypatch.setattr(handle, "_reload", reload)
    monkeypatch.setattr(handle, "_watch", watch)

    try:
        asyncio.run(
            server.gui._handle_gui_preview_warm(
                client_id, _messages.GuiPreviewWarmMessage(handle.id)
            )
        )
        assert warm_started.wait(2.0)
        asyncio.run(
            server.gui._handle_gui_updates(
                client_id,
                _messages.GuiUpdateMessage(handle.id, {"value": True}),
            )
        )
        for _ in range(2):
            asyncio.run(
                server.gui._handle_gui_preview_reload(
                    client_id, _messages.GuiPreviewReloadMessage(handle.id)
                )
            )
        asyncio.run(
            server.gui._handle_gui_preview_watch(
                client_id,
                _messages.GuiPreviewWatchMessage(handle.id, "old-version"),
            )
        )
    finally:
        release_warm.set()

    assert second_reload_finished.wait(2.0)
    assert events == ["warm:start", "warm:end", "preview", "reload:1", "reload:2"]


def test_preview_work_is_independent_across_clients_and_sources(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One blocked FIFO does not hold an unrelated browser or source."""
    first = server.gui.add_preview_button("First", b"1", filename="1.txt")
    second = server.gui.add_preview_button("Second", b"2", filename="2.txt")
    first_client = _Client(server)
    second_client = _Client(server)
    first_client_id = ClientId(21)
    second_client_id = ClientId(22)
    clients = {
        first_client_id: first_client,
        second_client_id: second_client,
    }
    monkeypatch.setattr(server.gui, "_resolve_client", clients.get)

    warm_started = threading.Event()
    release_warm = threading.Event()
    other_client_finished = threading.Event()
    other_source_finished = threading.Event()

    def blocked_warm(client: Any) -> None:
        warm_started.set()
        if not release_warm.wait(5.0):
            raise AssertionError("test did not release the warm operation")

    def first_reload(event: GuiEvent[Any]) -> None:
        if event.client is second_client:
            other_client_finished.set()

    def second_reload(event: GuiEvent[Any]) -> None:
        if event.client is first_client:
            other_source_finished.set()

    monkeypatch.setattr(first, "_warm", blocked_warm)
    monkeypatch.setattr(first, "_reload", first_reload)
    monkeypatch.setattr(second, "_reload", second_reload)

    try:
        asyncio.run(
            server.gui._handle_gui_preview_warm(
                first_client_id, _messages.GuiPreviewWarmMessage(first.id)
            )
        )
        assert warm_started.wait(2.0)
        asyncio.run(
            server.gui._handle_gui_preview_reload(
                second_client_id, _messages.GuiPreviewReloadMessage(first.id)
            )
        )
        asyncio.run(
            server.gui._handle_gui_preview_reload(
                first_client_id, _messages.GuiPreviewReloadMessage(second.id)
            )
        )
        assert other_client_finished.wait(2.0)
        assert other_source_finished.wait(2.0)
    finally:
        release_warm.set()


def test_disconnecting_drops_queued_preview_work(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle = server.gui.add_preview_button("Look", b"x", filename="x.txt")
    client = _Client(server)
    client_id = ClientId(29)
    monkeypatch.setattr(
        server.gui,
        "_resolve_client",
        lambda requested: client if requested == client_id else None,
    )
    client.gui = SimpleNamespace(_discard_client_work=lambda *_args, **_kwargs: None)
    with server._client_lock:
        server._connected_clients[client_id] = client  # type: ignore[assignment]

    warm_started = threading.Event()
    release_warm = threading.Event()
    events: list[str] = []
    worker = None

    def warm(requesting_client: Any) -> None:
        events.append("warm:start")
        warm_started.set()
        if not release_warm.wait(5.0):
            raise AssertionError("test did not release the warm operation")
        events.append("warm:end")

    monkeypatch.setattr(handle, "_warm", warm)
    monkeypatch.setattr(handle, "_send", lambda event: events.append("preview"))
    monkeypatch.setattr(handle, "_reload", lambda event: events.append("reload"))

    try:
        asyncio.run(
            server.gui._handle_gui_preview_warm(
                client_id, _messages.GuiPreviewWarmMessage(handle.id)
            )
        )
        assert warm_started.wait(2.0)
        asyncio.run(
            server.gui._handle_gui_updates(
                client_id,
                _messages.GuiUpdateMessage(handle.id, {"value": True}),
            )
        )
        assert handle._file_busy is True
        assert handle.disabled is True
        for _ in range(2):
            asyncio.run(
                server.gui._handle_gui_preview_reload(
                    client_id, _messages.GuiPreviewReloadMessage(handle.id)
                )
            )

        with server.gui._preview_work_lock:
            state = server.gui._preview_work_from_key[(client_id, handle.id)]
            worker = state.worker
        disconnect = server._websock_server._client_disconnect_cb[-1]
        assert inspect.iscoroutinefunction(disconnect)
        asyncio.run(disconnect(SimpleNamespace(client_id=client_id)))
        with server.gui._preview_work_lock:
            assert (client_id, handle.id) not in server.gui._preview_work_from_key
        assert handle._file_busy is False
        assert handle.disabled is False
    finally:
        release_warm.set()

    assert worker is not None
    worker.result(timeout=2.0)
    assert events == ["warm:start", "warm:end"]


def test_markdown_preview_snapshot_rejects_same_size_in_place_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from leika import _gui_handles as handles_impl

    source = tmp_path / "notes.md"
    source.write_bytes(b"before")
    real_fstat = handles_impl.os.fstat
    calls = 0

    def rewrite_between_descriptor_stats(descriptor: int) -> os.stat_result:
        nonlocal calls
        metadata = real_fstat(descriptor)
        calls += 1
        if calls == 2:
            source.write_bytes(b"after!")
            timestamp = metadata.st_mtime_ns + 1_000_000_000
            os.utime(source, ns=(timestamp, timestamp))
        return metadata if calls == 2 else real_fstat(descriptor)

    monkeypatch.setattr(handles_impl.os, "fstat", rewrite_between_descriptor_stats)
    with pytest.raises(OSError, match="changed while it was being read"):
        handles_impl._read_preview_markdown(source, 64)
