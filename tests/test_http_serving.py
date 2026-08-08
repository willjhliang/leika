from __future__ import annotations

import gzip
import http.client
import socket
import threading
import time
from concurrent.futures import Future
from pathlib import Path

import pytest
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


def test_registered_asset_url_never_serves_changed_bytes(tmp_path: Path) -> None:
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

        # Keep the same length to cover rewrites that a stat-only check could
        # mistake for the original content on a coarse filesystem.
        asset_path.write_bytes(b"other")
        assert _get(server._port, first_url)[0] == 404

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


def test_equal_registered_assets_keep_every_valid_backing_path(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_bytes(b"<html></html>")
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"shared")
    second.write_bytes(b"shared")

    server = infra.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=served,
        verbose=False,
    )
    first_url = server.register_http_asset(first).url
    assert server.register_http_asset(second).url == first_url
    server.start()
    try:
        second.unlink()
        assert _get(server._port, first_url)[2] == b"shared"

        first.write_bytes(b"changed")
        assert _get(server._port, first_url)[0] == 404
    finally:
        server.stop()


def test_equal_asset_backing_paths_are_bounded_and_keep_the_newest(
    tmp_path: Path,
) -> None:
    server = infra.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    sources: list[Path] = []
    url = ""
    for index in range(infra_impl._HTTP_ASSET_BACKING_LIMIT + 3):
        source = tmp_path / f"duplicate-{index}.txt"
        source.write_bytes(b"same")
        sources.append(source.resolve())
        next_url = server.register_http_asset(source).url
        if url:
            assert next_url == url
        url = next_url

    name = url.rsplit("/", 1)[-1]
    retained, _ = server._http_assets[name]
    assert retained == tuple(sources[-infra_impl._HTTP_ASSET_BACKING_LIMIT :])
    assert len(retained) == infra_impl._HTTP_ASSET_BACKING_LIMIT


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
