from __future__ import annotations

import contextlib
import http.client
import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from websockets import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Request
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._client_autobuild
import leika._transport._auth as auth_module
from leika._transport._auth import (
    AUTH_PATH,
    COOKIE_NAME,
    FONT_PATH,
    PASSWORD_HEADER,
    WORDMARK_FONT_PATH,
    HttpPasswordGuard,
)
from leika._transport._typescript import protocol_fingerprint
from leika._transport._websocket import WebsockClientConnection, WebsockServer

PASSWORD = "open sesame"
# URL-encoded, matching what the login page's `fetch` sends: header values
# must be ASCII, and encoding is what lets arbitrary passwords through.
PASSWORD_ENCODED = "open%20sesame"
INDEX = b"<html>Leika</html>"


async def _ignore(_: WebsockClientConnection) -> None:
    pass


@contextlib.contextmanager
def _protected(tmp_path: Path) -> Iterator[WebsockServer]:
    index = tmp_path / "index.html"
    index.write_bytes(INDEX)
    server = WebsockServer(
        "127.0.0.1",
        0,
        on_connect=_ignore,
        on_disconnect=_ignore,
        index_html=index,
        verbose=False,
        password=PASSWORD,
    )
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


def _login_cookie(port: int, encoded_password: str) -> str:
    status, headers, _ = _get(port, AUTH_PATH, {PASSWORD_HEADER: encoded_password})
    assert status == 204
    match = re.match(rf"({COOKIE_NAME}=[^;]+)", headers["set-cookie"])
    assert match is not None
    return match.group(1)


def test_password_gates_the_client_page(tmp_path: Path) -> None:
    with _protected(tmp_path) as server:
        # Anonymous requests get the login page -- for every path, not just
        # the index -- and it must never be cached.
        for path in ("/", "/index.html", "/missing"):
            status, headers, body = _get(server._port, path)
            assert status == 401
            assert b"password" in body
            assert headers["cache-control"] == "no-store"
            assert headers["cross-origin-resource-policy"] == "same-origin"

        # A wrong (or absent) password is turned away without a cookie.
        for login_headers in ({}, {PASSWORD_HEADER: "wrong"}):
            status, headers, _ = _get(server._port, AUTH_PATH, login_headers)
            assert status == 403
            assert "set-cookie" not in headers

        # The right password earns a session cookie, and the cookie unlocks
        # the page.
        cookie = _login_cookie(server._port, PASSWORD_ENCODED)
        assert _get(server._port, "/", {"Cookie": cookie})[::2] == (200, INDEX)

        # The password header works directly too (curl-style access).
        assert _get(server._port, "/", {PASSWORD_HEADER: PASSWORD_ENCODED})[::2] == (200, INDEX)

        # The login page's typefaces are the only pre-auth assets: they render
        # the page in the client's own faces and disclose nothing.
        for font_path in (FONT_PATH, WORDMARK_FONT_PATH):
            status, headers, body = _get(server._port, font_path)
            assert status == 200
            assert headers["content-type"] == "font/woff2"
            assert headers["cross-origin-resource-policy"] == "same-origin"
            assert body[:4] == b"wOF2"

        # Forwarding headers are rejected unless the exact tunnel hostname was
        # registered. The trusted tunnel path marks its cookie Secure; plain
        # localhost HTTP must not, or the browser drops it.
        status, _, _ = _get(
            server._port,
            AUTH_PATH,
            {PASSWORD_HEADER: PASSWORD_ENCODED, "X-Forwarded-Proto": "https"},
        )
        assert status == 403
        server.trust_proxy_host("fake.trycloudflare.com")
        status, headers, _ = _get(
            server._port,
            AUTH_PATH,
            {
                "Host": "fake.trycloudflare.com",
                PASSWORD_HEADER: PASSWORD_ENCODED,
                "X-Forwarded-Proto": "https",
            },
        )
        assert status == 204
        assert "Secure" in headers["set-cookie"]
        _, headers, _ = _get(server._port, AUTH_PATH, {PASSWORD_HEADER: PASSWORD_ENCODED})
        assert "Secure" not in headers["set-cookie"]


def test_password_gates_the_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False, password=PASSWORD)
    url = server.url.replace("http://", "ws://")
    subprotocol = Subprotocol(f"leika-{protocol_fingerprint()}")
    try:
        # No cookie: the handshake itself is refused, before the protocol
        # check or any connection accounting.
        with pytest.raises(InvalidStatus) as rejected:
            connect(url, subprotocols=[subprotocol], open_timeout=5)
        assert rejected.value.response.status_code == 401

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
    monkeypatch.setattr(auth_module, "FAILURE_WINDOW_SECONDS", 0.3)
    with _protected(tmp_path) as server:
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


def test_duplicate_password_headers_and_malformed_cookies_are_cleanly_rejected() -> None:
    guard = HttpPasswordGuard(PASSWORD)
    duplicate = Request(
        AUTH_PATH,
        Headers(
            [
                (PASSWORD_HEADER, PASSWORD_ENCODED),
                (PASSWORD_HEADER, PASSWORD_ENCODED),
            ]
        ),
    )
    response = guard.process(duplicate)
    assert response is not None
    assert response.status_code == 403

    malformed = Request(
        "/",
        Headers([("Cookie", 'leika_session="unterminated')]),
    )
    response = guard.process(malformed)
    assert response is not None
    assert response.status_code == 401


@pytest.mark.parametrize("value", ['leika_session="é"', r'leika_session="\351"'])
def test_non_ascii_session_cookie_is_rejected(value: str) -> None:
    response = HttpPasswordGuard(PASSWORD).process(Request("/", Headers({"Cookie": value})))
    assert response is not None
    assert response.status_code == 401


def test_authenticated_resources_never_enter_shared_caches(tmp_path: Path) -> None:
    asset = tmp_path / "private.png"
    asset.write_bytes(b"private asset")
    with _protected(tmp_path) as server:
        cookie = _login_cookie(server._port, PASSWORD_ENCODED)
        registered = server.register_http_asset(asset)
        for path in ("/", registered.url, "/missing"):
            _, headers, _ = _get(server._port, path, {"Cookie": cookie})
            assert headers["cache-control"] == "no-store"
            assert headers["cdn-cache-control"] == "no-store"
            assert _get(server._port, path)[0] == 401
