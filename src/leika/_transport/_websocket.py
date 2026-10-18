"""WebSocket and HTTP server on one port: connections, dispatch and framing."""

from __future__ import annotations

import abc
import asyncio
import atexit
import contextlib
import dataclasses
import http
import itertools
import logging
import threading
from collections.abc import Awaitable, Callable, Coroutine, Generator, Iterable, Sequence
from concurrent.futures import Future
from pathlib import Path
from typing import NewType, TypeVar, cast

import msgspec.msgpack
import websockets.exceptions
import websockets.legacy.server
import zstandard
from typing_extensions import override
from websockets import Headers
from websockets.headers import parse_subprotocol
from websockets.http11 import Request
from websockets.legacy.server import WebSocketServerProtocol
from websockets.typing import Subprotocol

from .._async_errors import await_callback_result, print_async_exception
from .._messages import Message, decode_message
from ._auth import HttpPasswordGuard
from ._http import HttpRequestHandler
from ._http_assets import HttpAsset, HttpAssetRegistry
from ._http_security import HttpRequestPolicy
from ._message_buffer import AsyncMessageBuffer
from ._typescript import protocol_fingerprint
from ._viser_proxy import VISER_PROXY_PREFIX, ViserProxy


class _WebsocketLogFilter(logging.Filter):
    """Hide the expected rejection used to serve ordinary HTTP responses."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage() != "connection rejected (200 OK)"


_WEBSOCKET_LOGGER = logging.getLogger("leika.websockets")
_WEBSOCKET_LOGGER.addFilter(_WebsocketLogFilter())

_SERVER_STOP_TIMEOUT_SECONDS = 10.0
_INCOMING_MESSAGE_LIMIT_BYTES = 4 * 1024 * 1024
_INCOMING_MESSAGE_QUEUE_LIMIT = 4
_MAX_ACTIVE_CONNECTIONS = 128

ClientId = NewType("ClientId", int)
TMessage = TypeVar("TMessage", bound=Message)


@dataclasses.dataclass
class _ClientHandleState:
    # Internal state for ClientConnection objects.
    message_buffer: AsyncMessageBuffer
    persistent_message_buffer: AsyncMessageBuffer


async def _run_callback(callback: Callable[..., object], *args: object) -> None:
    """Run one callback without letting its failure suppress later peers."""
    try:
        await await_callback_result(callback(*args))
    except Exception as error:
        # Cancellation passes through: a peer close or server shutdown must
        # still retire in-flight work.
        print_async_exception(error)


class WebsockMessageHandler:
    """Message handlers and outgoing queue of a server or one connection."""

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
        self._incoming_handlers.setdefault(message_cls, []).append(
            cast(Callable[[ClientId, Message], None | Coroutine], callback)
        )

    async def _handle_incoming_message(self, client_id: ClientId, message: Message) -> None:
        """Run handlers in registration order."""
        for callback in tuple(self._incoming_handlers.get(type(message), ())):
            await _run_callback(callback, client_id, message)

    @abc.abstractmethod
    def get_message_buffer(self) -> AsyncMessageBuffer: ...

    def queue_message(self, message: Message) -> bool:
        """Queue a message and report whether the connection is still open."""
        return self.get_message_buffer().push(message)

    def queue_message_or_raise(self, message: Message) -> None:
        """Queue a state message, or fail on a closed connection so callers
        never commit state the browser will not receive."""
        if not self.queue_message(message):
            raise RuntimeError("cannot queue a message on a closed connection")

    def queue_messages_or_raise(self, messages: Sequence[Message]) -> None:
        """Queue related state messages together, or fail as one operation."""
        if not self.get_message_buffer().push_many(messages):
            raise RuntimeError("cannot queue messages on a closed connection")

    def queue_reserved_file_message(self, message: Message, size: int) -> bool:
        """Queue a file part tied to capacity already reserved for it."""
        return self.get_message_buffer().push_reserved_file_message(message, size)

    @contextlib.contextmanager
    def atomic(self) -> Generator[None, None, None]:
        """Hold outgoing delivery until the outermost context exits.

        Queued messages keep their order and are then sent in one or more
        windows. This is a timing constraint, not a browser-side transaction.
        """
        buffer = self.get_message_buffer()
        buffer.atomic_start()
        try:
            yield
        finally:
            buffer.atomic_end()


class WebsockClientConnection(WebsockMessageHandler):
    """Handlers and outgoing queue of one connected client."""

    def __init__(self, client_id: ClientId, client_state: _ClientHandleState) -> None:
        self.client_id = client_id
        self._state = client_state
        super().__init__()

    @override
    def get_message_buffer(self) -> AsyncMessageBuffer:
        return self._state.message_buffer

    def request_delivery_scope(
        self, scope: str, begin_message: Message, ready_message: Message
    ) -> bool:
        """Replace the retained delivery scope for this connection."""
        return self._state.persistent_message_buffer.request_delivery_scope(
            self.client_id, scope, begin_message, ready_message
        )

    def delivery_scope(self) -> str | None:
        """This connection's latest requested retained scope."""
        return self._state.persistent_message_buffer.delivery_scope_from_client(self.client_id)


class WebsockServer(WebsockMessageHandler):
    """Serve Leika's client, assets and WebSocket protocol on one port.

    Messages queued on the server are retained and sent to every client;
    ``on_connect`` and ``on_disconnect`` run for each client in order with
    its traffic. The caller validates the arguments.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        on_connect: Callable[[WebsockClientConnection], Awaitable[None]],
        on_disconnect: Callable[[WebsockClientConnection], Awaitable[None]],
        index_html: Path | None = None,
        verbose: bool = True,
        password: str | None = None,
        allowed_hosts: frozenset[str] = frozenset(),
        allow_embedding: bool = False,
    ) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._index_html = index_html
        self._verbose = verbose
        self._http_policy = HttpRequestPolicy(host, allowed_hosts, allow_embedding=allow_embedding)
        self._auth_guard = HttpPasswordGuard(password) if password is not None else None
        self._viser_proxy = ViserProxy(protected=password is not None)
        self._http_asset_registry = HttpAssetRegistry()
        self._client_state_from_id: dict[int, _ClientHandleState] = {}
        self._client_state_lock = threading.Lock()
        # The loop and the retained broadcast queue exist before the server
        # listens, so the application can queue its initial state first.
        self._background_event_loop: asyncio.AbstractEventLoop | None = asyncio.new_event_loop()
        self._broadcast_buffer = AsyncMessageBuffer(
            self._background_event_loop, persistent_messages=True
        )
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = threading.Event()
        self._server_thread: threading.Thread | None = None

    def trust_proxy_host(self, host: str) -> None:
        """Trust forwarded origin metadata only for one exact proxy hostname."""
        self._http_policy.trust_proxy_host(host)

    def start(self) -> None:
        """Start the one-shot server thread and wait until it is listening."""
        if self._server_thread is not None:
            raise RuntimeError("WebsockServer instances can only be started once.")
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
        try:
            startup.result()
        except BaseException:
            self.signal_stop()
            self._server_thread.join(timeout=_SERVER_STOP_TIMEOUT_SECONDS)
            raise
        atexit.register(self.stop)

    def signal_stop(self) -> None:
        """Request shutdown without waiting for the server thread."""
        self._stop_requested.set()
        self._http_asset_registry.close()
        event_loop = self._background_event_loop
        stop_event = self._stop_event
        if event_loop is not None and stop_event is not None:
            try:
                event_loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                # The event loop may already be closed during teardown.
                pass

    def stop(self) -> None:
        """Request shutdown and wait for the server thread to finish."""
        atexit.unregister(self.stop)
        self.signal_stop()
        server_thread = self._server_thread
        if server_thread is None:
            # Never started: release the loop created with the server.
            event_loop, self._background_event_loop = self._background_event_loop, None
            if event_loop is not None:
                self._broadcast_buffer.set_done()
                event_loop.close()
            return
        if threading.current_thread() is server_thread:
            return
        server_thread.join(timeout=_SERVER_STOP_TIMEOUT_SECONDS)
        if server_thread.is_alive():
            raise RuntimeError(
                f"Leika server thread did not stop within {_SERVER_STOP_TIMEOUT_SECONDS:g} seconds."
            )

    @override
    def get_message_buffer(self) -> AsyncMessageBuffer:
        """The retained broadcast queue, sent to every client."""
        return self._broadcast_buffer

    def flush(self) -> None:
        """Send pending broadcast messages without waiting out the batching
        delay; this doesn't wait for any browser to receive them."""
        self._broadcast_buffer.flush()

    def flush_client(self, client_id: int) -> None:
        """Send one client's pending messages without the batching delay."""
        with self._client_state_lock:
            client_state = self._client_state_from_id.get(client_id)
        if client_state is not None:
            client_state.message_buffer.flush()

    def register_http_asset(self, path: Path) -> HttpAsset:
        """Serve an immutable snapshot of one file under its content hash."""
        return self._http_asset_registry.register(path)

    def _background_worker(self, startup: Future[None]) -> None:
        # A loop of its own keeps notebooks, which run theirs, working.
        event_loop = cast(asyncio.AbstractEventLoop, self._background_event_loop)
        asyncio.set_event_loop(event_loop)
        self._stop_event = asyncio.Event()
        # Checked after publishing the loop and event, so a concurrent
        # signal_stop() is never lost.
        if self._stop_requested.is_set():
            self._stop_event.set()
        try:
            self._serve_until_stopped(startup)
        finally:
            self._broadcast_buffer.set_done()
            with self._client_state_lock:
                client_states = tuple(self._client_state_from_id.values())
            for client_state in client_states:
                client_state.message_buffer.set_done()
            try:
                event_loop.run_until_complete(self._viser_proxy.close())
                pending = asyncio.all_tasks(event_loop)
                for task in pending:
                    task.cancel()
                event_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                event_loop.close()
                asyncio.set_event_loop(None)
                self._background_event_loop = None
                self._incoming_handlers.clear()

    def _serve_until_stopped(self, startup: Future[None]) -> None:
        import rich

        event_loop = cast(asyncio.AbstractEventLoop, self._background_event_loop)
        http_handler = HttpRequestHandler(
            index_html=self._index_html,
            assets=self._http_asset_registry,
            policy=self._http_policy,
            auth_guard=self._auth_guard,
            viser_proxy=self._viser_proxy,
        )
        client_ids = itertools.count()
        active_client_ids: set[ClientId] = set()
        leika_subprotocol = f"leika-{protocol_fingerprint()}"

        class Protocol(WebSocketServerProtocol):
            """Leika's HTTP and subprotocol hooks on the shared WebSockets API."""

            async def process_request(
                self, path: str, request_headers: Headers
            ) -> tuple[http.HTTPStatus, Headers, bytes] | None:
                response = await http_handler.response_for(Request(path, request_headers))
                if response is None:
                    return None
                return (
                    http.HTTPStatus(response.status_code),
                    response.headers,
                    bytes(response.body or b""),
                )

            def write_http_response(
                self, status: http.HTTPStatus, headers: Headers, body: bytes | None = None
            ) -> None:
                # This covers ordinary HTTP, upgrades and upstream handshake errors.
                http_handler.prepare_headers(status, headers)
                super().write_http_response(status, headers, body)

            def process_subprotocol(
                self, headers: Headers, available_subprotocols: Sequence[Subprotocol] | None
            ) -> Subprotocol | None:
                prefix = "viser-v" if self.path.startswith(VISER_PROXY_PREFIX) else "leika-"
                offered = (
                    protocol
                    for value in headers.get_all("Sec-WebSocket-Protocol")
                    for protocol in parse_subprotocol(value)
                )
                return next((p for p in offered if p.startswith(prefix)), None)

        async def serve_client(connection: WebSocketServerProtocol, client_id: ClientId) -> None:
            # The subprotocol names the schema and package version the page
            # was built from; a page that can't read this server's messages is
            # turned away with the reason.
            if connection.subprotocol != leika_subprotocol:
                offered = (connection.subprotocol or "leika-unknown")[len("leika-") :]
                reason = (
                    f"Protocol mismatch: client {offered}, server {leika_subprotocol[6:]}."
                    " Restart the server or reload."
                )
                rich.print(
                    f"[bold red](leika)[/bold red] Connection rejected. {reason} The page was"
                    " built from different code than this process is running. Restart the"
                    " Python program if its code changed, or rebuild the client if the page is"
                    " the stale one."
                )
                await connection.close(1002, reason[:123])
                return

            stop_event = cast(asyncio.Event, self._stop_event)
            client_state = _ClientHandleState(
                AsyncMessageBuffer(event_loop, persistent_messages=False),
                self._broadcast_buffer,
            )
            client_connection = WebsockClientConnection(client_id, client_state)
            # Register before connection callbacks can queue removals: this
            # client needs each one until its websocket has sent past it.
            self._broadcast_buffer.register_client(client_id)

            async def run_open_connection() -> None:
                await _run_callback(self._on_connect, client_connection)
                if self._verbose:
                    rich.print(
                        f"[bold](leika)[/bold] Connection opened ({client_id},"
                        f" {len(active_client_ids)} total),"
                        f" {len(self._broadcast_buffer)} persistent messages"
                    )

                async def handle_incoming(message: Message) -> None:
                    # One connection is one ordered stream: await dispatch so
                    # later messages cannot overtake earlier async handlers.
                    await self._handle_incoming_message(client_id, message)
                    await client_connection._handle_incoming_message(client_id, message)

                await _run_connection_tasks(
                    _message_producer(connection, client_state.message_buffer, client_id),
                    _message_producer(connection, self._broadcast_buffer, client_id),
                    _message_consumer(connection, handle_incoming),
                )

            try:
                with self._client_state_lock:
                    self._client_state_from_id[client_id] = client_state
                # Peer close and server stop are siblings of the connection's
                # work, so neither waits for an otherwise-live connection.
                await _run_connection_tasks(
                    run_open_connection(), connection.wait_closed(), stop_event.wait()
                )
            except websockets.exceptions.ConnectionClosed:
                pass
            finally:
                client_state.message_buffer.set_done()
                self._broadcast_buffer.unregister_client(client_id)
                with self._client_state_lock:
                    self._client_state_from_id.pop(client_id, None)
                await _run_until_stopped(
                    _run_callback(self._on_disconnect, client_connection), stop_event
                )
                if self._verbose:
                    rich.print(
                        f"[bold](leika)[/bold] Connection closed ({client_id},"
                        f" {len(active_client_ids - {client_id})} total)"
                    )

        async def ws_handler(connection: WebSocketServerProtocol) -> None:
            if len(active_client_ids) >= _MAX_ACTIVE_CONNECTIONS:
                await connection.close(1013, "Server connection capacity reached")
                return
            client_id = ClientId(next(client_ids))
            active_client_ids.add(client_id)
            try:
                if connection.path.startswith(VISER_PROXY_PREFIX):
                    await self._viser_proxy.websocket(connection)
                else:
                    await serve_client(connection, client_id)
            finally:
                active_client_ids.discard(client_id)

        async def serve() -> None:
            # Bind exactly the requested port; port=0 lets the OS choose.
            async with websockets.legacy.server.serve(
                ws_handler,
                self._host,
                self._port,
                create_protocol=Protocol,
                logger=_WEBSOCKET_LOGGER,
                # Bounds what browsers send. Uploads arrive in 512 KiB parts.
                max_size=_INCOMING_MESSAGE_LIMIT_BYTES,
                max_queue=_INCOMING_MESSAGE_QUEUE_LIMIT,
                # Compression costs more time than it saves for these payloads.
                compression=None,
            ) as running_server:
                ports = {socket.getsockname()[1] for socket in running_server.sockets}
                if len(ports) != 1:
                    raise RuntimeError(
                        "host resolved to listeners with different ephemeral ports; "
                        "bind an IP literal when using port=0"
                    )
                self._port = ports.pop()
                startup.set_result(None)
                await cast(asyncio.Event, self._stop_event).wait()

        event_loop.run_until_complete(serve())
        if self._verbose:
            rich.print("[bold](leika)[/bold] Server stopped")


async def _run_connection_tasks(*awaitables: Awaitable[object]) -> None:
    """Run a connection's tasks until one exits, then retire every sibling."""
    tasks = tuple(asyncio.ensure_future(awaitable) for awaitable in awaitables)
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Inspect completed tasks in declaration order so simultaneous
        # failures are reported deterministically.
        for task in tasks:
            if task in done:
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_until_stopped(awaitable: Awaitable[object], stop_event: asyncio.Event) -> None:
    """Run disconnect cleanup, cancelling it once server shutdown begins."""
    task = asyncio.ensure_future(awaitable)
    try:
        # Give the cleanup one turn even when shutdown was already requested,
        # so client registries are released before user code is cancelled.
        await asyncio.sleep(0)
        if not task.done():
            await _run_connection_tasks(task, stop_event.wait())
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _frame(compressor: zstandard.ZstdCompressor, encoded: Iterable[bytes]) -> bytes:
    """Frame already-encoded messages without decoding or re-encoding them.

    Layout: the decompressed size as a little-endian uint64, then a zstd
    frame of the MessagePack array of messages.
    """
    payload = msgspec.msgpack.encode([msgspec.Raw(data) for data in encoded])
    return len(payload).to_bytes(8, "little") + compressor.compress(payload)


async def _message_producer(
    websocket: WebSocketServerProtocol, buffer: AsyncMessageBuffer, client_id: int
) -> None:
    """Send one buffer's windows to one client until either closes.

    Messages are encoded once when queued, so a broadcast is serialized once
    for all clients. After each send the producer waits for the peer's pong:
    send() may only copy into a socket buffer, and the pong proves the frame
    arrived. Pending updates keep coalescing meanwhile, so a slow link gets
    fewer, newer frames instead of a backlog. Each connection's two producers
    wait independently; a slow browser holds back no other client.
    """
    compressor = zstandard.ZstdCompressor(level=1)
    windows = buffer.window_generator(client_id)
    try:
        async for window in windows:
            try:
                await websocket.send(
                    _frame(compressor, (record.data for record in window.messages))
                )
                await (await websocket.ping())
                buffer.mark_messages_sent(client_id, window.last_message_id)
            finally:
                if window.file_parts:
                    buffer.release_file_bytes(window.file_bytes, window.file_parts)
    finally:
        await windows.aclose()


async def _message_consumer(
    websocket: WebSocketServerProtocol, handle_message: Callable[[Message], Awaitable[None]]
) -> None:
    """Receive and fully dispatch each valid incoming message in wire order."""
    while True:
        raw = await websocket.recv()
        if not isinstance(raw, bytes):
            await websocket.close(1003, "Binary protocol messages are required.")
            return
        try:
            message = decode_message(raw)
        except Exception:
            # Malformed input closes only its own connection.
            await websocket.close(1007, "Invalid protocol message.")
            return
        await handle_message(message)
