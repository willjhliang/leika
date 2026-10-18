"""Server-owned, same-origin transport for explicitly registered local Viser panes.

Host/Origin checks and the password guard run before this router. Browser
requests never choose an upstream: only Python pane declarations register one.
"""

from __future__ import annotations

import asyncio
import dataclasses
import http
import re
import threading
import uuid
from collections.abc import Callable
from urllib.parse import unquote

import httpcore
import msgspec
from websockets import Headers
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.http11 import Request, Response
from websockets.legacy.client import connect
from websockets.legacy.server import WebSocketServerProtocol

from ._http_security import _canonical_hostname, _is_loopback_host

VISER_PROXY_PREFIX = "/_leika/viser/"
_MAX_HTTP_BYTES = 32 * 1024 * 1024
_MAX_UPSTREAM_MESSAGE_BYTES = 64 * 1024 * 1024
_ROOT_ASSET_URL = re.compile(rb"""(["'])(/(?:assets/|logo\.svg|manifest\.json))""")


def _rebase_assets(payload: bytes, prefix: str, reserve: Callable[[int], bool]) -> bytes | None:
    """Scope Viser's older Vite bundles to their pane, including worker URLs."""
    replacement = prefix.encode("ascii")
    count = sum(1 for _ in _ROOT_ASSET_URL.finditer(payload))
    if not count:
        return payload
    size = len(payload) + count * (len(replacement) - 1)
    # re.sub retains the source and replacement fragments while joining the
    # result. Charge all three, before creating any replacement fragments.
    if size > _MAX_HTTP_BYTES or not reserve(len(payload) + 2 * size):
        return None
    return _ROOT_ASSET_URL.sub(lambda m: m[1] + replacement + m[2][1:], payload)


class _LoopbackConnect(connect):
    """Never follow a backend redirect beyond its registered endpoint.

    The legacy client supports the entire declared WebSockets range and never
    reads proxy settings from the environment.
    """

    def handle_redirect(self, uri: str) -> None:
        raise InvalidHandshake("Embedded Viser redirects are not allowed")


@dataclasses.dataclass(eq=False)
class ViserEndpoint:
    path: str
    host: str
    port: int
    connections: set[WebSocketServerProtocol] = dataclasses.field(default_factory=set)


class ViserProxy:
    def __init__(self, *, protected: bool) -> None:
        self._protected = protected
        self._lock = threading.Lock()
        self._endpoints: dict[str, ViserEndpoint] = {}
        self._session: httpcore.AsyncConnectionPool | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def register(self, host: str, port: int) -> str:
        canonical = _canonical_hostname(host) if isinstance(host, str) else None
        # A protected Leika cannot protect a Viser listener exposed separately
        # on the LAN. Require callers to bind it to loopback before embedding.
        if canonical is None or not (
            _is_loopback_host(canonical) or (not self._protected and canonical in ("0.0.0.0", "::"))
        ):
            raise ValueError('Embedded Viser must bind to loopback; use host="127.0.0.1".')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Embedded Viser must report a concrete valid port.")
        host = "::1" if canonical == "::" else "127.0.0.1" if canonical == "0.0.0.0" else canonical
        path = VISER_PROXY_PREFIX + uuid.uuid4().hex + "/"
        with self._lock:
            self._endpoints[path] = ViserEndpoint(path, host, port)
        return path

    def unregister(self, path: str | None) -> None:
        with self._lock:
            endpoint = self._endpoints.pop(path, None) if path is not None else None
            connections = tuple(endpoint.connections) if endpoint is not None else ()
            loop = self._loop
        if loop is not None and not loop.is_closed():
            for connection in connections:
                loop.call_soon_threadsafe(
                    lambda connection=connection: asyncio.create_task(
                        connection.close(1001, "Viser pane removed or repointed")
                    )
                )

    def match(self, path: str) -> tuple[ViserEndpoint, str] | None:
        raw_path, separator, query = path.partition("?")
        if not raw_path.startswith(VISER_PROXY_PREFIX):
            return None
        token, slash, suffix = raw_path[len(VISER_PROXY_PREFIX) :].partition("/")
        key = VISER_PROXY_PREFIX + token + "/"
        decoded = unquote(suffix)
        if (
            "\\" in decoded
            or ".." in decoded.split("/")
            or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
        ):
            return None
        with self._lock:
            endpoint = self._endpoints.get(key)
        if endpoint is None:
            return None
        return endpoint, "/" + suffix + (separator + query if separator else "")

    def _client(self) -> httpcore.AsyncConnectionPool:
        if self._session is None:
            self._loop = asyncio.get_running_loop()
            # A raw HTTP transport has no cookies, redirect handling,
            # decompression, environment proxies or ambient credentials.
            self._session = httpcore.AsyncConnectionPool(max_connections=16)
        return self._session

    @staticmethod
    def _url(endpoint: ViserEndpoint, path: str) -> str:
        host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
        return f"http://{host}:{endpoint.port}{path}"

    async def http_response(self, request: Request, reserve: Callable[[int], bool]) -> Response:
        matched = self.match(request.path)
        if matched is None:
            return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
        endpoint, path = matched
        headers = {}
        # Text assets may need their root URLs rebased. Fetch raw identity
        # representations so neither compressed data nor partial ranges are
        # accidentally treated as editable source.
        asset_path = path.partition("?")[0]
        rebase = asset_path == "/" or asset_path.endswith((".html", ".js"))
        forwarded = (
            ("Accept",) if rebase else ("Accept", "Accept-Encoding", "If-None-Match", "Range")
        )
        for name in forwarded:
            values = request.headers.get_all(name)
            if len(values) == 1:
                headers[name] = values[0]
        if rebase:
            headers["Accept-Encoding"] = "identity"
        try:
            async with self._client().stream(
                "GET",
                self._url(endpoint, path),
                headers=headers,
                extensions={"timeout": {"connect": 5, "read": 15, "write": 15, "pool": 5}},
            ) as upstream:
                # Only representation headers cross the boundary. Never cookies,
                # redirects, CORS grants or backend connection/security policies.
                outgoing = Headers()
                upstream_headers = Headers(
                    (name.decode("ascii"), value.decode("latin-1"))
                    for name, value in upstream.headers
                )
                for name in (
                    "Content-Type",
                    "Content-Encoding",
                    "ETag",
                    "Content-Range",
                    "Accept-Ranges",
                ):
                    values = upstream_headers.get_all(name)
                    if len(values) == 1:
                        outgoing[name] = values[0]
                outgoing["Content-Security-Policy"] = "frame-ancestors 'self'"
                outgoing["Cache-Control"] = "no-store"
                chunks: list[bytes] = []
                size = 0
                async for chunk in upstream.aiter_stream():
                    size += len(chunk)
                    if size > _MAX_HTTP_BYTES or not reserve(2 * size):
                        return Response(
                            http.HTTPStatus.SERVICE_UNAVAILABLE, "SERVER BUSY", Headers()
                        )
                    chunks.append(chunk)
                payload = b"".join(chunks)
                chunks.clear()
                chunk = b""
                content_type = outgoing.get("Content-Type", "").partition(";")[0]
                if rebase and content_type in (
                    "text/html",
                    "application/javascript",
                    "text/javascript",
                ):
                    if outgoing.get("Content-Encoding", "identity") != "identity":
                        return Response(
                            http.HTTPStatus.BAD_GATEWAY, "ENCODED VISER ASSET", Headers()
                        )
                    payload = _rebase_assets(payload, endpoint.path, reserve)
                    if payload is None:
                        return Response(
                            http.HTTPStatus.SERVICE_UNAVAILABLE, "SERVER BUSY", Headers()
                        )
                    if "ETag" in outgoing:
                        del outgoing["ETag"]
                reserve(len(payload))
                reason = upstream.extensions.get("reason_phrase", b"").decode("ascii", "replace")
                return Response(upstream.status, reason, outgoing, payload)
        except (httpcore.NetworkError, httpcore.ProtocolError, httpcore.TimeoutException):
            return Response(http.HTTPStatus.BAD_GATEWAY, "VISER UNAVAILABLE", Headers())

    async def websocket(self, connection: WebSocketServerProtocol) -> None:
        matched = self.match(connection.path)
        if matched is None:
            await connection.close(1008, "Viser pane is unavailable")
            return
        endpoint, path = matched
        self._loop = asyncio.get_running_loop()
        with self._lock:
            active = self._endpoints.get(endpoint.path) is endpoint
            if active:
                endpoint.connections.add(connection)
        if not active:
            await connection.close(1008, "Viser pane is unavailable")
            return
        tasks: list[asyncio.Task[None]] = []
        try:
            protocols = [connection.subprotocol] if connection.subprotocol else None
            async with _LoopbackConnect(
                self._url(endpoint, path).replace("http:", "ws:", 1),
                subprotocols=protocols,
                max_size=_MAX_UPSTREAM_MESSAGE_BYTES,
                max_queue=1,
                open_timeout=5,
                compression=None,
            ) as upstream:

                async def from_client() -> None:
                    async for message in connection:
                        # Viser's hidden Share button still has a remote handler.
                        # Never allow an embedded client to expose its backend
                        # through an independent, unauthenticated tunnel.
                        if isinstance(message, bytes):
                            try:
                                decoded = msgspec.msgpack.decode(message)
                            except msgspec.DecodeError:
                                await connection.close(1007, "Invalid Viser message")
                                return
                            if isinstance(decoded, dict) and decoded.get("type") in (
                                "ShareUrlRequest",
                                "ShareUrlDisconnect",
                            ):
                                await connection.close(1008, "Use Leika's authenticated sharing")
                                return
                        await upstream.send(message)

                async def from_server() -> None:
                    async for message in upstream:
                        await connection.send(message)

                tasks = [asyncio.create_task(from_client()), asyncio.create_task(from_server())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except (OSError, TimeoutError, ConnectionClosed, InvalidHandshake):
            await connection.close(1011, "Viser connection closed")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with self._lock:
                endpoint.connections.discard(connection)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.aclose()
            self._session = None
