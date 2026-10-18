"""HTTP routing for the client page, runtime assets and embedded Viser panes."""

from __future__ import annotations

import gzip
import hashlib
import http
import mimetypes
from pathlib import Path
from typing import Literal

from websockets import Headers
from websockets.http11 import Request, Response

from ._auth import HttpPasswordGuard
from ._http_assets import _HTTP_ASSET_URL_PREFIX, HttpAssetRegistry
from ._http_security import HttpRequestPolicy
from ._viser_proxy import VISER_PROXY_PREFIX, ViserProxy


def _single_byte_range(value: str, size: int) -> tuple[int, int] | None | Literal[False]:
    """Return a half-open range, None to ignore, or False if unsatisfiable."""
    if not value.startswith("bytes=") or "," in value or len(value) > 128:
        return None
    left, dash, right = value[6:].partition("-")
    if (
        not dash
        or not (left or right)
        or any(part and (not part.isascii() or not part.isdigit()) for part in (left, right))
    ):
        return None
    if not left:
        length = int(right)
        return (max(0, size - length), size) if length and size else False
    start = int(left)
    last = int(right) if right else size - 1
    if right and last < start:
        return None
    if start >= size:
        return False
    return start, min(size, last + 1)


def _not_found() -> Response:
    return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())


class _IndexPage:
    """The single-file client, held in memory with a precomputed gzip copy.

    The file is reread when its modification time or size changes, so a
    rebuilt client is served without restarting Python.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._identity: tuple[int, int] | None = None
        self._encodings: dict[bool, tuple[bytes, str]] = {}

    def representation(self, use_gzip: bool) -> tuple[bytes, str]:
        """The page body and its ETag, raising OSError if the file is missing."""
        metadata = self._path.stat()
        identity = (metadata.st_mtime_ns, metadata.st_size)
        if identity != self._identity:
            raw = self._path.read_bytes()
            etag = hashlib.sha256(raw).hexdigest()[:32]
            self._encodings = {
                False: (raw, f'"{etag}"'),
                True: (gzip.compress(raw, mtime=0), f'"{etag}-gzip"'),
            }
            self._identity = identity
        return self._encodings[use_gzip]


class HttpRequestHandler:
    """HTTP handshake hooks; one instance belongs to one server worker."""

    def __init__(
        self,
        *,
        index_html: Path | None,
        assets: HttpAssetRegistry,
        policy: HttpRequestPolicy,
        auth_guard: HttpPasswordGuard | None,
        viser_proxy: ViserProxy,
    ) -> None:
        self._index = _IndexPage(index_html) if index_html is not None else None
        self._assets = assets
        self._policy = policy
        self._auth_guard = auth_guard
        self._viser_proxy = viser_proxy

    def prepare_headers(self, status: http.HTTPStatus, headers: Headers) -> None:
        if self._auth_guard is not None:
            # A shared cache must never hand one authenticated response to a
            # later anonymous client.
            for name in ("Cache-Control", "CDN-Cache-Control"):
                if name in headers:
                    del headers[name]
                headers[name] = "no-store"
        self._policy.secure_headers(status, headers)

    async def response_for(self, request: Request) -> Response | None:
        """The response to one request, or None to accept a websocket upgrade."""
        # Host and Origin are validated on every request: this is the
        # DNS-rebinding boundary.
        address = self._policy.address(request)
        if address is None:
            return Response(http.HTTPStatus.FORBIDDEN, "FORBIDDEN", Headers(), b"FORBIDDEN")
        # Credentials are evaluated only for a trusted browser endpoint.
        if self._auth_guard is not None:
            guard_response = self._auth_guard.process(request, secure=address.secure)
            if guard_response is not None:
                return guard_response

        upgrades = request.headers.get_all("Upgrade")
        is_websocket_upgrade = len(upgrades) == 1 and upgrades[0].lower() == "websocket"
        url_path = request.path.partition("?")[0]
        if url_path.startswith(VISER_PROXY_PREFIX):
            if self._viser_proxy.match(request.path) is None:
                return _not_found()
            if is_websocket_upgrade:
                return None
            return await self._viser_proxy.http_response(request)
        if is_websocket_upgrade:
            return None
        if url_path.startswith(_HTTP_ASSET_URL_PREFIX):
            return self._asset_response(request, url_path)
        if url_path in ("/", "/index.html") and self._index is not None:
            return self._index_response(request)
        return _not_found()

    def _asset_response(self, request: Request, url_path: str) -> Response:
        """Serve an immutable asset, including single byte ranges for media."""
        payload = self._assets.get(url_path[len(_HTTP_ASSET_URL_PREFIX) :])
        if payload is None:
            return _not_found()
        size = len(payload)
        etag = '"' + url_path.rsplit("/", 1)[-1] + '"'
        headers = Headers(
            {
                "Content-Type": mimetypes.guess_type(url_path)[0] or "application/octet-stream",
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Security-Policy": "sandbox; frame-ancestors 'none'",
                "Accept-Ranges": "bytes",
                "ETag": etag,
            }
        )
        status = http.HTTPStatus.OK
        start, end = 0, size
        ranges = request.headers.get_all("Range")
        if_range = request.headers.get_all("If-Range")
        if len(ranges) == 1 and (not if_range or if_range == [etag]):
            selected = _single_byte_range(ranges[0], size)
            if selected is False:
                headers["Content-Range"] = f"bytes */{size}"
                headers["Content-Length"] = "0"
                return Response(
                    http.HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
                    "Range Not Satisfiable",
                    headers,
                    b"",
                )
            if selected is not None:
                start, end = selected
                status = http.HTTPStatus.PARTIAL_CONTENT
                headers["Content-Range"] = f"bytes {start}-{end - 1}/{size}"
        headers["Content-Length"] = str(end - start)
        return Response(status, status.phrase, headers, payload[start:end])

    def _index_response(self, request: Request) -> Response:
        assert self._index is not None
        use_gzip = "gzip" in ",".join(request.headers.get_all("Accept-Encoding")).lower()
        try:
            body, etag = self._index.representation(use_gzip)
        except OSError:
            return _not_found()
        headers = Headers({"Cache-Control": "no-cache", "ETag": etag, "Vary": "Accept-Encoding"})
        matches = (
            candidate.strip().removeprefix("W/")
            for value in request.headers.get_all("If-None-Match")
            for candidate in value.split(",")
        )
        if any(candidate in ("*", etag) for candidate in matches):
            return Response(http.HTTPStatus.NOT_MODIFIED, "NOT MODIFIED", headers)
        headers["Content-Type"] = "text/html; charset=utf-8"
        headers["Content-Length"] = str(len(body))
        if use_gzip:
            headers["Content-Encoding"] = "gzip"
        return Response(http.HTTPStatus.OK, "OK", headers, body)
