"""Workspace composition, shared resources, and server lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import math
import secrets
import threading
import time
from collections.abc import Coroutine, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, ContextManager, TypeVar, cast
from urllib.parse import urlsplit

from . import _client_autobuild, _messages
from ._async_errors import await_user_callback, print_async_errors
from ._client_handle import ClientHandle
from ._file_transfer import PREVIEW_MAX_BYTES, validate_file_send
from ._gui_api import GuiApi
from ._pages import Pages, _page_name_from_label
from ._share import CloudflaredTunnel, ShareTunnelError
from ._transport._auth import HttpPasswordGuard
from ._transport._http_assets import HttpAsset
from ._transport._http_security import (
    _canonical_hostname,
    _configured_allowed_hosts,
    _is_loopback_host,
)
from ._transport._websocket import ClientId, WebsockClientConnection, WebsockServer
from ._validation import validate_layout_id
from ._validation import validate_nonnegative_integer as _validate_nonnegative_integer
from ._validation import validate_positive_integer as _validate_positive_integer

NoneOrCoroutine = TypeVar("NoneOrCoroutine", None, Coroutine)

_PAGE_SUBSCRIPTION_GENERATION_MAX = (1 << 53) - 1


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
    entries are hostnames without ports.
    With ``allowed_hosts=None``, load the JSON array in
    ``$XDG_CONFIG_HOME/leika/allowed_hosts.json`` (default
    ``~/.config/leika/allowed_hosts.json``). A missing file adds no names.
    An explicit sequence replaces user configuration; ``[]`` disables it.
    Configuration is read once per server construction, before allocating resources.
    Invalid names raise ``ValueError`` during construction. Browser ``Origin``
    must still match the accepted request origin. Pages deny framing by default; set
    ``allow_embedding=True`` only for an intentional iframe or notebook
    :meth:`show` use.

    Each connection's queues wait for the browser's receipt of a batch before
    sending it the next, so pending updates coalesce instead of queuing old
    frames in the network. A high-latency connection gets fewer, newer frames.
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
        default_page_name = _page_name_from_label(label)
        if password is not None:
            if type(password) is not str:
                raise TypeError("password must be a string or None.")
            # Validate before building the client or allocating executors.
            HttpPasswordGuard(password)
        if not isinstance(allow_embedding, bool):
            raise TypeError("allow_embedding must be a bool.")
        if not isinstance(share, bool):
            raise TypeError("share must be a bool.")
        if not isinstance(verbose, bool):
            raise TypeError("verbose must be a bool.")
        normalized_allowed_hosts = _configured_allowed_hosts(allowed_hosts)
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

        # Building can fail, but owns no runtime resources.
        _client_autobuild.ensure_client_is_built()
        self.host = host
        self.password = password
        self.workspace_id = workspace_id
        self.verbose = verbose
        self.allow_embedding = allow_embedding
        self._stopped = False
        self._share_tunnel: CloudflaredTunnel | None = None
        self._connected_clients: dict[int, ClientHandle] = {}
        self._client_lock = threading.RLock()
        self._client_connect_cb: list[Callable[[ClientHandle], None | Coroutine]] = []
        self._client_disconnect_cb: list[Callable[[ClientHandle], None | Coroutine]] = []
        self._gui_order_counter = 0
        self._gui_order_lock = threading.Lock()
        self._plotly_lock = threading.Lock()
        self._plotly_runtime_queued = False
        self._thread_executor = ThreadPoolExecutor(max_workers=32)

        server = WebsockServer(
            host,
            port,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
            index_html=Path(__file__).resolve().parent / "client" / "build" / "index.html",
            verbose=verbose,
            password=password,
            allowed_hosts=normalized_allowed_hosts,
            allow_embedding=allow_embedding,
        )
        self._websock_server = server
        self._event_loop = server._broadcast_buffer.event_loop
        server.register_handler(_messages.PageSubscribeMessage, self._handle_page_subscribe)
        server.register_handler(_messages.ClientPingMessage, self._handle_client_ping)
        server.register_handler(_messages.FileTransferAbort, self._handle_file_transfer_abort)

        try:
            # The workspace is complete before the server listens, so no
            # browser ever sees part of it.
            self.gui = GuiApi(
                self,
                thread_executor=self._thread_executor,
                event_loop=self._event_loop,
            )
            server.queue_message_or_raise(
                _messages.WorkspaceConfigurationMessage(workspace_id=workspace_id)
            )
            self.pages = Pages(self, default_page_name)
            self.panes = self.pages.default.panes
            server.start()
            self.port = server._port

            # A tunnel failure is reported but not fatal: the dashboard itself
            # still works locally.
            if share:
                tunnel = CloudflaredTunnel(self.port)
                try:
                    share_url = tunnel.start()
                except ShareTunnelError as error:
                    print(f"Leika share tunnel failed: {error}")
                else:
                    self._share_tunnel = tunnel
                    server.trust_proxy_host(cast(str, urlsplit(share_url).hostname))

            if verbose:
                print(f"Leika listening at {self.url}")
                if self.share_url is not None:
                    print(f"Leika share URL: {self.share_url}")
                if self._password_generated:
                    print(f"Leika password (auto-generated): {password}")
        except BaseException:
            # Release what construction started; its failure is the one reported.
            with contextlib.suppress(Exception):
                self._shut_down()
            raise

    async def _on_connect(self, conn: WebsockClientConnection) -> None:
        client = ClientHandle(conn, self)
        with self._client_lock:
            self._connected_clients[conn.client_id] = client
            callbacks = tuple(self._client_connect_cb)
        for callback in callbacks:
            await self._await_user_callback(callback, client)

    async def _on_disconnect(self, conn: WebsockClientConnection) -> None:
        with self._client_lock:
            client = self._connected_clients.pop(conn.client_id, None)
            callbacks = tuple(self._client_disconnect_cb)
        if client is None:
            return
        client.gui._retire_scope()
        self.gui._discard_client_work(conn.client_id)
        for callback in callbacks:
            await self._await_user_callback(callback, client)

    @property
    def share_url(self) -> str | None:
        """Current public tunnel URL, or ``None`` when no tunnel is live."""
        tunnel = self._share_tunnel
        return None if tunnel is None else tunnel.url

    @property
    def url(self) -> str:
        """Browser URL for the server, rendering wildcard binds as ``localhost``."""

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

    def _next_gui_order(self) -> float:
        """Allocate one deterministic implicit order across this server's GUIs."""
        with self._gui_order_lock:
            self._gui_order_counter += 1
            return self._gui_order_counter

    def _ensure_plotly_runtime(self) -> None:
        """Queue Plotly's browser runtime once; replay brings it to later browsers."""
        with self._plotly_lock:
            if self._plotly_runtime_queued:
                return
            try:
                import plotly
            except ImportError as error:
                raise ImportError(
                    "You must have the `plotly` package installed to use Plotly elements."
                ) from error
            runtime = Path(plotly.__file__ or "").parent / "package_data" / "plotly.min.js"
            self._websock_server.queue_message_or_raise(
                _messages.RunJavascriptMessage(source=runtime.read_text("utf-8"))
            )
            self._plotly_runtime_queued = True

    def _handle_file_transfer_abort(
        self, client_id: ClientId, message: _messages.FileTransferAbort
    ) -> None:
        """Cancel a server-to-browser transfer, if this UUID names one."""
        with self._client_lock:
            client = self._connected_clients.get(client_id)
        if client is not None:
            client._cancel_outgoing_file_transfer(message.transfer_uuid)

    def _handle_page_subscribe(
        self, client_id: ClientId, message: _messages.PageSubscribeMessage
    ) -> None:
        """Replace one browser's private active-page transport stream."""

        if (
            type(message.generation) is not int
            or not 0 <= message.generation <= _PAGE_SUBSCRIPTION_GENERATION_MAX
        ):
            return
        with self.pages._lock:
            page = self.pages._page_from_page_id.get(message.page_id)
        if page is None:
            return
        with self._client_lock:
            client = self._connected_clients.get(client_id)
        if client is None:
            return
        with page.panes._lock:
            client._websock_connection.request_delivery_scope(
                message.page_id,
                _messages.PageStreamBeginMessage(
                    page_id=message.page_id, generation=message.generation
                ),
                _messages.PageStreamReadyMessage(
                    page_id=message.page_id, generation=message.generation
                ),
            )

    def _handle_client_ping(
        self, client_id: ClientId, message: _messages.ClientPingMessage
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

    async def _await_user_callback(self, callback: Callable[..., Any], *args: Any) -> None:
        await await_user_callback(self._thread_executor, callback, *args)

    def _shut_down(self) -> None:
        """Stop serving, then close the tunnel and cancel callbacks not yet started."""
        if threading.current_thread() is self._websock_server._server_thread:
            # Waiting here would wait for this thread itself, and connection
            # teardown still needs the pool; finish from another thread.
            self._websock_server.signal_stop()
            threading.Thread(target=self._shut_down, name="leika-stop", daemon=True).start()
            return
        with self._client_lock:
            tunnel, self._share_tunnel = self._share_tunnel, None
        with contextlib.ExitStack() as cleanup:
            # Each step runs even if an earlier one fails.
            cleanup.callback(self._thread_executor.shutdown, wait=False, cancel_futures=True)
            if tunnel is not None:
                cleanup.callback(tunnel.close)
            self._websock_server.stop()

    def stop(self) -> None:
        """Stop the Leika server and cancel callbacks that have not started.

        Callbacks already running finish on their own threads. Stopping from
        inside a callback or on the server's event loop is safe, and repeat
        calls are harmless.
        """
        with self._client_lock:
            self._stopped = True
            clients = tuple(self._connected_clients.values())
        for client in clients:
            client.gui._retire_scope()
        self.gui._retire_scope()
        self._shut_down()

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
        with self._client_lock:
            if self._stopped:
                raise RuntimeError("Cannot register callbacks after Server.stop().")
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
            asyncio.run_coroutine_threadsafe(
                self._await_connect_callback_if_current(cb, client), self._event_loop
            ).add_done_callback(print_async_errors)

        return cast(Callable[[ClientHandle], NoneOrCoroutine], cb)

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
        with self._client_lock:
            if self._stopped:
                raise RuntimeError("Cannot register callbacks after Server.stop().")
            self._client_disconnect_cb.append(cb)
        return cb

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

    def _register_http_image(self, path: Path) -> HttpAsset:
        """:meth:`register_http_asset`, keeping the picture's size as well.

        The size is what a document needs in order to leave the right room for
        a figure before the figure has arrived.
        """
        return self._websock_server.register_http_asset(path)

    def send_file_download(
        self,
        filename: str,
        content: bytes | Path,
        chunk_size: int = 1024 * 1024,
        save_immediately: bool = False,
    ) -> None:
        """Send a file for every connected client to download.

        Args:
            filename: Name of the file to send. Used to infer MIME type.
            content: Contents of the file, or a path to read them from; see
                :meth:`ClientHandle.send_file_download`. A path is read once
                per client, so a file rewritten mid-fan-out can reach two
                clients differently.
            chunk_size: Positive part size, at most 8 MiB.
            save_immediately: Whether to save the file immediately. If `False`,
                a link to the file will be shown as a notification. Being able to
                right click the link and choose "Save as..." can be useful.
        """
        filename, content = validate_file_send(filename, content, chunk_size)
        if type(save_immediately) is not bool:
            raise TypeError("save_immediately must be a bool.")
        disposition = "save" if save_immediately else "link"
        for client in self.clients.values():
            client._send_download(filename, content, chunk_size, disposition)

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
        filename, content = validate_file_send(filename, content, chunk_size)
        _validate_nonnegative_integer(max_bytes, "max_bytes")
        for client in self.clients.values():
            client._send_preview(filename, content, chunk_size=chunk_size, max_bytes=max_bytes)

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
