"""What a preview button does with a press.

It is the download button's twin -- both are ``_GuiFileButtonHandle``, so
resolving the contents, defaulting the name and holding the button shut while
the file goes out are pinned once, in ``test_download_button.py``. What is
tested here is what only the preview does: show rather than save, and refuse a
file too large to hold in a tab.
"""

from __future__ import annotations

import base64
import re
import urllib.request
from pathlib import Path
from typing import Any, List, Tuple

import pytest

import leika
from leika._gui_handles import GuiEvent, GuiPreviewButtonHandle


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
        self.warmed: List[Tuple[str, Any]] = []

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
    ) -> None:
        assert disposition == "warm"
        self.warmed.append((filename, content))

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
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
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
    assert urls[0].startswith("/leika-assets/") and urls[0].endswith(".png")
    assert b"figures/plot.png" not in content
    assert b"base64" not in content

    # The URL the document now points at answers with the image itself.
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}{urls[0]}") as response:
        assert response.read() == png
        assert response.headers["Content-Type"] == "image/png"


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

    assert client.warmed == [("notes.md", b"# hi\n")]
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
    # The URL is the content's hash: re-registering an unchanged file answers
    # from the digest cache with the same URL (this is what lets the browser
    # cache forever), and an edit -- new mtime, new size -- is a new URL.
    asset = tmp_path / "plot.png"
    asset.write_bytes(b"one")

    first = server.register_http_asset(asset)
    assert server.register_http_asset(asset) == first

    asset.write_bytes(b"two, longer")
    assert server.register_http_asset(asset) != first


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
