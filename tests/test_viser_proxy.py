from __future__ import annotations

import contextlib
import gzip
import http.client
import threading
from types import SimpleNamespace

import msgspec
import pytest
from websockets import Headers
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.http11 import Response
from websockets.sync.client import connect
from websockets.sync.server import serve

import leika
from leika._transport._viser_proxy import VISER_PROXY_PREFIX, _rebase_assets


@contextlib.contextmanager
def backend(response=None):
    requests = []
    messages = []

    def process_request(connection, request):
        requests.append(request)
        if response is not None:
            return response
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        return Response(
            200,
            "OK",
            Headers(
                {
                    "Content-Type": "text/plain",
                    "Set-Cookie": "backend=must-not-escape",
                    "Cache-Control": "public, max-age=86400",
                }
            ),
            ("viser:" + request.path).encode(),
        )

    def handler(connection):
        try:
            for message in connection:
                messages.append(message)
                connection.send(message)
        except ConnectionClosed:
            pass

    with serve(
        handler,
        "127.0.0.1",
        0,
        process_request=process_request,
        select_subprotocol=lambda connection, protocols: next(iter(protocols), None),
    ) as listener:
        thread = threading.Thread(target=listener.serve_forever, daemon=True)
        thread.start()
        port = listener.socket.getsockname()[1]
        try:
            yield (
                SimpleNamespace(get_host=lambda: "127.0.0.1", get_port=lambda: port),
                requests,
                messages,
            )
        finally:
            listener.shutdown()
            thread.join(timeout=5)


def get(server, path, headers=None):
    client = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        client.request("GET", path, headers=headers or {})
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        client.close()


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    with leika.Server(host="127.0.0.1", port=0, password="secret", verbose=False) as server:
        yield server


def login(server):
    status, headers, _ = get(server, "/auth/session", {"x-leika-password": "secret"})
    assert status == 204
    assert "HttpOnly" in headers["Set-Cookie"]
    return {"Cookie": headers["Set-Cookie"].split(";", 1)[0]}


def websocket_url(server, pane):
    return server.url.replace("http:", "ws:") + pane.url.rstrip("/")


def test_password_protects_proxy_assets_and_both_websocket_routes(protected):
    with backend() as (target, requests, messages):
        pane = protected.panes.add_viser(target)
        assert pane.url.startswith(VISER_PROXY_PREFIX)
        for path in ("/", pane.url, pane.url + "assets/client.js"):
            assert get(protected, path)[0] == 401
        for path in ("/", pane.url):
            with pytest.raises(InvalidStatus) as error:
                connect(protected.url.replace("http:", "ws:") + path)
            assert error.value.response.status_code == 401
        assert requests == []
        cookie = login(protected)
        status, headers, body = get(protected, pane.url + "assets/client.js?x=1", cookie)
        assert (status, body) == (200, b"viser:/assets/client.js?x=1")
        assert headers["Content-Security-Policy"] == "frame-ancestors 'self'"
        assert headers["Cache-Control"] == "no-store"
        assert headers["CDN-Cache-Control"] == "no-store"
        assert "Set-Cookie" not in headers
        assert get(protected, pane.url + "assets/second.js", cookie)[0] == 200
        with connect(
            websocket_url(protected, pane), additional_headers=cookie, subprotocols=["viser-vtest"]
        ) as ws:
            assert ws.subprotocol == "viser-vtest"
            payload = msgspec.msgpack.encode({"type": "Camera", "position": [1, 2, 3]})
            ws.send(payload)
            assert ws.recv(timeout=5) == payload
        assert messages == [payload]
        for request in requests:
            assert "Cookie" not in request.headers
            assert "x-leika-password" not in request.headers
            assert "Origin" not in request.headers


def test_proxy_enforces_host_origin_and_path_boundaries(protected):
    with backend() as (target, requests, _):
        pane = protected.panes.add_viser(target)
        auth = {"x-leika-password": "secret"}
        for extra in (
            {"Host": "attacker.example"},
            {"Origin": "https://attacker.example"},
            {"X-Forwarded-Proto": "https"},
        ):
            assert get(protected, pane.url, dict(auth, **extra))[0] == 403
        for path in (
            pane.url + "%2e%2e/.env",
            pane.url + "a%5c..%5csecret",
            pane.url + "%00",
            VISER_PROXY_PREFIX + "unregistered/",
        ):
            assert get(protected, path, auth)[0] == 404
        with pytest.raises(InvalidStatus) as error:
            connect(
                websocket_url(protected, pane),
                origin="https://attacker.example",
                additional_headers=auth,
            )
        assert error.value.response.status_code == 403
        assert requests == []


def test_proxy_routes_are_retired_on_update_remove_and_failed_add(protected):
    with backend() as (target, _, _):
        pane = protected.panes.add_viser(target, pane_id="scene")
        route = pane.url
        auth = login(protected)
        pane.update(target)
        assert pane.url == route
        with pytest.raises(ValueError, match="already exists"):
            protected.panes.add_viser(target, pane_id="scene")
        proxy = protected._websock_server._viser_proxy
        assert len(proxy._endpoints) == 1
        with connect(websocket_url(protected, pane), additional_headers=auth) as ws:
            pane.update("https://external.example/scene")
            with pytest.raises(ConnectionClosed):
                ws.recv(timeout=5)
        assert get(protected, route, auth)[0] == 404
        assert len(proxy._endpoints) == 0
        pane.update(target)
        route = pane.url
        pane.remove()
        assert get(protected, route, auth)[0] == 404
        assert len(proxy._endpoints) == 0


def test_protected_embedding_requires_loopback_and_keeps_explicit_urls(protected):
    for host in ("0.0.0.0", "::", "192.0.2.1", "external.example"):
        target = SimpleNamespace(get_host=lambda: host, get_port=lambda: 8082)
        with pytest.raises(ValueError, match="loopback"):
            protected.panes.add_viser(target)
    direct = protected.panes.add_viser("https://external.example/scene")
    assert direct.url == "https://external.example/scene"
    assert protected._websock_server._viser_proxy._endpoints == {}


@pytest.mark.parametrize("kind", ["ShareUrlRequest", "ShareUrlDisconnect"])
def test_embedded_client_cannot_open_an_independent_tunnel(protected, kind):
    with backend() as (target, _, messages):
        pane = protected.panes.add_viser(target)
        with connect(websocket_url(protected, pane), additional_headers=login(protected)) as ws:
            ws.send(msgspec.msgpack.encode({"type": kind}))
            with pytest.raises(ConnectionClosed) as error:
                ws.recv(timeout=5)
            assert error.value.rcvd.code == 1008
        assert messages == []


def test_legacy_asset_urls_stay_with_their_pane():
    source = b'''<script src="/assets/app.js"></script> new Worker('/assets/worker.js')
        new URL("/assets/sort.wasm", import.meta.url); "/logo.svg"; "/manifest.json";
        "https://example.org/assets/remote.js"; "./assets/relative.js"'''
    first = VISER_PROXY_PREFIX + "first/"
    rewritten = _rebase_assets(source, first)
    assert rewritten.count(first.encode()) == 5
    assert b'"https://example.org/assets/remote.js"' in rewritten
    assert b'"./assets/relative.js"' in rewritten
    assert first.encode() not in _rebase_assets(source, VISER_PROXY_PREFIX + "second/")


def test_proxy_preserves_encoded_binary_representations_and_ranges(protected):
    payload = gzip.compress(b"binary scene asset")
    response = Response(
        206,
        "Partial Content",
        Headers({"Content-Encoding": "gzip", "Content-Range": "bytes 0-3/10", "ETag": '"asset"'}),
        payload,
    )
    with backend(response) as (target, requests, _):
        pane = protected.panes.add_viser(target)
        status, headers, body = get(
            protected,
            pane.url + "asset.bin",
            dict(login(protected), **{"Range": "bytes=0-3", "Accept-Encoding": "gzip"}),
        )
        assert status == 206 and body == payload
        assert headers["Content-Encoding"] == "gzip"
        assert headers["Content-Range"] == "bytes 0-3/10"
        assert headers["ETag"] == '"asset"'
        assert requests[0].headers["Range"] == "bytes=0-3"
        assert requests[0].headers["Accept-Encoding"] == "gzip"


def test_proxy_never_follows_http_or_websocket_redirects(protected):
    with backend() as (destination, reached, _):
        response = Response(
            302, "Found", Headers({"Location": f"http://127.0.0.1:{destination.get_port()}/"})
        )
        with backend(response) as (target, _, _):
            pane = protected.panes.add_viser(target)
            cookie = login(protected)
            status, headers, _ = get(protected, pane.url, cookie)
            assert status == 302
            assert "Location" not in headers
            with connect(websocket_url(protected, pane), additional_headers=cookie) as ws:
                with pytest.raises(ConnectionClosed) as error:
                    ws.recv(timeout=5)
                assert error.value.rcvd.code == 1011
        assert reached == []


def test_shutdown_closes_proxy_sockets_and_http_pool(protected):
    with backend() as (target, _, _):
        pane = protected.panes.add_viser(target)
        cookie = login(protected)
        assert get(protected, pane.url, cookie)[0] == 200
        proxy = protected._websock_server._viser_proxy
        assert proxy._session is not None
        with connect(websocket_url(protected, pane), additional_headers=cookie) as ws:
            ws.send(msgspec.msgpack.encode({"type": "Camera"}))
            ws.recv(timeout=5)
            protected.stop()
            with pytest.raises(ConnectionClosed):
                ws.recv(timeout=5)
        assert proxy._session is None
        assert all(not endpoint.connections for endpoint in proxy._endpoints.values())
