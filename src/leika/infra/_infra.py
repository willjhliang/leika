from __future__ import annotations

import abc
import asyncio
import atexit
import contextlib
import dataclasses
import gzip
import hashlib
import http
import inspect
import logging
import mimetypes
import threading
import time
from collections.abc import Awaitable, Coroutine, Iterable
from concurrent.futures import Future
from pathlib import Path, PureWindowsPath
from typing import Callable, Generator, NamedTuple, NewType, Optional, Tuple, TypeVar
from urllib.parse import unquote as _url_unquote

import msgspec.msgpack
import websockets.asyncio.server
import websockets.datastructures
import websockets.exceptions
import zstandard
from typing_extensions import override
from websockets import Headers
from websockets.asyncio.server import ServerConnection
from websockets.http11 import Request, Response
from websockets.typing import Subprotocol

from .._async_errors import print_async_exception
from ._async_message_buffer import AsyncMessageBuffer
from ._auth import HttpPasswordGuard
from ._image_headers import image_pixel_size
from ._messages import Message


class _WebsocketLogFilter(logging.Filter):
    """Hide the expected rejection used to serve ordinary HTTP responses."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() != "connection rejected (200 OK)"


_WEBSOCKET_LOGGER = logging.getLogger("leika.websockets")
_WEBSOCKET_LOGGER.addFilter(_WebsocketLogFilter())

_SERVER_STOP_TIMEOUT_SECONDS = 10.0


@dataclasses.dataclass
class _ClientHandleState:
    # Internal state for ClientConnection objects.
    message_buffer: AsyncMessageBuffer


ClientId = NewType("ClientId", int)
TMessage = TypeVar("TMessage", bound=Message)


async def _run_callback(callback: Callable[..., object], *args: object) -> None:
    """Run one callback without letting its failure suppress later peers."""
    try:
        result = callback(*args)
        if inspect.isawaitable(result):
            await result
    except Exception as error:
        # Cancellation is a BaseException and deliberately passes through: a
        # peer close or server shutdown must still retire in-flight user code.
        print_async_exception(error)


async def _run_callbacks(callbacks: Iterable[Callable[..., object]], *args: object) -> None:
    """Run a stable callback snapshot sequentially, isolating each failure."""
    for callback in tuple(callbacks):
        await _run_callback(callback, *args)


class WebsockMessageHandler:
    """Mix-in for adding message handling to a class."""

    def __init__(self) -> None:
        self._incoming_handlers: dict[
            type[Message], list[Callable[[ClientId, Message], None | Coroutine]]
        ] = {}

    def register_handler(
        self,
        message_cls: type[TMessage],
        callback: Callable[[ClientId, TMessage], None | Coroutine],
    ) -> None:
        """Register a handler for a particular message type."""
        if message_cls not in self._incoming_handlers:
            self._incoming_handlers[message_cls] = []
        self._incoming_handlers[message_cls].append(callback)  # type: ignore

    def unregister_handler(
        self,
        message_cls: type[TMessage],
        callback: Callable[[ClientId, TMessage], None | Coroutine] | None = None,
    ):
        """Unregister a handler for a particular message type."""
        assert message_cls in self._incoming_handlers, (
            "Tried to unregister a handler that hasn't been registered."
        )
        if callback is None:
            self._incoming_handlers.pop(message_cls)
        else:
            self._incoming_handlers[message_cls].remove(callback)  # type: ignore

    async def _handle_incoming_message(self, client_id: ClientId, message: Message) -> None:
        """Handle incoming messages in registration order."""
        await _run_callbacks(self._incoming_handlers.get(type(message), ()), client_id, message)

    @abc.abstractmethod
    def get_message_buffer(self) -> AsyncMessageBuffer: ...

    def queue_message(self, message: Message) -> bool:
        """Queue a message and report whether the connection is still open."""
        return self.get_message_buffer().push(message)

    @contextlib.contextmanager
    def atomic(self) -> Generator[None, None, None]:
        """Returns a context where: all outgoing messages are grouped and applied by
        clients atomically.

        This should be treated as a soft constraint that's helpful for things
        like animations, or when we want position and orientation updates to
        happen synchronously.

        Returns:
            Context manager.
        """
        # If called multiple times in the same thread, we ignore inner calls.
        #
        # try/finally so an exception raised inside the `with` body still
        # decrements the counter. Otherwise atomic_end() is skipped and the
        # counter stays stuck != 0, stalling message delivery permanently.
        buffer = self.get_message_buffer()
        buffer.atomic_start()
        try:
            yield
        finally:
            buffer.atomic_end()


class WebsockClientConnection(WebsockMessageHandler):
    """Handle for sending messages to and listening to messages from a single
    connected client."""

    def __init__(
        self,
        client_id: ClientId,
        client_state: _ClientHandleState,
    ) -> None:
        self.client_id = client_id
        self._state = client_state
        super().__init__()

    @override
    def get_message_buffer(self) -> AsyncMessageBuffer:
        """Get client message buffer."""
        return self._state.message_buffer


def _static_relpath(request_target: str) -> str | None:
    """Normalize one HTTP target, rejecting POSIX and Windows escapes."""
    path = _url_unquote(request_target.partition("?")[0]).replace("\\", "/")
    segments = [segment for segment in path.split("/") if segment and segment != "."]
    if any(
        segment == ".."
        or ":" in segment
        or any(ord(character) < 32 or ord(character) == 127 for character in segment)
        for segment in segments
    ):
        return None

    relpath = "/".join(segments) if segments else "index.html"
    # On Windows, a drive-qualified right operand discards the configured
    # static root. The colon check above also rejects NTFS alternate streams;
    # keep the explicit drive guard so that invariant is visible and testable.
    if PureWindowsPath(relpath).drive:
        return None
    return relpath


def _quality(parameters: Iterable[str]) -> float:
    """Parse an encoding quality, treating malformed q-values as refusal."""
    for parameter in parameters:
        name, separator, raw_value = parameter.partition("=")
        if name.strip().lower() != "q":
            continue
        if not separator:
            return 0.0
        try:
            quality = float(raw_value.strip())
        except ValueError:
            return 0.0
        return quality if 0.0 <= quality <= 1.0 else 0.0
    return 1.0


def _accepts_gzip(header_values: Iterable[str]) -> bool:
    """Whether Accept-Encoding permits gzip, including wildcard semantics."""
    gzip_quality: float | None = None
    wildcard_quality: float | None = None
    for value in header_values:
        for item in value.split(","):
            coding, *parameters = item.split(";")
            coding = coding.strip().lower()
            if coding not in ("gzip", "*"):
                continue
            quality = _quality(parameters)
            if coding == "gzip":
                gzip_quality = max(gzip_quality or 0.0, quality)
            else:
                wildcard_quality = max(wildcard_quality or 0.0, quality)

    # An explicit gzip entry overrides a wildcard, including gzip;q=0.
    if gzip_quality is not None:
        return gzip_quality > 0.0
    return wildcard_quality is not None and wildcard_quality > 0.0


def _http_content_type(name: str) -> str:
    """The Content-Type a file is served with, from its name.

    Known types are answered from a table rather than from ``guess_type()``,
    which can misname Javascript on some Windows machines. Some references:

        https://bugs.python.org/issue43975
        https://github.com/golang/go/issues/32350#issuecomment-525111557

    We're assuming UTF-8 for text, which is mostly reasonable but might want
    to be revisited.
    """
    mime_type = {
        ".css": "text/css; charset=utf-8",
        ".gif": "image/gif",
        ".htm": "text/html; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".jpg": "image/jpeg",
        ".js": "application/javascript",
        ".wasm": "application/wasm",
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".xml": "text/xml; charset=utf-8",
    }.get(Path(name).suffix.lower(), None)
    if mime_type is None:
        mime_type = mimetypes.guess_type(name)[0]
    if mime_type is None:
        mime_type = "application/octet-stream"
    return mime_type


_HTTP_ASSET_URL_PREFIX = "/leika-assets/"
"""Where runtime-registered files are served, apart from the static tree."""

_HTTP_ASSET_LIMIT = 1024
"""How many registered assets are remembered. Registrations past this evict
the oldest; a URL that has been evicted answers 404, the same as one that was
never registered."""

_HTTP_ASSET_BACKING_LIMIT = 16
"""Maximum equivalent source paths retained for one content-addressed URL.
Recent alternatives preserve fallback without allowing duplicate temporary
paths to create an unbounded request-time scan."""


class HttpAsset(NamedTuple):
    """Where a registered file is served, and how big it is if it is a picture.

    The size travels with the URL because both fall out of the same read: a
    caller writing an ``<img>`` wants the address and the box to leave for it
    at the same moment, and asking twice would mean reading the file twice.
    """

    url: str
    """Root-relative URL path the file is served at."""
    pixel_size: Optional[Tuple[int, int]]
    """``(width, height)`` if the file's header declares one, else ``None``."""


class WebsockServer(WebsockMessageHandler):
    """Websocket server abstraction. Communicates asynchronously with client
    applications.

    By default, all messages are broadcasted to all connected clients.

    To send messages to an individual client, we can use `on_client_connect()` to
    retrieve client handles.

    Args:
        host: Host to bind server to.
        port: Port to bind server to.
        message_class: Base class for message types. Subclasses of the message type
            should have unique names. This argument is optional currently, but will be
            required in the future.
        http_server_root: Path to root for HTTP server.
        verbose: Toggle for print messages.
        password: When set, every HTTP request and websocket handshake must
            authenticate against it before anything is served.
    """

    def __init__(
        self,
        host: str,
        port: int,
        message_class: type[Message] = Message,
        http_server_root: Path | None = None,
        verbose: bool = True,
        password: str | None = None,
    ):
        super().__init__()

        # Track connected clients.
        self._client_connect_cb: list[Callable[[WebsockClientConnection], None | Coroutine]] = []
        self._client_disconnect_cb: list[Callable[[WebsockClientConnection], None | Coroutine]] = []

        self._host = host
        self._port = port
        self._message_class = message_class
        self._http_server_root = http_server_root
        self._auth_guard = HttpPasswordGuard(password) if password is not None else None
        self._verbose = verbose
        self._background_event_loop: asyncio.AbstractEventLoop | None = None

        self._stop_event: asyncio.Event | None = None
        self._stop_requested = threading.Event()

        self._client_state_from_id: dict[int, _ClientHandleState] = {}
        self._server_thread: threading.Thread | None = None

        # Files registered at runtime to be fetched over HTTP, named by their
        # content's hash. Keep the expected digest with the mutable source path
        # so serving can enforce the content-addressed URL invariant.
        self._http_assets: dict[str, tuple[tuple[Path, ...], str]] = {}
        self._http_assets_lock = threading.Lock()

    def start(self) -> None:
        """Start the server."""

        self._stop_requested.clear()

        # A Future distinguishes failures before the socket is ready from
        # failures after startup. The former belong to this synchronous API;
        # the latter must still escape the worker thread instead of being
        # silently converted into a second readiness signal.
        startup: Future[None] = Future()

        def run_worker() -> None:
            try:
                self._background_worker(startup)
            except BaseException as error:
                if not startup.done():
                    startup.set_exception(error)
                    return
                raise

        self._server_thread = threading.Thread(target=run_worker, daemon=True)
        self._server_thread.start()

        # Wait for either a bound server or a reported startup failure.
        try:
            startup.result()
        except BaseException:
            # This can be either a worker failure or an interruption delivered
            # to the caller while it waits. Signal a partially initialized
            # worker in both cases, but never replace the original exception
            # with an unbounded join.
            self._signal_stop()
            self._join_server_thread(raise_on_timeout=False)
            raise

        # Exit the server thread when the main process exits. This would happen
        # automatically, but is nice to do explicitly to avoid some nanobind
        # reference leak warnings.
        atexit.register(self.stop)

        # Broadcast buffer should be populated by the background worker.
        assert isinstance(self._broadcast_buffer, AsyncMessageBuffer)

    def _signal_stop(self) -> None:
        """Request shutdown without waiting for the worker thread."""
        self._stop_requested.set()

        event_loop = self._background_event_loop
        stop_event = self._stop_event
        if event_loop is not None and stop_event is not None:
            try:
                event_loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                # Event loop may already be closed during teardown.
                pass

        # Clean up message buffers if startup reached far enough to create
        # them. Besides waking producers, this avoids pending-task warnings.
        broadcast_buffer = getattr(self, "_broadcast_buffer", None)
        if isinstance(broadcast_buffer, AsyncMessageBuffer):
            broadcast_buffer.set_done()
        for client in list(self._client_state_from_id.values()):
            client.message_buffer.set_done()

    def _join_server_thread(self, *, raise_on_timeout: bool) -> bool:
        """Join the worker when called off-thread; return whether it stopped."""
        server_thread = self._server_thread
        if server_thread is None or not server_thread.is_alive():
            return True
        if threading.current_thread() is server_thread:
            return False

        server_thread.join(timeout=_SERVER_STOP_TIMEOUT_SECONDS)
        if not server_thread.is_alive():
            return True

        message = (
            f"Leika server thread did not stop within {_SERVER_STOP_TIMEOUT_SECONDS:g} seconds."
        )
        if raise_on_timeout:
            raise RuntimeError(message)
        logging.getLogger(__name__).warning(message)
        return False

    def stop(self) -> None:
        """Request shutdown and wait when called outside the server thread.

        An async websocket callback runs on the server thread itself. In that
        case this method only signals shutdown; joining there would deadlock
        (and ``Thread.join()`` rejects a self-join). A later call from another
        thread can safely perform the bounded join.
        """
        # Unregister the atexit handler to prevent double-stop. ``unregister``
        # is deliberately idempotent, so partial startup and repeat calls are
        # safe as well.
        atexit.unregister(self.stop)
        self._signal_stop()
        self._join_server_thread(raise_on_timeout=True)

    def on_client_connect(
        self, cb: Callable[[WebsockClientConnection], None | Coroutine]
    ) -> Callable[[WebsockClientConnection], None | Coroutine]:
        """Attach a callback to run for newly connected clients."""
        self._client_connect_cb.append(cb)
        return cb

    def on_client_disconnect(
        self, cb: Callable[[WebsockClientConnection], None | Coroutine]
    ) -> Callable[[WebsockClientConnection], None | Coroutine]:
        """Attach a callback to run when clients disconnect."""
        self._client_disconnect_cb.append(cb)
        return cb

    @override
    def get_message_buffer(self) -> AsyncMessageBuffer:
        """Get the broadcast queue. Message will be sent to all clients."""
        return self._broadcast_buffer

    def flush(self) -> None:
        """Flush the outgoing message buffer for broadcasted messages. Any buffered
        messages will immediately be sent. (by default they are windowed)"""
        self._broadcast_buffer.flush()

    def flush_client(self, client_id: int) -> None:
        """Flush the outgoing message buffer for a particular client. Any buffered
        messages will immediately be sent. (by default they are windowed)"""
        # No-op if client is disconnected.
        client_state = self._client_state_from_id.get(client_id)
        if client_state is not None:
            client_state.message_buffer.flush()

    def register_http_asset(self, path: Path) -> HttpAsset:
        """Serve one file over plain HTTP, and return the URL path it lives at.

        This is for the big constituents of otherwise small payloads -- the
        images a markdown preview refers to, say. Sent inline, they arrive as
        base64 inside a message that nothing can show until all of it is
        there; served here, the message stays small enough to arrive at once,
        and the browser fetches the heavy parts in parallel, progressively,
        the way it loads any page.

        The URL is the content's hash, which is what makes it safe to cache
        forever: a changed file registers as a different URL, so the browser
        revisits nothing and refetches nothing across repeated previews. It
        also names nothing -- neither the path on disk nor anything guessable
        -- and only exact registered names are served, each behind the same
        password gate as the rest of the server.

        Registration hashes the bytes every time. File timestamps cannot prove
        that content is unchanged on every filesystem, while the URL makes a
        content-addressed promise. Serving independently verifies that current
        bytes still match the digest, so a mutable source can never change the
        response under an immutable URL.

        A picture's pixel size comes back with the URL, read out of the same
        bytes the digest was taken from. It lets a document reserve the right
        room for a figure before the figure arrives; ``None`` for anything
        whose header does not declare one.

        Raises ``OSError`` if the file cannot be read, which is also the
        moment the caller still knows what the URL was standing in for.
        """
        # Resolve once: HTTP requests may be served after the process changes
        # working directory, but a registered source must keep its identity.
        path = path.resolve()
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        # Read from the bytes already in hand for the hash, so knowing the
        # shape of a picture costs nothing over not knowing it.
        pixel_size = image_pixel_size(content)
        name = f"{digest}{path.suffix.lower()}"
        with self._http_assets_lock:
            # Equal content has one URL even when it came from several paths.
            # Retain every backing path so a later duplicate cannot shorten an
            # earlier registration's lifetime merely by changing or vanishing.
            previous = self._http_assets.pop(name, None)
            paths = list(previous[0]) if previous is not None else []
            with contextlib.suppress(ValueError):
                paths.remove(path)
            paths.append(path)
            if len(paths) > _HTTP_ASSET_BACKING_LIMIT:
                del paths[:-_HTTP_ASSET_BACKING_LIMIT]
            # Re-registration also refreshes this content key's eviction order.
            self._http_assets[name] = (tuple(paths), digest)
            while len(self._http_assets) > _HTTP_ASSET_LIMIT:
                del self._http_assets[next(iter(self._http_assets))]
        return HttpAsset(f"{_HTTP_ASSET_URL_PREFIX}{name}", pixel_size)

    def _background_worker(self, startup: Future[None]) -> None:
        import rich

        host = self._host
        port = self._port
        message_class = self._message_class
        http_server_root = self._http_server_root
        auth_guard = self._auth_guard

        # Need to make a new event loop for notebook compatibility.
        event_loop = asyncio.new_event_loop()

        def close_event_loop() -> None:
            """Cancel loop-owned work and close the loop on every exit path."""
            try:
                pending = asyncio.all_tasks(event_loop)
                for task in pending:
                    task.cancel()
                if pending:
                    event_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                try:
                    event_loop.close()
                finally:
                    asyncio.set_event_loop(None)
                    if self._background_event_loop is event_loop:
                        self._background_event_loop = None
                        self._stop_event = None

        try:
            asyncio.set_event_loop(event_loop)
            self._stop_event = asyncio.Event()
            self._background_event_loop = event_loop
            self._broadcast_buffer = AsyncMessageBuffer(event_loop, persistent_messages=True)
            if self._stop_requested.is_set():
                self._stop_event.set()
            count_lock = asyncio.Lock()
        except BaseException:
            close_event_loop()
            raise

        connection_count = 0
        total_connections = 0

        async def ws_handler(
            connection: websockets.asyncio.server.ServerConnection,
        ) -> None:
            """Handler for websocket connections."""
            async with count_lock:
                nonlocal connection_count
                client_id = ClientId(connection_count)
                connection_count += 1

                nonlocal total_connections
                total_connections += 1

            # Version and protocol check to make sure Leika server/client match.
            import leika
            import leika._messages

            from ._typescript_interface_gen import protocol_fingerprint

            # Both halves of the client's identification, `leika-vX.Y.Z+pHASH`.
            client_version_str = "unknown"
            client_protocol = "unknown"
            if connection.subprotocol is not None:
                if connection.subprotocol.startswith("leika-v"):
                    token = connection.subprotocol[len("leika-v") :].strip()
                    client_version_str, _, client_protocol = token.partition("+p")

            server_protocol = protocol_fingerprint(leika._messages.Message)
            # A close frame carries at most 123 bytes of reason, so what the
            # PAGE is told is short and what the TERMINAL is told is not. The
            # short one still has to stand on its own: it is the text the
            # browser shows in place of the connection status.
            reason: str | None = None
            detail = ""
            if client_version_str != leika.__version__:
                reason = (
                    f"Version mismatch: client {client_version_str}, server {leika.__version__}."
                )
            elif client_protocol != server_protocol:
                # Same version, different message schema: the two were built
                # from different code. In development that is nearly always a
                # server left running across an edit, and without this check it
                # reaches the user as a page that connects and then breaks on a
                # field one side has never heard of.
                reason = (
                    f"Protocol mismatch: client schema {client_protocol},"
                    f" server {server_protocol}. Restart the server or reload."
                )
                detail = (
                    " The page was built against a different message schema than this"
                    " process is running. Restart the Python program if its code has"
                    " changed, or rebuild the client if the page is the stale one."
                )

            if reason is not None:
                rich.print(f"[bold red](leika)[/bold red] Connection rejected. {reason}{detail}")
                async with count_lock:
                    total_connections -= 1
                await connection.close(1002, reason[:123])
                return  # Exit handler to prevent further processing.

            client_state = _ClientHandleState(
                AsyncMessageBuffer(event_loop, persistent_messages=False)
            )
            client_connection = WebsockClientConnection(client_id, client_state)
            stop_event = self._stop_event
            assert stop_event is not None

            async def run_open_connection() -> None:
                # New-connection callbacks and ordered message I/O share one
                # owned task. A peer close can therefore cancel either phase.
                await _run_callbacks(self._client_connect_cb, client_connection)

                if self._verbose:
                    rich.print(
                        f"[bold](leika)[/bold] Connection opened ({client_id},"
                        f" {total_connections} total),"
                        f" {len(self._broadcast_buffer.message_from_id)} persistent"
                        " messages"
                    )

                async def handle_incoming(message: Message) -> None:
                    # One connection is one ordered stream. Await dispatch so
                    # later messages cannot overtake earlier async handlers.
                    await self._handle_incoming_message(client_id, message)
                    await client_connection._handle_incoming_message(client_id, message)

                await _run_connection_tasks(
                    _message_producer(
                        connection,
                        client_state.message_buffer,
                        client_id,
                    ),
                    _message_producer(
                        connection,
                        self._broadcast_buffer,
                        client_id,
                    ),
                    _message_consumer(connection, handle_incoming, message_class),
                )

            try:
                self._client_state_from_id[client_id] = client_state
                # Transport closure is watched independently of callbacks and
                # ordered dispatch. Server stop is an explicit sibling too, so
                # shutdown never waits for an otherwise-live connection.
                await _run_connection_tasks(
                    run_open_connection(),
                    connection.wait_closed(),
                    stop_event.wait(),
                )
            except (
                websockets.exceptions.ConnectionClosedOK,
                websockets.exceptions.ConnectionClosedError,
            ):
                pass
            finally:
                client_state.message_buffer.set_done()

                # Remove transport state before user teardown. Even a callback
                # that fails or waits forever cannot make this client look live.
                self._client_state_from_id.pop(client_id, None)
                total_connections -= 1

                # Let disconnect cleanup enter once, then cancel it if shutdown
                # is already active or begins while user code is still waiting.
                await _run_callbacks_until_stopped(
                    self._client_disconnect_cb,
                    client_connection,
                    stop_event=stop_event,
                )
                if self._verbose:
                    rich.print(
                        f"[bold](leika)[/bold] Connection closed ({client_id},"
                        f" {total_connections} total)"
                    )

        # Host client on the same port as the websocket.
        file_cache: dict[Path, bytes] = {}
        file_cache_gzipped: dict[Path, bytes] = {}
        file_cache_etags: dict[tuple[Path, bool], str] = {}

        def leika_http_server(
            connection: ServerConnection,
            request: Request,
        ) -> Response | None:
            # The password gate comes first: nothing -- static files or the
            # websocket handshake -- is reachable without authenticating.
            if auth_guard is not None:
                guard_response = auth_guard.process(request)
                if guard_response is not None:
                    return guard_response

            # Ignore websocket packets.
            if request.headers.get("Upgrade") == "websocket":
                return None

            # Runtime-registered assets come before the static tree, and are
            # served whether or not there is one. The lookup is an exact match
            # against names this server handed out -- hex digests, nothing to
            # decode and no path in them -- so there is no traversal to guard.
            url_path = request.path.partition("?")[0]
            if url_path.startswith(_HTTP_ASSET_URL_PREFIX):
                with self._http_assets_lock:
                    asset = self._http_assets.get(url_path[len(_HTTP_ASSET_URL_PREFIX) :])
                payload: bytes | None = None
                if asset is not None:
                    paths, expected_digest = asset
                    # Most recently registered first, falling back to any
                    # equivalent source that still fulfills the immutable URL.
                    for source in reversed(paths):
                        try:
                            candidate = source.read_bytes()
                        except OSError:
                            continue
                        if hashlib.sha256(candidate).hexdigest() == expected_digest:
                            payload = candidate
                            break
                if payload is None:
                    # Every source is absent or changed. Never serve new bytes
                    # under the old content-addressed URL.
                    return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
                return Response(
                    http.HTTPStatus.OK,
                    "OK",
                    Headers(
                        **{
                            "Content-Type": _http_content_type(url_path),
                            "Content-Length": str(len(payload)),
                            # The name is the content's hash, so what this URL
                            # answers can never change; the browser may keep it
                            # for as long as it likes and never ask again.
                            "Cache-Control": "private, max-age=31536000, immutable",
                        }
                    ),
                    payload,
                )

            # No files to serve: only the websocket (and the guard above)
            # live on this port.
            if http_server_root is None:
                return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())

            # Normalize and reject traversal before joining the configured
            # root. This is lexical rather than resolve-based because runfile
            # trees may legitimately expose children through independent links.
            relpath = _static_relpath(request.path)
            if relpath is None:
                return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
            assert http_server_root is not None
            source_path = http_server_root / relpath
            # ``is_file()`` (not ``exists()``) so a request resolving to a
            # directory returns a clean 404 instead of raising
            # ``IsADirectoryError`` on ``read_bytes()`` below (-> a 500).
            if not source_path.is_file():
                return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())

            use_gzip = _accepts_gzip(request.headers.get_all("Accept-Encoding"))

            mime_type = _http_content_type(relpath)

            if source_path not in file_cache:
                file_cache[source_path] = source_path.read_bytes()
            if use_gzip:
                if source_path not in file_cache_gzipped:
                    file_cache_gzipped[source_path] = gzip.compress(
                        file_cache[source_path], mtime=0
                    )
                response_payload = file_cache_gzipped[source_path]
            else:
                response_payload = file_cache[source_path]

            cache_key = (source_path, use_gzip)
            if cache_key not in file_cache_etags:
                digest = hashlib.sha256(response_payload).hexdigest()
                file_cache_etags[cache_key] = f'"{digest}"'
            etag = file_cache_etags[cache_key]
            cache_headers = {
                "Cache-Control": "no-cache",
                "ETag": etag,
                "Vary": "Accept-Encoding",
            }

            etag_matches = False
            for value in request.headers.get_all("If-None-Match"):
                # Comma-splitting technically mis-parses entity-tags that
                # contain commas; ours never do, and a foreign ETag can only
                # produce a harmless 200 instead of a 304.
                for candidate in value.split(","):
                    candidate = candidate.strip()
                    if candidate.startswith("W/"):
                        candidate = candidate[2:]
                    if candidate in ("*", etag):
                        etag_matches = True
                        break
                if etag_matches:
                    break
            if etag_matches:
                return Response(
                    http.HTTPStatus.NOT_MODIFIED,
                    "NOT MODIFIED",
                    websockets.datastructures.Headers(**cache_headers),
                )

            response_headers = {
                **cache_headers,
                "Content-Type": mime_type,
                "Content-Length": str(len(response_payload)),
                "Content-Encoding": "gzip" if use_gzip else "identity",
            }

            # Try to read + send over file.
            return Response(
                http.HTTPStatus.OK,
                "OK",
                websockets.datastructures.Headers(**response_headers),
                response_payload,
            )

        async def start_server() -> None:
            port_attempt = port
            for _ in range(1000):
                try:
                    async with websockets.asyncio.server.serve(
                        ws_handler,
                        host,
                        port_attempt,
                        logger=_WEBSOCKET_LOGGER,
                        # Increase ws message size limit to 50MB to allow large messages.
                        # for large pane images.
                        max_size=50 * 1024 * 1024,
                        # Compression can be too slow for our use cases.
                        compression=None,
                        # The handler also serves runtime-registered assets;
                        # keep it installed even without a static root or auth.
                        process_request=leika_http_server,
                        # Accept connections with version-based protocol and extract version in handler.
                        subprotocols=None,
                        select_subprotocol=lambda _, subprotocols: next(
                            (Subprotocol(p) for p in subprotocols if p.startswith("leika-v")),
                            None,
                        ),
                    ) as serve_future:
                        assert serve_future.server is not None
                        # Read the bound port back off the socket rather than
                        # trusting the requested one: port=0 asks the OS to
                        # pick an ephemeral port, and callers need the real
                        # one to build a URL.
                        sockets = serve_future.server.sockets
                        self._port = sockets[0].getsockname()[1] if sockets else port_attempt
                        startup.set_result(None)
                        assert self._stop_event is not None
                        await self._stop_event.wait()
                        return
                except OSError:
                    # Binding failures are retryable. Once readiness has been
                    # reported, an OSError belongs to the running server and
                    # must escape rather than masquerading as another collision.
                    if startup.done():
                        raise
                    port_attempt += 1
                    continue
            # Every attempt failed: wake the waiting `start()` with the error.
            startup.set_exception(
                RuntimeError(f"Could not bind a port: tried {port} through {port_attempt - 1}.")
            )

        try:
            event_loop.run_until_complete(start_server())
            rich.print("[bold](leika)[/bold] Server stopped")
        finally:
            # Own the loop for every exit path, including a bind/setup failure
            # and an exception after readiness. No task or exception is left
            # attached to a closed worker thread.
            close_event_loop()


# Pre-allocated padding bytes for 8-byte alignment.
_ALIGNMENT_PADDING = tuple(b"\x00" * i for i in range(8))


def _append_aligned_buffers(
    parts: list[bytes | memoryview],
    binary_buffers: list[memoryview],
    current_offset: int,
) -> None:
    """Append binary buffers to `parts` with 8-byte alignment padding."""
    for buf in binary_buffers:
        padding = (8 - (current_offset % 8)) % 8
        if padding:
            parts.append(_ALIGNMENT_PADDING[padding])
            current_offset += padding
        parts.append(buf)
        current_offset += buf.nbytes


async def _run_connection_tasks(*awaitables: Awaitable[object]) -> None:
    """Run a connection's tasks until one exits, then retire every sibling."""
    tasks = tuple(asyncio.ensure_future(awaitable) for awaitable in awaitables)
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Inspect completed tasks in declaration order so simultaneous
        # failures have deterministic reporting.
        for task in tasks:
            if task in done:
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_callbacks_until_stopped(
    callbacks: Iterable[Callable[..., object]],
    *args: object,
    stop_event: asyncio.Event,
) -> None:
    """Own disconnect callbacks and cancel them when server shutdown begins."""
    callback_task = asyncio.ensure_future(_run_callbacks(callbacks, *args))
    try:
        # Give synchronous cleanup and the active callback's pre-await prologue
        # one turn even when shutdown was already requested. High-level client
        # registries are cleared in that prologue before user code is entered.
        await asyncio.sleep(0)
        if callback_task.done():
            callback_task.result()
            return
        await _run_connection_tasks(callback_task, stop_event.wait())
    finally:
        callback_task.cancel()
        await asyncio.gather(callback_task, return_exceptions=True)


async def _message_producer(
    websocket: ServerConnection,
    buffer: AsyncMessageBuffer,
    client_id: int,
) -> None:
    """Infinite loop to broadcast windows of messages from a buffer.

    Wire format (hybrid zstd-compressed msgpack + raw binary buffers):
    - Binary arrays (numpy) are extracted from messages and replaced with
      tagged placeholder dicts so msgpack.encode() doesn't walk large arrays.
    - Raw binary data is appended uncompressed after the zstd-compressed
      msgpack, with 8-byte alignment padding.
    - On the JS side, typed array views (Float32Array, etc.) are created
      directly into the WebSocket's ArrayBuffer -- zero-copy for binary data.

    Binary data is left uncompressed because float/int arrays (point clouds,
    meshes) compress poorly, and at 30-60fps the zstd compress+decompress
    cost adds up. Zero-copy is more valuable than modest compression.

    Layout:
      [8 bytes] decompressed size of msgpack (little-endian uint64)
      [8 bytes] compressed size of msgpack (little-endian uint64)
      [N bytes] zstd-compressed msgpack payload
      [P bytes] padding to 8-byte alignment
      [M bytes] concatenated binary buffers (each 8-byte aligned)
    """
    window_generator = buffer.window_generator(client_id)
    zstd = zstandard.ZstdCompressor(level=1)
    while not buffer.done:
        try:
            outgoing = await window_generator.__anext__()
        except StopAsyncIteration:
            break

        binary_buffers: list[memoryview] = []
        serialized_messages = tuple(
            message.as_serializable_dict(binary_buffers) for message in outgoing
        )
        inner = msgspec.msgpack.encode(
            {
                "messages": serialized_messages,
                "timestampSec": time.perf_counter(),
                "binaryBufferLengths": tuple(b.nbytes for b in binary_buffers),
            }
        )
        compressed = zstd.compress(inner)

        parts: list[bytes | memoryview] = [
            len(inner).to_bytes(8, "little"),
            len(compressed).to_bytes(8, "little"),
            compressed,
        ]
        _append_aligned_buffers(parts, binary_buffers, 16 + len(compressed))
        await websocket.send(b"".join(parts))


async def _message_consumer(
    websocket: ServerConnection,
    handle_message: Callable[[Message], Awaitable[None]],
    message_class: type[Message],
) -> None:
    """Receive and fully dispatch each incoming message in wire order."""
    while True:
        raw = await websocket.recv()
        assert isinstance(raw, bytes)
        message = message_class.deserialize(raw)
        await handle_message(message)
