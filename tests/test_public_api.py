from __future__ import annotations

import socket
import time

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
from leika._transport._typescript import protocol_fingerprint


def test_stop_is_idempotent_and_closes_the_listener(server: leika.Server) -> None:
    port = int(server.url.rsplit(":", 1)[1])
    server.stop()
    server.stop()
    time.sleep(0.05)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0


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
    try:
        code, reason = attempt(f"leika-{protocol_fingerprint()}")
        assert code is None, (code, reason)

        for subprotocol in ("leika-0123456789ab", "leika-v0.4.0+p0123456789ab"):
            code, reason = attempt(subprotocol)
            assert code == 1002, (subprotocol, code, reason)
            assert reason.startswith("Protocol mismatch"), reason
            # A close frame carries at most 123 bytes; over that the frame is
            # never sent and the page sees an unexplained disconnect instead.
            assert len(reason.encode()) <= 123, reason
    finally:
        server.stop()
