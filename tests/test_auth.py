from __future__ import annotations

import http.client
import re
import socket
import time
from pathlib import Path

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._messages
from leika import infra
from leika.infra._auth import (
    AUTH_PATH,
    COOKIE_NAME,
    FONT_PATH,
    PASSWORD_HEADER,
    WORDMARK_FONT_PATH,
)

PASSWORD = "open sesame"
# URL-encoded, matching what the login page's `fetch` sends: header values
# must be ASCII, and encoding is what lets arbitrary passwords through.
PASSWORD_ENCODED = "open%20sesame"


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


def _login_cookie(port: int, encoded_password: str) -> str:
    status, headers, _ = _get(port, AUTH_PATH, {PASSWORD_HEADER: encoded_password})
    assert status == 204
    match = re.match(rf"({COOKIE_NAME}=[^;]+)", headers["set-cookie"])
    assert match is not None
    return match.group(1)


def test_password_gates_static_files(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    payload = b"<html>Leika</html>"
    (served / "index.html").write_bytes(payload)
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=_free_port(),
        http_server_root=served,
        verbose=False,
        password=PASSWORD,
    )
    server.start()
    try:
        time.sleep(0.05)
        # Anonymous requests get the login page -- for every path, not just
        # the index -- and it must never be cached.
        for path in ("/", "/index.html"):
            status, headers, body = _get(server._port, path)
            assert status == 401
            assert b"password" in body
            assert headers["cache-control"] == "no-store"

        # A wrong (or absent) password is turned away without a cookie.
        for login_headers in ({}, {PASSWORD_HEADER: "wrong"}):
            status, headers, _ = _get(server._port, AUTH_PATH, login_headers)
            assert status == 403
            assert "set-cookie" not in headers

        # The right password earns a session cookie, and the cookie unlocks
        # the actual files.
        cookie = _login_cookie(server._port, PASSWORD_ENCODED)
        status, _, body = _get(server._port, "/", {"Cookie": cookie})
        assert status == 200
        assert body == payload

        # The password header works directly too (curl-style access).
        status, _, body = _get(server._port, "/", {PASSWORD_HEADER: PASSWORD_ENCODED})
        assert status == 200
        assert body == payload

        # The login page's typefaces are the only pre-auth assets: they render
        # the page in the client's own faces and disclose nothing.
        for font_path in (FONT_PATH, WORDMARK_FONT_PATH):
            status, headers, body = _get(server._port, font_path)
            assert status == 200
            assert headers["content-type"] == "font/woff2"
            assert body[:4] == b"wOF2"

        # Behind an HTTPS-terminating tunnel the cookie is marked Secure;
        # over plain localhost HTTP it must not be, or the browser drops it.
        status, headers, _ = _get(
            server._port,
            AUTH_PATH,
            {PASSWORD_HEADER: PASSWORD_ENCODED, "X-Forwarded-Proto": "https"},
        )
        assert status == 204
        assert "Secure" in headers["set-cookie"]
        _, headers, _ = _get(server._port, AUTH_PATH, {PASSWORD_HEADER: PASSWORD_ENCODED})
        assert "Secure" not in headers["set-cookie"]
    finally:
        server.stop()


def test_password_gates_the_websocket() -> None:
    server = leika.Server(host="127.0.0.1", port=0, verbose=False, password=PASSWORD)
    url = server.url.replace("http://", "ws://")
    subprotocol = Subprotocol(
        f"leika-v{leika.__version__}+p{infra.protocol_fingerprint(leika._messages.Message)}"
    )
    try:
        # No cookie: the handshake itself is refused, before the version
        # check or any connection accounting.
        try:
            with connect(url, subprotocols=[subprotocol], open_timeout=5):
                raise AssertionError("Handshake should have been rejected.")
        except InvalidStatus as exc:
            assert exc.response.status_code == 401

        # With the session cookie the handshake completes.
        cookie = _login_cookie(server.port, PASSWORD_ENCODED)
        with connect(
            url,
            subprotocols=[subprotocol],
            additional_headers={"Cookie": cookie},
            open_timeout=5,
        ) as ws:
            assert ws.protocol.close_code is None
    finally:
        server.stop()


def test_repeated_wrong_passwords_are_throttled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An online brute-force hits a wall, on every door a password fits in."""
    import leika.infra._auth as auth_module

    monkeypatch.setattr(auth_module, "FAILURE_WINDOW_SECONDS", 0.3)

    served = tmp_path / "served"
    served.mkdir()
    (served / "index.html").write_bytes(b"<html>Leika</html>")
    server = infra.WebsockServer(
        host="127.0.0.1",
        port=_free_port(),
        http_server_root=served,
        verbose=False,
        password=PASSWORD,
    )
    server.start()
    try:
        time.sleep(0.05)
        # A session issued before the lockout, to prove it rides through.
        cookie = _login_cookie(server._port, PASSWORD_ENCODED)

        for _ in range(auth_module.MAX_PASSWORD_FAILURES):
            assert _get(server._port, "/", {PASSWORD_HEADER: "wrong"})[0] == 401

        # Locked out: even the right password is refused everywhere a
        # password is accepted, and the login endpoint says why.
        assert _get(server._port, "/", {PASSWORD_HEADER: PASSWORD_ENCODED})[0] == 401
        assert _get(server._port, AUTH_PATH, {PASSWORD_HEADER: PASSWORD_ENCODED})[0] == 429

        # The cookie session is untouched, and plain anonymous requests
        # still get the login page rather than the throttle.
        assert _get(server._port, "/", {"Cookie": cookie})[0] == 200
        assert _get(server._port, "/")[0] == 401

        # Once the window drains, the right password works again.
        time.sleep(0.35)
        assert _get(server._port, "/", {PASSWORD_HEADER: PASSWORD_ENCODED})[0] == 200
    finally:
        server.stop()
