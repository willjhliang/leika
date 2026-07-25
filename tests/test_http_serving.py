from __future__ import annotations

import gzip
import http.client
import socket
import time
from pathlib import Path

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

        assert _get(server._port, "/..%2f..%2fetc%2fpasswd")[0] == 404
    finally:
        server.stop()


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
