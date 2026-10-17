from __future__ import annotations

import http.client
import json
import os
import socket
from pathlib import Path

import pytest
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._client_autobuild
import leika._messages
from leika import infra
from leika.infra._http_security import _configured_allowed_hosts


def _write_config(payload: str) -> Path:
    path = Path(os.environ["XDG_CONFIG_HOME"]) / "leika" / "allowed_hosts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    return path


def test_missing_config_preserves_defaults() -> None:
    assert _configured_allowed_hosts(None) == frozenset()


def test_home_fallback_and_normalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".config/leika/allowed_hosts.json"
    path.parent.mkdir(parents=True)
    path.write_text('["Dashboard.Example.", "100.64.0.1", "fd7a:115c:a1e0::1"]')
    assert _configured_allowed_hosts(None) == frozenset(
        {"dashboard.example", "100.64.0.1", "fd7a:115c:a1e0::1"}
    )


@pytest.mark.parametrize(
    "payload",
    [
        "{broken",
        "null",
        '"dashboard.example"',
        '{"allowed_hosts": []}',
        '["*"]',
        '["*.example"]',
        '["http://dashboard.example"]',
        '["dashboard.example:8080"]',
        '["dashboard.example/path"]',
        "[1]",
        '["Dashboard.Example", "dashboard.example."]',
        json.dumps([f"host-{index}.example" for index in range(257)]),
    ],
)
def test_bad_config_fails_before_client_build(
    payload: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(payload)
    monkeypatch.setattr(
        leika._client_autobuild,
        "ensure_client_is_built",
        lambda: pytest.fail("invalid host configuration must fail before client build"),
    )
    with pytest.raises(ValueError, match="allowed_hosts.json"):
        leika.Server(host="127.0.0.1", port=0)


def test_explicit_hosts_override_even_invalid_configuration() -> None:
    _write_config("{broken")
    assert _configured_allowed_hosts([]) == frozenset()
    assert _configured_allowed_hosts(["explicit.example"]) == frozenset({"explicit.example"})


def test_unreadable_config_reports_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(ValueError, match="allowed_hosts.json.*denied"):
        _configured_allowed_hosts(None)


def test_non_utf8_config_reports_path() -> None:
    path = _write_config("[]")
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError, match="allowed_hosts.json"):
        _configured_allowed_hosts(None)


def test_relative_config_home_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative-config")
    with pytest.raises(ValueError, match="absolute path"):
        _configured_allowed_hosts(None)


def test_persistent_names_work_for_http_and_websockets_without_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No discovery subprocess or DNS lookup: this also models VPN startup after
    # the server. Route the socket locally while using the real browser identity.
    _write_config('["dashboard", "dashboard.tailnet.ts.net"]')
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    protocol = Subprotocol(
        f"leika-v{leika.__version__}+p{infra.protocol_fingerprint(leika._messages.Message)}"
    )
    try:
        for host in ["localhost", "dashboard", "dashboard.tailnet.ts.net", "unlisted.example"]:
            connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            try:
                connection.request("GET", "/", headers={"Host": f"{host}:{server.port}"})
                response = connection.getresponse()
                assert response.status == (403 if host == "unlisted.example" else 200)
                response.read()
            finally:
                connection.close()

        url = f"ws://dashboard:{server.port}"
        for origin in [f"http://dashboard:{server.port}", "http://unlisted.example"]:
            sock = socket.create_connection(("127.0.0.1", server.port), timeout=5)
            try:
                if origin == "http://unlisted.example":
                    with pytest.raises(InvalidStatus) as rejected:
                        connect(
                            url, sock=sock, origin=origin, subprotocols=[protocol], open_timeout=3
                        )
                    assert rejected.value.response.status_code == 403
                else:
                    with connect(
                        url, sock=sock, origin=origin, subprotocols=[protocol], open_timeout=3
                    ):
                        pass
            finally:
                sock.close()
    finally:
        server.stop()
