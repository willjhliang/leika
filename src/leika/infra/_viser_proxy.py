"""Server-owned, same-origin transport for explicitly registered local Viser panes.

Host/Origin checks and the password guard run before this router. Browser
requests never choose an upstream: only Python pane declarations register one.
"""

from __future__ import annotations

import asyncio
import dataclasses
import http
import threading
import uuid
from collections.abc import Callable
from urllib.parse import unquote

import aiohttp
import msgspec
from websockets import Headers
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response
from yarl import URL

from ._http_security import _canonical_hostname, _is_loopback_host

VISER_PROXY_PREFIX = "/_leika/viser/"
_MAX_HTTP_BYTES = 32 * 1024 * 1024
_MAX_UPSTREAM_MESSAGE_BYTES = 64 * 1024 * 1024


@dataclasses.dataclass(eq=False)
class ViserEndpoint:
    path: str
    host: str
    port: int
    connections: set[ServerConnection] = dataclasses.field(default_factory=set)


class ViserProxy:
    def __init__(self, *, protected: bool) -> None:
        self._protected = protected
        self._lock = threading.Lock()
        self._endpoints: dict[str, ViserEndpoint] = {}
        self._session: aiohttp.ClientSession | None = None
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

    def _client(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._loop = asyncio.get_running_loop()
            self._session = aiohttp.ClientSession(
                auto_decompress=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                trust_env=False,
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=15),
                connector=aiohttp.TCPConnector(limit=16),
            )
        return self._session

    @staticmethod
    def _url(endpoint: ViserEndpoint, path: str) -> URL:
        host = f"[{endpoint.host}]" if ":" in endpoint.host else endpoint.host
        return URL(f"http://{host}:{endpoint.port}{path}", encoded=True)

    async def http_response(self, request: Request, reserve: Callable[[int], bool]) -> Response:
        matched = self.match(request.path)
        if matched is None:
            return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
        endpoint, path = matched
        headers = {}
        for name in ("Accept", "Accept-Encoding", "If-None-Match", "Range"):
            values = request.headers.get_all(name)
            if len(values) == 1:
                headers[name] = values[0]
        try:
            async with self._client().get(
                self._url(endpoint, path), headers=headers, allow_redirects=False
            ) as upstream:
                # Only representation headers cross the boundary. Never cookies,
                # redirects, CORS grants or backend connection/security policies.
                outgoing = Headers()
                for name in (
                    "Content-Type",
                    "Content-Encoding",
                    "ETag",
                    "Content-Range",
                    "Accept-Ranges",
                ):
                    if name in upstream.headers:
                        outgoing[name] = upstream.headers[name]
                outgoing["Content-Security-Policy"] = "frame-ancestors 'self'"
                outgoing["Cache-Control"] = "no-store"
                chunks: list[bytes] = []
                size = 0
                async for chunk in upstream.content.iter_chunked(128 * 1024):
                    size += len(chunk)
                    if size > _MAX_HTTP_BYTES or not reserve(2 * size):
                        return Response(
                            http.HTTPStatus.SERVICE_UNAVAILABLE, "SERVER BUSY", Headers()
                        )
                    chunks.append(chunk)
                payload = b"".join(chunks)
                chunks.clear()
                reserve(len(payload))
                return Response(upstream.status, upstream.reason or "", outgoing, payload)
        except (aiohttp.ClientError, TimeoutError):
            return Response(http.HTTPStatus.BAD_GATEWAY, "VISER UNAVAILABLE", Headers())

    async def websocket(self, connection: ServerConnection) -> None:
        assert connection.request is not None
        matched = self.match(connection.request.path)
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
            protocols = [connection.subprotocol] if connection.subprotocol else []
            async with self._client().ws_connect(
                self._url(endpoint, path),
                protocols=protocols,
                max_msg_size=_MAX_UPSTREAM_MESSAGE_BYTES,
                compress=0,
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
                            await upstream.send_bytes(message)
                        else:
                            await upstream.send_str(message)

                async def from_server() -> None:
                    async for message in upstream:
                        if message.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                            await connection.send(message.data)
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            return

                tasks = [asyncio.create_task(from_client()), asyncio.create_task(from_server())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except (aiohttp.ClientError, TimeoutError, ConnectionClosed):
            await connection.close(1011, "Viser connection closed")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with self._lock:
                endpoint.connections.discard(connection)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
