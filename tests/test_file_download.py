"""Server-side behavior of ``send_file_download``.

The browser half of this -- saving immediately versus offering a link the user
can right click -- lives in ``MessageHandler.tsx``. These tests pin down what
the server puts on the wire, which is what the client branches on.

``ClientHandle`` does the real work and ``Server`` fans out to its clients, so
the wire-format tests drive ``ClientHandle.send_file_download`` against a
recording stand-in rather than standing up a websocket and a GUI api.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, List, Tuple

import pytest

import leika
from leika import _messages
from leika._server import ClientHandle, _download_source


class _RecordingConnection:
    def __init__(self) -> None:
        self.messages: List[Any] = []

    def queue_message(self, message: Any) -> bool:
        self.messages.append(message)
        return True


class _CloseAfterStartConnection(_RecordingConnection):
    def queue_message(self, message: Any) -> bool:
        if self.messages:
            return False
        return super().queue_message(message)


class _Client:
    """The members the sending methods actually touch.

    ``_send_file`` is borrowed from the real class rather than stubbed: it is
    the thing under test, reached through whichever public method the test
    called. ``_send_preview`` comes with it, being the step between a preview
    and that.
    """

    _send_file = ClientHandle._send_file
    _send_preview = ClientHandle._send_preview

    def __init__(self) -> None:
        self._websock_connection = _RecordingConnection()
        self.flushes = 0
        self.notifications: List[Tuple[str, str]] = []

    def flush(self) -> None:
        self.flushes += 1

    def add_notification(self, title: str, body: str = "", **kwargs: Any) -> None:
        self.notifications.append((title, body))


def _send(filename: str, content: bytes | Path, **kwargs: Any) -> List[Any]:
    client = _Client()
    ClientHandle.send_file_download(client, filename, content, **kwargs)  # type: ignore[arg-type]
    return client._websock_connection.messages


def _start(messages: List[Any]) -> _messages.FileTransferStartDownload:
    starts = [m for m in messages if isinstance(m, _messages.FileTransferStartDownload)]
    assert len(starts) == 1
    return starts[0]


def _parts(messages: List[Any]) -> List[_messages.FileTransferPart]:
    return [m for m in messages if isinstance(m, _messages.FileTransferPart)]


def test_save_immediately_defaults_to_false() -> None:
    # The documented default is the link-in-a-notification flow, not a forced
    # save; the client reads the disposition to choose between them.
    assert _start(_send("report.csv", b"a,b\n1,2\n")).disposition == "link"


def test_save_immediately_is_forwarded() -> None:
    messages = _send("report.csv", b"a,b\n1,2\n", save_immediately=True)
    assert _start(messages).disposition == "save"


def test_filename_and_inferred_mime_type_are_sent() -> None:
    start = _start(_send("report.csv", b"a,b\n1,2\n"))
    assert start.filename == "report.csv"
    assert start.mime_type == "text/csv"


def test_unknown_extension_falls_back_to_octet_stream() -> None:
    assert _start(_send("blob.unknownext", b"\x00\x01")).mime_type == "application/octet-stream"


def test_content_is_chunked_and_reassembles() -> None:
    content = bytes(range(256)) * 4
    messages = _send("data.bin", content, chunk_size=100)
    start, parts = _start(messages), _parts(messages)

    assert start.size_bytes == len(content)
    assert start.part_count == len(parts)
    assert [part.part_index for part in parts] == list(range(len(parts)))
    assert all(part.transfer_uuid == start.transfer_uuid for part in parts)
    assert b"".join(part.content for part in parts) == content


def test_start_precedes_every_part() -> None:
    # The client errors out on a part for an unknown transfer.
    messages = _send("data.bin", b"0123456789", chunk_size=3)
    assert isinstance(messages[0], _messages.FileTransferStartDownload)
    assert len(messages) == 1 + len(_parts(messages))


def test_transfer_stops_when_connection_closes_after_start() -> None:
    client = _Client()
    client._websock_connection = _CloseAfterStartConnection()

    ClientHandle.send_file_download(client, "data.bin", b"0123456789", chunk_size=2)  # type: ignore[arg-type]

    assert len(client._websock_connection.messages) == 1
    assert isinstance(
        client._websock_connection.messages[0],
        _messages.FileTransferStartDownload,
    )
    assert client.flushes == 0


def test_empty_file_sends_no_parts() -> None:
    messages = _send("empty.txt", b"")
    assert _start(messages).size_bytes == 0
    assert _start(messages).part_count == 0
    assert _parts(messages) == []


def test_a_path_is_read_from_disk_and_chunked_like_bytes(tmp_path: Path) -> None:
    content = bytes(range(256)) * 4
    path = tmp_path / "data.bin"
    path.write_bytes(content)

    messages = _send("data.bin", path, chunk_size=100)
    start, parts = _start(messages), _parts(messages)

    assert start.size_bytes == len(content)
    assert start.part_count == len(parts)
    assert b"".join(part.content for part in parts) == content


def test_an_interrupted_send_emits_a_terminal_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = OSError("source shrank")

    @contextmanager
    def interrupted_source(content: bytes | Path, chunk_size: int):
        del content, chunk_size

        def chunks():
            yield b"first"
            raise failure

        yield 10, chunks()

    monkeypatch.setattr("leika._server._download_source", interrupted_source)
    client = _Client()
    with pytest.raises(OSError, match="source shrank") as captured:
        client._send_file("data.bin", b"ignored", 5, "preview")

    assert captured.value is failure
    start = _start(client._websock_connection.messages)
    assert isinstance(client._websock_connection.messages[1], _messages.FileTransferPart)
    abort = client._websock_connection.messages[-1]
    assert isinstance(abort, _messages.FileTransferAbort)
    assert abort.transfer_uuid == start.transfer_uuid
    assert abort.reason == "source shrank"
    assert client.flushes == 2


def test_an_empty_path_sends_no_parts(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    assert _parts(_send("empty.txt", path)) == []


def test_a_str_is_refused_rather_than_guessed_at() -> None:
    # It could be either the contents or a path, and picking one silently
    # sends the wrong file half the time.
    with pytest.raises(TypeError, match="bytes or a Path"):
        _send("notes.txt", "hello")  # type: ignore[arg-type]


def test_a_file_replaced_mid_send_is_still_sent_whole(tmp_path: Path) -> None:
    # A rotated log: the path is renamed away and a new file takes its place
    # after the transfer has announced its length. The open descriptor still
    # refers to the original, so the bytes match what was promised.
    path = tmp_path / "app.log"
    path.write_bytes(b"original contents")

    with _download_source(path, chunk_size=4) as (size_bytes, chunks):
        path.rename(tmp_path / "app.log.1")
        path.write_bytes(b"new")
        assert b"".join(chunks) == b"original contents"
    assert size_bytes == len(b"original contents")


def test_a_file_truncated_mid_send_says_so(tmp_path: Path) -> None:
    # The length is already on the wire and the client waits for exactly that
    # many bytes, so a short read has to raise rather than quietly hang the
    # download.
    # Large enough that the rest of it cannot be sitting in the reader's
    # buffer already, which is what makes a small file survive this.
    path = tmp_path / "app.log"
    path.write_bytes(b"x" * (1024 * 1024))

    with _download_source(path, chunk_size=4096) as (_, chunks):
        assert next(chunks) == b"x" * 4096
        with path.open("wb"):
            pass
        with pytest.raises(OSError, match="shrank while it was being sent"):
            list(chunks)


def test_a_preview_rides_the_same_transfer_under_its_own_disposition() -> None:
    # One transfer, three endings: the client reads the disposition to know
    # whether to save the file, offer it, or show it.
    client = _Client()
    ClientHandle.send_file_preview(client, "notes.md", b"# Title\n")  # type: ignore[arg-type]
    messages = client._websock_connection.messages

    assert _start(messages).disposition == "preview"
    assert _start(messages).mime_type == "text/markdown"
    assert b"".join(part.content for part in _parts(messages)) == b"# Title\n"


def test_preview_rejects_invalid_content_and_limits() -> None:
    client = _Client()
    with pytest.raises(TypeError, match="bytes or a Path"):
        ClientHandle.send_file_preview(client, "notes.txt", "hello")  # type: ignore[arg-type]
    ClientHandle.send_file_preview(client, "empty.txt", b"", max_bytes=0)  # type: ignore[arg-type]
    for max_bytes in (-1, True):
        with pytest.raises(ValueError, match="non-negative integer"):
            ClientHandle.send_file_preview(
                client,
                "notes.txt",
                b"hello",
                max_bytes=max_bytes,  # type: ignore[arg-type]
            )


def test_a_file_over_the_preview_limit_is_described_rather_than_sent() -> None:
    # Showing a file means holding all of it in the tab; past some size that
    # is a tab that stops responding, with nothing on screen to say why.
    client = _Client()
    ClientHandle.send_file_preview(client, "capture.bin", b"x" * 2048, max_bytes=1024)  # type: ignore[arg-type]

    assert client._websock_connection.messages == []
    assert len(client.notifications) == 1
    title, body = client.notifications[0]
    assert title == "Too large to preview"
    assert "capture.bin" in body
    assert "2.0 KiB" in body and "1.0 KiB" in body


def test_a_path_is_measured_from_the_open_descriptor(tmp_path: Path) -> None:
    # The limit is settled on the same descriptor the transfer would read, so
    # a path replacement cannot race a preliminary stat check.
    path = tmp_path / "capture.bin"
    path.write_bytes(b"x" * 2048)
    client = _Client()
    ClientHandle.send_file_preview(client, "capture.bin", path, max_bytes=1024)  # type: ignore[arg-type]

    assert client._websock_connection.messages == []
    assert client.notifications[0][0] == "Too large to preview"


def test_a_preview_limit_uses_the_source_opened_for_transfer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def replaced_source(content: bytes | Path, chunk_size: int):
        del content, chunk_size
        yield 2048, iter([b"x" * 2048])

    monkeypatch.setattr("leika._server._download_source", replaced_source)
    client = _Client()
    ClientHandle.send_file_preview(client, "capture.bin", b"small", max_bytes=1024)  # type: ignore[arg-type]

    assert client._websock_connection.messages == []
    assert client.notifications == [
        ("Too large to preview", "capture.bin is 2.0 KiB, over the 1.0 KiB preview limit.")
    ]


def test_a_file_at_the_limit_is_sent() -> None:
    # The limit is a ceiling, not a bound: exactly max_bytes is allowed.
    client = _Client()
    ClientHandle.send_file_preview(client, "capture.bin", b"x" * 1024, max_bytes=1024)  # type: ignore[arg-type]

    assert _start(client._websock_connection.messages).size_bytes == 1024
    assert client.notifications == []


@pytest.mark.parametrize("chunk_size", [0, -1, True])
def test_invalid_chunk_size_is_rejected_per_client(chunk_size: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _send("x.txt", b"data", chunk_size=chunk_size)


@pytest.mark.parametrize("chunk_size", [0, -1, True])
def test_invalid_chunk_size_is_rejected_on_the_server(
    server: leika.Server, chunk_size: object
) -> None:
    # Server validates up front rather than only inside the per-client fan-out,
    # so the error still surfaces with no clients connected.
    with pytest.raises(ValueError, match="positive integer"):
        server.send_file_download("x.txt", b"data", chunk_size=chunk_size)  # type: ignore[arg-type]
