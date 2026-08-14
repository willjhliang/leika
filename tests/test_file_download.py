"""Server-side behavior of ``send_file_download``.

The browser half of this -- saving immediately versus offering a link the user
can right click -- lives in ``MessageHandler.tsx``. These tests pin down what
the server puts on the wire, which is what the client branches on.

``ClientHandle`` does the real work and ``Server`` fans out to its clients, so
the wire-format tests drive ``ClientHandle.send_file_download`` against a
recording stand-in rather than standing up a websocket and a GUI api.
"""

from __future__ import annotations

import gc
import os
import threading
import time
import weakref
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Tuple

import pytest

import leika
from leika import _file_transfer as file_transfer_impl
from leika import _messages
from leika import _server as server_impl
from leika._server import ClientHandle, _download_source


class _RecordingBuffer:
    """Production-shaped buffer contract without asynchronous draining."""

    event_loop = object()

    def reserve_file_bytes(self, size: int) -> bool:
        return True

    def release_file_bytes(self, size: int) -> None:
        pass

    def file_transfer_must_be_deferred(self) -> bool:
        return False


class _RecordingConnection:
    def __init__(self) -> None:
        self.messages: List[Any] = []
        self.buffer = _RecordingBuffer()

    def get_message_buffer(self) -> _RecordingBuffer:
        return self.buffer

    def queue_message(self, message: Any) -> bool:
        self.messages.append(message)
        return True

    def queue_reserved_file_message(self, message: Any, size: int) -> bool:
        self.messages.append(message)
        return True


class _CloseAfterStartConnection(_RecordingConnection):
    def queue_message(self, message: Any) -> bool:
        if self.messages:
            return False
        return super().queue_message(message)

    def queue_reserved_file_message(self, message: Any, size: int) -> bool:
        del message, size
        return False


class _Client:
    """The members the sending methods actually touch.

    ``_send_file`` is borrowed from the real class rather than stubbed: it is
    the thing under test, reached through whichever public method the test
    called. ``_send_preview`` comes with it, being the step between a preview
    and that.
    """

    _send_file = ClientHandle._send_file
    _send_preview = ClientHandle._send_preview
    _track_outgoing_file_transfer = ClientHandle._track_outgoing_file_transfer
    _cancel_outgoing_file_transfer = ClientHandle._cancel_outgoing_file_transfer
    _cancel_all_outgoing_file_transfers = ClientHandle._cancel_all_outgoing_file_transfers

    def __init__(self) -> None:
        self._websock_connection = _RecordingConnection()
        self._outgoing_transfer_lock = threading.Lock()
        self._outgoing_transfer_cancel_from_uuid: dict[str, threading.Event] = {}
        self.flushes = 0
        self.notifications: List[Tuple[str, str]] = []

    def flush(self) -> None:
        self.flushes += 1

    def add_notification(self, title: str, body: str = "", **kwargs: Any) -> None:
        self.notifications.append((title, body))


class _PendingTransferFuture:
    def add_done_callback(self, callback: Any) -> None:
        del callback


class _RecordingTransferExecutor:
    def __init__(self) -> None:
        self.callbacks: list[Any] = []
        self.retained_bytes: list[int] = []

    def submit_retained(self, callback: Any, *, retained_bytes: int) -> _PendingTransferFuture:
        self.callbacks.append(callback)
        self.retained_bytes.append(retained_bytes)
        return _PendingTransferFuture()


def _broadcast_server(client: _Client, executor: _RecordingTransferExecutor) -> server_impl.Server:
    server = server_impl.Server.__new__(server_impl.Server)
    server._client_lock = threading.RLock()
    server._connected_clients = {1: client}  # type: ignore[dict-item]
    server._event_loop = object()  # type: ignore[assignment]
    server._transfer_executor = executor  # type: ignore[assignment]
    return server


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


@pytest.mark.parametrize("value", [1, 0, "yes", None])
def test_save_immediately_requires_an_exact_bool(value: object) -> None:
    client = _Client()
    with pytest.raises(TypeError, match="save_immediately must be a bool"):
        ClientHandle.send_file_download(
            client,
            "report.csv",
            b"data",
            save_immediately=value,  # type: ignore[arg-type]
        )
    assert client._websock_connection.messages == []


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


def test_browser_abort_cancels_download_and_releases_owned_reservation() -> None:
    client = _Client()

    class CancelOnReserveBuffer(_RecordingBuffer):
        def __init__(self) -> None:
            self.released: list[int] = []

        def reserve_file_bytes(self, size: int) -> bool:
            with client._outgoing_transfer_lock:
                (cancelled,) = client._outgoing_transfer_cancel_from_uuid.values()
            cancelled.set()
            return True

        def release_file_bytes(self, size: int) -> None:
            self.released.append(size)

    buffer = CancelOnReserveBuffer()
    client._websock_connection.buffer = buffer

    client._send_file("data.bin", b"0123456789", 2, "preview")

    assert len(client._websock_connection.messages) == 1
    assert isinstance(
        client._websock_connection.messages[0],
        _messages.FileTransferStartDownload,
    )
    assert buffer.released == [2]
    assert client._outgoing_transfer_cancel_from_uuid == {}
    assert not any(
        isinstance(message, _messages.FileTransferAbort)
        for message in client._websock_connection.messages
    )


def test_incoming_abort_routes_to_the_matching_client_transfer() -> None:
    client = _Client()
    server = server_impl.Server.__new__(server_impl.Server)
    server._client_lock = threading.RLock()
    server._connected_clients = {7: client}

    with client._track_outgoing_file_transfer("transfer") as cancelled:
        server._handle_file_transfer_abort(
            7, _messages.FileTransferAbort("transfer", "browser rejected start")
        )
        assert cancelled.is_set()


def test_active_outgoing_transfer_limit_releases_and_disconnect_cancels() -> None:
    client = _Client()
    stack = ExitStack()
    cancellations = [
        stack.enter_context(client._track_outgoing_file_transfer(f"transfer-{index}"))
        for index in range(server_impl._FILE_DOWNLOAD_MAX_ACTIVE)
    ]

    with pytest.raises(RuntimeError, match="128 active outgoing file transfers"):
        with client._track_outgoing_file_transfer("over-cap"):
            pass
    assert len(client._outgoing_transfer_cancel_from_uuid) == 128

    stack.close()
    assert client._outgoing_transfer_cancel_from_uuid == {}

    with client._track_outgoing_file_transfer("replacement") as replacement:
        client._cancel_all_outgoing_file_transfers()
        assert replacement.is_set()
        assert client._outgoing_transfer_cancel_from_uuid == {}

    assert not any(cancelled.is_set() for cancelled in cancellations)


def test_empty_file_sends_no_parts() -> None:
    messages = _send("empty.txt", b"")
    assert _start(messages).size_bytes == 0
    assert _start(messages).part_count == 0
    assert _parts(messages) == []


def test_special_file_download_is_rejected_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are not available on this platform")
    fifo = tmp_path / "download.fifo"
    os.mkfifo(fifo)

    started = time.monotonic()
    with pytest.raises(ValueError, match="regular file"):
        with _download_source(fifo, 1024):
            pass
    assert time.monotonic() - started < 1.0


def test_regular_file_replacement_between_stat_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"replacement")
    displaced = tmp_path / "displaced.bin"
    original_open = file_transfer_impl.os.open
    swapped = False

    def swap_then_open(path: os.PathLike[str] | str, flags: int) -> int:
        nonlocal swapped
        if Path(path) == source and not swapped:
            swapped = True
            source.rename(displaced)
            replacement.rename(source)
        return original_open(path, flags)

    monkeypatch.setattr(file_transfer_impl.os, "open", swap_then_open)
    with pytest.raises(OSError, match="replaced"):
        with file_transfer_impl.open_regular_file(source):
            pass
    assert swapped


def test_special_file_replacement_between_stat_and_open_is_rejected_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are not available on this platform")
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    displaced = tmp_path / "displaced.bin"
    fifo = tmp_path / "replacement.fifo"
    os.mkfifo(fifo)
    original_open = file_transfer_impl.os.open

    def swap_then_open(path: os.PathLike[str] | str, flags: int) -> int:
        if Path(path) == source and source.is_file():
            source.rename(displaced)
            fifo.rename(source)
        return original_open(path, flags)

    monkeypatch.setattr(file_transfer_impl.os, "open", swap_then_open)
    started = time.monotonic()
    with pytest.raises(ValueError, match="regular file"):
        with file_transfer_impl.open_regular_file(source):
            pass
    assert time.monotonic() - started < 1.0


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
    failure = OSError("/private/source.bin shrank\n" + "x" * 20_000)

    @contextmanager
    def interrupted_source(content: bytes | Path, chunk_size: int):
        del content, chunk_size

        def chunks():
            yield b"first"
            raise failure

        yield 10, chunks()

    monkeypatch.setattr("leika._server._download_source", interrupted_source)
    client = _Client()
    with pytest.raises(OSError) as captured:
        client._send_file("data.bin", b"ignored", 5, "preview")

    assert captured.value is failure
    start = _start(client._websock_connection.messages)
    assert isinstance(client._websock_connection.messages[1], _messages.FileTransferPart)
    abort = client._websock_connection.messages[-1]
    assert isinstance(abort, _messages.FileTransferAbort)
    assert abort.transfer_uuid == start.transfer_uuid
    assert abort.reason == "The server could not complete this transfer."
    assert len(abort.reason) <= 160
    assert "/private" not in abort.reason
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


@pytest.mark.parametrize("broadcast", [False, True], ids=["client", "server"])
@pytest.mark.parametrize("deferred", [False, True], ids=["direct", "deferred"])
def test_path_subclasses_are_detached_before_direct_and_deferred_sends(
    tmp_path: Path,
    broadcast: bool,
    deferred: bool,
) -> None:
    class Payload:
        pass

    class RichPath(type(Path())):
        pass

    source = tmp_path / "payload.bin"
    source.write_bytes(b"payload")
    payload = Payload()
    payload_ref = weakref.ref(payload)
    rich_path = RichPath(source)
    rich_path.payload = payload

    executor = _RecordingTransferExecutor()
    client = _Client()
    client._server = SimpleNamespace(_transfer_executor=executor)
    client._websock_connection.buffer.file_transfer_must_be_deferred = lambda: deferred
    observed: list[tuple[str, bytes | Path, int, str, dict[str, Any]]] = []

    def record_send(
        filename: str,
        content: bytes | Path,
        chunk_size: int,
        disposition: str,
        **kwargs: Any,
    ) -> None:
        observed.append((filename, content, chunk_size, disposition, kwargs))

    client._send_file = record_send  # type: ignore[method-assign]
    if broadcast:
        server = _broadcast_server(client, executor)
        server.send_file_preview("payload.bin", rich_path, max_bytes=8)
    else:
        ClientHandle.send_file_preview(client, "payload.bin", rich_path, max_bytes=8)  # type: ignore[arg-type]

    assert len(executor.callbacks) == int(deferred)
    assert executor.retained_bytes == ([0] if deferred else [])
    assert len(observed) == int(not deferred)

    del rich_path, payload
    gc.collect()
    assert payload_ref() is None

    if deferred:
        executor.callbacks.pop()()
    assert len(observed) == 1
    filename, normalized_path, chunk_size, disposition, kwargs = observed[0]
    assert filename == "payload.bin"
    assert normalized_path == source
    assert type(normalized_path) is type(Path())
    assert chunk_size == 1024 * 1024
    assert disposition == "preview"
    assert kwargs["max_bytes"] == 8
    assert type(kwargs["max_bytes"]) is int


@pytest.mark.parametrize("broadcast", [False, True], ids=["client", "server"])
@pytest.mark.parametrize(
    ("field", "exception_type", "message"),
    [
        ("filename", TypeError, "filename must be a string"),
        ("content", TypeError, "content must be bytes or a Path"),
        ("max_bytes", ValueError, "max_bytes must be a non-negative integer"),
    ],
)
def test_retaining_primitive_subclasses_are_rejected_before_deferred_sends(
    broadcast: bool,
    field: str,
    exception_type: type[Exception],
    message: str,
) -> None:
    class Payload:
        pass

    class RichStr(str):
        pass

    class RichBytes(bytes):
        pass

    class RichInt(int):
        pass

    payload = Payload()
    payload_ref = weakref.ref(payload)
    if field == "filename":
        rich: Any = RichStr("payload.bin")
    elif field == "content":
        rich = RichBytes(b"payload")
    else:
        rich = RichInt(8)
    rich.payload = payload
    arguments: dict[str, Any] = {
        "filename": "payload.bin",
        "content": b"payload",
        "max_bytes": 8,
    }
    arguments[field] = rich

    executor = _RecordingTransferExecutor()
    client = _Client()
    client._server = SimpleNamespace(_transfer_executor=executor)
    client._websock_connection.buffer.file_transfer_must_be_deferred = lambda: True
    with pytest.raises(exception_type, match=message):
        if broadcast:
            server = _broadcast_server(client, executor)
            server.send_file_preview(**arguments)
        else:
            ClientHandle.send_file_preview(client, **arguments)  # type: ignore[arg-type]

    assert executor.callbacks == []
    assert client._websock_connection.messages == []
    arguments.clear()
    del rich, payload
    gc.collect()
    assert payload_ref() is None


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


@pytest.mark.parametrize("chunk_size", [True, 1.5, "1024", None])
def test_noninteger_chunk_size_has_a_stable_type_error(chunk_size: object) -> None:
    with pytest.raises(TypeError, match="chunk_size must be an integer"):
        _send("x.txt", b"data", chunk_size=chunk_size)


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_invalid_chunk_size_is_rejected_per_client(chunk_size: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        _send("x.txt", b"data", chunk_size=chunk_size)


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_invalid_chunk_size_is_rejected_on_the_server(
    server: leika.Server, chunk_size: object
) -> None:
    # Server validates up front rather than only inside the per-client fan-out,
    # so the error still surfaces with no clients connected.
    with pytest.raises(ValueError, match="positive integer"):
        server.send_file_download("x.txt", b"data", chunk_size=chunk_size)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "filename",
    [
        "",
        "   ",
        ".",
        "..",
        "../secret.txt",
        r"..\secret.txt",
        "bad\x00name",
        "bad\nname",
        "x" * 256,
    ],
)
def test_download_filename_is_validated_before_queueing(filename: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        _send(filename, b"data")


def test_download_filename_requires_a_string() -> None:
    with pytest.raises(TypeError, match="string"):
        _send(123, b"data")  # type: ignore[arg-type]


def test_maximum_chunk_size_is_a_real_boundary() -> None:
    _send(
        "empty.bin",
        b"",
        chunk_size=server_impl._FILE_DOWNLOAD_MAX_CHUNK_BYTES,
    )
    with pytest.raises(ValueError, match="at most"):
        _send(
            "empty.bin",
            b"",
            chunk_size=server_impl._FILE_DOWNLOAD_MAX_CHUNK_BYTES + 1,
        )


class _RejectStartConnection(_RecordingConnection):
    def queue_message(self, message: Any) -> bool:
        self.messages.append(message)
        return False


@pytest.mark.parametrize(
    ("size_bytes", "chunk_size", "accepted"),
    [
        (server_impl._FILE_DOWNLOAD_MAX_BYTES, 8 * 1024 * 1024, True),
        (server_impl._FILE_DOWNLOAD_MAX_BYTES + 1, 8 * 1024 * 1024, False),
        (server_impl._FILE_DOWNLOAD_MAX_PARTS, 1, True),
        (server_impl._FILE_DOWNLOAD_MAX_PARTS + 1, 1, False),
    ],
)
def test_browser_download_preflight_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    size_bytes: int,
    chunk_size: int,
    accepted: bool,
) -> None:
    @contextmanager
    def advertised(content: bytes | Path, requested_chunk_size: int):
        del content
        assert requested_chunk_size == chunk_size
        yield size_bytes, iter(())

    monkeypatch.setattr(server_impl, "_download_source", advertised)
    client = _Client()
    client._websock_connection = _RejectStartConnection()
    if accepted:
        client._send_file("data.bin", b"", chunk_size, "link")
        assert isinstance(
            client._websock_connection.messages[0],
            _messages.FileTransferStartDownload,
        )
    else:
        with pytest.raises(ValueError):
            client._send_file("data.bin", b"", chunk_size, "link")
        assert client._websock_connection.messages == []


def test_off_loop_path_errors_raise_synchronously(tmp_path: Path) -> None:
    missing = tmp_path / "missing.bin"
    client = _Client()
    with pytest.raises(FileNotFoundError):
        ClientHandle.send_file_download(client, "missing.bin", missing)  # type: ignore[arg-type]


def test_atomic_or_event_loop_transfer_is_deferred_without_deadlock(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.bin"
    client = _Client()
    submitted: list[Any] = []

    class Future:
        def add_done_callback(self, callback: Any) -> None:
            del callback

    class Executor:
        def submit_retained(self, callback: Any, *, retained_bytes: int) -> Future:
            assert retained_bytes == 0
            submitted.append(callback)
            return Future()

    client._server = SimpleNamespace(_transfer_executor=Executor())
    client._websock_connection.buffer.file_transfer_must_be_deferred = lambda: True

    # The public call returns before path open in a context whose own outbound
    # drain would otherwise be blocked. The worker later observes the error.
    ClientHandle.send_file_download(client, "missing.bin", missing)  # type: ignore[arg-type]
    assert len(submitted) == 1
    with pytest.raises(FileNotFoundError):
        submitted[0]()
