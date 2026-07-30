"""What a preview button does with a press.

It is the download button's twin -- both are ``_GuiFileButtonHandle``, so
resolving the contents, defaulting the name and holding the button shut while
the file goes out are pinned once, in ``test_download_button.py``. What is
tested here is what only the preview does: show rather than save, and refuse a
file too large to hold in a tab.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

import pytest

import leika
from leika._gui_handles import GuiEvent, GuiPreviewButtonHandle


class _Client:
    """A client that records what it was asked to show."""

    def __init__(self) -> None:
        self.previewed: List[Tuple[str, Any, int]] = []
        self.downloaded: List[Tuple[str, Any]] = []

    def send_file_preview(
        self, filename: str, content: Any, chunk_size: int = 0, max_bytes: int = 0
    ) -> None:
        self.previewed.append((filename, content, max_bytes))

    def send_file_download(self, filename: str, content: Any, **kwargs: Any) -> None:
        self.downloaded.append((filename, content))


def _press(handle: GuiPreviewButtonHandle) -> _Client:
    client = _Client()
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
