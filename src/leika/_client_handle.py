"""Per-browser API and ownership of outgoing file transfers."""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ContextManager, Iterator
from uuid import uuid4

from . import _downloads, _messages, infra
from ._async_errors import print_async_errors
from ._file_transfer import PREVIEW_MAX_BYTES, validate_file_display_name
from ._gui_api import GuiApi
from ._notification_handle import NotificationHandle
from ._validation import validate_nonnegative_integer as _validate_nonnegative_integer

if TYPE_CHECKING:
    from ._server import Server


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
            if len(self._outgoing_transfer_cancel_from_uuid) >= _downloads.DOWNLOAD_MAX_ACTIVE:
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
                descriptor: replacing its directory entry cannot alter the
                transfer, though Windows may refuse that replacement until the
                transfer closes. An in-place writer can change bytes still to be
                read. Pass bytes when an immutable snapshot is required; on systems
                that permit replacing open files, atomic rename also preserves the
                transfer snapshot. Text has to be encoded: a `str` names no file
                and holds no bytes, so it is refused rather than guessed at.
            chunk_size: Positive part size, at most 8 MiB.
            save_immediately: Whether to save the file immediately. If `False`,
                a link to the file will be shown as a notification. Being able to
                right click the link and choose "Save as..." can be useful.
        """
        filename = validate_file_display_name(filename)
        content = _downloads.validate_file_content(content)
        _downloads.validate_download_chunk_size(chunk_size)
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
        content = _downloads.validate_file_content(content)
        _downloads.validate_download_chunk_size(chunk_size)
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
                    f"{filename} is {_downloads.format_bytes(rejected_size)}, over the"
                    f" {_downloads.format_bytes(max_bytes)} preview limit.",
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
        _downloads.validate_download_chunk_size(chunk_size)

        mime_type = mimetypes.guess_type(filename, strict=False)[0]
        if mime_type is None:
            mime_type = "application/octet-stream"

        uuid = str(uuid4())
        started = False
        expected_parts = 0
        sent_parts = 0
        buffer = self._websock_connection.get_message_buffer()
        with self._track_outgoing_file_transfer(uuid) as cancelled:
            try:
                with _downloads.download_source(content, chunk_size) as (size_bytes, chunks):
                    if cancelled.is_set():
                        return None
                    if max_bytes is not None and size_bytes > max_bytes:
                        return size_bytes
                    expected_parts = -(-size_bytes // chunk_size)
                    if size_bytes > _downloads.DOWNLOAD_MAX_BYTES:
                        raise ValueError("download exceeds the bundled browser's 256 MiB limit")
                    if expected_parts > _downloads.DOWNLOAD_MAX_PARTS:
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
