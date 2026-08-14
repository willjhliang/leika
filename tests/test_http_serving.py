from __future__ import annotations

import gzip
import http.client
import os
import re
import socket
import threading
import time
from concurrent.futures import Future
from pathlib import Path

import pytest
from websockets import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Request
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._messages
import leika.infra._infra as infra_impl
from leika import infra


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


@pytest.mark.parametrize(
    "target",
    [
        "/C:/Windows/win.ini",
        "/C:Windows/win.ini",
        "/%43%3A/Windows/win.ini",
        r"/C:\Windows\win.ini",
        "/index.html:private-stream",
        "/nested/../secret.txt",
        "/file%00.txt",
        "/file%1f.txt",
        "/file%7f.txt",
    ],
)
def test_static_target_rejects_cross_platform_escape_syntax(target: str) -> None:
    assert infra_impl._static_relpath(target) is None


@pytest.mark.parametrize(
    ("header", "accepted"),
    [
        ("gzip", True),
        ("GZip; q=0.5", True),
        ("br, *;q=0.25", True),
        ("gzip;q=0", False),
        ("gzip;q=0, *;q=1", False),
        ("br, xgzip", False),
        ("gzip;q=not-a-number", False),
        ("*;q=0", False),
    ],
)
def test_accept_encoding_gzip_quality(header: str, accepted: bool) -> None:
    assert infra_impl._accepts_gzip([header]) is accepted


def test_http_root_requires_path_and_is_resolved_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(TypeError, match="pathlib.Path"):
        infra.WebsockServer(
            host="127.0.0.1",
            port=0,
            http_server_root="served",  # type: ignore[arg-type]
            verbose=False,
        )

    first_cwd = tmp_path / "first"
    second_cwd = tmp_path / "second"
    first_root = first_cwd / "served"
    second_root = second_cwd / "served"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)
    (first_root / "index.html").write_bytes(b"first root")
    (second_root / "index.html").write_bytes(b"second root")

    monkeypatch.chdir(first_cwd)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=Path("served"),
        verbose=False,
    )
    assert server._http_server_root == first_root.resolve()
    monkeypatch.chdir(second_cwd)
    server.start()
    try:
        assert _get(server._port, "/")[2] == b"first root"
    finally:
        server.stop()


def test_http_response_budget_is_aggregate_and_released_on_connection_close() -> None:
    class Connection:
        def __init__(self) -> None:
            self.connection_lost_waiter: Future[None] = Future()

    budget = infra_impl._HttpResponseBudget(7, 2)
    first = Connection()
    second = Connection()
    assert budget.try_reserve(first, 5)  # type: ignore[arg-type]
    assert not budget.try_reserve(second, 3)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="already owns"):
        budget.try_reserve(first, 1)  # type: ignore[arg-type]

    first.connection_lost_waiter.set_result(None)
    assert budget._bytes == 0
    assert budget.try_reserve(second, 3)  # type: ignore[arg-type]
    second.connection_lost_waiter.set_result(None)
    assert budget._bytes == 0


def test_http_response_budget_bounds_zero_byte_owners_and_releases_capacity() -> None:
    class Connection:
        def __init__(self) -> None:
            self.connection_lost_waiter: Future[None] = Future()

    budget = infra_impl._HttpResponseBudget(100, 2)
    first = Connection()
    second = Connection()
    third = Connection()
    assert budget.try_reserve(first, 0)  # type: ignore[arg-type]
    assert budget.try_reserve(second, 0)  # type: ignore[arg-type]
    assert not budget.try_reserve(third, 0)  # type: ignore[arg-type]

    first.connection_lost_waiter.set_result(None)
    assert budget.try_reserve(third, 0)  # type: ignore[arg-type]
    second.connection_lost_waiter.set_result(None)
    third.connection_lost_waiter.set_result(None)
    assert budget._reserved_from_connection == {}


def test_http_response_owner_overload_returns_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_bytes(b"ok")
    monkeypatch.setattr(infra_impl, "_HTTP_RESPONSE_IN_FLIGHT_MAX_RESPONSES", 0)
    server = infra.WebsockServer(host="127.0.0.1", port=0, http_server_root=served, verbose=False)
    server.start()
    try:
        status, headers, body = _get(server._port, "/")
        assert status == 503
        assert headers["retry-after"] == "1"
        assert body == b"SERVER BUSY"
    finally:
        server.stop()


def test_large_http_responses_share_one_aggregate_admission_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_bytes(b"1234")
    (served / "large.bin").write_bytes(b"12345")
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"abcde")
    monkeypatch.setattr(infra_impl, "_HTTP_RESPONSE_IN_FLIGHT_MAX_BYTES", 4)
    server = infra.WebsockServer(host="127.0.0.1", port=0, http_server_root=served, verbose=False)
    asset_url = server.register_http_asset(asset).url
    server.start()
    try:
        for path in (asset_url, "/large.bin"):
            status, headers, body = _get(server._port, path)
            assert status == 503
            assert headers["retry-after"] == "1"
            assert body == b"SERVER BUSY"
        assert _get(server._port, "/")[2] == b"1234"
    finally:
        server.stop()


def test_etag_gzip_and_traversal(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    payload = b"<html>Leika</html>" * 200
    (served / "index.html").write_bytes(payload)
    server = infra.WebsockServer(
        host="127.0.0.1", port=_free_port(), http_server_root=served, verbose=False
    )
    server.start()
    try:
        time.sleep(0.05)
        status, headers, body = _get(server._port, "/")
        assert status == 200
        assert body == payload
        assert headers["cache-control"] == "no-cache"
        etag = headers["etag"]

        status, _, body = _get(server._port, "/", {"If-None-Match": etag})
        assert status == 304
        assert body == b""

        status, headers, body = _get(server._port, "/", {"Accept-Encoding": "gzip"})
        assert status == 200
        assert headers["content-encoding"] == "gzip"
        assert gzip.decompress(body) == payload

        for refused in ("gzip;q=0", "br, xgzip"):
            status, headers, body = _get(server._port, "/", {"Accept-Encoding": refused})
            assert status == 200
            assert headers["content-encoding"] == "identity"
            assert body == payload

        assert _get(server._port, "/..%2f..%2fetc%2fpasswd")[0] == 404
    finally:
        server.stop()


def test_registered_asset_requires_a_path_object() -> None:
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    with pytest.raises(TypeError, match="pathlib.Path"):
        server.register_http_asset("asset.png")  # type: ignore[arg-type]


def test_registered_asset_url_is_an_immutable_snapshot(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_bytes(b"<html></html>")
    asset_path = tmp_path / "asset.txt"
    asset_path.write_bytes(b"first")

    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    first_url = server.register_http_asset(asset_path).url
    server.start()
    try:
        assert _get(server._port, first_url)[2] == b"first"

        # A registered URL owns the bytes it hashed, independent of later file
        # mutation or deletion. Re-registering changed bytes creates a new URL.
        asset_path.write_bytes(b"other")
        assert _get(server._port, first_url)[2] == b"first"

        second_url = server.register_http_asset(asset_path).url
        assert second_url != first_url
        assert _get(server._port, second_url)[2] == b"other"
    finally:
        server.stop()


def test_registered_asset_keeps_a_relative_source_across_cwd_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "asset.txt").write_bytes(b"stable")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(source_dir)
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    url = server.register_http_asset(Path("asset.txt")).url
    monkeypatch.chdir(elsewhere)
    server.start()
    try:
        assert _get(server._port, url)[2] == b"stable"
    finally:
        server.stop()


def test_equal_registered_assets_share_one_snapshot(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"shared")
    second.write_bytes(b"shared")

    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    first_url = server.register_http_asset(first).url
    assert server.register_http_asset(second).url == first_url
    name = first_url.rsplit("/", 1)[-1]
    assert server._http_assets[name] == b"shared"
    assert server._http_asset_bytes == len(b"shared")


def test_registered_asset_snapshot_cache_evicts_by_aggregate_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(infra_impl, "_HTTP_ASSET_CACHE_MAX_BYTES", 7)
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"first")
    second.write_bytes(b"next")

    first_url = server.register_http_asset(first).url
    second_url = server.register_http_asset(second).url
    assert first_url != second_url
    assert first_url.rsplit("/", 1)[-1] not in server._http_assets
    assert server._http_assets[second_url.rsplit("/", 1)[-1]] == b"next"
    assert server._http_asset_bytes == 4


def test_ephemeral_port_is_reported_back(monkeypatch) -> None:
    """`port=0` asks the OS to choose; the server must report the real port."""
    import leika
    import leika._client_autobuild

    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
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
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    failure = RuntimeError("startup failed before ready")

    def fail_before_ready(_: Future[None]) -> None:
        raise failure

    monkeypatch.setattr(server, "_background_worker", fail_before_ready)
    with pytest.raises(RuntimeError, match="startup failed before ready") as captured:
        server.start()

    assert captured.value is failure
    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_failing_connect_callback_is_isolated_and_teardown_cleans_state() -> None:
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    connected = threading.Event()
    disconnected = threading.Event()

    def fail_connect(_: infra.WebsockClientConnection) -> None:
        raise RuntimeError("connect callback failed")

    def mark_disconnected(_: infra.WebsockClientConnection) -> None:
        disconnected.set()

    server.on_client_connect(fail_connect)
    server.on_client_connect(lambda _: connected.set())
    server.on_client_disconnect(mark_disconnected)
    server.start()
    subprotocol = Subprotocol(
        f"leika-v{leika.__version__}+p{infra.protocol_fingerprint(leika._messages.Message)}"
    )
    try:
        with connect(
            f"ws://127.0.0.1:{server._port}",
            subprotocols=[subprotocol],
            open_timeout=5,
        ):
            assert connected.wait(2.0)

        assert disconnected.wait(2.0)
        assert server._client_state_from_id == {}
    finally:
        server.stop()


def test_registered_assets_require_regular_files(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFOs are not available on this platform")
    fifo = tmp_path / "asset.fifo"
    os.mkfifo(fifo)
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)

    # This must reject before opening the FIFO; there is deliberately no writer
    # on the other end to rescue a blocking implementation.
    started = time.monotonic()
    with pytest.raises(ValueError, match="regular file"):
        server.register_http_asset(fifo)
    assert time.monotonic() - started < 1.0


def test_registered_asset_requests_do_not_reread_the_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"asset")
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    url = server.register_http_asset(asset).url

    def unexpected_read(path: Path, max_bytes: int) -> bytes:
        raise AssertionError(f"request reread {path} with limit {max_bytes}")

    monkeypatch.setattr(infra_impl, "_read_bounded_file", unexpected_read)
    server.start()
    try:
        assert _get(server._port, url)[2] == b"asset"
    finally:
        server.stop()


def test_registered_asset_rejects_oversized_and_unsafe_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(infra_impl, "_HTTP_ASSET_MAX_BYTES", 4)
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    oversized = tmp_path / "large.bin"
    oversized.write_bytes(b"12345")
    with pytest.raises(ValueError, match="larger"):
        server.register_http_asset(oversized)

    odd = tmp_path / "asset.?#%"
    odd.write_bytes(b"1234")
    url = server.register_http_asset(odd).url
    name = url.rsplit("/", 1)[-1]
    assert len(name) == 64
    assert all(char in "0123456789abcdef" for char in name)


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
    ],
)
def test_allowed_host_configuration_rejects_malformed_names(host: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        infra.WebsockServer(
            host="127.0.0.1",
            port=0,
            allowed_hosts=[host],
            verbose=False,
        )


def test_allowed_hosts_reject_duplicates_after_normalization() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        infra.WebsockServer(
            host="127.0.0.1",
            port=0,
            allowed_hosts=["Example.COM", "example.com."],
            verbose=False,
        )


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
    assert infra_impl._parse_authority(authority, scheme) == expected


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
    assert infra_impl._parse_origin(origin) == expected


def test_wildcard_bind_blocks_dns_rebinding_and_preserves_ip_access() -> None:
    kwargs = {
        "bind_host": "0:0:0:0:0:0:0:0",
        "allowed_hosts": frozenset(),
        "trusted_proxy_hosts": frozenset(),
    }
    assert infra_impl._request_address(_request(("Host", "attacker.example")), **kwargs) is None
    assert infra_impl._request_address(_request(("Host", "localhost:8080")), **kwargs)
    assert infra_impl._request_address(_request(("Host", "192.168.1.5:8080")), **kwargs)
    assert infra_impl._request_address(_request(("Host", "[::1]:8080")), **kwargs)

    allowed = infra_impl._request_address(
        _request(("Host", "dashboard.tailnet.example:8080")),
        bind_host="::",
        allowed_hosts=frozenset({"dashboard.tailnet.example"}),
        trusted_proxy_hosts=frozenset(),
    )
    assert allowed is not None
    assert allowed.origin == ("http", "dashboard.tailnet.example", 8080)


def test_explicit_and_loopback_binds_allow_only_sane_host_forms() -> None:
    common = {"allowed_hosts": frozenset(), "trusted_proxy_hosts": frozenset()}
    assert infra_impl._request_address(
        _request(("Host", "dashboard.example:9000")),
        bind_host="dashboard.example",
        **common,
    )
    assert (
        infra_impl._request_address(
            _request(("Host", "other.example:9000")),
            bind_host="dashboard.example",
            **common,
        )
        is None
    )
    assert infra_impl._request_address(
        _request(("Host", "localhost:9000")),
        bind_host="127.0.0.1",
        **common,
    )
    assert infra_impl._request_address(
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
    assert infra_impl._request_address(
        _request(("Host", "127.0.0.1:8080"), ("Origin", "http://127.0.0.1:8080")),
        **common,
    )
    assert (
        infra_impl._request_address(
            _request(("Host", "127.0.0.1:8080"), ("Origin", "https://evil.example")),
            **common,
        )
        is None
    )
    assert (
        infra_impl._request_address(
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
    direct = infra_impl._request_address(
        _request(
            ("Host", "quick.trycloudflare.com"),
            ("X-Forwarded-Proto", "https"),
            ("Origin", "https://quick.trycloudflare.com"),
        ),
        **common,
    )
    assert direct is not None and direct.secure
    assert direct.origin == ("https", "quick.trycloudflare.com", 443)

    with_host = infra_impl._request_address(
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
    assert all(infra_impl._request_address(request, **common) is None for request in refused)


def test_real_websocket_origin_rejection_does_not_harm_server_health() -> None:
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    server.start()
    url = f"ws://127.0.0.1:{server._port}"
    protocol = Subprotocol(
        f"leika-v{leika.__version__}+p{infra.protocol_fingerprint(leika._messages.Message)}"
    )
    try:
        with pytest.raises(InvalidStatus) as rejected:
            connect(
                url,
                origin="https://evil.example",
                subprotocols=[protocol],
                open_timeout=2,
            )
        assert rejected.value.response.status_code == 403

        with connect(
            url,
            origin=f"http://127.0.0.1:{server._port}",
            subprotocols=[protocol],
            open_timeout=2,
        ):
            pass
    finally:
        server.stop()


def test_security_headers_cover_success_not_found_and_embedding_opt_in(
    tmp_path: Path,
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_bytes(b"<html>safe</html>")
    for allow_embedding in (False, True):
        server = infra.WebsockServer(
            host="127.0.0.1",
            port=0,
            http_server_root=served,
            allow_embedding=allow_embedding,
            verbose=False,
        )
        server.start()
        try:
            for path in ("/", "/missing"):
                _, headers, _ = _get(server._port, path)
                assert headers["x-content-type-options"] == "nosniff"
                assert headers["referrer-policy"] == "no-referrer"
                assert headers["cross-origin-resource-policy"] == "same-origin"
                if allow_embedding:
                    assert "content-security-policy" not in headers
                else:
                    assert headers["content-security-policy"] == "frame-ancestors 'none'"
        finally:
            server.stop()


def test_static_cache_observes_an_in_place_client_rebuild(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    source = served / "index.html"
    source.write_bytes(b"first bundle")
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    server.start()
    try:
        _, first_headers, first_payload = _get(server._port, "/")
        source.write_bytes(b"second bundle with a different size")
        _, second_headers, second_payload = _get(server._port, "/")
    finally:
        server.stop()

    assert first_payload == b"first bundle"
    assert second_payload == b"second bundle with a different size"
    assert first_headers["etag"] != second_headers["etag"]


def test_static_server_finishes_a_request_across_atomic_build_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = tmp_path / "client"
    served = client / "build"
    served.mkdir(parents=True)
    source = served / "index.html"
    old_payload = b"complete old generation"
    source.write_bytes(old_payload)
    backup = served.with_name(infra_impl._BUILD_BACKUP_DIR_NAME)
    monkeypatch.setattr(infra_impl, "_MANAGED_CLIENT_BUILD_ROOT", served)
    original = infra_impl._read_bounded_file
    swapped = False

    def swap_after_stat(path: Path, limit: int, **kwargs: object) -> bytes:
        nonlocal swapped
        if path == source and not swapped:
            swapped = True
            os.replace(served, backup)
        return original(path, limit, **kwargs)

    monkeypatch.setattr(infra_impl, "_read_bounded_file", swap_after_stat)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    server.start()
    try:
        status, _, body = _get(server._port, "/")
        assert status == 200
        assert body == old_payload
        assert swapped

        # Once the live root is back, it wins over the retained backup and is
        # cached under a distinct generation key.
        served.mkdir()
        new_payload = b"complete new generation"
        (served / "index.html").write_bytes(new_payload)
        status, _, body = _get(server._port, "/")
        assert status == 200
        assert body == new_payload
    finally:
        server.stop()


def test_static_server_retries_a_live_generation_published_after_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = tmp_path / "client"
    served = client / "build"
    served.mkdir(parents=True)
    source = served / "index.html"
    source.write_bytes(b"old generation")
    backup = served.with_name(infra_impl._BUILD_BACKUP_DIR_NAME)
    monkeypatch.setattr(infra_impl, "_MANAGED_CLIENT_BUILD_ROOT", served)
    original = infra_impl._read_bounded_file
    replaced = False

    def replace_during_first_read(path: Path, limit: int, **kwargs: object) -> bytes:
        nonlocal replaced
        if path == source and not replaced:
            replaced = True
            os.replace(served, backup)
            served.mkdir()
            source.write_bytes(b"new generation")
            raise FileNotFoundError(path)
        return original(path, limit, **kwargs)

    monkeypatch.setattr(infra_impl, "_read_bounded_file", replace_during_first_read)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    server.start()
    try:
        status, _, body = _get(server._port, "/")
    finally:
        server.stop()

    assert replaced
    assert status == 200
    assert body == b"new generation"


def test_static_server_never_uses_backup_for_a_missing_live_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = tmp_path / "client"
    served = client / "build"
    served.mkdir(parents=True)
    (served / "index.html").write_bytes(b"new")
    backup = served.with_name(infra_impl._BUILD_BACKUP_DIR_NAME)
    backup.mkdir()
    (backup / "removed.js").write_bytes(b"old generation only")
    monkeypatch.setattr(infra_impl, "_MANAGED_CLIENT_BUILD_ROOT", served)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    server.start()
    try:
        assert _get(server._port, "/removed.js")[0] == 404
    finally:
        server.stop()


def test_static_cache_evicts_by_byte_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    first = served / "first.txt"
    second = served / "second.txt"
    first.write_bytes(b"first!")
    second.write_bytes(b"second")
    monkeypatch.setattr(infra_impl, "_HTTP_STATIC_CACHE_MAX_BYTES", 10)
    calls: list[Path] = []
    original = infra_impl._read_bounded_file

    def record(path: Path, limit: int, **kwargs: object) -> bytes:
        calls.append(path)
        return original(path, limit, **kwargs)

    monkeypatch.setattr(infra_impl, "_read_bounded_file", record)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    server.start()
    try:
        assert _get(server._port, "/first.txt")[2] == b"first!"
        assert _get(server._port, "/second.txt")[2] == b"second"
        assert _get(server._port, "/first.txt")[2] == b"first!"
    finally:
        server.stop()
    assert calls.count(first) == 2
    assert calls.count(second) == 1


def test_static_file_disappearing_during_worker_read_is_a_clean_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    source = served / "gone.txt"
    source.write_bytes(b"gone")
    original = infra_impl._read_bounded_file
    removed = False

    def remove_before_read(path: Path, limit: int, **kwargs: object) -> bytes:
        nonlocal removed
        if path == source and not removed:
            removed = True
            source.unlink()
        return original(path, limit, **kwargs)

    monkeypatch.setattr(infra_impl, "_read_bounded_file", remove_before_read)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    server.start()
    try:
        status, _, _ = _get(server._port, "/gone.txt")
        assert status == 404
        assert removed
    finally:
        server.stop()


def test_static_file_over_response_limit_is_rejected_without_harming_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "large.bin").write_bytes(b"12345")
    (served / "small.bin").write_bytes(b"1234")
    monkeypatch.setattr(infra_impl, "_HTTP_STATIC_CACHE_MAX_BYTES", 4)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    server.start()
    try:
        assert _get(server._port, "/large.bin")[0] == 413
        status, _, body = _get(server._port, "/small.bin")
        assert status == 200
        assert body == b"1234"
    finally:
        server.stop()


def test_runtime_assets_are_csp_sandboxed_even_when_embedding_is_allowed(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.html"
    active.write_text("<script>parent.document.body.textContent = 'owned'</script>")
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False, allow_embedding=True)
    url = server.register_http_asset(active).url
    server.start()
    try:
        status, headers, body = _get(server._port, url)
        assert status == 200
        assert body.startswith(b"<script>")
        assert headers["content-security-policy"] == "sandbox; frame-ancestors 'none'"
        assert headers["x-content-type-options"] == "nosniff"
    finally:
        server.stop()


def test_static_root_symlink_cannot_serve_outside_file(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_text("healthy")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = served / "escape.txt"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is unavailable on this platform")

    server = infra.WebsockServer(host="127.0.0.1", port=0, http_server_root=served, verbose=False)
    server.start()
    try:
        assert _get(server._port, "/escape.txt")[0] == 404
        assert _get(server._port, "/")[2] == b"healthy"
    finally:
        server.stop()


def test_static_containment_identity_survives_symlink_swap_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    source = served / "asset.txt"
    source.write_text("inside")
    healthy = served / "healthy.txt"
    healthy.write_text("healthy")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    displaced = tmp_path / "inside.txt"
    original = infra_impl._read_bounded_file
    swapped = False

    def swap_before_open(path: Path, limit: int, **kwargs: object) -> bytes:
        nonlocal swapped
        if path == source and not swapped:
            swapped = True
            source.rename(displaced)
            try:
                source.symlink_to(outside)
            except (NotImplementedError, OSError):
                pytest.skip("symlink creation is unavailable on this platform")
        return original(path, limit, **kwargs)

    monkeypatch.setattr(infra_impl, "_read_bounded_file", swap_before_open)
    server = infra.WebsockServer(host="127.0.0.1", port=0, http_server_root=served, verbose=False)
    server.start()
    try:
        assert _get(server._port, "/asset.txt")[0] == 404
        assert _get(server._port, "/healthy.txt")[2] == b"healthy"
    finally:
        server.stop()
    assert swapped


def test_runtime_asset_registration_loads_are_aggregate_bounded_without_blocking_gets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    existing = tmp_path / "existing.bin"
    existing.write_bytes(b"existing")
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    monkeypatch.setattr(infra_impl, "_HTTP_ASSET_MAX_BYTES", 8)
    monkeypatch.setattr(infra_impl, "_HTTP_ASSET_LOAD_MAX_BYTES", 8)
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    existing_url = server.register_http_asset(existing).url
    original = infra_impl._read_bounded_file
    release = threading.Event()
    entered = threading.Event()
    active = 0
    peak = 0
    state_lock = threading.Lock()

    def blocked(path: Path, limit: int, **kwargs: object) -> bytes:
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
            entered.set()
        try:
            assert release.wait(2.0)
            return original(path, limit, **kwargs)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(infra_impl, "_read_bounded_file", blocked)
    errors: list[BaseException] = []

    def register(path: Path) -> None:
        try:
            server.register_http_asset(path)
        except BaseException as error:
            errors.append(error)

    server.start()
    threads = [threading.Thread(target=register, args=(path,)) for path in (first, second)]
    try:
        for thread in threads:
            thread.start()
        assert entered.wait(2.0)
        time.sleep(0.05)
        with state_lock:
            assert active == 1
        # GET only takes the registry lookup lock, not the load admission lock.
        assert _get(server._port, existing_url)[2] == b"existing"
        release.set()
        for thread in threads:
            thread.join(2.0)
        assert errors == []
        assert peak == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(2.0)
        server.stop()


def test_runtime_asset_load_reservation_covers_post_read_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    monkeypatch.setattr(infra_impl, "_HTTP_ASSET_MAX_BYTES", 8)
    monkeypatch.setattr(infra_impl, "_HTTP_ASSET_LOAD_MAX_BYTES", 8)
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    original = infra_impl.hashlib.sha256
    release = threading.Event()
    entered = threading.Event()
    active = 0
    peak = 0
    state_lock = threading.Lock()

    def blocked(payload: bytes):
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
            entered.set()
        try:
            assert release.wait(2.0)
            return original(payload)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(infra_impl.hashlib, "sha256", blocked)
    errors: list[BaseException] = []

    def register(path: Path) -> None:
        try:
            server.register_http_asset(path)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=register, args=(path,)) for path in (first, second)]
    for thread in threads:
        thread.start()
    assert entered.wait(2.0)
    time.sleep(0.05)
    with state_lock:
        assert active == 1
    release.set()
    for thread in threads:
        thread.join(2.0)
    assert errors == []
    assert peak == 1
    assert server._http_asset_load_bytes == 0


def _png_header_with_size(width: int, height: int) -> bytes:
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + len(ihdr).to_bytes(4, "big")
        + b"IHDR"
        + ihdr
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IDAT\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00"
    )


def test_internal_runtime_image_registration_requires_safe_raster_header(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe.dat"
    safe.write_bytes(_png_header_with_size(16_384, 2_048))
    misleading = tmp_path / "safe.html"
    misleading.write_bytes(safe.read_bytes())
    oversized = tmp_path / "oversized.png"
    oversized.write_bytes(_png_header_with_size(8_193, 4_096))
    malformed = tmp_path / "malformed.png"
    malformed.write_bytes(b"not an image")
    server = infra.WebsockServer("127.0.0.1", 0, verbose=False)

    generic_asset = server.register_http_asset(safe)
    safe_asset = server.register_http_asset(safe, _require_safe_image=True)
    assert safe_asset.pixel_size == (16_384, 2_048)
    assert re.fullmatch(r"/leika-assets/[0-9a-f]{64}-16384x2048\.png", safe_asset.url)
    assert re.fullmatch(r"/leika-assets/[0-9a-f]{64}\.dat", generic_asset.url)
    assert safe_asset.url != generic_asset.url
    assert server.register_http_asset(misleading, _require_safe_image=True).url == safe_asset.url
    with pytest.raises(ValueError, match="decoded pixels"):
        server.register_http_asset(oversized, _require_safe_image=True)
    with pytest.raises(ValueError, match="recognized"):
        server.register_http_asset(malformed, _require_safe_image=True)

    server.start()
    try:
        forged = safe_asset.url.replace("-16384x2048", "-1x1")
        assert _get(server._port, forged)[0] == 404
        status, headers, body = _get(server._port, safe_asset.url)
        assert status == 200
        assert headers["content-type"] == "image/png"
        assert body == safe.read_bytes()
    finally:
        server.stop()

    # Generic runtime assets remain arbitrary downloadable byte snapshots.
    assert server.register_http_asset(oversized).pixel_size == (8_193, 4_096)
    assert server.register_http_asset(malformed).pixel_size is None


def test_bounded_file_snapshot_rejects_same_size_in_place_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "mutable.bin"
    source.write_bytes(b"before")
    real_fstat = infra_impl.os.fstat
    calls = 0

    def rewrite_between_descriptor_stats(descriptor: int) -> os.stat_result:
        nonlocal calls
        metadata = real_fstat(descriptor)
        calls += 1
        if calls == 2:
            source.write_bytes(b"after!")
            timestamp = metadata.st_mtime_ns + 1_000_000_000
            os.utime(source, ns=(timestamp, timestamp))
        return metadata if calls == 2 else real_fstat(descriptor)

    monkeypatch.setattr(infra_impl.os, "fstat", rewrite_between_descriptor_stats)
    with pytest.raises(OSError, match="changed while it was being read"):
        infra_impl._read_bounded_file(source, 64)


def test_ordinary_http_forces_close_and_sequential_client_requests_reconnect(
    tmp_path: Path,
) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_bytes(b"ok")
    server = infra.WebsockServer(host="127.0.0.1", port=0, http_server_root=served, verbose=False)
    server.start()
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
        server.stop()
