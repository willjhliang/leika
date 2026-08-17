from __future__ import annotations

import abc
import asyncio
import atexit
import contextlib
import dataclasses
import gzip
import hashlib
import http
import ipaddress
import itertools
import logging
import mimetypes
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Coroutine, Iterable, Sequence
from concurrent.futures import Future
from pathlib import Path, PureWindowsPath
from typing import (
    Callable,
    Generator,
    Iterator,
    NamedTuple,
    NewType,
    Optional,
    Tuple,
    TypeVar,
    cast,
)
from urllib.parse import unquote as _url_unquote
from urllib.parse import urlsplit

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

from .._async_errors import (
    await_callback_result,
    in_sync_user_callback,
    print_async_exception,
)
from .._client_autobuild import _BUILD_BACKUP_DIR_NAME
from .._file_transfer import read_regular_file_snapshot
from ._async_message_buffer import (
    _OUTGOING_BINARY_BUFFER_LIMIT,
    _OUTGOING_FRAME_LIMIT_BYTES,
    _OUTGOING_METADATA_LIMIT_BYTES,
    AsyncMessageBuffer,
)
from ._auth import HttpPasswordGuard
from ._image_headers import image_pixel_size, safe_image_info
from ._messages import Message


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
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Prevent another LAN origin from embedding passwordless media/static
    # responses through no-CORS element loads. Same-origin workspace assets
    # and direct top-level navigation remain available.
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _canonical_hostname(host: str) -> str | None:
    """Normalize one DNS or IP host without accepting authority syntax."""
    if (
        not host
        or host != host.strip()
        or any(ord(c) < 33 or ord(c) == 127 for c in host)
        or any(c in host for c in "/?#@,[]*")
    ):
        return None
    candidate = host[:-1] if host.endswith(".") else host
    candidate = candidate.replace("%25", "%")
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        if ":" in candidate or "%" in candidate:
            return None
        try:
            normalized = candidate.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
        labels = normalized.split(".")
        if not normalized or len(normalized) > 253:
            return None
        for label in labels:
            if (
                not 1 <= len(label) <= 63
                or not label[0].isalnum()
                or not label[-1].isalnum()
                or any(not (c.isdigit() or "a" <= c <= "z" or c == "-") for c in label)
            ):
                return None
        return normalized
    return str(address).lower()


def _parse_authority(authority: str, scheme: str) -> tuple[str, str, int] | None:
    """Parse a Host-style authority into a comparable origin tuple."""
    if not authority or authority != authority.strip() or any(c.isspace() for c in authority):
        return None
    if "," in authority or (authority.count(":") > 1 and not authority.startswith("[")):
        return None
    try:
        parsed = urlsplit(f"{scheme}://{authority}")
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
    ):
        return None
    host = _canonical_hostname(parsed.hostname or "")
    if host is None:
        return None
    return scheme, host, port if port is not None else (443 if scheme == "https" else 80)


def _parse_origin(origin: str) -> tuple[str, str, int] | None:
    """Parse an HTTP browser Origin, rejecting opaque and malformed values."""
    if not origin or origin != origin.strip() or any(c.isspace() for c in origin):
        return None
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in ("http", "https")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != ""
        or parsed.query
        or parsed.fragment
    ):
        return None
    host = _canonical_hostname(parsed.hostname or "")
    if host is None:
        return None
    return (
        parsed.scheme,
        host,
        port if port is not None else (443 if parsed.scheme == "https" else 80),
    )


_ALLOWED_HOSTS_MAX = 256


def _normalize_allowed_hosts(hosts: Sequence[str] | None) -> frozenset[str]:
    if hosts is None:
        return frozenset()
    if isinstance(hosts, str) or not isinstance(hosts, Sequence):
        raise TypeError("allowed_hosts must be a sequence of host names, not one string.")
    reported_length = len(hosts)
    if reported_length > _ALLOWED_HOSTS_MAX:
        raise ValueError(f"allowed_hosts cannot contain more than {_ALLOWED_HOSTS_MAX} entries.")
    materialized = tuple(itertools.islice(iter(hosts), _ALLOWED_HOSTS_MAX + 1))
    if len(materialized) != reported_length:
        raise ValueError("allowed_hosts length changed during validation.")
    normalized: set[str] = set()
    for host in materialized:
        if not isinstance(host, str):
            raise TypeError("allowed_hosts entries must be strings.")
        canonical = _canonical_hostname(host)
        if canonical is None:
            raise ValueError(f"Invalid allowed host: {host!r}.")
        if canonical in normalized:
            raise ValueError(f"Duplicate allowed host: {host!r}.")
        normalized.add(canonical)
    return frozenset(normalized)


def _is_ip_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _direct_host_allowed(request_host: str, bind_host: str, allowed: frozenset[str]) -> bool:
    if request_host in allowed:
        return True
    bind = _canonical_hostname(bind_host)
    try:
        wildcard_bind = bind is not None and ipaddress.ip_address(bind).is_unspecified
    except ValueError:
        wildcard_bind = False
    if wildcard_bind:
        return _is_ip_host(request_host) or request_host == "localhost"
    if bind is None:
        return False
    if _is_loopback_host(bind):
        return _is_loopback_host(request_host)
    return request_host == bind


def _first_forwarded_value(headers: Headers, name: str) -> str | None:
    values = headers.get_all(name)
    if len(values) != 1:
        return None
    if "," in values[0]:
        return None
    return values[0].strip() or None


@dataclasses.dataclass(frozen=True)
class _RequestAddress:
    origin: tuple[str, str, int]
    secure: bool


def _request_address(
    request: Request,
    *,
    bind_host: str,
    allowed_hosts: frozenset[str],
    trusted_proxy_hosts: frozenset[str],
) -> _RequestAddress | None:
    """Validate Host/proxy/Origin and return the browser-visible origin."""
    hosts = request.headers.get_all("Host")
    if len(hosts) != 1:
        return None
    direct = _parse_authority(hosts[0], "http")
    if direct is None:
        return None

    forwarded_protos = request.headers.get_all("X-Forwarded-Proto")
    forwarded_hosts = request.headers.get_all("X-Forwarded-Host")
    if forwarded_hosts and not forwarded_protos:
        return None
    if forwarded_protos:
        proto = _first_forwarded_value(request.headers, "X-Forwarded-Proto")
        if proto != "https" or direct[1] not in trusted_proxy_hosts:
            return None
        if forwarded_hosts:
            forwarded_host = _first_forwarded_value(request.headers, "X-Forwarded-Host")
            forwarded = (
                _parse_authority(forwarded_host, proto) if forwarded_host is not None else None
            )
            if (
                forwarded is None
                or forwarded[1] != direct[1]
                or forwarded[1] not in trusted_proxy_hosts
                or forwarded[2] != 443
            ):
                return None
        effective = ("https", direct[1], 443)
    else:
        if not _direct_host_allowed(direct[1], bind_host, allowed_hosts):
            return None
        effective = direct

    origins = request.headers.get_all("Origin")
    if len(origins) > 1 or (origins and _parse_origin(origins[0]) != effective):
        return None
    return _RequestAddress(effective, secure=effective[0] == "https")


def _add_security_headers(response: Response, *, allow_embedding: bool) -> Response:
    # websockets serves ordinary HTTP as a rejected opening handshake and
    # closes the transport after the response. Spell that contract explicitly
    # so clients never attempt a second request against the same reservation.
    if response.status_code != http.HTTPStatus.SWITCHING_PROTOCOLS:
        response.headers["Connection"] = "close"
    if not allow_embedding:
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@dataclasses.dataclass
class _ClientHandleState:
    # Internal state for ClientConnection objects.
    message_buffer: AsyncMessageBuffer
    persistent_message_buffer: AsyncMessageBuffer | None = None


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

_HTTP_ASSET_MAX_BYTES = 64 * 1024 * 1024
"""Largest runtime asset accepted into the bounded snapshot registry."""

_HTTP_ASSET_CACHE_MAX_BYTES = 128 * 1024 * 1024
"""Maximum runtime-asset bytes retained and shared by all responses."""

_HTTP_ASSET_LOAD_MAX_BYTES = 128 * 1024 * 1024
"""Maximum aggregate asset snapshots being read before registry admission."""

_HTTP_ASSET_LIMIT = 1024
"""How many registered assets are remembered. Registrations past this evict
the oldest; a URL that has been evicted answers 404, the same as one that was
never registered."""

_HTTP_ASSET_SUFFIX_PATTERN = re.compile(r"\.[a-z0-9]{1,16}\Z")

_HTTP_STATIC_CACHE_MAX_BYTES = 32 * 1024 * 1024
"""Maximum raw and compressed static response bytes retained together."""

_HTTP_STATIC_CACHE_MAX_ENTRIES = 128

_HTTP_RESPONSE_IN_FLIGHT_MAX_BYTES = 128 * 1024 * 1024
"""Maximum aggregate HTTP response bytes owned by live connections."""

_HTTP_RESPONSE_IN_FLIGHT_MAX_RESPONSES = 256
"""Maximum response owners retained while their transports remain live."""


class _HttpResponseBudget:
    """Admission for forced-close HTTP response bodies and owners."""

    def __init__(self, max_bytes: int, max_responses: int) -> None:
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("max_bytes must be a non-negative integer")
        if type(max_responses) is not int or max_responses < 0:
            raise ValueError("max_responses must be a non-negative integer")
        self._max_bytes = max_bytes
        self._max_responses = max_responses
        self._bytes = 0
        self._reserved_from_connection: dict[object, int] = {}

    def try_reserve(self, connection: ServerConnection, size: int) -> bool:
        """Reserve one forced-close response until its transport closes."""
        if type(size) is not int or size < 0:
            raise ValueError("size must be a non-negative integer")
        if connection in self._reserved_from_connection:
            raise RuntimeError("HTTP connection already owns a response reservation")
        if (
            len(self._reserved_from_connection) >= self._max_responses
            or self._bytes + size > self._max_bytes
        ):
            return False
        self._reserved_from_connection[connection] = size
        self._bytes += size

        def release(_: object) -> None:
            self.release(connection)

        try:
            connection.connection_lost_waiter.add_done_callback(release)
        except BaseException:
            self.release(connection)
            raise
        return True

    def try_resize(self, connection: ServerConnection, size: int) -> bool:
        """Change one admitted owner to its final response-body size."""
        if type(size) is not int or size < 0:
            raise ValueError("size must be a non-negative integer")
        if connection not in self._reserved_from_connection:
            raise RuntimeError("HTTP connection has no response reservation")
        previous = self._reserved_from_connection[connection]
        proposed = self._bytes - previous + size
        if proposed > self._max_bytes:
            return False
        self._reserved_from_connection[connection] = size
        self._bytes = proposed
        return True

    def release(self, connection: ServerConnection) -> None:
        """Release one owner; safe when its transport callback runs later."""
        reserved = self._reserved_from_connection.pop(connection, 0)
        self._bytes -= reserved


_MANAGED_CLIENT_BUILD_ROOT = Path(__file__).resolve().parent.parent / "client" / "build"
"""The sole static root whose transactional build backup may be served."""


def _read_bounded_file(
    path: Path, max_bytes: int, *, expected_metadata: os.stat_result | None = None
) -> bytes:
    """Read one identity-checked regular-file descriptor within the byte limit."""
    return read_regular_file_snapshot(path, max_bytes, expected_metadata=expected_metadata)


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
        allowed_hosts: Additional DNS hostnames accepted in HTTP ``Host``
            headers. Wildcard binds accept localhost and IP literals by
            default; DNS, mDNS, and tailnet names require explicit opt-in.
            Entries are hostnames only, without ports; at most 256 may be
            configured. Invalid, duplicate, changing, or oversized sequences
            raise :class:`ValueError` during construction.
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
        normalized_allowed_hosts = _normalize_allowed_hosts(allowed_hosts)
        super().__init__()

        # Track connected clients.
        self._client_connect_cb: list[Callable[[WebsockClientConnection], None | Coroutine]] = []
        self._client_disconnect_cb: list[Callable[[WebsockClientConnection], None | Coroutine]] = []
        self._client_callback_lock = threading.RLock()

        self._host = host
        self._port = port
        self._allowed_hosts = normalized_allowed_hosts
        self._allow_embedding = allow_embedding
        self._trusted_proxy_hosts: frozenset[str] = frozenset()
        self._trusted_proxy_lock = threading.Lock()
        self._message_class = message_class
        self._http_server_root = http_server_root
        self._auth_guard = HttpPasswordGuard(password) if password is not None else None
        self._verbose = verbose
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

        # Runtime assets are immutable, content-addressed byte snapshots. A
        # bounded shared snapshot avoids repeated event-loop disk reads and
        # makes concurrent responses reuse one payload object.
        self._http_assets: dict[str, bytes] = {}
        self._http_asset_bytes = 0
        self._http_assets_lock = threading.Lock()
        self._http_assets_terminal = False
        self._http_asset_load_condition = threading.Condition()
        self._http_asset_load_bytes = 0

    def trust_proxy_host(self, host: str) -> None:
        """Trust forwarded origin metadata only for one exact proxy hostname."""
        canonical = _canonical_hostname(host)
        if canonical is None:
            raise ValueError(f"Invalid trusted proxy host: {host!r}.")
        with self._trusted_proxy_lock:
            self._trusted_proxy_hosts = self._trusted_proxy_hosts | {canonical}

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

    def _retire_http_assets(self) -> None:
        """Close runtime-asset admission and release every cached snapshot."""
        with self._http_assets_lock:
            self._http_assets_terminal = True
            self._http_assets.clear()
            self._http_asset_bytes = 0
        # Wake registrations waiting for load headroom so they can observe the
        # terminal state instead of remaining blocked behind abandoned work.
        with self._http_asset_load_condition:
            self._http_asset_load_condition.notify_all()

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
        self._retire_http_assets()

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
                self._retire_http_assets()
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
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        with self._http_assets_lock:
            if self._http_assets_terminal:
                raise RuntimeError("Cannot register HTTP assets after server shutdown.")
        # Resolve once: HTTP requests may be served after the process changes
        # working directory, but a registered source must keep its identity.
        path = path.resolve()
        # Reserve from the regular file's current size before loading. This
        # bounds simultaneous snapshots without holding the lookup lock used by
        # live HTTP GETs. Descriptor-based reading still verifies the source.
        estimated_metadata = path.stat()
        if estimated_metadata.st_size > _HTTP_ASSET_MAX_BYTES:
            raise ValueError(f"File is larger than the {_HTTP_ASSET_MAX_BYTES}-byte limit.")
        with self._http_asset_load_condition:
            while self._http_asset_load_bytes + _HTTP_ASSET_MAX_BYTES > _HTTP_ASSET_LOAD_MAX_BYTES:
                with self._http_assets_lock:
                    if self._http_assets_terminal:
                        raise RuntimeError("Cannot register HTTP assets after server shutdown.")
                self._http_asset_load_condition.wait()
            with self._http_assets_lock:
                if self._http_assets_terminal:
                    raise RuntimeError("Cannot register HTTP assets after server shutdown.")
            # Charge the per-file ceiling, not the racy pre-open stat size: a
            # concurrent writer can grow the file before descriptor reading.
            self._http_asset_load_bytes += _HTTP_ASSET_MAX_BYTES
        try:
            content = _read_bounded_file(
                path,
                _HTTP_ASSET_MAX_BYTES,
                expected_metadata=(
                    _expected_metadata if _expected_metadata is not None else estimated_metadata
                ),
            )
            digest = hashlib.sha256(content).hexdigest()
            # Read from the bytes already in hand for the hash, so knowing the
            # shape of a picture costs nothing over not knowing it. The load
            # reservation remains owned until this immutable snapshot enters
            # the bounded cache; hashing and image parsing may retain it too.
            if _require_safe_image:
                image_kind, pixel_size = safe_image_info(content)
                width, height = pixel_size
                # The suffix is authenticated by the same bytes as the digest and
                # dimensions. A misleading or absent source suffix cannot change
                # MIME interpretation under nosniff.
                suffix = f".{image_kind}"
                name = f"{digest}-{width}x{height}{suffix}"
            else:
                pixel_size = image_pixel_size(content)
                suffix = path.suffix.lower()
                if _HTTP_ASSET_SUFFIX_PATTERN.fullmatch(suffix) is None:
                    suffix = ""
                name = f"{digest}{suffix}"
            with self._http_assets_lock:
                if self._http_assets_terminal:
                    raise RuntimeError("Cannot register HTTP assets after server shutdown.")
                previous = self._http_assets.pop(name, None)
                if previous is not None:
                    self._http_asset_bytes -= len(previous)
                # Re-registration refreshes this content key's eviction order.
                self._http_assets[name] = content
                self._http_asset_bytes += len(content)
                while self._http_assets and (
                    len(self._http_assets) > _HTTP_ASSET_LIMIT
                    or self._http_asset_bytes > _HTTP_ASSET_CACHE_MAX_BYTES
                ):
                    oldest_name = next(iter(self._http_assets))
                    evicted = self._http_assets.pop(oldest_name)
                    self._http_asset_bytes -= len(evicted)
            return HttpAsset(f"{_HTTP_ASSET_URL_PREFIX}{name}", pixel_size)
        finally:
            with self._http_asset_load_condition:
                self._http_asset_load_bytes -= _HTTP_ASSET_MAX_BYTES
                self._http_asset_load_condition.notify_all()

    def _background_worker(self, startup: Future[None]) -> None:
        import rich

        host = self._host
        port = self._port
        message_class = self._message_class
        http_server_root = self._http_server_root
        http_server_publication_backup = None
        if (
            http_server_root is not None
            and http_server_root.resolve() == _MANAGED_CLIENT_BUILD_ROOT.resolve()
        ):
            http_server_publication_backup = http_server_root.with_name(_BUILD_BACKUP_DIR_NAME)
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
                    ),
                    _message_producer(
                        connection,
                        self._broadcast_buffer,
                        client_id,
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
                await _serve_admitted_connection(connection, client_id)
            finally:
                async with count_lock:
                    active_client_ids.discard(client_id)

        # Host client on the same port as the websocket.
        static_cache: OrderedDict[tuple[Path, Path, bool, int, int, int], tuple[bytes, str]] = (
            OrderedDict()
        )
        static_cache_bytes = 0
        static_cache_lock = threading.Lock()
        http_response_budget = _HttpResponseBudget(
            _HTTP_RESPONSE_IN_FLIGHT_MAX_BYTES,
            _HTTP_RESPONSE_IN_FLIGHT_MAX_RESPONSES,
        )

        def static_source_candidates(source: Path) -> Iterator[Path]:
            """Yield the live file, then its old generation only during swap."""
            yield source
            if http_server_root is None or http_server_publication_backup is None:
                return
            try:
                relative = source.relative_to(http_server_root)
            except ValueError:
                return
            if not http_server_root.exists():
                yield http_server_publication_backup / relative
            # The new generation may have appeared while the backup was being
            # selected or after the first live-file lookup failed. Retry it
            # once before reporting a clean 404.
            yield source

        def cached_static_payload(source: Path, compressed: bool) -> tuple[bytes, str]:
            """Read/compress one contained static response with bounded LRU retention."""
            nonlocal static_cache_bytes
            last_error: OSError | None = None
            for candidate in static_source_candidates(source):
                candidate_root = (
                    http_server_publication_backup if candidate != source else http_server_root
                )
                if candidate_root is None:
                    continue
                try:
                    resolved_root = candidate_root.resolve(strict=True)
                    resolved_candidate = candidate.resolve(strict=True)
                    resolved_candidate.relative_to(resolved_root)
                    metadata = resolved_candidate.stat()
                except (OSError, ValueError) as error:
                    # A static root never grants access outside its configured
                    # tree. The captured identity is checked again after open,
                    # closing the validation-to-descriptor replacement race.
                    last_error = OSError("static source leaves configured root")
                    if isinstance(error, OSError):
                        last_error = error
                    continue
                # Once the live root has reappeared, never answer a genuinely
                # missing new-generation file from the old generation.
                if candidate != source and http_server_root is not None:
                    if http_server_root.exists():
                        continue
                key = (
                    source,
                    candidate,
                    compressed,
                    metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                    metadata.st_size,
                )
                # This function runs in worker threads so filesystem reads and
                # gzip cannot block the websocket loop. Serialize the small
                # shared LRU and byte counter; concurrent requests remain
                # bounded rather than racing duplicate insertions.
                with static_cache_lock:
                    cached = static_cache.pop(key, None)
                    if cached is not None:
                        static_cache[key] = cached
                        return cached

                    try:
                        raw = _read_bounded_file(
                            resolved_candidate,
                            _HTTP_STATIC_CACHE_MAX_BYTES,
                            expected_metadata=metadata,
                        )
                    except OSError as error:
                        last_error = error
                        continue

                    # Discard raw and compressed variants from older metadata
                    # or a different generation. A long-lived server must not
                    # retain the old bundle after the atomic swap completes.
                    for stale_key in tuple(static_cache):
                        if stale_key[0] == source and stale_key != key:
                            stale_payload, _ = static_cache.pop(stale_key)
                            static_cache_bytes -= len(stale_payload)

                    payload = gzip.compress(raw, mtime=0) if compressed else raw
                    etag = f'"{hashlib.sha256(payload).hexdigest()}"'
                    if len(payload) <= _HTTP_STATIC_CACHE_MAX_BYTES:
                        while static_cache and (
                            len(static_cache) >= _HTTP_STATIC_CACHE_MAX_ENTRIES
                            or static_cache_bytes + len(payload) > _HTTP_STATIC_CACHE_MAX_BYTES
                        ):
                            _, (evicted, _) = static_cache.popitem(last=False)
                            static_cache_bytes -= len(evicted)
                        static_cache[key] = (payload, etag)
                        static_cache_bytes += len(payload)
                    return payload, etag
            if last_error is not None:
                raise last_error
            raise FileNotFoundError(source)

        def server_busy_response() -> Response:
            return Response(
                http.HTTPStatus.SERVICE_UNAVAILABLE,
                "SERVER BUSY",
                Headers(**{"Retry-After": "1"}),
                b"SERVER BUSY",
            )

        async def leika_http_server(
            connection: ServerConnection,
            request: Request,
        ) -> Response | None:
            upgrades = request.headers.get_all("Upgrade")
            is_websocket_upgrade = len(upgrades) == 1 and upgrades[0].lower() == "websocket"
            # Websocket connections enter their own active-client admission
            # below. Every ordinary HTTP response owns a budget token from the
            # start, including auth/error/zero-byte branches.
            if not is_websocket_upgrade and not http_response_budget.try_reserve(connection, 0):
                return server_busy_response()

            # Host validation applies to every HTTP request, not only browser
            # websocket handshakes: it is the DNS-rebinding boundary.
            with self._trusted_proxy_lock:
                trusted_proxy_hosts = self._trusted_proxy_hosts
            address = _request_address(
                request,
                bind_host=host,
                allowed_hosts=self._allowed_hosts,
                trusted_proxy_hosts=trusted_proxy_hosts,
            )
            if address is None:
                return Response(http.HTTPStatus.FORBIDDEN, "FORBIDDEN", Headers(), b"FORBIDDEN")

            # The password gate follows Host/Origin validation so credentials
            # are never evaluated for an untrusted browser endpoint.
            if auth_guard is not None:
                guard_response = auth_guard.process(request, secure=address.secure)
                if guard_response is not None:
                    return guard_response

            # Ignore websocket packets. Header duplication is handled without
            # the single-value Headers.get() exception path.
            if is_websocket_upgrade:
                return None

            # Runtime-registered assets come before the static tree, and are
            # served whether or not there is one. The lookup is an exact match
            # against names this server handed out -- a hex digest and optional
            # short ASCII suffix -- so there is no traversal to guard.
            url_path = request.path.partition("?")[0]
            if url_path.startswith(_HTTP_ASSET_URL_PREFIX):
                with self._http_assets_lock:
                    payload = self._http_assets.get(url_path[len(_HTTP_ASSET_URL_PREFIX) :])
                if payload is None:
                    return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
                if not http_response_budget.try_resize(connection, len(payload)):
                    return server_busy_response()
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
                            # Runtime assets may originate in an untrusted
                            # Markdown tree. Even if one is HTML or SVG and a
                            # user navigates to it directly, it cannot execute
                            # with Leika's same-origin authority.
                            "Content-Security-Policy": "sandbox; frame-ancestors 'none'",
                        }
                    ),
                    payload,
                )

            # No files to serve: only the websocket (and the guard above)
            # live on this port.
            if http_server_root is None:
                return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())

            # Normalize traversal lexically before joining. The worker also
            # resolves the selected live/backup candidate and enforces that its
            # real target remains beneath that generation root.
            relpath = _static_relpath(request.path)
            if relpath is None:
                return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
            source_path = http_server_root / relpath
            use_gzip = _accepts_gzip(request.headers.get_all("Accept-Encoding"))

            mime_type = _http_content_type(relpath)

            try:
                response_payload, etag = await event_loop.run_in_executor(
                    None, cached_static_payload, source_path, use_gzip
                )
            except ValueError:
                return Response(
                    http.HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "CONTENT TOO LARGE",
                    Headers(),
                    b"CONTENT TOO LARGE",
                )
            except OSError:
                return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
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

            if not http_response_budget.try_resize(connection, len(response_payload)):
                return server_busy_response()

            return Response(
                http.HTTPStatus.OK,
                "OK",
                websockets.datastructures.Headers(**response_headers),
                response_payload,
            )

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
                process_request=leika_http_server,
                process_response=lambda _, __, response: _add_security_headers(
                    response, allow_embedding=self._allow_embedding
                ),
                # The bundled client negotiates its private version token;
                # custom low-level protocols use normal no-subprotocol sockets.
                subprotocols=None,
                select_subprotocol=(
                    lambda _, subprotocols: (
                        next(
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
    """Return UTF-8 byte length without allocating an encoded copy."""
    size = 0
    for char in value:
        codepoint = ord(char)
        size += (
            1 if codepoint < 0x80 else 2 if codepoint < 0x800 else 3 if codepoint < 0x10000 else 4
        )
    return size


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
                await websocket.send(parts)
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
