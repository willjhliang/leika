from __future__ import annotations

import abc
import asyncio
import atexit
import contextlib
import dataclasses
import logging
import os
import threading
import time
from collections.abc import Awaitable, Coroutine, Iterable, Sequence
from concurrent.futures import Future
from pathlib import Path
from typing import (
    Callable,
    Generator,
    NewType,
    TypeVar,
    cast,
)

import msgspec.msgpack
import websockets.asyncio.server
import websockets.datastructures
import websockets.exceptions
import zstandard
from typing_extensions import override
from websockets.asyncio.server import ServerConnection
from websockets.typing import Subprotocol

from .._async_errors import (
    await_callback_result,
    in_sync_user_callback,
    print_async_exception,
)
from ._async_message_buffer import (
    _OUTGOING_BINARY_BUFFER_LIMIT,
    _OUTGOING_FRAME_LIMIT_BYTES,
    _OUTGOING_METADATA_LIMIT_BYTES,
    AsyncMessageBuffer,
)
from ._auth import HttpPasswordGuard
from ._http_assets import HttpAsset, HttpAssetRegistry
from ._http_security import HttpRequestPolicy, _canonical_hostname, _normalize_allowed_hosts
from ._http_server import HttpRequestHandler
from ._messages import Message
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
"""Maximum fully admitted websocket connections owned by one server."""
_CALLBACK_REGISTRATION_MAX = 256
"""Maximum callbacks retained by one low-level event source."""


@dataclasses.dataclass
class _ClientHandleState:
    # Internal state for ClientConnection objects.
    message_buffer: AsyncMessageBuffer
    persistent_message_buffer: AsyncMessageBuffer | None = None
    delivery_rate: float | None = None
    prepare_outgoing: Callable[[Sequence[Message]], Awaitable[Sequence[Message]]] | None = None
    rendering_backpressure: bool = False

    def record_delivery(self, size: int, elapsed: float) -> None:
        # Tiny control-only batches measure RTT, not useful bulk throughput.
        if size < 4096 or elapsed <= 0:
            return
        rate = size / elapsed
        prior = self.delivery_rate
        # Smooth time per byte: a prior fast LAN sample must not mask a new
        # slow connection for dozens of large transfers. This also recovers as
        # successful fast receipts replace the old cost, without extra probes.
        self.delivery_rate = rate if prior is None else 1.0 / (0.7 / prior + 0.3 / rate)


ClientId = NewType("ClientId", int)
_CLIENT_ID_MAX = (1 << 53) - 1
TMessage = TypeVar("TMessage", bound=Message)


def _allocate_client_id(
    next_candidate: int, active_client_ids: set[ClientId]
) -> tuple[ClientId, int]:
    """Allocate a collision-free JavaScript-safe ID, wrapping after the max."""
    if not 0 <= next_candidate <= _CLIENT_ID_MAX:
        raise ValueError("next client ID candidate is outside the JavaScript-safe range")
    candidate = next_candidate
    for _ in range(len(active_client_ids) + 1):
        client_id = ClientId(candidate)
        candidate = 0 if candidate == _CLIENT_ID_MAX else candidate + 1
        if client_id not in active_client_ids:
            return client_id, candidate
    raise RuntimeError("no collision-free client ID is available")


async def _run_callback(callback: Callable[..., object], *args: object) -> None:
    """Run one callback without letting its failure suppress later peers."""
    try:
        result = callback(*args)
        await await_callback_result(result)
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
        self._incoming_handlers_lock = threading.RLock()

    def register_handler(
        self,
        message_cls: type[TMessage],
        callback: Callable[[ClientId, TMessage], None | Coroutine],
    ) -> None:
        """Register a handler for a particular message type."""
        if not isinstance(message_cls, type) or not issubclass(message_cls, Message):
            raise TypeError("message_cls must be a Message subclass")
        if not callable(callback):
            raise TypeError("message callback must be callable")
        with self._incoming_handlers_lock:
            if message_cls not in self._incoming_handlers:
                self._incoming_handlers[message_cls] = []
            if len(self._incoming_handlers[message_cls]) >= _CALLBACK_REGISTRATION_MAX:
                raise RuntimeError(
                    f"A message type cannot own more than {_CALLBACK_REGISTRATION_MAX} handlers."
                )
            self._incoming_handlers[message_cls].append(
                cast(Callable[[ClientId, Message], None | Coroutine], callback)
            )

    def unregister_handler(
        self,
        message_cls: type[TMessage],
        callback: Callable[[ClientId, TMessage], None | Coroutine] | None = None,
    ) -> None:
        """Unregister a handler for a particular message type."""
        if not isinstance(message_cls, type) or not issubclass(message_cls, Message):
            raise TypeError("message_cls must be a Message subclass")
        if callback is not None and not callable(callback):
            raise TypeError("message callback must be callable or None")
        with self._incoming_handlers_lock:
            if message_cls not in self._incoming_handlers:
                raise ValueError("Tried to unregister a handler that has not been registered.")
            if callback is None:
                self._incoming_handlers.pop(message_cls)
            else:
                self._incoming_handlers[message_cls].remove(
                    cast(Callable[[ClientId, Message], None | Coroutine], callback)
                )

    async def _handle_incoming_message(self, client_id: ClientId, message: Message) -> None:
        """Handle incoming messages in registration order."""
        with self._incoming_handlers_lock:
            callbacks = tuple(self._incoming_handlers.get(type(message), ()))
        await _run_callbacks(callbacks, client_id, message)

    @abc.abstractmethod
    def get_message_buffer(self) -> AsyncMessageBuffer: ...

    def queue_message(self, message: Message) -> bool:
        """Queue a message and report whether the connection is still open."""
        return self.get_message_buffer().push(message)

    def queue_message_or_raise(self, message: Message) -> None:
        """Queue an ordinary state message or fail on a closed connection.

        Stateful callers commit their local registry only after this returns.
        Treating a closed or overloaded buffer as success would silently leave
        Python and the browser with different state.
        """
        if not self.queue_message(message):
            raise RuntimeError("cannot queue a message on a closed connection")

    def queue_messages_or_raise(self, messages: Sequence[Message]) -> None:
        """Atomically queue related state messages or fail as one operation."""
        if not self.get_message_buffer().push_many(messages):
            raise RuntimeError("cannot queue messages on a closed connection")

    def queue_reserved_file_message(self, message: Message, size: int) -> bool:
        """Queue a file part tied to capacity already reserved for it."""
        return self.get_message_buffer().push_reserved_file_message(message, size)

    @contextlib.contextmanager
    def atomic(self) -> Generator[None, None, None]:
        """Hold outgoing delivery until the outermost context exits.

        Queued messages keep their order and are then emitted in one or more
        transport-bounded windows. This is a soft timing constraint, not a
        browser-side transactional or all-or-nothing commit.

        Returns:
            Context manager.
        """
        # Nested blocks are counted so delivery resumes only after the outermost
        # context exits. try/finally ensures an exception raised inside the
        # `with` body still decrements the counter. Otherwise atomic_end() is skipped and the
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

    def request_delivery_scope(
        self,
        scope: str,
        begin_message: Message,
        ready_message: Message,
    ) -> bool:
        """Replace the retained delivery scope for this connection."""

        buffer = self._state.persistent_message_buffer
        if buffer is None:
            raise RuntimeError("connection has no persistent message buffer")
        return buffer.request_delivery_scope(self.client_id, scope, begin_message, ready_message)

    def delivery_scope(self) -> str | None:
        """Return this connection's latest requested retained scope."""

        buffer = self._state.persistent_message_buffer
        if buffer is None:
            raise RuntimeError("connection has no persistent message buffer")
        return buffer.delivery_scope_from_client(self.client_id)


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
        allowed_hosts: Additional DNS hostnames accepted in HTTP ``Host``
            headers. Wildcard binds accept localhost and IP literals by
            default; DNS, mDNS, and tailnet names require explicit opt-in.
            Entries are hostnames only, without ports; at most 256 may be
            configured. Invalid, duplicate, changing, or oversized sequences
            raise :class:`ValueError` during construction.
        delivery_backpressure: Wait for a WebSocket pong after each outbound
            batch before advancing its producer. Pending updates coalesce while
            slow clients receive earlier bytes. Disabled by default.
        allow_embedding: Opt out of the default ``frame-ancestors 'none'``
            protection when this workspace is intentionally embedded.
    """

    def __init__(
        self,
        host: str,
        port: int,
        message_class: type[Message] = Message,
        http_server_root: Path | None = None,
        verbose: bool = True,
        password: str | None = None,
        allowed_hosts: Sequence[str] | None = None,
        allow_embedding: bool = False,
        delivery_backpressure: bool = False,
    ):
        if type(host) is not str or _canonical_hostname(host) is None:
            raise ValueError("host must be a valid DNS name or IP address.")
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("port must be an integer from 0 to 65535.")
        if not isinstance(message_class, type) or not issubclass(message_class, Message):
            raise TypeError("message_class must be a Message subclass.")
        # Resolve the concrete wire graph before allocating any server state.
        # This rejects duplicate, non-dataclass, or reserved-name leaves at the
        # constructor boundary rather than after the first client frame.
        message_class._subclass_from_type_string()
        if password is not None and type(password) is not str:
            raise TypeError("password must be a string or None.")
        if http_server_root is not None and not isinstance(http_server_root, Path):
            raise TypeError("http_server_root must be a pathlib.Path or None.")
        if http_server_root is not None:
            # Keep the served tree stable if application code later changes cwd.
            # Existence is deliberately checked at request time because the
            # managed client build can be published after construction.
            http_server_root = Path(os.fspath(http_server_root)).resolve()
        if not isinstance(verbose, bool):
            raise TypeError("verbose must be a bool.")
        if not isinstance(allow_embedding, bool):
            raise TypeError("allow_embedding must be a bool.")
        if not isinstance(delivery_backpressure, bool):
            raise TypeError("delivery_backpressure must be a bool.")
        normalized_allowed_hosts = _normalize_allowed_hosts(allowed_hosts)
        super().__init__()

        # Track connected clients.
        self._client_connect_cb: list[Callable[[WebsockClientConnection], None | Coroutine]] = []
        self._client_disconnect_cb: list[Callable[[WebsockClientConnection], None | Coroutine]] = []
        self._client_callback_lock = threading.RLock()

        self._host = host
        self._port = port
        self._allowed_hosts = normalized_allowed_hosts
        self._http_policy = HttpRequestPolicy(
            host, normalized_allowed_hosts, allow_embedding=allow_embedding
        )
        self._message_class = message_class
        self._http_server_root = http_server_root
        self._auth_guard = HttpPasswordGuard(password) if password is not None else None
        self._viser_proxy = ViserProxy(protected=password is not None)
        self._verbose = verbose
        self._delivery_backpressure = delivery_backpressure
        self._background_event_loop: asyncio.AbstractEventLoop | None = None

        self._stop_event: asyncio.Event | None = None
        self._stop_requested = threading.Event()

        self._client_state_from_id: dict[int, _ClientHandleState] = {}
        self._client_state_lock = threading.Lock()
        self._server_thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._lifecycle_state = "new"
        self._callback_activity_lock = threading.Lock()
        self._active_callback_dispatches = 0
        self._stop_finalizer_lock = threading.Lock()
        self._stop_finalizer: threading.Thread | None = None

        self._http_asset_registry = HttpAssetRegistry()

    def trust_proxy_host(self, host: str) -> None:
        """Trust forwarded origin metadata only for one exact proxy hostname."""
        self._http_policy.trust_proxy_host(host)

    def start(self) -> None:
        """Start this one-shot server."""
        # A Future distinguishes failures before the socket is ready from
        # failures after startup. The former belong to this synchronous API;
        # the latter must still escape the worker thread.
        startup: Future[None] = Future()

        def run_worker() -> None:
            try:
                self._background_worker(startup)
            except BaseException as error:
                if not startup.done():
                    startup.set_exception(error)
                    return
                raise

        server_thread = threading.Thread(target=run_worker, daemon=True)
        with self._lifecycle_lock:
            if self._lifecycle_state != "new":
                raise RuntimeError("WebsockServer instances can only be started once.")
            # Publish and launch under one lock. stop() acquires the same lock
            # before signalling, so it cannot return while Thread.start() is
            # paused or before the worker is actually joinable.
            self._stop_requested.clear()
            self._server_thread = server_thread
            self._lifecycle_state = "starting"
            try:
                server_thread.start()
            except BaseException:
                self._lifecycle_state = "stopped"
                raise
            self._lifecycle_state = "started"

        try:
            startup.result()
        except BaseException:
            self._signal_stop()
            self._join_server_thread(raise_on_timeout=False)
            raise

        atexit.register(self.stop)
        if not isinstance(self._broadcast_buffer, AsyncMessageBuffer):
            self.stop()
            raise RuntimeError("server worker started without a broadcast buffer")

    @contextlib.contextmanager
    def _active_callback_dispatch(self) -> Generator[None, None, None]:
        """Mark callback/result work that the server loop is awaiting."""
        with self._callback_activity_lock:
            self._active_callback_dispatches += 1
        try:
            yield
        finally:
            with self._callback_activity_lock:
                self._active_callback_dispatches -= 1

    def _finish_stop(self) -> None:
        """Perform the bounded worker join and release retained callbacks."""
        try:
            self._join_server_thread(raise_on_timeout=False)
        finally:
            with self._client_callback_lock:
                self._client_connect_cb.clear()
                self._client_disconnect_cb.clear()
            with self._incoming_handlers_lock:
                self._incoming_handlers.clear()
            with self._stop_finalizer_lock:
                if self._stop_finalizer is threading.current_thread():
                    self._stop_finalizer = None

    def _start_stop_finalizer(self) -> None:
        """Join outside callback dependency chains, retrying start failures."""
        with self._stop_finalizer_lock:
            if self._stop_finalizer is not None:
                return
            finalizer = threading.Thread(
                target=self._finish_stop,
                name="leika-infra-stop-finalizer",
                daemon=True,
            )
            self._stop_finalizer = finalizer
            try:
                finalizer.start()
            except BaseException:
                self._stop_finalizer = None
                raise

    def _signal_stop(self) -> None:
        """Request shutdown without waiting for the worker thread."""
        self._stop_requested.set()
        self._http_asset_registry.close()

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
        with self._client_state_lock:
            client_states = tuple(self._client_state_from_id.values())
        for client in client_states:
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

        An async websocket callback runs on the server thread itself, while a
        synchronous user callback may run in the callback executor as that
        thread awaits it. A callback may also return an external Future whose
        worker requests shutdown. In each callback-owned context this method
        signals promptly and a short-lived finalizer performs the join, avoiding
        a circular wait. A concurrent caller may therefore observe asynchronous
        completion while callback result work is active.
        """
        # Unregister the atexit handler to prevent double-stop. ``unregister``
        # is deliberately idempotent, so partial startup and repeat calls are
        # safe as well.
        atexit.unregister(self.stop)
        # Wait for a concurrent start() to finish publishing and launching its
        # worker. Never hold this lock while joining: worker teardown takes it.
        with self._lifecycle_lock:
            if self._lifecycle_state == "new":
                self._lifecycle_state = "stopped"
                self._stop_requested.set()
                self._http_asset_registry.close()
                with self._client_callback_lock:
                    self._client_connect_cb.clear()
                    self._client_disconnect_cb.clear()
                with self._incoming_handlers_lock:
                    self._incoming_handlers.clear()
                return
        self._signal_stop()
        with self._callback_activity_lock:
            callback_active = self._active_callback_dispatches > 0
        if (
            threading.current_thread() is self._server_thread
            or in_sync_user_callback()
            or callback_active
        ):
            # A callback may return an external Future whose worker calls stop.
            # Joining here would wait for the loop that is awaiting this worker.
            self._start_stop_finalizer()
            return
        self._join_server_thread(raise_on_timeout=True)
        with self._client_callback_lock:
            self._client_connect_cb.clear()
            self._client_disconnect_cb.clear()
        with self._incoming_handlers_lock:
            self._incoming_handlers.clear()

    def on_client_connect(
        self, cb: Callable[[WebsockClientConnection], None | Coroutine]
    ) -> Callable[[WebsockClientConnection], None | Coroutine]:
        """Attach a callback to run for newly connected clients."""
        if not callable(cb):
            raise TypeError("client connection callback must be callable")
        with self._client_callback_lock:
            if len(self._client_connect_cb) >= _CALLBACK_REGISTRATION_MAX:
                raise RuntimeError(
                    f"A server cannot own more than {_CALLBACK_REGISTRATION_MAX} connect callbacks."
                )
            self._client_connect_cb.append(cb)
        return cb

    def remove_client_connect_callback(
        self,
        callback: Callable[[WebsockClientConnection], None | Coroutine] | None = None,
    ) -> None:
        """Remove one connect callback, or all callbacks when omitted."""
        if callback is not None and not callable(callback):
            raise TypeError("client connection callback must be callable or None")
        with self._client_callback_lock:
            if callback is None:
                self._client_connect_cb.clear()
            else:
                self._client_connect_cb[:] = [
                    existing for existing in self._client_connect_cb if existing != callback
                ]

    def on_client_disconnect(
        self, cb: Callable[[WebsockClientConnection], None | Coroutine]
    ) -> Callable[[WebsockClientConnection], None | Coroutine]:
        """Attach a callback to run when clients disconnect."""
        if not callable(cb):
            raise TypeError("client disconnection callback must be callable")
        with self._client_callback_lock:
            if len(self._client_disconnect_cb) >= _CALLBACK_REGISTRATION_MAX:
                raise RuntimeError(
                    f"A server cannot own more than "
                    f"{_CALLBACK_REGISTRATION_MAX} disconnect callbacks."
                )
            self._client_disconnect_cb.append(cb)
        return cb

    def remove_client_disconnect_callback(
        self,
        callback: Callable[[WebsockClientConnection], None | Coroutine] | None = None,
    ) -> None:
        """Remove one disconnect callback, or all callbacks when omitted."""
        if callback is not None and not callable(callback):
            raise TypeError("client disconnection callback must be callable or None")
        with self._client_callback_lock:
            if callback is None:
                self._client_disconnect_cb.clear()
            else:
                self._client_disconnect_cb[:] = [
                    existing for existing in self._client_disconnect_cb if existing != callback
                ]

    @override
    def get_message_buffer(self) -> AsyncMessageBuffer:
        """Get the broadcast queue. Message will be sent to all clients."""
        return self._broadcast_buffer

    def flush(self) -> None:
        """Request immediate windowing of pending broadcast messages.

        This bypasses the normal batching delay. It doesn't wait for a socket
        send or for any browser to receive or apply the messages.
        """
        self._broadcast_buffer.flush()

    def flush_client(self, client_id: int) -> None:
        """Request immediate windowing of one client's pending messages.

        This is asynchronous and is a no-op if the client has disconnected.
        """
        # No-op if client is disconnected.
        with self._client_state_lock:
            client_state = self._client_state_from_id.get(client_id)
        if client_state is not None:
            client_state.message_buffer.flush()

    def register_http_asset(
        self,
        path: Path,
        *,
        _expected_metadata: os.stat_result | None = None,
        _require_safe_image: bool = False,
    ) -> HttpAsset:
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

        Registration reads and hashes the bytes once. The immutable snapshot is
        retained in a bounded cache, so concurrent requests share one payload
        and a mutable source can never change the response under an old URL.

        A picture's pixel size comes back with the URL, read out of the same
        bytes the digest was taken from. It lets a document reserve the right
        room for a figure before the figure arrives; ``None`` for anything
        whose header does not declare one.

        Raises ``OSError`` if the file cannot be read, which is also the
        moment the caller still knows what the URL was standing in for.
        """
        return self._http_asset_registry.register(
            path,
            _expected_metadata=_expected_metadata,
            _require_safe_image=_require_safe_image,
        )

    def _background_worker(self, startup: Future[None]) -> None:
        import rich

        host = self._host
        port = self._port
        message_class = self._message_class
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
                    with self._lifecycle_lock:
                        self._lifecycle_state = "stopped"

        try:
            asyncio.set_event_loop(event_loop)
            self._stop_event = asyncio.Event()
            self._background_event_loop = event_loop
            self._broadcast_buffer = AsyncMessageBuffer(event_loop, persistent_messages=True)
            if self._stop_requested.is_set():
                self._stop_event.set()
            count_lock = asyncio.Lock()
            http_handler = HttpRequestHandler(
                root=self._http_server_root,
                assets=self._http_asset_registry,
                policy=self._http_policy,
                auth_guard=self._auth_guard,
                viser_proxy=self._viser_proxy,
            )
        except BaseException:
            close_event_loop()
            raise

        import leika._messages

        enforce_leika_subprotocol = message_class is leika._messages.Message
        next_client_id = 0
        active_client_ids: set[ClientId] = set()

        async def _serve_admitted_connection(
            connection: websockets.asyncio.server.ServerConnection,
            client_id: ClientId,
        ) -> None:
            """Run one connection after its active-slot reservation succeeds."""
            # The bundled Leika browser identifies both its package version
            # and generated schema. The low-level infra API is intentionally
            # generic: custom Message roots accept ordinary websocket clients
            # without imposing Leika's private subprotocol.
            if enforce_leika_subprotocol:
                import leika

                from ._typescript_interface_gen import protocol_fingerprint

                client_version_str = "unknown"
                client_protocol = "unknown"
                if connection.subprotocol is not None and connection.subprotocol.startswith(
                    "leika-v"
                ):
                    token = connection.subprotocol[len("leika-v") :].strip()
                    client_version_str, _, client_protocol = token.partition("+p")

                server_protocol = protocol_fingerprint(message_class)
                reason: str | None = None
                detail = ""
                if client_version_str != leika.__version__:
                    reason = (
                        f"Version mismatch: client {client_version_str}, "
                        f"server {leika.__version__}."
                    )
                elif client_protocol != server_protocol:
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
                    rich.print(
                        f"[bold red](leika)[/bold red] Connection rejected. {reason}{detail}"
                    )
                    await connection.close(1002, reason[:123])
                    return

            client_state = _ClientHandleState(
                AsyncMessageBuffer(event_loop, persistent_messages=False),
                self._broadcast_buffer,
            )
            client_connection = WebsockClientConnection(client_id, client_state)
            stop_event = self._stop_event
            if stop_event is None:
                await connection.close(1011, "Server lifecycle error")
                return

            # Register before connection callbacks can queue lifecycle removes.
            # Future clients don't need tombstones, but this client does until
            # its websocket has successfully sent past each one.
            self._broadcast_buffer.register_client(client_id)

            async def run_open_connection() -> None:
                # New-connection callbacks and ordered message I/O share one
                # owned task. A peer close can therefore cancel either phase.
                with self._client_callback_lock:
                    connect_callbacks = tuple(self._client_connect_cb)
                with self._active_callback_dispatch():
                    await _run_callbacks(connect_callbacks, client_connection)

                if self._verbose:
                    async with count_lock:
                        active_count = len(active_client_ids)
                    rich.print(
                        f"[bold](leika)[/bold] Connection opened ({client_id},"
                        f" {active_count} total),"
                        f" {len(self._broadcast_buffer.message_from_id)} persistent"
                        " messages"
                    )

                async def handle_incoming(message: Message) -> None:
                    # One connection is one ordered stream. Await dispatch so
                    # later messages cannot overtake earlier async handlers.
                    with self._active_callback_dispatch():
                        await self._handle_incoming_message(client_id, message)
                        await client_connection._handle_incoming_message(client_id, message)

                await _run_connection_tasks(
                    _message_producer(
                        connection,
                        client_state.message_buffer,
                        client_id,
                        delivery_backpressure=self._delivery_backpressure,
                        client_state=client_state,
                    ),
                    _message_producer(
                        connection,
                        self._broadcast_buffer,
                        client_id,
                        delivery_backpressure=self._delivery_backpressure,
                        client_state=client_state,
                    ),
                    _message_consumer(connection, handle_incoming, message_class),
                )

            try:
                with self._client_state_lock:
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
                self._broadcast_buffer.unregister_client(client_id)

                # Remove transport state before user teardown. Even a callback
                # that fails or waits forever cannot make this client look live.
                with self._client_state_lock:
                    self._client_state_from_id.pop(client_id, None)
                # Let disconnect cleanup enter once, then cancel it if shutdown
                # is already active or begins while user code is still waiting.
                with self._client_callback_lock:
                    disconnect_callbacks = tuple(self._client_disconnect_cb)
                with self._active_callback_dispatch():
                    await _run_callbacks_until_stopped(
                        disconnect_callbacks,
                        client_connection,
                        stop_event=stop_event,
                    )
                if self._verbose:
                    async with count_lock:
                        remaining_count = len(active_client_ids - {client_id})
                    rich.print(
                        f"[bold](leika)[/bold] Connection closed ({client_id},"
                        f" {remaining_count} total)"
                    )

        async def ws_handler(
            connection: websockets.asyncio.server.ServerConnection,
        ) -> None:
            """Admit one bounded websocket connection and release it exactly once."""
            nonlocal next_client_id
            async with count_lock:
                if len(active_client_ids) >= _MAX_ACTIVE_CONNECTIONS:
                    client_id: ClientId | None = None
                else:
                    client_id, next_client_id = _allocate_client_id(
                        next_client_id, active_client_ids
                    )
                    active_client_ids.add(client_id)

            if client_id is None:
                await connection.close(1013, "Server connection capacity reached")
                return
            try:
                if connection.request is not None and connection.request.path.startswith(
                    VISER_PROXY_PREFIX
                ):
                    await self._viser_proxy.websocket(connection)
                else:
                    await _serve_admitted_connection(connection, client_id)
            finally:
                async with count_lock:
                    active_client_ids.discard(client_id)

        async def start_server() -> None:
            # Bind exactly the requested port. Callers that want availability
            # without a race use port=0 and let the OS select it.
            async with websockets.asyncio.server.serve(
                ws_handler,
                host,
                port,
                logger=_WEBSOCKET_LOGGER,
                # This limits inbound client frames. Uploads are paced
                # in 512 KiB parts; server-to-client pane images are not
                # governed by this option.
                max_size=_INCOMING_MESSAGE_LIMIT_BYTES,
                max_queue=_INCOMING_MESSAGE_QUEUE_LIMIT,
                # Compression can be too slow for our use cases.
                compression=None,
                # The handler also serves runtime-registered assets;
                # keep it installed even without a static root or auth.
                process_request=http_handler.process_request,
                process_response=http_handler.process_response,
                # The bundled client negotiates its private version token;
                # custom low-level protocols use normal no-subprotocol sockets.
                subprotocols=None,
                select_subprotocol=(
                    lambda connection, subprotocols: (
                        next(
                            (Subprotocol(p) for p in subprotocols if p.startswith("viser-v")), None
                        )
                        if connection.request is not None
                        and connection.request.path.startswith(VISER_PROXY_PREFIX)
                        else next(
                            (Subprotocol(p) for p in subprotocols if p.startswith("leika-v")),
                            None,
                        )
                        if enforce_leika_subprotocol
                        else None
                    )
                ),
            ) as running_server:
                server = running_server.server
                if server is None:
                    raise RuntimeError("websocket server did not expose its listening socket")
                sockets = server.sockets
                if not sockets:
                    raise RuntimeError("websocket server started without a listening socket")
                ports = {socket.getsockname()[1] for socket in sockets}
                if len(ports) != 1:
                    raise RuntimeError(
                        "host resolved to listeners with different ephemeral ports; "
                        "bind an IP literal when using port=0"
                    )
                self._port = ports.pop()
                startup.set_result(None)
                stop_event = self._stop_event
                if stop_event is None:
                    raise RuntimeError("websocket server stop event was not initialized")
                await stop_event.wait()

        try:
            event_loop.run_until_complete(start_server())
            if self._verbose:
                rich.print("[bold](leika)[/bold] Server stopped")
        finally:
            # Own the loop for every exit path, including a bind/setup failure
            # and an exception after readiness. No task or exception is left
            # attached to a closed worker thread.
            try:
                event_loop.run_until_complete(self._viser_proxy.close())
            finally:
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


def _utf8_size(value: str) -> int:
    """Count UTF-8 bytes with bounded native conversions instead of Python loops."""
    if value.isascii():
        return len(value)
    chunk_size = 64 * 1024
    return sum(
        len(value[start : start + chunk_size].encode("utf-8", errors="surrogatepass"))
        for start in range(0, len(value), chunk_size)
    )


def _metadata_payload_exceeds(value: object, limit: int) -> bool:
    """Cheap lower-bound preflight before msgpack duplicates large payloads."""
    remaining = limit
    stack = [value]
    while stack:
        item = stack.pop()
        if item is None or isinstance(item, bool):
            remaining -= 1
        elif isinstance(item, int):
            # MsgPack integers use between one and nine bytes. This preflight
            # is a lower bound only; charging nine would falsely reject large
            # arrays of compact zeros before exact encoding.
            remaining -= 1
        elif isinstance(item, float):
            remaining -= 9
        elif isinstance(item, str):
            if len(item) > remaining:
                return True
            remaining -= _utf8_size(item)
        elif isinstance(item, (bytes, bytearray, memoryview)):
            remaining -= len(item)
        elif isinstance(item, dict):
            remaining -= 1
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            remaining -= 1
            stack.extend(item)
        else:
            # msgspec owns rejection of unsupported leaf types.
            remaining -= 1
        if remaining < 0:
            return True
    return False


async def _close_oversized_outgoing(websocket: ServerConnection) -> None:
    """Close one client cleanly when its batch exceeds the decoder contract."""
    await websocket.close(1009, "Outgoing message batch exceeds the client size limit.")


async def _message_producer(
    websocket: ServerConnection,
    buffer: AsyncMessageBuffer,
    client_id: int,
    *,
    delivery_backpressure: bool = False,
    client_state: _ClientHandleState | None = None,
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
    try:
        while not buffer.done:
            try:
                window = await window_generator.__anext__()
            except StopAsyncIteration:
                break

            outgoing = window.messages
            reserved_file_bytes = window.file_bytes_reserved
            reserved_file_parts = window.file_parts_reserved
            try:
                if client_state is not None and client_state.prepare_outgoing is not None:
                    outgoing = await client_state.prepare_outgoing(outgoing)
                binary_buffers: list[memoryview] = []
                serialized_messages = tuple(
                    message.as_serializable_dict(binary_buffers) for message in outgoing
                )
                if len(binary_buffers) > _OUTGOING_BINARY_BUFFER_LIMIT:
                    await _close_oversized_outgoing(websocket)
                    return
                # Reject obviously oversized raw arrays before encoding or
                # compressing metadata. Seven bytes is the maximum alignment
                # padding per buffer.
                raw_upper_bound = sum(buffer.nbytes + 7 for buffer in binary_buffers)
                if raw_upper_bound + 16 > _OUTGOING_FRAME_LIMIT_BYTES:
                    await _close_oversized_outgoing(websocket)
                    return
                envelope = {
                    "messages": serialized_messages,
                    "timestampSec": time.perf_counter(),
                    "binaryBufferLengths": tuple(b.nbytes for b in binary_buffers),
                }
                if _metadata_payload_exceeds(envelope, _OUTGOING_METADATA_LIMIT_BYTES):
                    await _close_oversized_outgoing(websocket)
                    return
                inner = msgspec.msgpack.encode(envelope)
                if len(inner) > _OUTGOING_METADATA_LIMIT_BYTES:
                    await _close_oversized_outgoing(websocket)
                    return
                compressed = zstd.compress(inner)

                parts: list[bytes | memoryview] = [
                    len(inner).to_bytes(8, "little"),
                    len(compressed).to_bytes(8, "little"),
                    compressed,
                ]
                _append_aligned_buffers(parts, binary_buffers, 16 + len(compressed))
                frame_size = sum(
                    part.nbytes if isinstance(part, memoryview) else len(part) for part in parts
                )
                if frame_size > _OUTGOING_FRAME_LIMIT_BYTES:
                    await _close_oversized_outgoing(websocket)
                    return
                # websockets sends an iterable of bytes-like objects as one
                # fragmented binary message. This preserves the client wire
                # format while avoiding a frame-sized copy of every ndarray.
                started = time.monotonic()
                await websocket.send(parts)
                if delivery_backpressure or (
                    client_state is not None and client_state.rendering_backpressure
                ):
                    # send() may only copy into an OS socket buffer. A pong
                    # proves the peer received the preceding bytes, keeping
                    # stale updates in our coalescing queue until then.
                    # This is per connection and producer; a slow browser
                    # cannot hold back other clients. Existing connection
                    # keepalive and closure own timeout/cancellation policy.
                    receipt = await websocket.ping()
                    await receipt
                    if client_state is not None:
                        client_state.record_delivery(frame_size, time.monotonic() - started)
                buffer.mark_messages_sent(client_id, window.last_message_id)
            finally:
                if reserved_file_parts:
                    buffer.release_file_bytes(reserved_file_bytes, reserved_file_parts)
            # A quiet connection must not retain its last frame's original,
            # encoded, and compressed payloads while awaiting the next window.
            del window
            del outgoing
            del binary_buffers
            del serialized_messages
            del envelope
            del inner
            del compressed
            del parts
    finally:
        await window_generator.aclose()
        if buffer.overload_reason is not None:
            await websocket.close(1013, buffer.overload_reason[:123])


async def _message_consumer(
    websocket: ServerConnection,
    handle_message: Callable[[Message], Awaitable[None]],
    message_class: type[Message],
) -> None:
    """Receive and fully dispatch each valid incoming message in wire order."""
    while True:
        raw = await websocket.recv()
        if not isinstance(raw, bytes):
            await websocket.close(1003, "Binary protocol messages are required.")
            return
        try:
            message = message_class.deserialize(raw)
        except Exception:
            # Malformed untrusted input closes only its connection and should
            # never escape as a server-thread traceback.
            await websocket.close(1007, "Invalid protocol message.")
            return
        await handle_message(message)
