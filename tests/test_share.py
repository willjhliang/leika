from __future__ import annotations

import http.client
import shutil
import subprocess
import sys
import threading
import time

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


def _fake_cloudflared(monkeypatch: pytest.MonkeyPatch, body: str) -> str:
    original_popen = subprocess.Popen
    child_body = "import sys\n" + body

    def launch(command, **kwargs):
        assert command == [
            "fake-cloudflared",
            "tunnel",
            "--url",
            "http://127.0.0.1:1234",
            "--no-autoupdate",
        ]
        return original_popen([sys.executable, "-u", "-c", child_body], **kwargs)

    monkeypatch.setattr(leika._share.subprocess, "Popen", launch)
    return "fake-cloudflared"


def test_share_url_is_read_from_cloudflared_banner() -> None:
    banner = (
        "2026-07-31T00:00:00Z INF |  Your quick Tunnel has been created!"
        "  Visit it at:  https://alfa-bravo-charlie-delta.trycloudflare.com  |"
    )
    assert find_share_url(banner) == "https://alfa-bravo-charlie-delta.trycloudflare.com"
    assert find_share_url("INF Requesting new quick Tunnel on trycloudflare.com...") is None
    # The registration API is a trycloudflare.com URL too; it is not a tunnel.
    assert find_share_url("POST https://api.trycloudflare.com/tunnel") is None
    assert find_share_url("POST HTTPS://API.TRYCLOUDFLARE.COM/tunnel") is None
    assert (
        find_share_url("HTTPS://LEIKA-TEST.TRYCLOUDFLARE.COM")
        == "https://leika-test.trycloudflare.com"
    )


def test_missing_binary_reports_install_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ShareTunnelError, match="brew install cloudflared"):
        CloudflaredTunnel(1234).start(timeout=1)


def test_tunnel_reports_url_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    binary = _fake_cloudflared(
        monkeypatch,
        "import time\n"
        'print("INF Requesting new quick Tunnel on trycloudflare.com...", file=sys.stderr, flush=True)\n'
        'print("INF https://leika-test.trycloudflare.com", file=sys.stderr, flush=True)\n'
        "time.sleep(30)\n",
    )
    tunnel = CloudflaredTunnel(1234, binary=binary)
    try:
        assert tunnel.start(timeout=10) == "https://leika-test.trycloudflare.com"
        assert tunnel.url == "https://leika-test.trycloudflare.com"
    finally:
        tunnel.close()
    assert tunnel.url is None


def test_early_exit_surfaces_cloudflared_output(monkeypatch: pytest.MonkeyPatch) -> None:
    binary = _fake_cloudflared(
        monkeypatch,
        'print("ERR failed to request quick tunnel", file=sys.stderr, flush=True)\nraise SystemExit(1)\n',
    )
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
        instances: list[FakeTunnel] = []

        def __init__(self, local_port: int, binary: str | None = None) -> None:
            self.local_port = local_port
            self._url: str | None = None
            self.instances.append(self)

        @property
        def url(self) -> str | None:
            return self._url

        def start(self, timeout: float = 20.0) -> str:
            self._url = "https://fake.trycloudflare.com"
            return self._url

        def close(self) -> None:
            self._url = None
            closed.append(self.local_port)

    monkeypatch.setattr(leika._server, "CloudflaredTunnel", FakeTunnel)
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False, share=True)
    try:
        assert server.share_url == "https://fake.trycloudflare.com"
        # The public property follows tunnel liveness rather than retaining the
        # string copied at startup. This models an unexpected process EOF.
        FakeTunnel.instances[0]._url = None
        assert server.share_url is None
        FakeTunnel.instances[0]._url = "https://fake.trycloudflare.com"
        # A public URL without a password would be an open door; sharing must
        # have generated one and switched the auth gate on.
        assert server.password
        assert _get(server.port, "/") == 401
        assert _get(server.port, "/", {PASSWORD_HEADER: server.password}) == 200
    finally:
        server.stop()
    assert closed == [server.port]
    assert server.share_url is None


def test_share_start_failure_is_not_masked_by_tunnel_close_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FailingTunnel:
        url = None

        def __init__(self, local_port: int) -> None:
            del local_port

        def start(self) -> str:
            raise ShareTunnelError("primary tunnel start failure")

        def close(self) -> None:
            raise OSError("secondary tunnel close failure")

    monkeypatch.setattr(leika._server, "CloudflaredTunnel", FailingTunnel)
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False, share=True)
    try:
        assert server.share_url is None
        output = capsys.readouterr().out
        assert "primary tunnel start failure" in output
        assert "secondary tunnel close failure" in output
    finally:
        server.stop()


def test_share_refuses_a_non_loopback_bind() -> None:
    """The tunnel is the encrypted way in; 0.0.0.0 would open a second,
    unencrypted one to the local network, password traveling in the clear."""
    with pytest.raises(ValueError, match="unencrypted HTTP"):
        leika.Server(port=0, verbose=False, share=True)


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf"), float("nan"), "slow"])
def test_timeout_validation_does_not_consume_one_shot(
    monkeypatch: pytest.MonkeyPatch, timeout: object
) -> None:
    tunnel = CloudflaredTunnel(1234)
    with pytest.raises(ValueError, match="positive finite"):
        tunnel.start(timeout=timeout)  # type: ignore[arg-type]
    assert not tunnel._started


def test_start_is_explicitly_one_shot_after_close(monkeypatch: pytest.MonkeyPatch) -> None:
    binary = _fake_cloudflared(
        monkeypatch,
        "import time\n"
        'print("INF https://one-shot.trycloudflare.com", file=sys.stderr, flush=True)\n'
        "time.sleep(30)\n",
    )
    tunnel = CloudflaredTunnel(1234, binary=binary)
    assert tunnel.start(timeout=5) == "https://one-shot.trycloudflare.com"
    tunnel.close()
    with pytest.raises(RuntimeError, match="one-shot"):
        tunnel.start(timeout=1)


def test_failed_start_is_explicitly_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    binary = _fake_cloudflared(
        monkeypatch,
        'print("ERR failed", file=sys.stderr, flush=True)\nraise SystemExit(1)\n',
    )
    tunnel = CloudflaredTunnel(1234, binary=binary)
    with pytest.raises(ShareTunnelError):
        tunnel.start(timeout=2)
    with pytest.raises(RuntimeError, match="one-shot"):
        tunnel.start(timeout=2)


def test_spawn_oserror_is_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        del args, kwargs
        raise OSError("cannot execute")

    monkeypatch.setattr(leika._share.subprocess, "Popen", fail)
    with pytest.raises(ShareTunnelError, match="cannot execute"):
        CloudflaredTunnel(1234, binary="/missing/cloudflared").start(timeout=1)


def test_banner_followed_by_exit_is_not_published_as_a_live_tunnel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_cloudflared(
        monkeypatch,
        'print("INF https://already-dead.trycloudflare.com", file=sys.stderr, flush=True)\n',
    )
    tunnel = CloudflaredTunnel(1234, binary=binary)
    with pytest.raises(ShareTunnelError):
        tunnel.start(timeout=2)
    assert tunnel.url is None


def test_concurrent_close_takes_process_ownership_once() -> None:
    class Process:
        def __init__(self) -> None:
            self.terminate_calls = 0
            self.wait_calls = 0
            self._stopped = False
            self.lock = threading.Lock()

        def poll(self):
            return 0 if self._stopped else None

        def terminate(self) -> None:
            with self.lock:
                self.terminate_calls += 1
                self._stopped = True

        def wait(self, timeout=None):
            del timeout
            with self.lock:
                self.wait_calls += 1
            return 0

    process = Process()
    tunnel = CloudflaredTunnel(1234)
    tunnel._process = process  # type: ignore[assignment]
    threads = [threading.Thread(target=tunnel.close) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    assert all(not thread.is_alive() for thread in threads)
    assert process.terminate_calls == 1
    assert process.wait_calls == 1


def test_process_cleanup_is_bounded_and_escalates_to_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        def __init__(self) -> None:
            self.killed = False
            self.waits = 0

        def poll(self):
            return None

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout=None):
            assert timeout == 0.01
            self.waits += 1
            raise subprocess.TimeoutExpired("cloudflared", timeout)

    monkeypatch.setattr(leika._share, "_PROCESS_STOP_TIMEOUT_SECONDS", 0.01)
    process = Process()
    CloudflaredTunnel._terminate_process(process)  # type: ignore[arg-type]
    assert process.killed
    assert process.waits == 2


def test_late_reader_output_cannot_restore_url_after_close() -> None:
    release = threading.Event()

    class Output:
        def __iter__(self):
            release.wait(1)
            yield "INF https://late.trycloudflare.com\n"

    class Process:
        stdout = Output()

        def __init__(self) -> None:
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

        def terminate(self) -> None:
            self.stopped = True

        def wait(self, timeout=None):
            del timeout
            self.stopped = True
            return 0

    tunnel = CloudflaredTunnel(1234)
    process = Process()
    tunnel._process = process  # type: ignore[assignment]
    reader = threading.Thread(target=tunnel._read_output)
    reader.start()
    tunnel.close()
    release.set()
    reader.join(timeout=1)
    assert not reader.is_alive()
    assert tunnel.url is None
