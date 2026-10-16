"""Worker-owned HTTP routing, static file caching, and response admission.

The websocket server supplies lifecycle and a shared port. This module owns
ordinary HTTP handling and keeps file reads and compression off its event loop.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import http
import mimetypes
import threading
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from pathlib import Path, PureWindowsPath
from typing import Literal
from urllib.parse import unquote as _url_unquote

from websockets import Headers
from websockets.http11 import Request, Response

from .._client_autobuild import _BUILD_BACKUP_DIR_NAME
from .._file_transfer import read_regular_file_snapshot
from ._auth import HttpPasswordGuard
from ._http_assets import _HTTP_ASSET_URL_PREFIX, HttpAssetRegistry
from ._http_security import HttpRequestPolicy
from ._viser_proxy import VISER_PROXY_PREFIX, ViserProxy
from ._websocket import ServerConnection


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


class _StaticFileCache:
    """Cache contained static snapshots across requests for one worker lifetime."""

    def __init__(self, root: Path | None) -> None:
        self._root = root
        self._publication_backup: Path | None = None
        if root is not None and root.resolve() == _MANAGED_CLIENT_BUILD_ROOT.resolve():
            self._publication_backup = root.with_name(_BUILD_BACKUP_DIR_NAME)
        self._entries: OrderedDict[tuple[Path, Path, bool, int, int, int], tuple[bytes, str]] = (
            OrderedDict()
        )
        self._bytes = 0
        self._lock = threading.Lock()

    @property
    def root(self) -> Path | None:
        return self._root

    def _source_candidates(self, source: Path) -> Iterator[Path]:
        """Yield the live file, then its old generation only during swap."""
        yield source
        if self._root is None or self._publication_backup is None:
            return
        try:
            relative = source.relative_to(self._root)
        except ValueError:
            return
        if not self._root.exists():
            yield self._publication_backup / relative
        # The new generation may have appeared while the backup was being
        # selected or after the first live-file lookup failed. Retry it
        # once before reporting a clean 404.
        yield source

    def read(self, source: Path, compressed: bool) -> tuple[bytes, str]:
        """Read/compress one contained static response with bounded LRU retention."""
        last_error: OSError | None = None
        for candidate in self._source_candidates(source):
            candidate_root = self._publication_backup if candidate != source else self._root
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
            if candidate != source and self._root is not None:
                if self._root.exists():
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
            with self._lock:
                cached = self._entries.pop(key, None)
                if cached is not None:
                    self._entries[key] = cached
                    return cached

                try:
                    raw = read_regular_file_snapshot(
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
                # Keep both encodings of the current generation: mixed gzip
                # and identity requests must not evict each other's work.
                for stale_key in tuple(self._entries):
                    if stale_key[0] == source and (
                        stale_key[1] != candidate or stale_key[3:] != key[3:]
                    ):
                        stale_payload, _ = self._entries.pop(stale_key)
                        self._bytes -= len(stale_payload)

                payload = gzip.compress(raw, mtime=0) if compressed else raw
                etag = f'"{hashlib.sha256(payload).hexdigest()}"'
                if len(payload) <= _HTTP_STATIC_CACHE_MAX_BYTES:
                    while self._entries and (
                        len(self._entries) >= _HTTP_STATIC_CACHE_MAX_ENTRIES
                        or self._bytes + len(payload) > _HTTP_STATIC_CACHE_MAX_BYTES
                    ):
                        _, (evicted, _) = self._entries.popitem(last=False)
                        self._bytes -= len(evicted)
                    self._entries[key] = (payload, etag)
                    self._bytes += len(payload)
                return payload, etag
        if last_error is not None:
            raise last_error
        raise FileNotFoundError(source)


def _server_busy_response() -> Response:
    return Response(
        http.HTTPStatus.SERVICE_UNAVAILABLE,
        "SERVER BUSY",
        Headers(**{"Retry-After": "1"}),
        b"SERVER BUSY",
    )


class HttpRequestHandler:
    """HTTP handshake hooks whose mutable state belongs to one server worker."""

    def __init__(
        self,
        *,
        root: Path | None,
        assets: HttpAssetRegistry,
        policy: HttpRequestPolicy,
        auth_guard: HttpPasswordGuard | None,
        viser_proxy: ViserProxy | None = None,
    ) -> None:
        self._viser_proxy = viser_proxy
        self._assets = assets
        self._policy = policy
        self._auth_guard = auth_guard
        self._static = _StaticFileCache(root)
        self._response_budget = _HttpResponseBudget(
            _HTTP_RESPONSE_IN_FLIGHT_MAX_BYTES,
            _HTTP_RESPONSE_IN_FLIGHT_MAX_RESPONSES,
        )

    def process_response(
        self, connection: ServerConnection, request: Request, response: Response
    ) -> Response:
        if self._auth_guard is not None:
            # Never let a shared cache turn one authenticated response into
            # data served to a later anonymous client, regardless of asset type.
            for name in ("Cache-Control", "CDN-Cache-Control"):
                if name in response.headers:
                    del response.headers[name]
                response.headers[name] = "no-store"
        return self._policy.secure_response(response)

    async def process_request(
        self,
        connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        upgrades = request.headers.get_all("Upgrade")
        is_websocket_upgrade = len(upgrades) == 1 and upgrades[0].lower() == "websocket"
        # Websocket connections have separate admission in WebsockServer.
        # Every ordinary HTTP response owns a budget token from the
        # start, including auth/error/zero-byte branches.
        if not is_websocket_upgrade and not self._response_budget.try_reserve(connection, 0):
            return _server_busy_response()

        # Host validation applies to every HTTP request, not only browser
        # websocket handshakes: it is the DNS-rebinding boundary.
        address = self._policy.address(request)
        if address is None:
            return Response(http.HTTPStatus.FORBIDDEN, "FORBIDDEN", Headers(), b"FORBIDDEN")

        # The password gate follows Host/Origin validation so credentials
        # are never evaluated for an untrusted browser endpoint.
        if self._auth_guard is not None:
            guard_response = self._auth_guard.process(request, secure=address.secure)
            if guard_response is not None:
                return guard_response

        if request.path.partition("?")[0].startswith(VISER_PROXY_PREFIX):
            if self._viser_proxy is None or self._viser_proxy.match(request.path) is None:
                return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
            if is_websocket_upgrade:
                return None
            return await self._viser_proxy.http_response(
                request, lambda size: self._response_budget.try_resize(connection, size)
            )

        # Ignore websocket packets. Header duplication is handled without
        # the single-value Headers.get() exception path.
        if is_websocket_upgrade:
            return None

        # Runtime assets take precedence and are available without a static root.
        url_path = request.path.partition("?")[0]
        if url_path.startswith(_HTTP_ASSET_URL_PREFIX):
            return self._asset_response(connection, request, url_path)
        return await self._static_response(connection, request)

    def _asset_response(
        self, connection: ServerConnection, request: Request, url_path: str
    ) -> Response:
        """Serve immutable assets, including bounded single byte ranges for media."""
        payload = self._assets.get(url_path[len(_HTTP_ASSET_URL_PREFIX) :])
        if payload is None:
            return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
        size = len(payload)
        etag = '"' + url_path.rsplit("/", 1)[-1] + '"'
        headers = Headers(
            {
                "Content-Type": _http_content_type(url_path),
                "Cache-Control": "private, max-age=31536000, immutable",
                "Content-Security-Policy": "sandbox; frame-ancestors 'none'",
                "Accept-Ranges": "bytes",
                "ETag": etag,
            }
        )
        status = http.HTTPStatus.OK
        ranges = request.headers.get_all("Range")
        if_range = request.headers.get_all("If-Range")
        start, end = 0, size
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
        if not self._response_budget.try_resize(connection, end - start):
            return _server_busy_response()
        headers["Content-Length"] = str(end - start)
        return Response(status, status.phrase, headers, payload[start:end])

    async def _static_response(self, connection: ServerConnection, request: Request) -> Response:
        """Read a contained static file and apply representation cache semantics."""
        # No files to serve: only the websocket (and the guard above)
        # live on this port.
        if self._static.root is None:
            return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())

        # Normalize traversal lexically before joining. The worker also
        # resolves the selected live/backup candidate and enforces that its
        # real target remains beneath that generation root.
        relpath = _static_relpath(request.path)
        if relpath is None:
            return Response(http.HTTPStatus.NOT_FOUND, "NOT FOUND", Headers())
        source_path = self._static.root / relpath
        use_gzip = _accepts_gzip(request.headers.get_all("Accept-Encoding"))

        mime_type = _http_content_type(relpath)

        try:
            response_payload, etag = await asyncio.get_running_loop().run_in_executor(
                None, self._static.read, source_path, use_gzip
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
                Headers(**cache_headers),
            )

        response_headers = {
            **cache_headers,
            "Content-Type": mime_type,
            "Content-Length": str(len(response_payload)),
            "Content-Encoding": "gzip" if use_gzip else "identity",
        }

        if not self._response_budget.try_resize(connection, len(response_payload)):
            return _server_busy_response()

        return Response(
            http.HTTPStatus.OK,
            "OK",
            Headers(**response_headers),
            response_payload,
        )
