"""What ``add_download_button`` does that a plain button and a callback do not.

The transfer itself is ``send_file_download``'s, and pinned in
``test_file_download.py``. What is left to check here is the wiring: which
client the file goes to, what it is named, and that the button holds itself
shut while it is going out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

import pytest

import leika
from leika._gui_handles import GuiDownloadButtonHandle, GuiEvent


class _Client:
    """A client that records what it was asked to send."""

    def __init__(self) -> None:
        self.sent: List[Tuple[str, Any]] = []
        self.kwargs: List[dict] = []

    def send_file_download(self, filename: str, content: Any, **kwargs: Any) -> None:
        self.sent.append((filename, content))
        self.kwargs.append(kwargs)


def _press(handle: GuiDownloadButtonHandle) -> _Client:
    """Press the button the way a client would, and hand back that client."""
    client = _Client()
    handle._send(GuiEvent(client, 0, handle))  # type: ignore[arg-type]
    return client


def test_the_file_goes_to_the_client_that_pressed(server: leika.Server) -> None:
    # The mistake this exists to head off: reaching for the server-wide
    # `send_file_download`, which hands the file to every open browser.
    handle = server.gui.add_download_button("Export", b"a,b\n", filename="report.csv")
    assert _press(handle).sent == [("report.csv", b"a,b\n")]


def test_the_file_saves_rather_than_arriving_as_a_link(server: leika.Server) -> None:
    # The press is already the ask: a notification to press a second time is
    # the thing a download button exists to spare its user.
    handle = server.gui.add_download_button("Export", b"a,b\n", filename="report.csv")
    assert _press(handle).kwargs == [{"save_immediately": True}]


def test_contents_can_be_bytes_a_path_or_a_function(server: leika.Server, tmp_path: Path) -> None:
    path = tmp_path / "manual.pdf"
    path.write_bytes(b"%PDF-")

    from_bytes = server.gui.add_download_button("A", b"raw", filename="raw.txt")
    from_path = server.gui.add_download_button("B", path)
    from_call = server.gui.add_download_button("C", lambda _: path)

    assert _press(from_bytes).sent == [("raw.txt", b"raw")]
    assert _press(from_path).sent == [("manual.pdf", path)]
    assert _press(from_call).sent == [("manual.pdf", path)]


def test_a_function_runs_on_every_press(server: leika.Server) -> None:
    # The point of passing one: the file is made when it is asked for, not
    # when the button was.
    presses = []

    def contents(event: leika.GuiEvent[Any]) -> bytes:
        presses.append(event)
        return f"press {len(presses)}".encode()

    handle = server.gui.add_download_button("Export", contents, filename="n.txt")
    assert _press(handle).sent == [("n.txt", b"press 1")]
    assert _press(handle).sent == [("n.txt", b"press 2")]


def test_filename_defaults_to_the_name_on_disk(server: leika.Server, tmp_path: Path) -> None:
    path = tmp_path / "readings.csv"
    path.write_bytes(b"t,v\n")
    handle = server.gui.add_download_button("Export", path)
    assert _press(handle).sent == [("readings.csv", path)]


def test_an_explicit_filename_wins_over_the_one_on_disk(
    server: leika.Server, tmp_path: Path
) -> None:
    path = tmp_path / "tmp-38f1.csv"
    path.write_bytes(b"t,v\n")
    handle = server.gui.add_download_button("Export", path, filename="readings.csv")
    assert _press(handle).sent == [("readings.csv", path)]


def test_bytes_without_a_filename_are_rejected_at_creation(server: leika.Server) -> None:
    # Nothing about the bytes says what to call them, and this much is known
    # before anyone presses anything.
    with pytest.raises(ValueError, match="filename= is required"):
        server.gui.add_download_button("Export", b"a,b\n")


def test_a_function_returning_bytes_without_a_filename_is_rejected_on_press(
    server: leika.Server,
) -> None:
    # The same complaint, as early as it can be made: a function says nothing
    # about which of the two it returns until it has run.
    handle = server.gui.add_download_button("Export", lambda _: b"a,b\n")
    with pytest.raises(ValueError, match="no name to save under"):
        _press(handle)


def test_a_str_is_refused_at_creation(server: leika.Server) -> None:
    with pytest.raises(TypeError, match="bytes, a Path"):
        server.gui.add_download_button("Export", "notes.txt")  # type: ignore[arg-type]


def test_the_button_is_shut_while_the_file_is_going_out(server: leika.Server) -> None:
    # Producing a large export takes long enough to click again; the second
    # press would run the whole thing a second time.
    seen: List[bool] = []

    def contents(event: leika.GuiEvent[Any]) -> bytes:
        seen.append(event.target.disabled)
        return b"done"

    handle = server.gui.add_download_button("Export", contents, filename="n.txt")
    assert handle.disabled is False
    _press(handle)
    assert seen == [True]
    assert handle.disabled is False


def test_the_button_reopens_when_the_contents_fail(server: leika.Server) -> None:
    # Otherwise one failed export leaves the button dead for the session.
    def contents(event: leika.GuiEvent[Any]) -> bytes:
        raise RuntimeError("no data yet")

    handle = server.gui.add_download_button("Export", contents, filename="n.txt")
    with pytest.raises(RuntimeError, match="no data yet"):
        _press(handle)
    assert handle.disabled is False


def test_contents_and_filename_can_be_changed_afterwards(server: leika.Server) -> None:
    handle = server.gui.add_download_button("Export", b"first", filename="a.txt")
    handle.content = b"second"
    handle.filename = "b.txt"
    assert _press(handle).sent == [("b.txt", b"second")]


def test_a_press_with_no_client_sends_nothing(server: leika.Server) -> None:
    # `value` can be set from the server, which raises the same callbacks with
    # nobody to send to.
    handle = server.gui.add_download_button("Export", b"a", filename="a.txt")
    handle._send(GuiEvent(None, None, handle))
    assert handle.disabled is False
