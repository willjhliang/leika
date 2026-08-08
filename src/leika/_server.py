from __future__ import annotations

import asyncio
import contextlib
import inspect
import mimetypes
import os
import secrets
import threading
import time
from collections.abc import Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, BinaryIO, Callable, ContextManager, Iterator, Tuple, TypeVar

from . import _client_autobuild, _messages, infra
from ._async_errors import await_async_errors, print_async_errors
from ._gui_api import GuiApi
from ._gui_handles import PREVIEW_MAX_BYTES, _make_uuid
from ._notification_handle import NotificationHandle
from ._panes import Panes
from ._share import CloudflaredTunnel, ShareTunnelError
from ._validation import validate_nonnegative_integer as _validate_nonnegative_integer
from ._validation import validate_positive_integer as _validate_positive_integer
from .infra._infra import HttpAsset

NoneOrCoroutine = TypeVar("NoneOrCoroutine", None, Coroutine)


class _CallbackExecutor(ThreadPoolExecutor):
    """Thread pool whose queued work can be cancelled on server shutdown.

    Python cannot terminate a callback that is already running. Those
    callbacks finish naturally; ``wait=False`` is essential because the
    running callback may itself be the caller that stops the server.
    """

    def __init__(self, max_workers: int) -> None:
        super().__init__(max_workers=max_workers)
        self._pending_lock = threading.RLock()
        self._pending_futures: set[Future[Any]] = set()

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        with self._pending_lock:
            future = super().submit(fn, *args, **kwargs)
            self._pending_futures.add(future)
            future.add_done_callback(self._discard)
            return future

    def _discard(self, future: Future[Any]) -> None:
        with self._pending_lock:
            self._pending_futures.discard(future)

    def shutdown_cancel_pending(self) -> None:
        """Reject new work, cancel queued work, and let running work finish."""
        with self._pending_lock:
            for future in tuple(self._pending_futures):
                future.cancel()
            # ``cancel_futures=`` is unavailable on Python 3.8, so futures
            # are tracked explicitly and the compatible API closes the pool.
            super().shutdown(wait=False)


def _format_bytes(count: int) -> str:
    """A byte count as something to read in a notification."""
    size = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    raise AssertionError("unreachable")


def _validate_file_content(content: object) -> None:
    if not isinstance(content, (bytes, Path)):
        raise TypeError(
            "content must be bytes or a Path; a str is neither a file's contents"
            " (encode it) nor a path we would guess at (wrap it in Path)."
        )


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
        return plotly_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ImportError(f"Could not find plotly.min.js at {plotly_path}.") from error


def _read_in_chunks(
    file: BinaryIO, size_bytes: int, chunk_size: int, path: Path
) -> Iterator[bytes]:
    """Exactly `size_bytes` from an open file, `chunk_size` at a time."""
    remaining = size_bytes
    while remaining > 0:
        part = file.read(min(chunk_size, remaining))
        if not part:
            # The transfer announced its length before the first byte went out
            # and the client waits for exactly that many; a file truncated
            # underneath us can no longer supply them, and a short transfer
            # would leave the download hanging with no way to say why.
            raise OSError(
                f"{path} shrank while it was being sent: {remaining} of"
                f" {size_bytes} bytes were still expected."
            )
        remaining -= len(part)
        yield part


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
    if isinstance(content, bytes):
        yield (
            len(content),
            (content[i : i + chunk_size] for i in range(0, len(content), chunk_size)),
        )
        return
    _validate_file_content(content)
    assert isinstance(content, Path)
    with content.open("rb") as file:
        size_bytes = os.fstat(file.fileno()).st_size
        yield size_bytes, _read_in_chunks(file, size_bytes, chunk_size, content)


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

    def flush(self) -> None:
        """Flush the outgoing message buffer. Any buffered messages will immediately be
        sent. (by default they are windowed)"""
        self._server._websock_server.flush_client(self.client_id)

    def atomic(self) -> ContextManager[None]:
        """Returns a context where: all outgoing messages are grouped and applied by
        clients atomically.

        This should be treated as a soft constraint that's helpful for things
        like animations, or when we want position and orientation updates to
        happen synchronously.

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
            content: Contents of the file, or a path to read them from. A path
                is opened when this is called and streamed a chunk at a time,
                so sending a file costs one chunk of memory rather than its
                whole length. Text has to be encoded: a `str` names no file and
                holds no bytes, so it is refused rather than guessed at.
            chunk_size: Number of bytes to send at a time.
            save_immediately: Whether to save the file immediately. If `False`,
                a link to the file will be shown as a notification. Being able to
                right click the link and choose "Save as..." can be useful.
        """
        self._send_file(filename, content, chunk_size, "save" if save_immediately else "link")

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
            chunk_size: Number of bytes to send at a time.
            max_bytes: Size past which the file is not sent at all, and the
                client is told why. A preview is held whole in the browser --
                that is what showing it means -- so an arbitrarily large file
                would be an arbitrarily large tab. Defaults to 64 MiB.
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
        _validate_file_content(content)
        _validate_positive_integer(chunk_size, "chunk_size")
        _validate_nonnegative_integer(max_bytes, "max_bytes")
        assert isinstance(content, (bytes, Path))
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
        _validate_positive_integer(chunk_size, "chunk_size")

        mime_type = mimetypes.guess_type(filename, strict=False)[0]
        if mime_type is None:
            mime_type = "application/octet-stream"

        uuid = _make_uuid()
        started = False
        expected_parts = 0
        sent_parts = 0
        try:
            with _download_source(content, chunk_size) as (size_bytes, chunks):
                if max_bytes is not None and size_bytes > max_bytes:
                    return size_bytes
                expected_parts = -(-size_bytes // chunk_size)
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
                if queued is False:
                    return None
                started = True
                for i, part in enumerate(chunks):
                    queued = self._websock_connection.queue_message(
                        _messages.FileTransferPart(
                            None,
                            transfer_uuid=uuid,
                            part_index=i,
                            content=part,
                        )
                    )
                    if queued is False:
                        return None
                    sent_parts = i + 1
                    self.flush()
        except Exception as error:
            # Once a start is on the wire, every incomplete transfer needs a
            # terminal message. Otherwise previews and their reload watches can
            # wait forever while the connection itself remains healthy.
            if started and sent_parts < expected_parts:
                with contextlib.suppress(Exception):
                    self._websock_connection.queue_message(
                        _messages.FileTransferAbort(
                            transfer_uuid=uuid,
                            reason=str(error) or type(error).__name__,
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
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        *,
        workspace_id: str = "default",
        label: str | None = None,
        password: str | None = None,
        share: bool = False,
        verbose: bool = True,
    ) -> None:
        if not workspace_id:
            raise ValueError("workspace_id must not be empty.")
        # Sharing means the dashboard carries data worth protecting, and a
        # non-loopback bind would serve that same data as unencrypted HTTP to
        # the local network -- where the password itself travels in the clear.
        # With the tunnel open there is no reason for a second, weaker door.
        if share and host not in ("127.0.0.1", "localhost", "::1"):
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
        self.host = host
        self.password = password
        self.workspace_id = workspace_id
        self.verbose = verbose
        self._stopped = False
        self._stop_lock = threading.Lock()
        self._stop_finalizer: threading.Thread | None = None
        self._executor_shutdown = False
        self._connected_clients: dict[int, ClientHandle] = {}
        self._client_lock = threading.RLock()
        self._client_connect_cb: list[Callable[[ClientHandle], None | Coroutine]] = []
        self._client_disconnect_cb: list[Callable[[ClientHandle], None | Coroutine]] = []
        self._thread_executor = _CallbackExecutor(max_workers=32)
        self._gui_order_counter = 0
        self._gui_order_lock = threading.Lock()
        self._plotly_js_lock = threading.Lock()
        self._plotly_js_source: str | None = None
        self._plotly_js_required_globally = False
        self._plotly_js_sent_client_ids: set[infra.ClientId] = set()

        _client_autobuild.ensure_client_is_built()
        server = infra.WebsockServer(
            host=host,
            port=port,
            message_class=_messages.Message,
            http_server_root=Path(__file__).resolve().parent / "client" / "build",
            verbose=verbose,
            password=password,
        )
        self._websock_server = server

        @server.on_client_connect
        async def _on_connect(conn: infra.WebsockClientConnection) -> None:
            self._run_garbage_collector()
            client = ClientHandle(conn, self)
            with self._client_lock:
                self._connected_clients[conn.client_id] = client
                callbacks = tuple(self._client_connect_cb)
            # The connection-local queue is registered before user callbacks,
            # so their Plotly messages cannot overtake this bootstrap.
            self._initialize_plotly_connection(conn)
            for callback in callbacks:
                if inspect.iscoroutinefunction(callback):
                    await await_async_errors(callback(client))
                else:
                    self._thread_executor.submit(callback, client).add_done_callback(
                        print_async_errors
                    )

        server.register_handler(_messages.ClientPingMessage, self._handle_client_ping)

        @server.on_client_disconnect
        async def _on_disconnect(conn: infra.WebsockClientConnection) -> None:
            with self._client_lock:
                client = self._connected_clients.pop(conn.client_id, None)
                callbacks = tuple(self._client_disconnect_cb)
            self._discard_plotly_connection(conn.client_id)
            if client is None:
                return
            client.gui._discard_client_work(conn.client_id)
            gui = getattr(self, "gui", None)
            if gui is not None:
                gui._discard_client_work(conn.client_id)
            for callback in callbacks:
                if inspect.iscoroutinefunction(callback):
                    await await_async_errors(callback(client))
                else:
                    self._thread_executor.submit(callback, client).add_done_callback(
                        print_async_errors
                    )

        server.start()
        self._event_loop = server._broadcast_buffer.event_loop
        self.port = server._port
        self.gui = GuiApi(
            self,
            thread_executor=self._thread_executor,
            event_loop=self._event_loop,
        )
        server.queue_message(_messages.WorkspaceConfigurationMessage(workspace_id=workspace_id))
        self.panes = Panes(self)
        self.gui.set_panel_label(label)

        # Open the share tunnel last: it only matters once the server it
        # forwards to is up. A tunnel failure is reported but not fatal --
        # the dashboard itself still works locally.
        self.share_url: str | None = None
        self._share_tunnel: CloudflaredTunnel | None = None
        if share:
            try:
                tunnel = CloudflaredTunnel(self.port)
                self.share_url = tunnel.start()
                self._share_tunnel = tunnel
            except ShareTunnelError as e:
                print(f"Leika share tunnel failed: {e}")

        if verbose:
            print(f"Leika listening at {self.url}")
            if self.share_url is not None:
                print(f"Leika share URL: {self.share_url}")
            if self._password_generated:
                print(f"Leika password (auto-generated): {password}")

    @property
    def url(self) -> str:
        display_host = "localhost" if self.host in ("0.0.0.0", "::") else self.host
        return f"http://{display_host}:{self.port}"

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
        assert source is not None
        if connection.queue_message(_messages.RunJavascriptMessage(source=source)) is False:
            return
        self._plotly_js_sent_client_ids.add(client_id)

    def _ensure_plotly_js_sent(self, connection: infra.WebsockClientConnection | None) -> None:
        """Initialize one client, or every current and future client, once."""
        with self._plotly_js_lock:
            if self._plotly_js_source is None:
                self._plotly_js_source = _load_plotly_js()

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

    def _handle_client_ping(
        self, client_id: infra.ClientId, message: _messages.ClientPingMessage
    ) -> None:
        """Answer one client's ping, and get out of the way.

        Flushed rather than left to the outgoing window, which holds messages
        for a frame before sending them: waiting would add that frame to every
        reading and hide the very delays the client is measuring for.
        """
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
        try:
            from IPython import get_ipython  # type: ignore[import-not-found]

            if get_ipython() is not None:
                from IPython.display import IFrame, display  # type: ignore[import-not-found]

                frame = IFrame(self.url, width="100%", height=height)
                display(frame)
                return frame
        except ImportError:
            pass
        import webbrowser

        webbrowser.open(self.url)
        return None

    def _run_garbage_collector(self) -> None:
        """Purge tombstones and updates for removed persistent entities."""
        buffer = self._websock_server._broadcast_buffer
        with buffer.buffer_lock:
            # Skip GC while there are messages queued but not yet processed by
            # the window generators. Without this, we could cull messages
            # before they reach existing clients.
            if buffer.message_event.is_set():
                return

            # First pass: collect every tombstone's entity id.
            remove_message_ids: list[int] = []
            removed_ids_by_type: dict[str, set[str]] = {}
            for msg_id, message in buffer.message_from_id.items():
                if message.lifecycle_phase == "remove":
                    assert message.entity_type is not None and message.entity_id_field is not None
                    remove_message_ids.append(msg_id)
                    removed_ids_by_type.setdefault(message.entity_type, set()).add(
                        getattr(message, message.entity_id_field)
                    )

            # Second pass: purge updates whose target entity has a tombstone.
            if removed_ids_by_type:
                for msg_id, message in buffer.message_from_id.items():
                    phase = message.lifecycle_phase
                    if phase in ("update_dict", "update_simple"):
                        assert (
                            message.entity_type is not None and message.entity_id_field is not None
                        )
                        entity_id = getattr(message, message.entity_id_field)
                        if entity_id in removed_ids_by_type.get(message.entity_type, ()):
                            remove_message_ids.append(msg_id)

            for msg_id in remove_message_ids:
                message = buffer.message_from_id.pop(msg_id)
                buffer.id_from_redundancy_key.pop(message.redundancy_key(), None)

    def _shutdown_callback_executor(self) -> None:
        """Cancel queued callbacks once, after websocket teardown is done."""
        with self._stop_lock:
            if self._executor_shutdown:
                return
            self._executor_shutdown = True
        self._thread_executor.shutdown_cancel_pending()

    def _finish_stop(self) -> None:
        """Join the websocket worker, then retire its callback executor."""
        try:
            self._websock_server.stop()
        finally:
            self._shutdown_callback_executor()

    def stop(self) -> None:
        """Stop the Leika server and cancel callbacks that have not started.

        Callbacks already running are allowed to finish: Python threads cannot
        be terminated safely. When this is called from an async websocket
        callback, a short-lived finalizer performs the join after that callback
        returns, avoiding a server-thread self-join. Repeat calls remain safe
        and may complete the same bounded shutdown from another thread.
        """
        with self._stop_lock:
            first_request = not self._stopped
            self._stopped = True
            tunnel = self._share_tunnel if first_request else None
            if first_request:
                self._share_tunnel = None
                self.share_url = None

        if tunnel is not None:
            tunnel.close()

        server_thread = self._websock_server._server_thread
        if threading.current_thread() is server_thread:
            self._websock_server.stop()
            with self._stop_lock:
                if self._stop_finalizer is None:
                    self._stop_finalizer = threading.Thread(
                        target=self._finish_stop,
                        name="leika-stop-finalizer",
                        daemon=True,
                    )
                    self._stop_finalizer.start()
            return

        self._finish_stop()

    def on_client_connect(
        self, cb: Callable[[ClientHandle], NoneOrCoroutine]
    ) -> Callable[[ClientHandle], NoneOrCoroutine]:
        """Attach a callback to run for newly connected clients.

        The callback can be either a standard function or an async function:
        - Standard functions (def) will be executed in a threadpool.
        - Async functions (async def) will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        with self._client_lock:
            clients = self._connected_clients.copy().values()
            self._client_connect_cb.append(cb)

        # Trigger callback on any already-connected clients.
        # If we have:
        #
        #     server = Server()
        #     server.on_client_connect(...)
        #
        # This makes sure that the the callback is applied to any clients that
        # connect between the two lines.
        for client in clients:
            if inspect.iscoroutinefunction(cb):
                future = asyncio.run_coroutine_threadsafe(cb(client), self._event_loop)
                future.add_done_callback(print_async_errors)
            else:
                self._thread_executor.submit(cb, client).add_done_callback(print_async_errors)

        return cb  # type: ignore

    def on_client_disconnect(
        self, cb: Callable[[ClientHandle], NoneOrCoroutine]
    ) -> Callable[[ClientHandle], NoneOrCoroutine]:
        """Attach a callback to run when clients disconnect.

        The callback can be either a standard function or an async function:
        - Standard functions (def) will be executed in a threadpool.
        - Async functions (async def) will be executed in the event loop.

        Using async functions can be useful for reducing race conditions.
        """
        with self._client_lock:
            self._client_disconnect_cb.append(cb)
        return cb

    def flush(self) -> None:
        """Flush the outgoing message buffer. Any buffered messages will immediately be
        sent. (by default they are windowed)"""
        self._websock_server.flush()

    def atomic(self) -> ContextManager[None]:
        """Returns a context where: all outgoing messages are grouped and applied by
        clients atomically.

        This should be treated as a soft constraint that's helpful for things
        like animations, or when we want position and orientation updates to
        happen synchronously.

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
            path: File to serve. Read at registration to hash it, and again
                per request, so it is never held in memory.

        Returns:
            Root-relative URL path (``/leika-assets/<hash><suffix>``).
        """
        return self._websock_server.register_http_asset(path).url

    def _register_http_image(self, path: Path) -> HttpAsset:
        """:meth:`register_http_asset`, keeping the picture's size as well.

        The size is what a document needs in order to leave the right room for
        a figure before the figure has arrived, and it is read from the bytes
        the URL was already being hashed from -- so it is the same
        registration, told in full rather than told twice.
        """
        return self._websock_server.register_http_asset(path)

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
            chunk_size: Number of bytes to send at a time.
            save_immediately: Whether to save the file immediately. If `False`,
                a link to the file will be shown as a notification. Being able to
                right click the link and choose "Save as..." can be useful.
        """
        _validate_positive_integer(chunk_size, "chunk_size")

        for client in self.clients.values():
            client.send_file_download(filename, content, chunk_size, save_immediately)

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
            chunk_size: Number of bytes to send at a time.
            max_bytes: Size past which the file is not sent, and the clients
                are told why; see :meth:`ClientHandle.send_file_preview`.
        """
        _validate_positive_integer(chunk_size, "chunk_size")
        _validate_nonnegative_integer(max_bytes, "max_bytes")

        for client in self.clients.values():
            client.send_file_preview(filename, content, chunk_size, max_bytes)

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
