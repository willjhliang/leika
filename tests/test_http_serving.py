from __future__ import annotations

import asyncio
import contextlib
import gzip
import hashlib
import http.client
import os
import struct
import threading
from collections.abc import Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from websockets import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Request
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._client_autobuild
import leika._transport._http_assets as asset_impl
import leika._transport._http_security as security_impl
import leika._transport._websocket as websocket_impl
from leika._transport._http_assets import HttpAsset, HttpAssetRegistry
from leika._transport._typescript import protocol_fingerprint
from leika._transport._websocket import WebsockClientConnection, WebsockServer

PROTOCOL = Subprotocol(f"leika-{protocol_fingerprint()}")


@pytest.fixture(autouse=True)
def _skip_client_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)


async def _ignore(_: WebsockClientConnection) -> None:
    pass


def _server(**kwargs: Any) -> WebsockServer:
    kwargs.setdefault("on_connect", _ignore)
    kwargs.setdefault("on_disconnect", _ignore)
    return WebsockServer("127.0.0.1", 0, verbose=False, **kwargs)


@contextlib.contextmanager
def _serving(**kwargs: Any) -> Iterator[WebsockServer]:
    server = _server(**kwargs)
    server.start()
    try:
        yield server
    finally:
        server.stop()


def _get(port: int, path: str, headers: dict[str, str] | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


def test_index_is_served_from_memory_with_etags_gzip_and_304(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    payload = b"<html>Leika</html>" * 200
    index.write_bytes(payload)
    identity = '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'
    gzipped = identity[:-1] + '-gzip"'
    with _serving(index_html=index) as server:
        for path in ("/", "/index.html", "/?reload=1"):
            status, headers, body = _get(server._port, path)
            assert (status, body) == (200, payload)
            assert headers["etag"] == identity
            assert headers["cache-control"] == "no-cache"
            assert headers["vary"] == "Accept-Encoding"
            assert headers["content-type"] == "text/html; charset=utf-8"
            assert "content-encoding" not in headers

        status, headers, body = _get(server._port, "/", {"Accept-Encoding": "br, GZip"})
        assert status == 200
        assert headers["content-encoding"] == "gzip"
        assert headers["etag"] == gzipped
        assert gzip.decompress(body) == payload

        for encoding, etag in (("identity", identity), ("gzip", gzipped)):
            for condition in (etag, f"W/{etag}", f'"other", {etag}', "*"):
                status, headers, body = _get(
                    server._port, "/", {"Accept-Encoding": encoding, "If-None-Match": condition}
                )
                assert (status, body) == (304, b"")
                assert headers["etag"] == etag
        # Each representation has its own validator.
        assert _get(server._port, "/", {"If-None-Match": gzipped})[0] == 200


def test_only_the_index_routes_serve_the_client_page(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_bytes(b"page")
    (tmp_path / "sibling.js").write_bytes(b"never served")
    with _serving(index_html=index) as server:
        for path in (
            "/sibling.js",
            "/index.htm",
            "/index.html/",
            "/..%2fsibling.js",
            "/leika-assets/missing",
        ):
            assert _get(server._port, path)[0] == 404
        index.unlink()
        assert _get(server._port, "/")[0] == 404
    with _serving() as server:
        assert _get(server._port, "/")[0] == 404


def test_index_reloads_after_an_in_place_rebuild(tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_bytes(b"first bundle")
    with _serving(index_html=index) as server:
        _, first_headers, first = _get(server._port, "/")
        index.write_bytes(b"second bundle, a different size")
        status, second_headers, second = _get(
            server._port, "/", {"If-None-Match": first_headers["etag"]}
        )
        # A same-size rebuild is noticed through its modification time.
        index.write_bytes(second.upper())
        metadata = index.stat()
        os.utime(index, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000))
        _, third_headers, third = _get(server._port, "/")

    assert first == b"first bundle"
    assert (status, second) == (200, b"second bundle, a different size")
    assert third == b"SECOND BUNDLE, A DIFFERENT SIZE"
    assert len({first_headers["etag"], second_headers["etag"], third_headers["etag"]}) == 3


def test_registered_asset_is_an_immutable_snapshot_served_from_memory(tmp_path: Path) -> None:
    source = tmp_path / "asset.txt"
    source.write_bytes(b"first")
    with _serving() as server:
        first = server.register_http_asset(source).url
        source.write_bytes(b"other")
        second = server.register_http_asset(source).url
        source.unlink()
        assert _get(server._port, first)[2] == b"first"
        assert _get(server._port, second)[2] == b"other"
    assert first != second


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 7


def test_asset_names_carry_content_hash_picture_size_and_safe_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = HttpAssetRegistry()
    picture = tmp_path / "Figure.GIF"
    picture.write_bytes(_gif(640, 360))
    digest = hashlib.sha256(picture.read_bytes()).hexdigest()
    assert registry.register(picture) == HttpAsset(
        f"/leika-assets/{digest}-640x360.gif", (640, 360)
    )

    odd = tmp_path / "notes.bad_suffix"
    odd.write_bytes(b"text")
    digest = hashlib.sha256(b"text").hexdigest()
    assert registry.register(odd) == HttpAsset(f"/leika-assets/{digest}", None)

    monkeypatch.setattr(asset_impl, "_HTTP_ASSET_MAX_BYTES", 4)
    oversized = tmp_path / "large.bin"
    oversized.write_bytes(b"12345")
    with pytest.raises(ValueError, match="larger"):
        registry.register(oversized)


def test_equal_assets_share_a_snapshot_and_the_oldest_are_evicted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asset_impl, "_HTTP_ASSET_CACHE_MAX_BYTES", 10)
    registry = HttpAssetRegistry()

    def register(name: str, content: bytes) -> str:
        path = tmp_path / name
        path.write_bytes(content)
        return registry.register(path).url.removeprefix("/leika-assets/")

    shared = register("first.txt", b"shared")
    older = register("next.txt", b"next")
    # Re-registering equal bytes reuses the snapshot and refreshes its age.
    assert register("copy.txt", b"shared") == shared
    assert registry._bytes == 10
    newest = register("more.txt", b"more")
    assert registry.get(older) is None
    assert registry.get(shared) == b"shared"
    assert registry.get(newest) == b"more"
    assert registry._bytes == 10


def test_runtime_assets_are_released_on_stop(tmp_path: Path) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"cached")
    with _serving() as server:
        url = server.register_http_asset(asset).url
        assert _get(server._port, url)[2] == b"cached"
    registry = server._http_asset_registry
    assert (registry._snapshots, registry._bytes) == ({}, 0)
    with pytest.raises(RuntimeError, match="after server shutdown"):
        server.register_http_asset(asset)


def test_runtime_assets_are_csp_sandboxed_even_when_embedding_is_allowed(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.html"
    active.write_text("<script>parent.document.body.textContent = 'owned'</script>")
    with _serving(allow_embedding=True) as server:
        status, headers, body = _get(server._port, server.register_http_asset(active).url)
    assert status == 200
    assert body.startswith(b"<script>")
    assert headers["content-type"] == "text/html"
    assert headers["content-security-policy"] == "sandbox; frame-ancestors 'none'"
    assert headers["cache-control"] == "private, max-age=31536000, immutable"
    assert headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("value", "status", "body", "content_range"),
    [
        ("bytes=2-5", 206, b"2345", "bytes 2-5/10"),
        ("bytes=7-", 206, b"789", "bytes 7-9/10"),
        ("bytes=-3", 206, b"789", "bytes 7-9/10"),
        ("bytes=8-99", 206, b"89", "bytes 8-9/10"),
        ("bytes=10-", 416, b"", "bytes */10"),
        ("bytes=-0", 416, b"", "bytes */10"),
        ("bytes=4-2", 200, b"0123456789", None),
        ("bytes=0-1,3-4", 200, b"0123456789", None),
        ("bytes=nope", 200, b"0123456789", None),
    ],
)
def test_runtime_asset_byte_ranges(
    server: leika.Server,
    tmp_path: Path,
    value: str,
    status: int,
    body: bytes,
    content_range: str | None,
) -> None:
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"0123456789")
    url = server.register_http_asset(clip)
    actual, headers, payload = _get(server.port, url, {"Range": value})
    assert actual == status
    assert payload == body
    assert headers.get("content-range") == content_range
    assert headers["accept-ranges"] == "bytes"
    assert int(headers["content-length"]) == len(body)
    assert _get(server.port, url, {"Range": "bytes=0-1", "If-Range": '"stale"'})[0] == 200
    assert _get(server.port, url, {"Range": "bytes=0-1", "If-Range": headers["etag"]})[0] == 206


def test_ephemeral_port_is_reported_back() -> None:
    """`port=0` asks the OS to choose; the server must report the real port."""
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    try:
        assert server.port != 0
        assert str(server.port) in server.url
        status, _, body = _get(server.port, "/")
        assert status == 200
        assert body
    finally:
        server.stop()


def test_start_propagates_background_worker_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _server()
    failure = RuntimeError("startup failed before ready")

    def fail_before_ready(_: Future[None]) -> None:
        raise failure

    monkeypatch.setattr(server, "_background_worker", fail_before_ready)
    with pytest.raises(RuntimeError, match="startup failed before ready") as captured:
        server.start()

    assert captured.value is failure
    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_http_setup_failure_releases_worker_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    loops: list[asyncio.AbstractEventLoop] = []
    new_event_loop = asyncio.new_event_loop

    def capture_loop() -> asyncio.AbstractEventLoop:
        loop = new_event_loop()
        loops.append(loop)
        return loop

    def fail_setup(**_: object) -> None:
        raise OSError("HTTP setup failed")

    monkeypatch.setattr(asyncio, "new_event_loop", capture_loop)
    monkeypatch.setattr(websocket_impl, "HttpRequestHandler", fail_setup)
    server = _server()
    with pytest.raises(OSError, match="HTTP setup failed"):
        server.start()

    assert len(loops) == 1
    assert loops[0].is_closed()
    assert server._background_event_loop is None
    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_failing_connect_callback_is_isolated_and_teardown_cleans_state(
    capsys: pytest.CaptureFixture[str],
) -> None:
    disconnected = threading.Event()

    async def fail_connect(_: WebsockClientConnection) -> None:
        raise RuntimeError("connect callback failed")

    async def mark_disconnected(_: WebsockClientConnection) -> None:
        disconnected.set()

    with _serving(on_connect=fail_connect, on_disconnect=mark_disconnected) as server:
        with connect(
            f"ws://127.0.0.1:{server._port}", subprotocols=[PROTOCOL], open_timeout=5
        ) as websocket:
            # The connection outlives its failed callback.
            assert websocket.ping().wait(2.0)
        assert disconnected.wait(2.0)
        assert server._client_state_from_id == {}
    assert "RuntimeError: connect callback failed" in capsys.readouterr().err


def _request(*headers: tuple[str, str], path: str = "/") -> Request:
    return Request(path, Headers(headers))


@pytest.mark.parametrize(
    "host",
    [
        "",
        " ",
        "example.com:8080",
        "foo bar",
        "*",
        "under_score.example",
        "foo\x00bar",
        "example.com/path",
        "example.com?query",
        "example.com#fragment",
        "example.com,evil.example",
        1,
    ],
)
def test_allowed_host_configuration_rejects_malformed_names(host: Any) -> None:
    with pytest.raises(ValueError, match="Invalid allowed host"):
        security_impl._normalize_allowed_hosts([host])


def test_allowed_hosts_are_canonicalized_and_collapse_duplicates() -> None:
    assert security_impl._normalize_allowed_hosts(
        ("Example.COM", "example.com.", "FD7A::1")
    ) == frozenset({"example.com", "fd7a::1"})
    with pytest.raises(TypeError, match="not one string"):
        security_impl._normalize_allowed_hosts("example.com")


@pytest.mark.parametrize(
    ("authority", "scheme", "expected"),
    [
        ("example.com", "http", ("http", "example.com", 80)),
        ("example.com:443", "https", ("https", "example.com", 443)),
        ("[::1]", "http", ("http", "::1", 80)),
        ("[fe80::1%25eth0]:8080", "http", ("http", "fe80::1%eth0", 8080)),
        ("example.com/", "http", None),
        ("example.com?x", "http", None),
        ("example.com#x", "http", None),
        ("user@example.com", "http", None),
        ("example.com:99999", "http", None),
    ],
)
def test_authority_normalization_is_strict(
    authority: str, scheme: str, expected: tuple[str, str, int] | None
) -> None:
    assert security_impl._parse_authority(authority, scheme) == expected


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://example.com", ("https", "example.com", 443)),
        ("http://[::1]:8080", ("http", "::1", 8080)),
        ("https://example.com/", None),
        ("https://example.com?x", None),
        ("null", None),
        ("ftp://example.com", None),
    ],
)
def test_origin_normalization_is_strict(origin: str, expected: tuple[str, str, int] | None) -> None:
    assert security_impl._parse_origin(origin) == expected


def test_wildcard_bind_blocks_dns_rebinding_and_preserves_ip_access() -> None:
    kwargs = {
        "bind_host": "0:0:0:0:0:0:0:0",
        "allowed_hosts": frozenset(),
        "trusted_proxy_hosts": frozenset(),
    }
    assert security_impl._request_address(_request(("Host", "attacker.example")), **kwargs) is None
    assert security_impl._request_address(_request(("Host", "localhost:8080")), **kwargs)
    assert security_impl._request_address(_request(("Host", "192.168.1.5:8080")), **kwargs)
    assert security_impl._request_address(_request(("Host", "[::1]:8080")), **kwargs)

    allowed = security_impl._request_address(
        _request(("Host", "dashboard.tailnet.example:8080")),
        bind_host="::",
        allowed_hosts=frozenset({"dashboard.tailnet.example"}),
        trusted_proxy_hosts=frozenset(),
    )
    assert allowed is not None
    assert allowed.origin == ("http", "dashboard.tailnet.example", 8080)


def test_explicit_and_loopback_binds_allow_only_sane_host_forms() -> None:
    common = {"allowed_hosts": frozenset(), "trusted_proxy_hosts": frozenset()}
    assert security_impl._request_address(
        _request(("Host", "dashboard.example:9000")),
        bind_host="dashboard.example",
        **common,
    )
    assert (
        security_impl._request_address(
            _request(("Host", "other.example:9000")),
            bind_host="dashboard.example",
            **common,
        )
        is None
    )
    assert security_impl._request_address(
        _request(("Host", "localhost:9000")),
        bind_host="127.0.0.1",
        **common,
    )
    assert security_impl._request_address(
        _request(("Host", "[::1]:9000")),
        bind_host="127.0.0.1",
        **common,
    )


def test_browser_origin_must_match_effective_origin() -> None:
    common = {
        "bind_host": "0.0.0.0",
        "allowed_hosts": frozenset(),
        "trusted_proxy_hosts": frozenset(),
    }
    assert security_impl._request_address(
        _request(("Host", "127.0.0.1:8080"), ("Origin", "http://127.0.0.1:8080")),
        **common,
    )
    assert (
        security_impl._request_address(
            _request(("Host", "127.0.0.1:8080"), ("Origin", "https://evil.example")),
            **common,
        )
        is None
    )
    assert (
        security_impl._request_address(
            _request(
                ("Host", "127.0.0.1:8080"),
                ("Origin", "http://127.0.0.1:8080"),
                ("Origin", "http://127.0.0.1:8080"),
            ),
            **common,
        )
        is None
    )


def test_quick_tunnel_forwarding_is_narrow_and_exact() -> None:
    common = {
        "bind_host": "127.0.0.1",
        "allowed_hosts": frozenset(),
        "trusted_proxy_hosts": frozenset({"quick.trycloudflare.com"}),
    }
    direct = security_impl._request_address(
        _request(
            ("Host", "quick.trycloudflare.com"),
            ("X-Forwarded-Proto", "https"),
            ("Origin", "https://quick.trycloudflare.com"),
        ),
        **common,
    )
    assert direct is not None and direct.secure
    assert direct.origin == ("https", "quick.trycloudflare.com", 443)

    with_host = security_impl._request_address(
        _request(
            ("Host", "quick.trycloudflare.com"),
            ("X-Forwarded-Proto", "https"),
            ("X-Forwarded-Host", "quick.trycloudflare.com"),
        ),
        **common,
    )
    assert with_host is not None and with_host.secure

    refused = [
        _request(("Host", "quick.trycloudflare.com"), ("X-Forwarded-Proto", "http")),
        _request(
            ("Host", "quick.trycloudflare.com"),
            ("X-Forwarded-Proto", "https,http"),
        ),
        _request(
            ("Host", "quick.trycloudflare.com"),
            ("X-Forwarded-Proto", "https"),
            ("X-Forwarded-Host", "evil.example"),
        ),
        _request(
            ("Host", "quick.trycloudflare.com"),
            ("X-Forwarded-Proto", "https"),
            ("X-Forwarded-Host", "quick.trycloudflare.com:8443"),
        ),
        _request(("Host", "untrusted.example"), ("X-Forwarded-Proto", "https")),
    ]
    assert all(security_impl._request_address(request, **common) is None for request in refused)


def test_real_websocket_origin_rejection_does_not_harm_server_health() -> None:
    with _serving() as server:
        url = f"ws://127.0.0.1:{server._port}"
        with pytest.raises(InvalidStatus) as rejected:
            connect(url, origin="https://evil.example", subprotocols=[PROTOCOL], open_timeout=2)
        assert rejected.value.response.status_code == 403

        with connect(
            url,
            origin=f"http://127.0.0.1:{server._port}",
            subprotocols=[PROTOCOL],
            open_timeout=2,
        ):
            pass


def test_security_headers_cover_success_not_found_and_embedding_opt_in(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.html"
    index.write_bytes(b"<html>safe</html>")
    for allow_embedding in (False, True):
        with _serving(index_html=index, allow_embedding=allow_embedding) as server:
            for path in ("/", "/missing"):
                _, headers, _ = _get(server._port, path)
                assert headers["x-content-type-options"] == "nosniff"
                assert headers["referrer-policy"] == "no-referrer"
                assert headers["cross-origin-resource-policy"] == "same-origin"
                if allow_embedding:
                    assert "content-security-policy" not in headers
                else:
                    assert headers["content-security-policy"] == "frame-ancestors 'none'"


@pytest.mark.parametrize(
    "method,invalid_headers",
    [
        ("POST", {}),
        ("GET", {"Sec-WebSocket-Key": "invalid"}),
        ("GET", {"Sec-WebSocket-Protocol": "not a token"}),
    ],
)
def test_native_handshake_errors_receive_security_headers(method, invalid_headers) -> None:
    with leika.Server(host="127.0.0.1", port=0, verbose=False) as server:
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        try:
            connection.request(
                method,
                "/",
                headers={
                    "Connection": "Upgrade",
                    "Upgrade": "websocket",
                    "Sec-WebSocket-Version": "13",
                    "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                    **invalid_headers,
                },
            )
            response = connection.getresponse()
            assert response.status == 400
            assert response.headers.get_all("Connection") == ["close"]
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
            assert response.read()
        finally:
            connection.close()
        assert _get(server.port, "/")[0] == 200


def test_ordinary_http_forces_close_and_sequential_client_requests_reconnect(
    tmp_path: Path,
) -> None:
    index = tmp_path / "index.html"
    index.write_bytes(b"ok")
    with _serving(index_html=index) as server:
        connection = http.client.HTTPConnection("127.0.0.1", server._port, timeout=5)
        try:
            for _ in range(2):
                connection.request("GET", "/", headers={"Connection": "keep-alive"})
                response = connection.getresponse()
                assert response.status == 200
                assert response.getheader("Connection") == "close"
                assert response.read() == b"ok"
        finally:
            connection.close()
