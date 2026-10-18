"""Per-browser API and ownership of outgoing file transfers."""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ContextManager, Sequence
from uuid import uuid4

from . import _messages
from ._async_errors import print_async_errors
from ._file_transfer import PREVIEW_MAX_BYTES, file_parts, format_bytes, validate_file_send
from ._gui_api import GuiApi
from ._rendering import RenderingMode, render_message
from ._transport._websocket import WebsockClientConnection
from ._validation import validate_nonnegative_integer as _validate_nonnegative_integer

if TYPE_CHECKING:
    from ._server import Server


class ClientHandle:
    """A connected browser with its own client-local GUI."""

    def __init__(self, conn: WebsockClientConnection, server: Server) -> None:
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
        self._rendering: RenderingMode = "auto"
        self._image_fit = "fit"
        self._pane_size_lock = threading.Lock()
        self._pane_sizes: dict[tuple[str, str], tuple[int, int]] = {}
        self._transfer_lock = threading.Lock()
        self._transfer_cancel_from_uuid: dict[str, threading.Event] = {}

    async def _prepare_rendering(
        self, messages: Sequence[_messages.Message]
    ) -> Sequence[_messages.Message]:
        with self._pane_size_lock:
            mode, fit = self._rendering, self._image_fit
            sizes = self._pane_sizes.copy()
        if mode == "quality" or not any(
            isinstance(message, _messages.ViewportImageMessage)
            or (
                isinstance(message, _messages.ViewportPaneUpdateMessage)
                and "_data" in message.updates
            )
            for message in messages
        ):
            return messages

        delivery_rate = self.delivery_rate if mode == "auto" else None

        def prepare() -> Sequence[_messages.Message]:
            return tuple(
                render_message(
                    message,
                    mode,
                    sizes.get((getattr(message, "page_id", ""), getattr(message, "pane_id", ""))),
                    fit,
                    self._server,
                    delivery_rate=delivery_rate,
                )
                for message in messages
            )

        return await asyncio.get_running_loop().run_in_executor(
            self._server._thread_executor, prepare
        )

    @property
    def delivery_rate(self) -> float | None:
        """Smoothed received bytes/second, or None before a bulk receipt.

        Available with browser rendering preferences or explicit server
        ``delivery_backpressure``. Includes
        round-trip delay, so this is conservative delivery throughput, not a
        measurement of the physical link's maximum bandwidth.
        """
        return self._websock_connection._state.delivery_rate

    def pane_size(self, pane) -> tuple[int, int] | None:
        """Latest browser content size in physical pixels, or None if unknown.

        A hidden pane reports (0, 0). A pane on another subscribed page also
        returns (0, 0). Applications may use this hint to size streamed images.
        """
        page_id = pane._panes._page_id
        if self._websock_connection.delivery_scope() != page_id:
            return (0, 0)
        with self._pane_size_lock:
            return self._pane_sizes.get((page_id, str(pane.pane_id)))

    def _cancel_outgoing_file_transfer(self, transfer_uuid: str) -> None:
        """Honor a browser abort without echoing another abort back to it."""
        with self._transfer_lock:
            cancelled = self._transfer_cancel_from_uuid.get(transfer_uuid)
        if cancelled is not None:
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
        """Send a file for this client to download.

        Args:
            filename: Name of the file to send. Used to infer MIME type.
            content: Contents of the file, or a path to read them from. Text
                has to be encoded: a `str` names no file and holds no bytes,
                so it is refused rather than guessed at. A path is opened when
                the transfer starts and streamed from that open file, so
                replacing the path mid-send does not alter the transfer, while
                writing into the same file can. Calls from the server event
                loop or inside an atomic block start the transfer on a worker
                thread, so their read errors are reported asynchronously. At
                most 8 MiB of file payload is queued per client; the browser
                assembles the whole file before saving it.
            chunk_size: Positive part size, at most 8 MiB.
            save_immediately: Whether to save the file immediately. If `False`,
                a link to the file will be shown as a notification. Being able to
                right click the link and choose "Save as..." can be useful.
        """
        filename, content = validate_file_send(filename, content, chunk_size)
        if type(save_immediately) is not bool:
            raise TypeError("save_immediately must be a bool")
        self._send_download(filename, content, chunk_size, "save" if save_immediately else "link")

    def send_file_preview(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int = 1024 * 1024,
        max_bytes: int = PREVIEW_MAX_BYTES,
    ) -> None:
        """Send a file for this client to look at in a dialog.

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
            max_bytes: Size past which the file is not sent at all, and the
                client is told why. A preview is held whole in the browser, so
                an arbitrarily large file would be an arbitrarily large tab.
                Defaults to 64 MiB. The bundled browser renders plain-text
                sources only through 16 MiB and Markdown through 1 MiB;
                larger files remain available to download rather than render
                inline.
        """
        filename, content = validate_file_send(filename, content, chunk_size)
        _validate_nonnegative_integer(max_bytes, "max_bytes")
        self._send_preview(filename, content, chunk_size=chunk_size, max_bytes=max_bytes)

    def _send_download(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int,
        disposition: _messages.FileDisposition,
    ) -> None:
        """Send a download whose arguments are already checked."""
        self._run_file_transfer(lambda: self._send_file(filename, content, chunk_size, disposition))

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
        """Send a checked preview, plus what only a preview button knows.

        A button's file can be asked for again -- reloaded by hand, or resent
        when the file it was read from changes -- and the browser does the
        asking, so it has to be told which component to ask and what it is
        already holding. A script calling the public method has no component
        behind it and passes neither.
        """

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
                if disposition == "preview" and source_uuid is not None:
                    self._websock_connection.queue_message(
                        _messages.GuiPreviewCancelMessage(source_uuid)
                    )
                # Said rather than sent: the alternative is a tab that stops
                # responding with nothing on screen to explain why.
                self.gui.add_notification(
                    "Too large to preview",
                    f"{filename} is {format_bytes(rejected_size)}, over the"
                    f" {format_bytes(max_bytes)} preview limit.",
                )

        self._run_file_transfer(send)

    def _run_file_transfer(self, send: Callable[[], object]) -> None:
        """Send now, or on a worker when waiting here would block delivery.

        On the event loop, or inside an atomic block holding this connection's
        messages, waiting for transfer capacity would block the very delivery
        that frees it.
        """
        buffer = self._websock_connection.get_message_buffer()
        try:
            on_event_loop = asyncio.get_running_loop() is buffer.event_loop
        except RuntimeError:
            on_event_loop = False
        if on_event_loop or buffer.file_transfer_must_be_deferred():
            self._server._thread_executor.submit(send).add_done_callback(print_async_errors)
        else:
            send()

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
        """Send one file; return its size instead when it exceeds ``max_bytes``."""
        connection = self._websock_connection
        buffer = connection.get_message_buffer()
        transfer_uuid = str(uuid4())
        cancelled = threading.Event()
        with self._transfer_lock:
            self._transfer_cancel_from_uuid[transfer_uuid] = cancelled
        started = False
        try:
            with file_parts(content, chunk_size) as (size_bytes, parts):
                if max_bytes is not None and size_bytes > max_bytes:
                    return size_bytes
                started = connection.queue_message(
                    _messages.FileTransferStartDownload(
                        disposition=disposition,
                        transfer_uuid=transfer_uuid,
                        filename=filename,
                        mime_type=mimetypes.guess_type(filename, strict=False)[0]
                        or "application/octet-stream",
                        part_count=-(-size_bytes // chunk_size),
                        size_bytes=size_bytes,
                        source_uuid=source_uuid,
                        source_version=source_version,
                    )
                )
                if not started:
                    return None
                if disposition == "preview":
                    # Open the loading dialog before disk reads or transfer
                    # backpressure can delay the first part.
                    self.flush()
                for index, part in enumerate(parts):
                    # Reserving waits on the browser, which may abort meanwhile.
                    if not buffer.reserve_file_bytes(len(part)):
                        return None
                    message = _messages.FileTransferPart(
                        None, transfer_uuid=transfer_uuid, part_index=index, content=part
                    )
                    if cancelled.is_set() or not connection.queue_reserved_file_message(
                        message, len(part)
                    ):
                        buffer.release_file_bytes(len(part))
                        return None
                    self.flush()
        except Exception:
            # Once a start is on the wire, an incomplete transfer needs a
            # terminal message, or the browser waits for it forever. A browser
            # cancellation already is that message and is not echoed.
            if started and not cancelled.is_set():
                with contextlib.suppress(Exception):
                    connection.queue_message(
                        _messages.FileTransferAbort(
                            transfer_uuid=transfer_uuid,
                            # Never disclose local paths or exception text.
                            reason="The server could not complete this transfer.",
                        )
                    )
                    self.flush()
            raise
        finally:
            with self._transfer_lock:
                del self._transfer_cancel_from_uuid[transfer_uuid]
        return None
