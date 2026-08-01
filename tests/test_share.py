from __future__ import annotations

import http.client
import shutil
import stat
import time
from pathlib import Path

import pytest

import leika
import leika._client_autobuild
import leika._server
import leika._share
from leika._share import CloudflaredTunnel, ShareTunnelError, find_share_url
from leika.infra._auth import PASSWORD_HEADER


def _get(port: int, path: str, headers: dict[str, str] | None = None) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path, headers=headers or {})
        return connection.getresponse().status
    finally:
        connection.close()


def _fake_cloudflared(tmp_path: Path, body: str) -> str:
    script = tmp_path / "fake_cloudflared"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_share_url_is_read_from_cloudflared_banner() -> None:
    banner = (
        "2026-07-31T00:00:00Z INF |  Your quick Tunnel has been created!"
        "  Visit it at:  https://alfa-bravo-charlie-delta.trycloudflare.com  |"
    )
    assert find_share_url(banner) == "https://alfa-bravo-charlie-delta.trycloudflare.com"
    assert find_share_url("INF Requesting new quick Tunnel on trycloudflare.com...") is None
    # The registration API is a trycloudflare.com URL too; it is not a tunnel.
    assert find_share_url("POST https://api.trycloudflare.com/tunnel") is None


def test_missing_binary_reports_install_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ShareTunnelError, match="brew install cloudflared"):
        CloudflaredTunnel(1234).start(timeout=1)


def test_tunnel_reports_url_and_closes(tmp_path: Path) -> None:
    binary = _fake_cloudflared(
        tmp_path,
        'echo "INF Requesting new quick Tunnel on trycloudflare.com..." >&2\n'
        'echo "INF https://leika-test.trycloudflare.com" >&2\n'
        "sleep 30",
    )
    tunnel = CloudflaredTunnel(1234, binary=binary)
    try:
        assert tunnel.start(timeout=10) == "https://leika-test.trycloudflare.com"
        assert tunnel.url == "https://leika-test.trycloudflare.com"
    finally:
        tunnel.close()
    assert tunnel.url is None


def test_early_exit_surfaces_cloudflared_output(tmp_path: Path) -> None:
    binary = _fake_cloudflared(tmp_path, 'echo "ERR failed to request quick tunnel" >&2\nexit 1')
    tunnel = CloudflaredTunnel(1234, binary=binary)
    # The failure must carry cloudflared's own words: they are the only
    # diagnostic there is, and waiting out the full timeout would be worse.
    start = time.monotonic()
    with pytest.raises(ShareTunnelError, match="failed to request quick tunnel"):
        tunnel.start(timeout=30)
    assert time.monotonic() - start < 10


def test_share_requires_and_generates_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = []

    class FakeTunnel:
        def __init__(self, local_port: int, binary: str | None = None) -> None:
            self.local_port = local_port

        def start(self, timeout: float = 20.0) -> str:
            return "https://fake.trycloudflare.com"

        def close(self) -> None:
            closed.append(self.local_port)

    monkeypatch.setattr(leika._server, "CloudflaredTunnel", FakeTunnel)
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False, share=True)
    try:
        assert server.share_url == "https://fake.trycloudflare.com"
        # A public URL without a password would be an open door; sharing must
        # have generated one and switched the auth gate on.
        assert server.password
        assert _get(server.port, "/") == 401
        assert _get(server.port, "/", {PASSWORD_HEADER: server.password}) == 200
    finally:
        server.stop()
    assert closed == [server.port]
    assert server.share_url is None


def test_share_refuses_a_non_loopback_bind() -> None:
    """The tunnel is the encrypted way in; 0.0.0.0 would open a second,
    unencrypted one to the local network, password traveling in the clear."""
    with pytest.raises(ValueError, match="unencrypted HTTP"):
        leika.Server(port=0, verbose=False, share=True)
