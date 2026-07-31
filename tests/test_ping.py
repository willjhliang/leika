"""What the server does with a client's ping.

The measuring is the browser's -- it stamps the ping, times the answer, and
keeps the numbers -- so the server's whole part is here: hand the stamp back to
the one client that asked, and do it now rather than at the end of the outgoing
window. The window is a frame long, which is the same order as a round trip on
a local link, so waiting for it would show up as latency that is not there.
"""

from __future__ import annotations

from typing import Any, List

import leika
from leika import _messages
from leika.infra import ClientId


class _RecordingConnection:
    def __init__(self) -> None:
        self.messages: List[Any] = []

    def queue_message(self, message: Any) -> None:
        self.messages.append(message)


class _Client:
    """The two members answering a ping touches."""

    def __init__(self) -> None:
        self._websock_connection = _RecordingConnection()
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1


def _connect(server: leika.Server, client_id: int) -> _Client:
    client = _Client()
    server._connected_clients[client_id] = client  # type: ignore[assignment]
    return client


def test_a_ping_is_answered_with_the_stamp_it_carried(server: leika.Server) -> None:
    client = _connect(server, 1)

    server._handle_client_ping(ClientId(1), _messages.ClientPingMessage(sent_ms=1234.5))

    (pong,) = client._websock_connection.messages
    assert isinstance(pong, _messages.ServerPongMessage)
    # Echoed, not read: the stamp is the client's own clock, and the two never
    # have to agree on one.
    assert pong.sent_ms == 1234.5


def test_the_answer_goes_out_immediately(server: leika.Server) -> None:
    client = _connect(server, 1)
    server._handle_client_ping(ClientId(1), _messages.ClientPingMessage(sent_ms=1.0))
    assert client.flushes == 1


def test_only_the_client_that_pinged_is_answered(server: leika.Server) -> None:
    # A pong broadcast to every browser would be a round trip the others never
    # started, timed against a stamp from a clock that is not theirs.
    pinger = _connect(server, 1)
    bystander = _connect(server, 2)

    server._handle_client_ping(ClientId(1), _messages.ClientPingMessage(sent_ms=7.0))

    assert len(pinger._websock_connection.messages) == 1
    assert bystander._websock_connection.messages == []


def test_pings_do_not_replace_one_another_in_the_buffer(server: leika.Server) -> None:
    # The buffer drops messages that share a redundancy key, keeping the last.
    # Under the name-based default every ping would share one, so a second ping
    # would swallow the first and the round trip it was timing would never be
    # answered.
    first = _messages.ClientPingMessage(sent_ms=1.0)
    second = _messages.ClientPingMessage(sent_ms=2.0)
    assert first.redundancy_key() != second.redundancy_key()

    pongs = (
        _messages.ServerPongMessage(sent_ms=1.0),
        _messages.ServerPongMessage(sent_ms=2.0),
    )
    assert pongs[0].redundancy_key() != pongs[1].redundancy_key()


def test_a_ping_from_a_client_that_has_gone_is_dropped(server: leika.Server) -> None:
    # The socket can close between the ping arriving and this running; there is
    # nobody left to answer, and looking one up would raise.
    server._handle_client_ping(ClientId(99), _messages.ClientPingMessage(sent_ms=1.0))
