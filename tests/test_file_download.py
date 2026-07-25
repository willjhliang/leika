"""Server-side behavior of ``send_file_download``.

The browser half of this -- saving immediately versus offering a link the user
can right click -- lives in ``MessageHandler.tsx``. These tests pin down what
the server puts on the wire, which is what the client branches on.

``ClientHandle`` does the real work and ``Server`` fans out to its clients, so
the wire-format tests drive ``ClientHandle.send_file_download`` against a
recording stand-in rather than standing up a websocket and a GUI api.
"""

from __future__ import annotations

from typing import Any, List

import pytest

import leika
from leika import _messages
from leika._server import ClientHandle


class _RecordingConnection:
    def __init__(self) -> None:
        self.messages: List[Any] = []

    def queue_message(self, message: Any) -> None:
        self.messages.append(message)


class _Client:
    """The two members ``ClientHandle.send_file_download`` actually touches."""

    def __init__(self) -> None:
        self._websock_connection = _RecordingConnection()
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1


def _send(filename: str, content: bytes, **kwargs: Any) -> List[Any]:
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
    # save; the client reads this flag to choose between them.
    assert _start(_send("report.csv", b"a,b\n1,2\n")).save_immediately is False


def test_save_immediately_is_forwarded() -> None:
    messages = _send("report.csv", b"a,b\n1,2\n", save_immediately=True)
    assert _start(messages).save_immediately is True


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


def test_empty_file_sends_no_parts() -> None:
    messages = _send("empty.txt", b"")
    assert _start(messages).size_bytes == 0
    assert _start(messages).part_count == 0
    assert _parts(messages) == []


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
