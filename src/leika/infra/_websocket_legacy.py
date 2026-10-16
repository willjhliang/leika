"""WebSockets 12 hooks with the request/response contract used by Leika.

Upstream still owns parsing, framing, response writes and connection shutdown.
In particular, HTTP response reservations live until connection_lost_waiter
completes, exactly as they do with the modern implementation.
"""

from __future__ import annotations

import http
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast

from websockets import Headers
from websockets.headers import parse_subprotocol
from websockets.http11 import Request, Response
from websockets.legacy.server import WebSocketServerProtocol
from websockets.legacy.server import serve as legacy_serve
from websockets.typing import Subprotocol


class ServerConnection(WebSocketServerProtocol):
    request: Request | None = None


def serve(
    handler: Callable[[ServerConnection], Awaitable[None]],
    host: str,
    port: int,
    *,
    process_request: Callable[[ServerConnection, Request], Awaitable[Response | None]],
    process_response: Callable[[ServerConnection, Request, Response], Response],
    select_subprotocol: Callable[[ServerConnection, Sequence[Subprotocol]], Subprotocol | None],
    **kwargs: Any,
) -> legacy_serve:
    class Protocol(ServerConnection):
        async def process_request(self, path: str, request_headers: Headers):
            self.request = Request(path, request_headers)
            response = await process_request(self, self.request)
            if response is None:
                return None
            # WebSockets 12 represents an empty Response body as None, but its
            # legacy HTTP writer requires bytes, including for 204/304/errors.
            return (
                http.HTTPStatus(response.status_code),
                response.headers,
                bytes(response.body or b""),
            )

        def process_subprotocol(self, headers: Headers, available_subprotocols):
            offered = [
                protocol
                for value in headers.get_all("Sec-WebSocket-Protocol")
                for protocol in parse_subprotocol(value)
            ]
            return select_subprotocol(self, offered)

        def write_http_response(
            self, status: http.HTTPStatus, headers: Headers, body: bytes | None = None
        ) -> None:
            response = Response(status.value, status.phrase, headers, body or b"")
            if self.request is not None:
                response = process_response(self, self.request, response)
            super().write_http_response(
                http.HTTPStatus(response.status_code),
                response.headers,
                bytes(response.body or b"") if body is not None else None,
            )

    async def handle(connection: WebSocketServerProtocol) -> None:
        await handler(cast(ServerConnection, connection))

    return legacy_serve(handle, host, port, create_protocol=Protocol, **kwargs)
