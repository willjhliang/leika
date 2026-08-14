from __future__ import annotations

import inspect
import re
import socket
import time
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._messages
import leika.infra

VERSION_INFO = Path(__file__).resolve().parents[1] / "src/leika/client/src/VersionInfo.ts"
WEBSOCKET_MESSAGES = (
    Path(__file__).resolve().parents[1] / "src/leika/client/src/WebsocketMessages.ts"
)


def test_version_and_server_signature() -> None:
    # The browser client rejects connections on a version mismatch, so the
    # generated constant must track __version__ rather than a pinned literal.
    generated = re.search(r'LEIKA_VERSION = "([^"]+)"', VERSION_INFO.read_text(encoding="utf-8"))
    assert generated is not None
    assert generated.group(1) == leika.__version__
    signature = inspect.signature(leika.Server)
    assert signature.parameters["host"].default == "0.0.0.0"
    assert signature.parameters["port"].default == 8080
    assert signature.parameters["workspace_id"].default == "default"


def test_server_surface_is_data_only(server: leika.Server) -> None:
    assert server.url.startswith("http://127.0.0.1:")
    assert server.clients == {}
    assert server.panes is not None
    assert server.gui is not None
    assert not hasattr(server, "scene")
    assert not hasattr(server, "camera")
    assert not hasattr(server, "request_share_url")
    assert not hasattr(leika, "SceneApi")
    assert not hasattr(leika, "CameraHandle")


def test_atomic_flush_and_idempotent_stop(server: leika.Server) -> None:
    with server.atomic():
        enabled = server.gui.add_checkbox("Enabled", initial_value=True)
        enabled.value = False
    server.flush()
    assert enabled.value is False

    port = int(server.url.rsplit(":", 1)[1])
    server.stop()
    server.stop()
    time.sleep(0.05)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


def test_client_carries_the_protocol_fingerprint() -> None:
    """The bundle names the schema it was built against, and the server sends
    anything else away.

    Without this the two can disagree while agreeing on the version, which is
    what a server left running across an edit does: it feeds the page fields
    the page has never heard of, and the page goes blank rather than saying so.
    """
    generated = re.search(
        r'LEIKA_PROTOCOL = "([^"]+)"', WEBSOCKET_MESSAGES.read_text(encoding="utf-8")
    )
    assert generated is not None
    assert generated.group(1) == leika.infra.protocol_fingerprint(leika._messages.Message)


def test_a_mismatched_client_is_turned_away_with_a_reason() -> None:
    """The rejection has to reach the page, not just the terminal."""

    def attempt(subprotocol: str) -> tuple[int | None, str]:
        # The synchronous client, because other tests in this suite leave an
        # event loop running in this thread.
        try:
            with connect(url, subprotocols=[Subprotocol(subprotocol)], open_timeout=5) as ws:
                try:
                    ws.recv(timeout=1.0)
                except ConnectionClosed:
                    pass
                # Through the sans-io protocol, which has carried the close
                # handshake since 13.1; the connection only forwards it in 14+.
                return ws.protocol.close_code, ws.protocol.close_reason or ""
        except ConnectionClosed as exc:
            return exc.code, exc.reason or ""

    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    url = server.url.replace("http://", "ws://")
    version = leika.__version__
    fingerprint = leika.infra.protocol_fingerprint(leika._messages.Message)
    try:
        code, reason = attempt(f"leika-v{version}+p{fingerprint}")
        assert code is None, (code, reason)

        for subprotocol, expected in (
            (f"leika-v{version}+p0123456789ab", "Protocol mismatch"),
            (f"leika-v0.0.0+p{fingerprint}", "Version mismatch"),
        ):
            code, reason = attempt(subprotocol)
            assert code == 1002, (subprotocol, code, reason)
            assert reason.startswith(expected), reason
            # A close frame carries at most 123 bytes; over that the frame is
            # never sent and the page sees an unexplained disconnect instead.
            assert len(reason.encode()) <= 123, reason
    finally:
        server.stop()
