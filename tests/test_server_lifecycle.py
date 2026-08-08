from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from types import SimpleNamespace
from typing import Any

import pytest
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._client_autobuild
import leika._messages
import leika.infra._infra as infra_impl
from leika._server import ClientHandle, _CallbackExecutor
from leika.infra import protocol_fingerprint


@pytest.mark.parametrize("interruption_type", [KeyboardInterrupt, SystemExit])
def test_start_interruption_is_signalled_and_never_waits_without_a_bound(
    monkeypatch: pytest.MonkeyPatch,
    interruption_type: type[BaseException],
) -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()

    class InterruptingFuture(Future):
        def result(self, timeout: float | None = None) -> Any:
            assert worker_started.wait(1.0)
            raise interruption_type()

    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)

    def stubborn_worker(_: Future[None]) -> None:
        worker_started.set()
        release_worker.wait()

    monkeypatch.setattr(infra_impl, "Future", InterruptingFuture)
    monkeypatch.setattr(infra_impl, "_SERVER_STOP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(server, "_background_worker", stubborn_worker)

    try:
        with pytest.raises(interruption_type):
            server.start()

        # The worker deliberately ignores the signal. Returning while it is
        # still alive proves the caller was not trapped in an unbounded join.
        assert server._stop_requested.is_set()
        assert server._server_thread is not None
        assert server._server_thread.is_alive()
    finally:
        release_worker.set()
        if server._server_thread is not None:
            server._server_thread.join(timeout=1.0)

    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_post_ready_oserror_escapes_and_closes_the_worker_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loops: list[asyncio.AbstractEventLoop] = []

    class FailingServeContext:
        async def __aenter__(self) -> Any:
            loops.append(asyncio.get_running_loop())
            socket = SimpleNamespace(getsockname=lambda: ("127.0.0.1", 43210))
            return SimpleNamespace(server=SimpleNamespace(sockets=[socket]))

        async def __aexit__(self, *_: Any) -> None:
            raise OSError("ready server failed during shutdown")

    monkeypatch.setattr(
        infra_impl.websockets.asyncio.server,
        "serve",
        lambda *args, **kwargs: FailingServeContext(),
    )
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    startup: Future[None] = Future()
    failures: list[BaseException] = []

    def run_worker() -> None:
        try:
            server._background_worker(startup)
        except BaseException as error:
            failures.append(error)

    worker = threading.Thread(target=run_worker)
    worker.start()
    startup.result(timeout=1.0)
    server._signal_stop()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], OSError)
    assert str(failures[0]) == "ready server failed during shutdown"
    assert len(loops) == 1 and loops[0].is_closed()
    assert server._background_event_loop is None
    assert server._stop_event is None


def test_high_level_stop_is_safe_from_the_server_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    callback_returned = threading.Event()
    failures: list[BaseException] = []

    async def stop_inside_event_loop() -> None:
        try:
            assert threading.current_thread() is server._websock_server._server_thread
            server.stop()
        except BaseException as error:
            failures.append(error)
        finally:
            callback_returned.set()

    asyncio.run_coroutine_threadsafe(stop_inside_event_loop(), server._event_loop)
    try:
        assert callback_returned.wait(2.0)
        assert failures == []

        # A repeat call off-thread completes the bounded join even if the
        # asynchronous finalizer has not won the race yet.
        server.stop()
        assert server._websock_server._server_thread is not None
        assert not server._websock_server._server_thread.is_alive()
        assert server._executor_shutdown
    finally:
        server.stop()


def test_callback_executor_cancels_queued_work_and_finishes_running_work() -> None:
    executor = _CallbackExecutor(max_workers=1)
    running_started = threading.Event()
    release_running = threading.Event()
    running_finished = threading.Event()
    queued_ran = threading.Event()

    def running_callback() -> None:
        running_started.set()
        release_running.wait()
        running_finished.set()

    running = executor.submit(running_callback)
    assert running_started.wait(1.0)
    queued = executor.submit(queued_ran.set)

    try:
        executor.shutdown_cancel_pending()
        assert queued.cancelled()
        assert not running.cancelled()
        with pytest.raises(RuntimeError, match="shutdown"):
            executor.submit(lambda: None)
    finally:
        release_running.set()

    running.result(timeout=1.0)
    assert running_finished.is_set()
    assert not queued_ran.is_set()


def test_client_handle_uses_the_live_connection_loop_before_server_start_returns() -> None:
    loop = asyncio.new_event_loop()
    executor = _CallbackExecutor(max_workers=1)
    server = SimpleNamespace(
        _thread_executor=executor,
        _next_gui_order=lambda: 1.0,
    )

    async def make_buffer() -> infra_impl.AsyncMessageBuffer:
        # Python 3.8 binds asyncio primitives to the currently running loop.
        # Build the buffer on the loop it belongs to, matching production.
        return infra_impl.AsyncMessageBuffer(loop, persistent_messages=False)

    buffer = loop.run_until_complete(make_buffer())
    connection = infra_impl.WebsockClientConnection(
        infra_impl.ClientId(1),
        infra_impl._ClientHandleState(buffer),
    )

    try:
        # The high-level server intentionally has no _event_loop yet: a browser
        # can connect after the socket binds but before Server.__init__ returns.
        client = ClientHandle(connection, server)  # type: ignore[arg-type]
        assert client.gui._event_loop is loop
    finally:
        executor.shutdown_cancel_pending()
        loop.close()


def test_high_level_async_connection_callbacks_are_isolated(
    server: leika.Server,
    capsys: pytest.CaptureFixture[str],
) -> None:
    connected = threading.Event()
    disconnected = threading.Event()

    @server.on_client_connect
    async def fail_connect(_: ClientHandle) -> None:
        raise RuntimeError("high-level connect failed")

    @server.on_client_connect
    async def continue_connect(_: ClientHandle) -> None:
        connected.set()

    @server.on_client_disconnect
    async def fail_disconnect(_: ClientHandle) -> None:
        raise RuntimeError("high-level disconnect failed")

    @server.on_client_disconnect
    async def continue_disconnect(_: ClientHandle) -> None:
        disconnected.set()

    protocol = Subprotocol(
        f"leika-v{leika.__version__}+p{protocol_fingerprint(leika._messages.Message)}"
    )
    with connect(
        f"ws://127.0.0.1:{server.port}",
        subprotocols=[protocol],
        open_timeout=2,
    ):
        assert connected.wait(2.0)

    assert disconnected.wait(2.0)
    errors = capsys.readouterr().err
    assert "RuntimeError: high-level connect failed" in errors
    assert "RuntimeError: high-level disconnect failed" in errors
