from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import math
import mimetypes
import os
import secrets
import threading
import time
from collections.abc import Coroutine, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, BinaryIO, Callable, ContextManager, Iterator, Tuple, TypeVar, cast
from urllib.parse import urlsplit

from . import _client_autobuild, _messages, infra
from ._async_errors import (
    await_callback_result,
    await_user_callback,
    in_sync_user_callback,
    print_async_errors,
)
from ._file_transfer import (
    open_regular_file,
    read_regular_file_snapshot,
    validate_file_display_name,
)
from ._gui_api import GuiApi
from ._gui_handles import PREVIEW_MAX_BYTES, _GuiResourceCost, _make_uuid
from ._notification_handle import NotificationHandle
from ._panes import Panes
from ._share import CloudflaredTunnel, ShareTunnelError
from ._validation import utf16_code_unit_length, validate_layout_id
from ._validation import validate_nonnegative_integer as _validate_nonnegative_integer
from ._validation import validate_positive_integer as _validate_positive_integer
from .infra._async_message_buffer import _FILE_TRANSFER_BUFFER_BYTES
from .infra._auth import HttpPasswordGuard
from .infra._infra import (
    HttpAsset,
    _canonical_hostname,
    _is_loopback_host,
    _normalize_allowed_hosts,
)

NoneOrCoroutine = TypeVar("NoneOrCoroutine", None, Coroutine)

_FILE_UPLOAD_AGGREGATE_MAX_BYTES = 256 * 1024 * 1024
"""Maximum retained payload bytes across simultaneous uploads."""

_FILE_UPLOAD_MAX_ACTIVE = 128
"""Maximum simultaneous uploads, including empty uploads."""

_FILE_DOWNLOAD_MAX_CHUNK_BYTES = _FILE_TRANSFER_BUFFER_BYTES
"""Maximum download part and per-client queued file payload."""

_FILE_DOWNLOAD_MAX_BYTES = 256 * 1024 * 1024
_FILE_DOWNLOAD_MAX_PARTS = 65_536
_FILE_DOWNLOAD_MAX_ACTIVE = 128
"""Hard limits of the bundled browser download assembler."""

_SERVER_GUI_RETAINED_MAX_BYTES = 256 * 1024 * 1024
_SERVER_GUI_PIXELS_MAX = 128 * 1024 * 1024
_SERVER_PAGE_PIXELS_MAX = 64 * 1024 * 1024
_SERVER_CALLBACK_MAX = 256
_IMAGE_PREPARATION_MAX_BYTES = 512 * 1024 * 1024

_CALLBACK_EXECUTOR_MAX_PENDING = 256
_TRANSFER_EXECUTOR_MAX_PENDING = 16
_TRANSFER_EXECUTOR_MAX_RETAINED_BYTES = 256 * 1024 * 1024
_PLOTLY_JS_MAX_BYTES = 32 * 1024 * 1024
"""Maximum stable UTF-8 source loaded from an installed Plotly runtime."""


class _CallbackExecutor(ThreadPoolExecutor):
    """Thread pool with explicit job and captured-payload admission bounds."""

    def __init__(
        self,
        max_workers: int,
        *,
        max_pending: int = _CALLBACK_EXECUTOR_MAX_PENDING,
        max_retained_bytes: int | None = None,
    ) -> None:
        if type(max_pending) is not int or max_pending < max_workers:
            raise ValueError("max_pending must be an integer at least max_workers")
        if max_retained_bytes is not None and (
            type(max_retained_bytes) is not int or max_retained_bytes < 0
        ):
            raise ValueError("max_retained_bytes must be a non-negative integer or None")
        super().__init__(max_workers=max_workers)
        self._max_pending = max_pending
        self._max_retained_bytes = max_retained_bytes
        self._pending_lock = threading.RLock()
        self._pending_futures: set[Future[Any]] = set()
        self._retained_bytes_from_future: dict[Future[Any], int] = {}
        self._retained_bytes = 0

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        return self.submit_retained(fn, *args, retained_bytes=0, **kwargs)

    def submit_retained(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        retained_bytes: int,
        **kwargs: Any,
    ) -> Future[Any]:
        if type(retained_bytes) is not int or retained_bytes < 0:
            raise ValueError("retained_bytes must be a non-negative integer")
        with self._pending_lock:
            if len(self._pending_futures) >= self._max_pending:
                raise RuntimeError("executor pending-work limit reached")
            if (
                self._max_retained_bytes is not None
                and self._retained_bytes + retained_bytes > self._max_retained_bytes
            ):
                raise RuntimeError("executor retained-payload limit reached")
            future = super().submit(fn, *args, **kwargs)
            self._pending_futures.add(future)
            self._retained_bytes_from_future[future] = retained_bytes
            self._retained_bytes += retained_bytes
            future.add_done_callback(self._discard)
            return future

    def _discard(self, future: Future[Any]) -> None:
        with self._pending_lock:
            self._pending_futures.discard(future)
            self._retained_bytes -= self._retained_bytes_from_future.pop(future, 0)

    def shutdown_cancel_pending(self) -> None:
        """Reject new work, cancel queued work, and let running work finish."""
        with self._pending_lock:
            for future in tuple(self._pending_futures):
                future.cancel()
            super().shutdown(wait=False, cancel_futures=True)


def _format_bytes(count: int) -> str:
    """A byte count as something to read in a notification."""
    size = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    raise RuntimeError("byte-size formatter exhausted its units")


def _validate_file_content(content: object) -> bytes | Path:
    if type(content) is bytes:
        return content
    if isinstance(content, Path):
        return Path(os.fspath(content))
    raise TypeError(
        "content must be bytes or a Path; a str is neither a file's contents"
        " (encode it) nor a path we would guess at (wrap it in Path)."
    )


def _validate_download_chunk_size(chunk_size: object) -> int:
    if type(chunk_size) is not int:
        raise TypeError("chunk_size must be an integer")
    _validate_positive_integer(chunk_size, "chunk_size")
    if chunk_size > _FILE_DOWNLOAD_MAX_CHUNK_BYTES:
        raise ValueError(
            f"chunk_size must be at most {_FILE_DOWNLOAD_MAX_CHUNK_BYTES} bytes (8 MiB)."
        )
    return chunk_size


def _load_plotly_js() -> str:
    """Read the browser runtime used by every Plotly surface on this server."""
    try:
        import plotly
    except ImportError as error:
        raise ImportError(
            "You must have the `plotly` package installed to use Plotly elements."
        ) from error

    plotly_file = plotly.__file__
    if plotly_file is None:
        raise ImportError("Could not locate the installed `plotly` package.")
    plotly_path = Path(plotly_file).parent / "package_data" / "plotly.min.js"
    try:
        payload = read_regular_file_snapshot(plotly_path, _PLOTLY_JS_MAX_BYTES)
    except FileNotFoundError as error:
        raise ImportError(f"Could not find plotly.min.js at {plotly_path}.") from error
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("plotly.min.js must contain valid UTF-8") from error


def _read_in_chunks(
    file: BinaryIO, size_bytes: int, chunk_size: int, path: Path
) -> Iterator[bytes]:
    """Exactly `size_bytes` from an open file, `chunk_size` at a time."""
    remaining = size_bytes
    while remaining > 0:
        expected = min(chunk_size, remaining)
        pieces: list[bytes] = []
        received = 0
        while received < expected:
            piece = file.read(expected - received)
            if not piece:
                # The transfer announced its length before the first byte went
                # out and the client waits for exactly that many.
                raise OSError(
                    f"{path} shrank while it was being sent: {remaining - received} of"
                    f" {size_bytes} bytes were still expected."
                )
            pieces.append(piece)
            received += len(piece)
        remaining -= received
        yield pieces[0] if len(pieces) == 1 else b"".join(pieces)


@contextlib.contextmanager
def _download_source(
    content: bytes | Path, chunk_size: int
) -> Iterator[Tuple[int, Iterator[bytes]]]:
    """How long a download is and how to read it, from memory or from disk.

    The length is settled first because the transfer declares it up front, and
    it is taken from the open descriptor rather than from the path so that a
    file replaced mid-send -- a rotated log, say -- is still sent whole from
    the copy this holds open.
    """
    if type(content) is bytes:
        yield (
            len(content),
            (content[i : i + chunk_size] for i in range(0, len(content), chunk_size)),
        )
        return
    validated_content = _validate_file_content(content)
    if not isinstance(validated_content, Path):
        raise TypeError("path download source must be a Path")
    with open_regular_file(validated_content) as file:
        size_bytes = os.fstat(file.fileno()).st_size
        yield size_bytes, _read_in_chunks(file, size_bytes, chunk_size, validated_content)


class ClientHandle:
    """A connected browser with its own client-local GUI."""

    def __init__(self, conn: infra.WebsockClientConnection, server: Server) -> None:
        # Private attributes.
        self._websock_connection = conn
        self._server = server

        # Public attributes.
        self.gui: GuiApi = GuiApi(
            self,
            thread_executor=server._thread_executor,
            event_loop=conn.get_message_buffer().event_loop,
        )
        """Handle for interacting with the GUI."""
        self.client_id: int = conn.client_id
        """Unique ID for this client."""
        self._outgoing_transfer_lock = threading.Lock()
        self._outgoing_transfer_cancel_from_uuid: dict[str, threading.Event] = {}

    @contextlib.contextmanager
    def _track_outgoing_file_transfer(self, transfer_uuid: str) -> Iterator[threading.Event]:
        """Own one cancellable server-to-browser transfer until it terminates."""
        cancelled = threading.Event()
        with self._outgoing_transfer_lock:
            if transfer_uuid in self._outgoing_transfer_cancel_from_uuid:
                raise RuntimeError("duplicate outgoing file transfer identifier")
            if len(self._outgoing_transfer_cancel_from_uuid) >= _FILE_DOWNLOAD_MAX_ACTIVE:
                raise RuntimeError("client already has 128 active outgoing file transfers")
            self._outgoing_transfer_cancel_from_uuid[transfer_uuid] = cancelled
        try:
            yield cancelled
        finally:
            with self._outgoing_transfer_lock:
                if self._outgoing_transfer_cancel_from_uuid.get(transfer_uuid) is cancelled:
                    self._outgoing_transfer_cancel_from_uuid.pop(transfer_uuid)

    def _cancel_outgoing_file_transfer(self, transfer_uuid: str) -> None:
        """Honor a browser abort without echoing another abort back to it."""
        with self._outgoing_transfer_lock:
            cancelled = self._outgoing_transfer_cancel_from_uuid.get(transfer_uuid)
        if cancelled is not None:
            cancelled.set()

    def _cancel_all_outgoing_file_transfers(self) -> None:
        """Wake all producer jobs owned by this connection."""
        with self._outgoing_transfer_lock:
            cancellations = tuple(self._outgoing_transfer_cancel_from_uuid.values())
            self._outgoing_transfer_cancel_from_uuid.clear()
        for cancelled in cancellations:
            cancelled.set()

    def flush(self) -> None:
        """Request immediate windowing of this client's pending messages.

        This skips the normal batching delay but doesn't wait for socket
        delivery or for the browser to apply the batch.
        """
        self._server._websock_server.flush_client(self.client_id)

    def atomic(self) -> ContextManager[None]:
        """Hold outgoing delivery until the outermost context exits.

        Queued messages keep their order and are then emitted in one or more
        transport-bounded windows. This is a soft timing constraint, not a
        browser-side transactional or all-or-nothing commit.

        Returns:
            Context manager.
        """
        return self._websock_connection.atomic()

    def send_file_download(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int = 1024 * 1024,
        save_immediately: bool = False,
    ) -> None:
        """Send a file for a client or clients to download.

        Args:
            filename: Name of the file to send. Used to infer MIME type.
            content: Contents of the file, or a path to read them from. During
                an ordinary off-loop call, a path is opened and read before
                this method returns; path and read errors therefore raise
                synchronously. Calls from the server event loop or inside an
                atomic block are deferred to the transfer executor and return
                before opening the path, so those errors are reported
                asynchronously. At most 8 MiB of file payload is queued per
                client, and at most 128 outgoing transfers may be active for
                one client at once; exceeding that transfer count raises a
                ``RuntimeError`` (reported asynchronously for a deferred call).
                The bundled browser
                retains the complete download to create its Blob and rejects
                files over 256 MiB or 65,536 parts, so this is not end-to-end
                constant-memory streaming. A path is streamed from one live open
                descriptor: replacing its directory entry cannot alter the transfer,
                but an in-place writer can change bytes still to be read. Pass bytes
                (or publish files by atomic rename) when an immutable snapshot is
                required. Text has to be encoded: a `str` names no file and
                holds no bytes, so it is refused rather than guessed at.
            chunk_size: Positive part size, at most 8 MiB.
            save_immediately: Whether to save the file immediately. If `False`,
                a link to the file will be shown as a notification. Being able to
                right click the link and choose "Save as..." can be useful.
        """
        filename = validate_file_display_name(filename)
        content = _validate_file_content(content)
        _validate_download_chunk_size(chunk_size)
        if type(save_immediately) is not bool:
            raise TypeError("save_immediately must be a bool")
        ClientHandle._run_file_transfer(
            self,
            lambda: self._send_file(
                filename, content, chunk_size, "save" if save_immediately else "link"
            ),
            retained_bytes=len(content) if type(content) is bytes else 0,
        )

    def send_file_preview(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int = 1024 * 1024,
        max_bytes: int = PREVIEW_MAX_BYTES,
    ) -> None:
        """Send a file for a client or clients to look at in a dialog.

        The same transfer as :meth:`send_file_download`, shown rather than
        saved: text and markdown as themselves, images, audio and video in
        players, PDFs in a frame, and anything with no viewer of its own as a
        card naming it and offering to download it instead.

        Args:
            filename: Name of the file to send. Its type decides which viewer
                the browser reaches for, so an extension is worth having.
            content: Contents of the file, or a path to read them from; see
                :meth:`send_file_download`.
            chunk_size: Positive part size, at most 8 MiB.
            max_bytes: Transport size past which the file is not sent at all,
                and the client is told why. A preview is held whole in the
                browser, so an arbitrarily large file would be an arbitrarily
                large tab. Defaults to 64 MiB. The bundled browser renders
                plain-text sources only through 16 MiB and Markdown through
                1 MiB; larger transported files remain available to download
                rather than render inline.
        """
        self._send_preview(filename, content, chunk_size=chunk_size, max_bytes=max_bytes)

    def _send_preview(
        self,
        filename: str,
        content: bytes | Path,
        *,
        chunk_size: int = 1024 * 1024,
        max_bytes: int = PREVIEW_MAX_BYTES,
        disposition: _messages.FileDisposition = "preview",
        source_uuid: str | None = None,
        source_version: str | None = None,
    ) -> None:
        """:meth:`send_file_preview`, plus what only a preview BUTTON knows.

        A button's file can be asked for again -- reloaded by hand, or resent
        when the file it was read from changes -- and the browser does the
        asking, so it has to be told which component to ask and what it is
        already holding. A script calling the public method has no component
        behind it and passes neither.
        """
        filename = validate_file_display_name(filename)
        content = _validate_file_content(content)
        _validate_download_chunk_size(chunk_size)
        _validate_nonnegative_integer(max_bytes, "max_bytes")

        def send() -> None:
            rejected_size = self._send_file(
                filename,
                content,
                chunk_size,
                disposition,
                source_uuid=source_uuid,
                source_version=source_version,
                max_bytes=max_bytes,
            )
            if rejected_size is not None:
                # Said rather than sent: the alternative is a tab that stops
                # responding with nothing on screen to explain why.
                self.add_notification(
                    "Too large to preview",
                    f"{filename} is {_format_bytes(rejected_size)}, over the"
                    f" {_format_bytes(max_bytes)} preview limit.",
                )

        ClientHandle._run_file_transfer(
            self, send, retained_bytes=len(content) if type(content) is bytes else 0
        )

    def _run_file_transfer(
        self, callback: Callable[[], object], *, retained_bytes: int = 0
    ) -> None:
        """Run synchronously unless that would deadlock, with bounded deferral."""
        buffer = self._websock_connection.get_message_buffer()
        try:
            on_event_loop = asyncio.get_running_loop() is buffer.event_loop
        except RuntimeError:
            on_event_loop = False
        if on_event_loop or buffer.file_transfer_must_be_deferred():
            self._server._transfer_executor.submit_retained(
                callback, retained_bytes=retained_bytes
            ).add_done_callback(print_async_errors)
        else:
            callback()

    def _send_file(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int,
        disposition: _messages.FileDisposition,
        *,
        source_uuid: str | None = None,
        source_version: str | None = None,
        max_bytes: int | None = None,
    ) -> int | None:
        """Send one file, or return its opened size when it exceeds a limit."""
        filename = validate_file_display_name(filename)
        _validate_download_chunk_size(chunk_size)

        mime_type = mimetypes.guess_type(filename, strict=False)[0]
        if mime_type is None:
            mime_type = "application/octet-stream"

        uuid = _make_uuid()
        started = False
        expected_parts = 0
        sent_parts = 0
        buffer = self._websock_connection.get_message_buffer()
        with self._track_outgoing_file_transfer(uuid) as cancelled:
            try:
                with _download_source(content, chunk_size) as (size_bytes, chunks):
                    if cancelled.is_set():
                        return None
                    if max_bytes is not None and size_bytes > max_bytes:
                        return size_bytes
                    expected_parts = -(-size_bytes // chunk_size)
                    if size_bytes > _FILE_DOWNLOAD_MAX_BYTES:
                        raise ValueError("download exceeds the bundled browser's 256 MiB limit")
                    if expected_parts > _FILE_DOWNLOAD_MAX_PARTS:
                        raise ValueError(
                            "download requires more than 65,536 parts; increase chunk_size"
                        )
                    queued = self._websock_connection.queue_message(
                        _messages.FileTransferStartDownload(
                            disposition=disposition,
                            transfer_uuid=uuid,
                            filename=filename,
                            mime_type=mime_type,
                            part_count=expected_parts,
                            size_bytes=size_bytes,
                            source_uuid=source_uuid,
                            source_version=source_version,
                        )
                    )
                    if queued is False or cancelled.is_set():
                        return None
                    started = True
                    chunks = iter(chunks)
                    for i in range(expected_parts):
                        if cancelled.is_set():
                            return None
                        reservation = min(chunk_size, size_bytes - i * chunk_size)
                        reservation_owned = False
                        if not buffer.reserve_file_bytes(reservation):
                            return None
                        reservation_owned = True
                        try:
                            if cancelled.is_set():
                                return None
                            try:
                                part = next(chunks)
                            except StopIteration as error:
                                raise OSError(
                                    f"File source ended before part {i} of {expected_parts}."
                                ) from error
                            if len(part) != reservation:
                                raise OSError(
                                    f"File source yielded {len(part)} bytes for part {i};"
                                    f" expected {reservation}."
                                )
                            if cancelled.is_set():
                                return None
                            message = _messages.FileTransferPart(
                                None, transfer_uuid=uuid, part_index=i, content=part
                            )
                            queued = self._websock_connection.queue_reserved_file_message(
                                message, reservation
                            )
                            if queued is False:
                                return None
                            reservation_owned = False
                        finally:
                            if reservation_owned:
                                buffer.release_file_bytes(reservation)
                        sent_parts = i + 1
                        self.flush()
            except Exception:
                # Once a start is on the wire, every incomplete transfer needs a
                # terminal message. Otherwise previews and their reload watches can
                # wait forever while the connection itself remains healthy. A browser
                # cancellation already is that terminal signal and must not be echoed.
                if started and sent_parts < expected_parts and not cancelled.is_set():
                    with contextlib.suppress(Exception):
                        self._websock_connection.queue_message(
                            _messages.FileTransferAbort(
                                transfer_uuid=uuid,
                                # A terminal signal must itself remain valid and
                                # must not disclose local paths or exception text.
                                reason="The server could not complete this transfer.",
                            )
                        )
                        self.flush()
                raise
        return None

    def add_notification(
        self,
        title: str,
        body: str = "",
        *,
        loading: bool = False,
        with_close_button: bool = True,
        auto_close_seconds: float | None = 5.0,
    ) -> NotificationHandle:
        """Add a notification to the client's interface.

        This method creates a new notification that will be displayed at the
        top left corner of the client's viewer. Notifications are useful for
        providing alerts or status updates to users.

        Args:
            title: Title to display on the notification.
            body: Message to display on the notification body.
            loading: Whether the notification shows loading icon.
            with_close_button: Whether the notification can be manually closed.
            auto_close_seconds: Time before the notification automatically
                closes; None if the notification does not close on its own.

        Returns:
            A handle that can be used to interact with the GUI element.
        """
        return self.gui.add_notification(
            title,
            body,
            loading=loading,
            with_close_button=with_close_button,
            auto_close_seconds=auto_close_seconds,
        )


class Server:
    """Run a Leika workspace and synchronize it with browser clients.

    Set ``password`` to gate the dashboard behind a login page: both the web
    client and the underlying websocket refuse unauthenticated requests.

    Set ``share=True`` to also open a Cloudflare quick tunnel and print a
    public ``https://....trycloudflare.com`` URL that reaches this server
    from any machine, with no port forwarding. Sharing requires the
    ``cloudflared`` binary on the PATH, a loopback ``host`` (so no
    unencrypted network path exists beside the tunnel), and always requires
    a password: if none is given, one is generated and printed alongside
    the URL.

    Wildcard binds accept localhost and IP-literal request hosts by default.
    Add intentional DNS, mDNS, or tailnet names with ``allowed_hosts``;
    entries are hostnames without ports and the sequence is capped at 256.
    Invalid, duplicate, changing, or oversized sequences raise ``ValueError``
    during construction. Browser ``Origin`` must still match
    the accepted request origin. Pages deny framing by default; set
    ``allow_embedding=True`` only for an intentional iframe or notebook
    :meth:`show` use.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        *,
        workspace_id: str = "default",
        label: str | None = None,
        password: str | None = None,
        allowed_hosts: Sequence[str] | None = None,
        allow_embedding: bool = False,
        share: bool = False,
        verbose: bool = True,
    ) -> None:
        if type(host) is not str or _canonical_hostname(host) is None:
            raise ValueError("host must be a valid DNS name or IP address.")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an integer from 0 to 65535.")
        workspace_id = validate_layout_id(workspace_id, "workspace_id")
        if label is not None and not isinstance(label, str):
            raise TypeError("label must be a string or None.")
        if password is not None:
            if type(password) is not str:
                raise TypeError("password must be a string or None.")
            # Validate before building the client or allocating executors. The
            # guard repeats this low-level boundary for direct infrastructure use.
            HttpPasswordGuard(password)
        if not isinstance(allow_embedding, bool):
            raise TypeError("allow_embedding must be a bool.")
        if not isinstance(share, bool):
            raise TypeError("share must be a bool.")
        if not isinstance(verbose, bool):
            raise TypeError("verbose must be a bool.")
        normalized_allowed_hosts = tuple(sorted(_normalize_allowed_hosts(allowed_hosts)))
        # Sharing means the dashboard carries data worth protecting, and a
        # non-loopback bind would serve that same data as unencrypted HTTP to
        # the local network -- where the password itself travels in the clear.
        # With the tunnel open there is no reason for a second, weaker door.
        canonical_host = _canonical_hostname(host)
        if share and (canonical_host is None or not _is_loopback_host(canonical_host)):
            raise ValueError(
                f"share=True reaches the dashboard through an encrypted tunnel, but"
                f" host={host!r} would also serve unencrypted HTTP to the local network."
                ' Bind host="127.0.0.1" so localhost and the tunnel are the only ways in.'
            )
        # A public tunnel without a password would hand the dashboard to
        # anyone who sees the URL, so sharing always gets one.
        if share and password is None:
            password = secrets.token_urlsafe(9)
            self._password_generated = True
        else:
            self._password_generated = False

        # Building can fail, but owns no runtime resources. Complete it before
        # allocating executors so constructor failure is leak-free.
        _client_autobuild.ensure_client_is_built()
        self.host = host
        self.password = password
        self.workspace_id = workspace_id
        self.verbose = verbose
        self.allow_embedding = allow_embedding
        self._stopped = False
        self._stop_lock = threading.Lock()
        self._stop_finalizer: threading.Thread | None = None
        self._active_user_callbacks = 0
        self._executor_shutdown = False
        self._connected_clients: dict[int, ClientHandle] = {}
        self._client_lock = threading.RLock()
        self._file_upload_reservation_lock = threading.Lock()
        self._file_upload_bytes_reserved = 0
        self._file_upload_count = 0
        self._client_connect_cb: list[Callable[[ClientHandle], None | Coroutine]] = []
        self._client_disconnect_cb: list[Callable[[ClientHandle], None | Coroutine]] = []
        self._gui_order_counter = 0
        self._gui_order_lock = threading.Lock()
        self._gui_resource_lock = threading.Lock()
        self._image_preparation_condition = threading.Condition(threading.Lock())
        self._image_preparation_bytes = 0
        self._renderer_preparation_condition = threading.Condition(threading.Lock())
        self._renderer_preparation_active = False
        self._renderer_preparation_local = threading.local()
        self._gui_retained_units_and_bytes = 0
        self._gui_decoded_pixels = 0
        self._page_global_decoded_pixels = 0
        self._plotly_js_lock = threading.Lock()
        self._plotly_js_source: str | None = None
        self._plotly_resource_cost = _GuiResourceCost()
        self._plotly_js_required_globally = False
        self._plotly_js_sent_client_ids: set[infra.ClientId] = set()

        server = infra.WebsockServer(
            host=host,
            port=port,
            message_class=_messages.Message,
            http_server_root=Path(__file__).resolve().parent / "client" / "build",
            verbose=verbose,
            password=password,
            allowed_hosts=normalized_allowed_hosts,
            allow_embedding=allow_embedding,
        )
        self._websock_server = server

        @server.on_client_connect
        async def _on_connect(conn: infra.WebsockClientConnection) -> None:
            client = ClientHandle(conn, self)
            with self._client_lock:
                self._connected_clients[conn.client_id] = client
                callbacks = tuple(self._client_connect_cb)
            # The connection-local queue is registered before user callbacks,
            # so their Plotly messages cannot overtake this bootstrap.
            self._initialize_plotly_connection(conn)
            for callback in callbacks:
                await self._await_user_callback(callback, client)

        server.register_handler(_messages.ClientPingMessage, self._handle_client_ping)
        server.register_handler(_messages.FileTransferAbort, self._handle_file_transfer_abort)

        @server.on_client_disconnect
        async def _on_disconnect(conn: infra.WebsockClientConnection) -> None:
            with self._client_lock:
                client = self._connected_clients.pop(conn.client_id, None)
                callbacks = tuple(self._client_disconnect_cb)
            self._discard_plotly_connection(conn.client_id)
            if client is None:
                return
            client._cancel_all_outgoing_file_transfers()
            client.gui._discard_client_work(conn.client_id, release_retained_uploads=True)
            gui = getattr(self, "gui", None)
            if gui is not None:
                gui._discard_client_work(conn.client_id)
            for callback in callbacks:
                await self._await_user_callback(callback, client)

        try:
            # Allocate worker pools only after all pure construction and handler
            # registration succeeds. The common rollback below also covers a
            # failure while allocating the second pool.
            self._thread_executor = _CallbackExecutor(
                max_workers=32, max_pending=_CALLBACK_EXECUTOR_MAX_PENDING
            )
            self._transfer_executor = _CallbackExecutor(
                max_workers=8,
                max_pending=_TRANSFER_EXECUTOR_MAX_PENDING,
                max_retained_bytes=_TRANSFER_EXECUTOR_MAX_RETAINED_BYTES,
            )
            server.start()
            self._event_loop = server._broadcast_buffer.event_loop
            self.port = server._port
            self.gui = GuiApi(
                self,
                thread_executor=self._thread_executor,
                event_loop=self._event_loop,
            )
            server.queue_message_or_raise(
                _messages.WorkspaceConfigurationMessage(workspace_id=workspace_id)
            )
            self.panes = Panes(self)
            self.gui.set_panel_label(label)

            # Open the share tunnel last: it only matters once the server it
            # forwards to is up. A tunnel failure is reported but not fatal --
            # the dashboard itself still works locally.
            self._share_tunnel: CloudflaredTunnel | None = None
            if share:
                try:
                    tunnel = CloudflaredTunnel(self.port)
                    self._share_tunnel = tunnel
                    started_share_url = tunnel.start()
                    tunnel_host = urlsplit(started_share_url).hostname
                    if tunnel_host is None:
                        raise ShareTunnelError("cloudflared returned a malformed share URL.")
                    server.trust_proxy_host(tunnel_host)
                except ShareTunnelError as e:
                    close_error: Exception | None = None
                    if self._share_tunnel is not None:
                        try:
                            self._share_tunnel.close()
                        except Exception as error:
                            close_error = error
                    self._share_tunnel = None
                    print(f"Leika share tunnel failed: {e}")
                    if close_error is not None:
                        print(f"Leika share tunnel cleanup also failed: {close_error}")

            if verbose:
                print(f"Leika listening at {self.url}")
                if self.share_url is not None:
                    print(f"Leika share URL: {self.share_url}")
                if self._password_generated:
                    print(f"Leika password (auto-generated): {password}")
        except BaseException:
            # Preserve the construction failure while independently attempting
            # every resource cleanup; no secondary teardown failure may mask it.
            tunnel = getattr(self, "_share_tunnel", None)
            cleanup: tuple[Callable[[], object], ...] = (
                *((tunnel.close,) if tunnel is not None else ()),
                server.stop,
                self._shutdown_callback_executor,
            )
            for action in cleanup:
                try:
                    action()
                except BaseException:
                    pass
            raise

    @property
    def share_url(self) -> str | None:
        """Current public tunnel URL, or ``None`` when no tunnel is live."""
        tunnel = getattr(self, "_share_tunnel", None)
        return None if tunnel is None else tunnel.url

    @property
    def url(self) -> str:
        canonical_host = _canonical_hostname(self.host)
        if canonical_host is None:
            raise RuntimeError("server host became invalid after construction")
        try:
            wildcard = ipaddress.ip_address(canonical_host).is_unspecified
        except ValueError:
            wildcard = False
        display_host = "localhost" if wildcard else canonical_host
        if ":" in display_host and not display_host.startswith("["):
            escaped_host = display_host.replace("%", "%25")
            display_host = f"[{escaped_host}]"
        return f"http://{display_host}:{self.port}"

    def _reserve_file_upload(self, size_bytes: int) -> bool:
        """Reserve builder storage plus immutable-conversion headroom."""
        if type(size_bytes) is not int or size_bytes < 0:
            raise ValueError("upload size must be a non-negative integer")
        charged_bytes = size_bytes * 2
        with self._file_upload_reservation_lock:
            if (
                self._file_upload_count >= _FILE_UPLOAD_MAX_ACTIVE
                or self._file_upload_bytes_reserved + charged_bytes
                > _FILE_UPLOAD_AGGREGATE_MAX_BYTES
            ):
                return False
            self._file_upload_count += 1
            self._file_upload_bytes_reserved += charged_bytes
            return True

    def _release_file_upload(self, size_bytes: int) -> None:
        """Release an incomplete upload and its conversion headroom."""
        charged_bytes = size_bytes * 2
        with self._file_upload_reservation_lock:
            if self._file_upload_count == 0 or charged_bytes > self._file_upload_bytes_reserved:
                raise RuntimeError("upload reservation accounting underflow")
            self._file_upload_count -= 1
            self._file_upload_bytes_reserved -= charged_bytes

    def _complete_file_upload(self, size_bytes: int, replaced_bytes: int) -> None:
        """Convert one active reservation into retained immutable payload."""
        with self._file_upload_reservation_lock:
            released = size_bytes + replaced_bytes
            if self._file_upload_count == 0 or released > self._file_upload_bytes_reserved:
                raise RuntimeError("upload reservation accounting underflow")
            self._file_upload_count -= 1
            self._file_upload_bytes_reserved -= released

    def _replace_retained_file_upload(self, old_bytes: int, new_bytes: int) -> None:
        """Account for a user assignment to an upload handle value."""
        if min(old_bytes, new_bytes) < 0:
            raise ValueError("retained upload sizes must be non-negative")
        with self._file_upload_reservation_lock:
            updated = self._file_upload_bytes_reserved - old_bytes + new_bytes
            if old_bytes > self._file_upload_bytes_reserved:
                raise RuntimeError("upload reservation accounting underflow")
            if updated > _FILE_UPLOAD_AGGREGATE_MAX_BYTES:
                raise ValueError("UploadedFile values exceed the 256 MiB server memory limit.")
            self._file_upload_bytes_reserved = updated

    def _release_retained_file_upload(self, size_bytes: int) -> None:
        """Release a completed value when its handle is removed."""
        with self._file_upload_reservation_lock:
            if not 0 <= size_bytes <= self._file_upload_bytes_reserved:
                raise RuntimeError("upload reservation accounting underflow")
            self._file_upload_bytes_reserved -= size_bytes

    @contextlib.contextmanager
    def _reserve_image_preparation(self, source_bytes: int) -> Iterator[None]:
        """Bound private array snapshots plus conservative encoded headroom."""
        if type(source_bytes) is not int or source_bytes < 0:
            raise ValueError("image preparation size must be a non-negative integer")
        # The source snapshot can coexist with clipping/scaling output and
        # encoder/output buffers. Four source-sized units conservatively cover
        # the bounded NumPy/OpenCV/Pillow paths and serialize maximum images.
        charge = source_bytes * 4
        if charge > _IMAGE_PREPARATION_MAX_BYTES:
            raise RuntimeError("Image preparation exceeds the 512 MiB safety budget.")
        with self._image_preparation_condition:
            while (
                not self._stopped
                and self._image_preparation_bytes + charge > _IMAGE_PREPARATION_MAX_BYTES
            ):
                self._image_preparation_condition.wait()
            if self._stopped:
                raise RuntimeError("The server stopped during image preparation.")
            self._image_preparation_bytes += charge
        try:
            yield
        finally:
            with self._image_preparation_condition:
                self._image_preparation_bytes -= charge
                if self._image_preparation_bytes < 0:
                    raise RuntimeError("image preparation accounting underflow")
                self._image_preparation_condition.notify_all()

    @contextlib.contextmanager
    def _reserve_renderer_preparation(self) -> Iterator[None]:
        """Serialize bounded Plotly/Matplotlib output ownership per server."""
        if getattr(self._renderer_preparation_local, "active", False):
            raise RuntimeError("Renderer preparation cannot re-enter the same server.")
        self._renderer_preparation_local.active = True
        acquired = False
        try:
            with self._renderer_preparation_condition:
                while not self._stopped and self._renderer_preparation_active:
                    self._renderer_preparation_condition.wait()
                if self._stopped:
                    raise RuntimeError("The server stopped during renderer preparation.")
                self._renderer_preparation_active = True
                acquired = True
            yield
        finally:
            if acquired:
                with self._renderer_preparation_condition:
                    self._renderer_preparation_active = False
                    self._renderer_preparation_condition.notify_all()
            self._renderer_preparation_local.active = False

    def _replace_gui_resource_cost(
        self,
        old: Any,
        new: Any,
        *,
        page_global: bool,
    ) -> None:
        """Reserve process-wide retained GUI source and decoded-raster capacity."""
        old_retained = old.text_units * 2 + old.payload_bytes
        new_retained = new.text_units * 2 + new.payload_bytes
        with self._gui_resource_lock:
            retained = self._gui_retained_units_and_bytes - old_retained + new_retained
            pixels = self._gui_decoded_pixels - old.decoded_pixels + new.decoded_pixels
            page_pixels = self._page_global_decoded_pixels
            if page_global:
                page_pixels = page_pixels - old.decoded_pixels + new.decoded_pixels
            if retained > _SERVER_GUI_RETAINED_MAX_BYTES:
                raise RuntimeError("The server exceeded its 256 MiB retained GUI budget.")
            if pixels > _SERVER_GUI_PIXELS_MAX:
                raise RuntimeError("The server exceeded its 128 Mi-pixel GUI raster budget.")
            if page_pixels > _SERVER_PAGE_PIXELS_MAX:
                raise RuntimeError("The shared page exceeded its 64 Mi-pixel raster budget.")
            if min(retained, pixels, page_pixels) < 0:
                raise RuntimeError("GUI resource accounting underflow")
            self._gui_retained_units_and_bytes = retained
            self._gui_decoded_pixels = pixels
            self._page_global_decoded_pixels = page_pixels

    def _next_gui_order(self) -> float:
        """Allocate one deterministic implicit order across this server's GUIs."""
        with self._gui_order_lock:
            self._gui_order_counter += 1
            return self._gui_order_counter

    def _queue_plotly_js_locked(self, connection: infra.WebsockClientConnection) -> None:
        """Queue the cached runtime once for one browser connection. Lock held."""
        client_id = connection.client_id
        if client_id in self._plotly_js_sent_client_ids:
            return
        source = self._plotly_js_source
        if source is None:
            raise RuntimeError("Plotly runtime must be loaded before it is queued.")
        if connection.queue_message(_messages.RunJavascriptMessage(source=source)) is False:
            return
        self._plotly_js_sent_client_ids.add(client_id)

    def _ensure_plotly_js_sent(self, connection: infra.WebsockClientConnection | None) -> None:
        """Initialize one client, or every current and future client, once."""
        with self._plotly_js_lock:
            if self._plotly_js_source is None:
                source = _load_plotly_js()
                cost = _GuiResourceCost(
                    text_units=utf16_code_unit_length(source),
                    payload_bytes=len(source.encode("utf-8")),
                )
                self._replace_gui_resource_cost(self._plotly_resource_cost, cost, page_global=False)
                self._plotly_resource_cost = cost
                self._plotly_js_source = source

            if connection is not None:
                self._queue_plotly_js_locked(connection)
                return

            self._plotly_js_required_globally = True
            with self._client_lock:
                connections = tuple(
                    client._websock_connection for client in self._connected_clients.values()
                )
            for client_connection in connections:
                self._queue_plotly_js_locked(client_connection)

    def _initialize_plotly_connection(self, connection: infra.WebsockClientConnection) -> None:
        """Apply a prior global Plotly requirement to a new connection."""
        with self._plotly_js_lock:
            if self._plotly_js_required_globally:
                self._queue_plotly_js_locked(connection)

    def _discard_plotly_connection(self, client_id: infra.ClientId) -> None:
        """Forget per-connection delivery state when a browser disconnects."""
        with self._plotly_js_lock:
            self._plotly_js_sent_client_ids.discard(client_id)

    def _handle_file_transfer_abort(
        self, client_id: infra.ClientId, message: _messages.FileTransferAbort
    ) -> None:
        """Cancel a server-to-browser transfer, if this UUID names one."""
        with self._client_lock:
            client = self._connected_clients.get(client_id)
        if client is not None:
            client._cancel_outgoing_file_transfer(message.transfer_uuid)

    def _handle_client_ping(
        self, client_id: infra.ClientId, message: _messages.ClientPingMessage
    ) -> None:
        """Answer one client's ping, and get out of the way.

        Flushed rather than left to the outgoing window, which holds messages
        for a frame before sending them: waiting would add that frame to every
        reading and hide the very delays the client is measuring for.
        """
        if type(message.sent_ms) not in (int, float) or not math.isfinite(float(message.sent_ms)):
            return
        with self._client_lock:
            client = self._connected_clients.get(client_id)
        if client is None:
            return
        client._websock_connection.queue_message(
            _messages.ServerPongMessage(sent_ms=message.sent_ms)
        )
        client.flush()

    @property
    def clients(self) -> dict[int, ClientHandle]:
        """Snapshot of the connected clients, keyed by client ID.

        A copy: mutating it does not affect the server, and iterating it is
        safe while clients connect or disconnect.
        """
        with self._client_lock:
            return self._connected_clients.copy()

    def __enter__(self) -> Server:
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()

    def show(self, height: int = 600) -> Any:
        """Display inline in IPython, otherwise open the default browser."""
        _validate_positive_integer(height, "height")
        try:
            from IPython import get_ipython  # type: ignore[import-not-found]

            if get_ipython() is not None:
                if not self.allow_embedding:
                    raise RuntimeError(
                        "Inline display is disabled by frame protection; construct "
                        "Server(allow_embedding=True) to opt in."
                    )
                from IPython.display import IFrame, display  # type: ignore[import-not-found]

                frame = IFrame(self.url, width="100%", height=height)
                display(frame)
                return frame
        except ImportError:
            pass
        import webbrowser

        webbrowser.open(self.url)
        return None

    @contextlib.contextmanager
    def _active_user_callback(self) -> Iterator[None]:
        """Mark callback work whose completion is owned by the server loop."""
        with self._stop_lock:
            self._active_user_callbacks += 1
        try:
            yield
        finally:
            with self._stop_lock:
                self._active_user_callbacks -= 1

    async def _await_user_callback(self, callback: Callable[..., Any], *args: Any) -> None:
        with self._active_user_callback():
            await await_user_callback(self._thread_executor, callback, *args)

    async def _await_user_callback_result(self, result: object) -> None:
        with self._active_user_callback():
            await await_callback_result(result)

    def _shutdown_callback_executor(self) -> None:
        """Cancel queued callbacks once, after websocket teardown is done."""
        with self._stop_lock:
            if self._executor_shutdown:
                return
            self._executor_shutdown = True
        # Websocket teardown marks every buffer done first, waking blocked
        # transfers before their executor is retired. Attempt both pools even
        # if an injected or platform shutdown failure affects the first one.
        primary_error: BaseException | None = None
        for executor_name in ("_transfer_executor", "_thread_executor"):
            executor = getattr(self, executor_name, None)
            if executor is None:
                continue
            try:
                executor.shutdown_cancel_pending()
            except BaseException as error:
                if primary_error is None:
                    primary_error = error
        if primary_error is not None:
            with self._stop_lock:
                self._executor_shutdown = False
            raise primary_error

    def _finish_stop(self) -> None:
        """Join the worker, close the tunnel, then release callback ownership."""
        tunnel: CloudflaredTunnel | None
        with self._stop_lock:
            tunnel = self._share_tunnel
            self._share_tunnel = None

        primary_error: BaseException | None = None

        def attempt(cleanup: Callable[[], object]) -> None:
            nonlocal primary_error
            try:
                cleanup()
            except BaseException as error:
                # Python 3.10 has no ExceptionGroup. Preserve the first failure
                # while still attempting every independently owned cleanup.
                if primary_error is None:
                    primary_error = error

        attempt(self._websock_server.stop)
        if tunnel is not None:
            attempt(tunnel.close)

        def clear_callbacks() -> None:
            with self._client_lock:
                self._client_connect_cb.clear()
                self._client_disconnect_cb.clear()

        attempt(clear_callbacks)
        attempt(self._shutdown_callback_executor)
        if primary_error is not None:
            raise primary_error

    def _run_stop_finalizer(self) -> None:
        """Finish asynchronous shutdown and release finalizer ownership."""
        try:
            self._finish_stop()
        finally:
            current = threading.current_thread()
            with self._stop_lock:
                if self._stop_finalizer is current:
                    self._stop_finalizer = None

    def stop(self) -> None:
        """Stop the Leika server and cancel callbacks that have not started.

        Python threads already executing user code cannot be terminated safely;
        loop-owned callback awaits may be cancelled as connection tasks retire.
        If shutdown is requested from callback-owned work -- including a
        synchronous callback or an external Future that the server loop awaits --
        this call signals promptly and a short-lived finalizer performs the join,
        avoiding a circular wait. A concurrent off-callback caller may observe
        the same asynchronous completion while such work is active. Repeat calls
        remain safe and can complete the bounded join.
        """
        with self._stop_lock:
            first_request = not self._stopped
            self._stopped = True
            callback_active = self._active_user_callbacks > 0

        if first_request:
            with self._image_preparation_condition:
                self._image_preparation_condition.notify_all()
            with self._renderer_preparation_condition:
                self._renderer_preparation_condition.notify_all()
            with self._client_lock:
                clients = tuple(self._connected_clients.values())
            for client in clients:
                client._cancel_all_outgoing_file_transfers()
                client.gui._retire_scope_without_queue()
            gui = getattr(self, "gui", None)
            if gui is not None:
                gui._retire_scope_without_queue()
            panes = getattr(self, "panes", None)
            if panes is not None:
                panes._retire_without_queue()
            with self._plotly_js_lock:
                self._replace_gui_resource_cost(
                    self._plotly_resource_cost, _GuiResourceCost(), page_global=False
                )
                self._plotly_resource_cost = _GuiResourceCost()
                self._plotly_js_source = None
                self._plotly_js_sent_client_ids.clear()

        server_thread = self._websock_server._server_thread
        if (
            threading.current_thread() is server_thread
            or in_sync_user_callback()
            or callback_active
        ):
            # Signal only. Calling the low-level stop() here from an external
            # Future's worker would join the loop that is awaiting that Future.
            self._websock_server._signal_stop()
            with self._stop_lock:
                if self._stop_finalizer is None:
                    finalizer = threading.Thread(
                        target=self._run_stop_finalizer,
                        name="leika-stop-finalizer",
                        daemon=True,
                    )
                    # Publish before start while holding the lock. A fast target
                    # cannot clear itself until this critical section exits, and
                    # a start failure rolls the sentinel back synchronously.
                    self._stop_finalizer = finalizer
                    try:
                        finalizer.start()
                    except BaseException:
                        if self._stop_finalizer is finalizer:
                            self._stop_finalizer = None
                        raise
            return

        self._finish_stop()

    async def _await_connect_callback_if_current(
        self,
        callback: Callable[[ClientHandle], Any],
        client: ClientHandle,
    ) -> None:
        """Dispatch an immediate connect callback only to the same live client."""
        with self._client_lock:
            if self._connected_clients.get(client.client_id) is not client:
                return
        await self._await_user_callback(callback, client)

    def on_client_connect(
        self, cb: Callable[[ClientHandle], NoneOrCoroutine]
    ) -> Callable[[ClientHandle], NoneOrCoroutine]:
        """Attach a callback to run for newly connected clients.

        The callback can be either a standard function or an async function:
        - Standard functions (def) will be executed in a threadpool.
        - Async functions (async def) will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        if not callable(cb):
            raise TypeError("client connection callback must be callable")
        with self._stop_lock:
            if self._stopped:
                raise RuntimeError("Cannot register callbacks after Server.stop().")
        with self._client_lock:
            if len(self._client_connect_cb) >= _SERVER_CALLBACK_MAX:
                raise RuntimeError(
                    f"A server cannot own more than {_SERVER_CALLBACK_MAX} connect callbacks."
                )
            clients = tuple(self._connected_clients.values())
            self._client_connect_cb.append(cb)

        # Trigger callback on any already-connected clients.
        # If we have:
        #
        #     server = Server()
        #     server.on_client_connect(...)
        #
        # This makes sure that the callback is applied to any clients that
        # connect between the two lines. The common dispatcher invokes ordinary
        # callables off-loop and awaits any result they return.
        for client in clients:
            callback_work = self._await_connect_callback_if_current(cb, client)
            try:
                future = asyncio.run_coroutine_threadsafe(
                    callback_work,
                    self._event_loop,
                )
            except BaseException:
                callback_work.close()
                with self._client_lock:
                    self._client_connect_cb[:] = [
                        existing for existing in self._client_connect_cb if existing != cb
                    ]
                raise
            future.add_done_callback(print_async_errors)

        return cast(Callable[[ClientHandle], NoneOrCoroutine], cb)

    def remove_client_connect_callback(
        self,
        callback: Callable[[ClientHandle], NoneOrCoroutine] | None = None,
    ) -> None:
        """Remove one connect callback, or all callbacks when omitted."""
        if callback is not None and not callable(callback):
            raise TypeError("client connection callback must be callable or None")
        with self._client_lock:
            if callback is None:
                self._client_connect_cb.clear()
            else:
                self._client_connect_cb[:] = [
                    existing for existing in self._client_connect_cb if existing != callback
                ]

    def on_client_disconnect(
        self, cb: Callable[[ClientHandle], NoneOrCoroutine]
    ) -> Callable[[ClientHandle], NoneOrCoroutine]:
        """Attach a callback to run when clients disconnect.

        The callback can be either a standard function or an async function:
        - Standard functions (def) will be executed in a threadpool.
        - Async functions (async def) will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        if not callable(cb):
            raise TypeError("client disconnection callback must be callable")
        with self._stop_lock:
            if self._stopped:
                raise RuntimeError("Cannot register callbacks after Server.stop().")
        with self._client_lock:
            if len(self._client_disconnect_cb) >= _SERVER_CALLBACK_MAX:
                raise RuntimeError(
                    f"A server cannot own more than {_SERVER_CALLBACK_MAX} disconnect callbacks."
                )
            self._client_disconnect_cb.append(cb)
        return cb

    def remove_client_disconnect_callback(
        self,
        callback: Callable[[ClientHandle], NoneOrCoroutine] | None = None,
    ) -> None:
        """Remove one disconnect callback, or all callbacks when omitted."""
        if callback is not None and not callable(callback):
            raise TypeError("client disconnection callback must be callable or None")
        with self._client_lock:
            if callback is None:
                self._client_disconnect_cb.clear()
            else:
                self._client_disconnect_cb[:] = [
                    existing for existing in self._client_disconnect_cb if existing != callback
                ]

    def flush(self) -> None:
        """Request immediate windowing of pending broadcast messages.

        This skips the normal batching delay but doesn't wait for socket
        delivery or for any browser to apply the batch.
        """
        self._websock_server.flush()

    def atomic(self) -> ContextManager[None]:
        """Hold outgoing delivery until the outermost context exits.

        Queued messages keep their order and are then emitted in one or more
        transport-bounded windows. This is a soft timing constraint, not a
        browser-side transactional or all-or-nothing commit.

        Returns:
            Context manager.
        """
        return self._websock_server.atomic()

    def register_http_asset(self, path: Path) -> str:
        """Serve one file over plain HTTP, returning the URL path it lives at.

        The heavy constituents of an otherwise small payload -- the images a
        previewed document refers to, say -- are better fetched by the browser
        than carried inside a message: the message arrives at once, and the
        browser loads the heavy parts in parallel, progressively, the way it
        loads any page. The URL is the content's hash, so it caches forever
        and names nothing about the machine; it is served behind the same
        password gate as everything else.

        Args:
            path: Regular file to snapshot at registration. The immutable
                content-addressed bytes are shared by responses and retained in
                the server's bounded 128 MiB runtime-asset cache; later changes
                to the source path do not change an existing URL.

        Returns:
            Root-relative URL path (``/leika-assets/<hash><suffix>``).
        """
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        return self._websock_server.register_http_asset(path).url

    def _register_http_image(
        self, path: Path, *, _expected_metadata: os.stat_result | None = None
    ) -> HttpAsset:
        """:meth:`register_http_asset`, keeping the picture's size as well.

        The size is what a document needs in order to leave the right room for
        a figure before the figure has arrived, and it is read from the bytes
        the URL was already being hashed from -- so it is the same
        registration, told in full rather than told twice.
        """
        return self._websock_server.register_http_asset(
            path,
            _expected_metadata=_expected_metadata,
            _require_safe_image=True,
        )

    def _run_broadcast_file_transfer(
        self,
        clients: tuple[ClientHandle, ...],
        callback: Callable[[ClientHandle], object],
        *,
        retained_bytes: int,
    ) -> None:
        """Run one all-client transfer job with atomic admission."""
        if not clients:
            return

        def send_all() -> None:
            for client in clients:
                callback(client)

        try:
            on_event_loop = asyncio.get_running_loop() is self._event_loop
        except RuntimeError:
            on_event_loop = False
        must_defer = on_event_loop or any(
            client._websock_connection.get_message_buffer().file_transfer_must_be_deferred()
            for client in clients
        )
        if must_defer:
            # One bytes object is retained once even when it is broadcast. Admit
            # the whole fan-out before sending to any client, avoiding partial
            # delivery caused solely by the executor's retained-byte ceiling.
            self._transfer_executor.submit_retained(
                send_all, retained_bytes=retained_bytes
            ).add_done_callback(print_async_errors)
        else:
            send_all()

    def send_file_download(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int = 1024 * 1024,
        save_immediately: bool = False,
    ) -> None:
        """Send a file for a client or clients to download.

        Args:
            filename: Name of the file to send. Used to infer MIME type.
            content: Contents of the file, or a path to read them from; see
                :meth:`ClientHandle.send_file_download`. A path is read once
                per client rather than held in memory between them, so a file
                rewritten mid-fan-out can reach two clients differently.
            chunk_size: Positive part size, at most 8 MiB.
            save_immediately: Whether to save the file immediately. If `False`,
                a link to the file will be shown as a notification. Being able to
                right click the link and choose "Save as..." can be useful.
        """
        filename = validate_file_display_name(filename)
        content = _validate_file_content(content)
        _validate_download_chunk_size(chunk_size)
        if type(save_immediately) is not bool:
            raise TypeError("save_immediately must be a bool.")
        clients = tuple(self.clients.values())
        self._run_broadcast_file_transfer(
            clients,
            lambda client: client._send_file(
                filename,
                content,
                chunk_size,
                "save" if save_immediately else "link",
            ),
            retained_bytes=len(content) if type(content) is bytes else 0,
        )

    def send_file_preview(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int = 1024 * 1024,
        max_bytes: int = PREVIEW_MAX_BYTES,
    ) -> None:
        """Open a file in a dialog on every connected client.

        Args:
            filename: Name of the file to send. Its type decides which viewer
                the browser reaches for.
            content: Contents of the file, or a path to read them from; see
                :meth:`ClientHandle.send_file_download`.
            chunk_size: Positive part size, at most 8 MiB.
            max_bytes: Size past which the file is not sent, and the clients
                are told why; see :meth:`ClientHandle.send_file_preview`.
        """
        filename = validate_file_display_name(filename)
        content = _validate_file_content(content)
        _validate_download_chunk_size(chunk_size)
        _validate_nonnegative_integer(max_bytes, "max_bytes")
        clients = tuple(self.clients.values())

        def send(client: ClientHandle) -> None:
            rejected_size = client._send_file(
                filename,
                content,
                chunk_size,
                "preview",
                max_bytes=max_bytes,
            )
            if rejected_size is not None:
                client.add_notification(
                    "Too large to preview",
                    f"{filename} is {_format_bytes(rejected_size)}, over the"
                    f" {_format_bytes(max_bytes)} preview limit.",
                )

        self._run_broadcast_file_transfer(
            clients,
            send,
            retained_bytes=len(content) if type(content) is bytes else 0,
        )

    def add_notification(
        self,
        title: str,
        body: str = "",
        *,
        loading: bool = False,
        with_close_button: bool = True,
        auto_close_seconds: float | None = 5.0,
    ) -> NotificationHandle:
        """Show a notification for all clients.

        See :meth:`GuiApi.add_notification` for argument semantics.
        """
        return self.gui.add_notification(
            title,
            body,
            loading=loading,
            with_close_button=with_close_button,
            auto_close_seconds=auto_close_seconds,
        )

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        """Get the asyncio event loop used by the Leika background thread. This
        can be useful for safe concurrent operations."""
        return self._event_loop

    def sleep_forever(self) -> None:
        """Equivalent to:

        while True:
            time.sleep(3600)
        """
        while True:
            time.sleep(3600)
