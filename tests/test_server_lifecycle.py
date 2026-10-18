from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
import types
from concurrent.futures import Future, ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._client_autobuild
import leika._pages as pages_impl
import leika._server as server_impl
import leika._transport._websocket as websocket_impl
from leika._client_handle import ClientHandle
from leika._messages import Message
from leika._transport._message_buffer import AsyncMessageBuffer
from leika._transport._typescript import protocol_fingerprint
from leika._transport._websocket import ClientId, WebsockClientConnection, WebsockServer

PROTOCOL = Subprotocol(f"leika-{protocol_fingerprint()}")


@pytest.fixture(autouse=True)
def _skip_client_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)


async def _ignore(_: WebsockClientConnection) -> None:
    pass


def _low_level_server(host: str = "127.0.0.1", port: int = 0) -> WebsockServer:
    return WebsockServer(host, port, on_connect=_ignore, on_disconnect=_ignore, verbose=False)


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

    server = _low_level_server()

    def stubborn_worker(_: Future[None]) -> None:
        worker_started.set()
        release_worker.wait()

    monkeypatch.setattr(websocket_impl, "Future", InterruptingFuture)
    monkeypatch.setattr(websocket_impl, "_SERVER_STOP_TIMEOUT_SECONDS", 0.01)
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
            return SimpleNamespace(sockets=[socket])

        async def __aexit__(self, *_: Any) -> None:
            raise OSError("ready server failed during shutdown")

    monkeypatch.setattr(
        websocket_impl.websockets.legacy.server,
        "serve",
        lambda *args, **kwargs: FailingServeContext(),
    )
    server = _low_level_server()
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
    server.signal_stop()
    worker.join(timeout=1.0)

    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], OSError)
    assert str(failures[0]) == "ready server failed during shutdown"
    assert len(loops) == 1 and loops[0].is_closed()
    assert server._background_event_loop is None


def test_high_level_stop_is_safe_from_the_server_event_loop() -> None:
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

        # A repeat call off-thread joins the worker directly.
        server.stop()
        assert server._websock_server._server_thread is not None
        assert not server._websock_server._server_thread.is_alive()
        assert server._thread_executor._shutdown
    finally:
        server.stop()


def test_stop_on_the_event_loop_still_runs_disconnect_callbacks() -> None:
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    connected = threading.Event()
    disconnected = threading.Event()
    server.on_client_connect(lambda _: connected.set())
    server.on_client_disconnect(lambda _: disconnected.set())

    async def stop_inside_event_loop() -> None:
        server.stop()

    try:
        with connect(
            f"ws://127.0.0.1:{server.port}",
            subprotocols=[PROTOCOL],
            open_timeout=2,
        ):
            assert connected.wait(2.0)
            asyncio.run_coroutine_threadsafe(stop_inside_event_loop(), server._event_loop).result(2)
            assert disconnected.wait(2.0)
    finally:
        server.stop()
    assert server._thread_executor._shutdown


def test_high_level_stop_from_sync_connection_callback_returns_promptly() -> None:
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    callback_returned = threading.Event()
    failures: list[BaseException] = []
    elapsed: list[float] = []

    @server.on_client_connect
    def stop_inside_callback(_: ClientHandle) -> None:
        started = time.monotonic()
        try:
            server.stop()
        except BaseException as error:
            failures.append(error)
        finally:
            elapsed.append(time.monotonic() - started)
            callback_returned.set()

    try:
        with connect(
            f"ws://127.0.0.1:{server.port}",
            subprotocols=[PROTOCOL],
            open_timeout=2,
        ):
            assert callback_returned.wait(2.0)
    finally:
        server.stop()

    assert failures == []
    assert elapsed and elapsed[0] < 1.0
    server_thread = server._websock_server._server_thread
    assert server_thread is not None
    # callback_returned is set by the callback itself, just before the event
    # loop releases callback ownership. The repeat stop() in finally may
    # therefore still take the deliberately asynchronous callback-safe path.
    # Synchronize with the terminal worker state before asserting it.
    server_thread.join(timeout=2.0)
    assert not server_thread.is_alive()


def test_client_handle_gui_uses_the_connection_loop() -> None:
    loop = asyncio.new_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    server = SimpleNamespace(
        _thread_executor=executor,
        _next_gui_order=lambda: 1.0,
    )

    async def make_buffer(persistent: bool) -> AsyncMessageBuffer:
        # Build the buffer on its owning loop, matching production.
        return AsyncMessageBuffer(loop, persistent_messages=persistent)

    connection = WebsockClientConnection(
        ClientId(1),
        websocket_impl._ClientHandleState(
            loop.run_until_complete(make_buffer(False)),
            loop.run_until_complete(make_buffer(True)),
        ),
    )

    try:
        client = ClientHandle(connection, server)  # type: ignore[arg-type]
        assert client.gui._event_loop is loop
    finally:
        executor.shutdown()
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

    with connect(
        f"ws://127.0.0.1:{server.port}",
        subprotocols=[PROTOCOL],
        open_timeout=2,
    ):
        assert connected.wait(2.0)

    assert disconnected.wait(2.0)
    errors = capsys.readouterr().err
    assert "RuntimeError: high-level connect failed" in errors
    assert "RuntimeError: high-level disconnect failed" in errors


def test_high_level_callbacks_await_callable_objects_and_returned_awaitables(
    server: leika.Server,
) -> None:
    calls: list[str] = []
    connected = threading.Event()
    immediate = threading.Event()
    disconnected = threading.Event()

    class AsyncRecorder:
        def __init__(self, name: str, finished: threading.Event) -> None:
            self.name = name
            self.finished = finished

        async def __call__(self, _: ClientHandle) -> None:
            await asyncio.sleep(0)
            calls.append(self.name)
            self.finished.set()

    server.on_client_connect(AsyncRecorder("connect", connected))
    server.on_client_disconnect(AsyncRecorder("disconnect", disconnected))

    with connect(
        f"ws://127.0.0.1:{server.port}",
        subprotocols=[PROTOCOL],
        open_timeout=2,
    ):
        assert connected.wait(2.0)

        def returning_coroutine(_: ClientHandle) -> Any:
            async def finish() -> None:
                await asyncio.sleep(0)
                calls.append("immediate")
                immediate.set()

            return finish()

        server.on_client_connect(returning_coroutine)
        assert immediate.wait(2.0)

    assert disconnected.wait(2.0)
    assert calls == ["connect", "immediate", "disconnect"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"host": ""},
        {"host": " "},
        {"host": "bad_host"},
        {"port": -1},
        {"port": 65_536},
        {"port": True},
        {"workspace_id": ""},
        {"workspace_id": True},
        {"label": 1},
        {"password": 1},
        {"password": ""},
        {"share": 1},
        {"verbose": 1},
        {"allow_embedding": 1},
        {"allowed_hosts": ["bad_host"]},
    ],
)
def test_invalid_high_level_constructor_inputs_fail_before_build_or_workers(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict[str, Any]
) -> None:
    built = False

    def build() -> None:
        nonlocal built
        built = True

    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", build)
    with pytest.raises((TypeError, ValueError)):
        leika.Server(**kwargs)
    assert not built


@pytest.mark.parametrize(
    ("field", "exception_type", "message"),
    [
        ("host", ValueError, "host must be a valid"),
        ("password", TypeError, "password must be a string"),
    ],
)
def test_server_rejects_string_subclasses_before_allocation(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    exception_type: type[Exception],
    message: str,
) -> None:
    class RichStr(str):
        pass

    built = False

    def build() -> None:
        nonlocal built
        built = True

    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", build)
    value = RichStr("127.0.0.1" if field == "host" else "secret")
    arguments: dict[str, Any] = {"host": "127.0.0.1", "port": 0, "verbose": False}
    arguments[field] = value
    with pytest.raises(exception_type, match=message):
        leika.Server(**arguments)
    assert not built


def test_client_build_failure_occurs_before_executor_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("client build failed")
    allocated = False

    def fail_build() -> None:
        raise failure

    class ForbiddenExecutor:
        def __init__(self, max_workers: int) -> None:
            del max_workers
            nonlocal allocated
            allocated = True

    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", fail_build)
    monkeypatch.setattr(server_impl, "ThreadPoolExecutor", ForbiddenExecutor)
    with pytest.raises(RuntimeError, match="client build failed") as captured:
        leika.Server(host="127.0.0.1", port=0, verbose=False)
    assert captured.value is failure
    assert not allocated


def _record_construction(
    monkeypatch: pytest.MonkeyPatch, server_type: type[WebsockServer] = WebsockServer
) -> tuple[list[WebsockServer], list[ThreadPoolExecutor]]:
    servers: list[WebsockServer] = []
    executors: list[ThreadPoolExecutor] = []

    class RecordingServer(server_type):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            servers.append(self)

    class RecordingExecutor(ThreadPoolExecutor):
        def __init__(self, max_workers: int) -> None:
            super().__init__(max_workers)
            executors.append(self)

    monkeypatch.setattr(server_impl, "WebsockServer", RecordingServer)
    monkeypatch.setattr(server_impl, "ThreadPoolExecutor", RecordingExecutor)
    return servers, executors


def _assert_released(servers: list[WebsockServer], executors: list[ThreadPoolExecutor]) -> None:
    # The workspace is built before the server listens, so it never started.
    assert len(servers) == 1
    assert servers[0]._server_thread is None
    assert servers[0]._background_event_loop is None
    assert len(executors) == 1
    assert executors[0]._shutdown


def test_late_constructor_failure_releases_the_server_and_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    servers, executors = _record_construction(monkeypatch)

    def fail_panes(*_: Any) -> None:
        raise RuntimeError("late pane initialization failure")

    monkeypatch.setattr(pages_impl, "Panes", fail_panes)
    with pytest.raises(RuntimeError, match="late pane initialization failure"):
        leika.Server(host="127.0.0.1", port=0, verbose=False)
    _assert_released(servers, executors)


def test_constructor_failure_is_not_masked_by_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = RuntimeError("primary pane construction failure")

    class FailingStopServer(WebsockServer):
        def stop(self) -> None:
            super().stop()
            raise RuntimeError("secondary cleanup failure")

    servers, executors = _record_construction(monkeypatch, FailingStopServer)

    def fail_panes(*_: Any) -> None:
        raise primary

    monkeypatch.setattr(pages_impl, "Panes", fail_panes)
    with pytest.raises(RuntimeError, match="primary pane construction failure") as captured:
        leika.Server(host="127.0.0.1", port=0, verbose=False)
    assert captured.value is primary
    _assert_released(servers, executors)


def test_workspace_publication_failure_releases_the_server_and_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectingServer(WebsockServer):
        def queue_message(self, message: Message) -> bool:
            del message
            return False

    servers, executors = _record_construction(monkeypatch, RejectingServer)
    with pytest.raises(RuntimeError, match="closed connection"):
        leika.Server(host="127.0.0.1", port=0, verbose=False)
    _assert_released(servers, executors)


def test_quiet_low_level_server_is_one_shot(capsys: pytest.CaptureFixture[str]) -> None:
    server = _low_level_server()
    server.start()
    try:
        with pytest.raises(RuntimeError, match="only be started once"):
            server.start()
    finally:
        server.stop()
    with pytest.raises(RuntimeError, match="only be started once"):
        server.start()
    assert "Server stopped" not in capsys.readouterr().out


def test_requested_occupied_port_fails_without_scanning() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        server = _low_level_server(port=port)
        with pytest.raises(OSError):
            server.start()
    assert server._port == port
    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_localhost_ephemeral_multi_bind_fails_with_actionable_guidance() -> None:
    server = _low_level_server("localhost")
    try:
        server.start()
    except RuntimeError as error:
        assert "bind an IP literal" in str(error)
        assert server._server_thread is not None
        assert not server._server_thread.is_alive()
    else:
        # Platforms that resolve localhost to one listener don't need the
        # multi-bind guard; the selected port is a real bound port.
        assert server._port > 0
        server.stop()


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("::1", "http://[::1]:8080"),
        ("fe80::1%eth0", "http://[fe80::1%25eth0]:8080"),
        ("::", "http://localhost:8080"),
    ],
)
def test_public_url_formats_ipv6_authorities(host: str, expected: str) -> None:
    server = leika.Server.__new__(leika.Server)
    server.host = host
    server.port = 8080
    assert server.url == expected


def test_server_asset_registration_requires_a_path(server: leika.Server) -> None:
    with pytest.raises(TypeError, match="pathlib.Path"):
        server.register_http_asset("asset.png")  # type: ignore[arg-type]


@pytest.mark.parametrize("height", [0, -1, True, 1.5, "600"])
def test_show_validates_height_before_environment_detection(height: object) -> None:
    server = leika.Server.__new__(leika.Server)
    server.host = "127.0.0.1"
    server.port = 8080
    server.allow_embedding = True
    with pytest.raises(ValueError, match="positive integer"):
        server.show(height=height)  # type: ignore[arg-type]


def test_show_requires_and_honors_embedding_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ipython = types.ModuleType("IPython")

    def get_ipython() -> object:
        return object()

    ipython.get_ipython = get_ipython  # type: ignore[attr-defined]
    display_module = types.ModuleType("IPython.display")
    shown: list[Any] = []
    display_module.IFrame = lambda url, width, height: (url, width, height)  # type: ignore[attr-defined]
    display_module.display = shown.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)

    server = leika.Server.__new__(leika.Server)
    server.host = "127.0.0.1"
    server.port = 8080
    server.allow_embedding = False
    with pytest.raises(RuntimeError, match="allow_embedding=True"):
        server.show()

    server.allow_embedding = True
    frame = server.show(height=420)
    assert frame == ("http://127.0.0.1:8080", "100%", 420)
    assert shown == [frame]


def test_stop_from_external_future_returned_by_callback_never_joins_its_owner() -> None:
    from concurrent.futures import ThreadPoolExecutor

    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    returned = threading.Event()
    failures: list[BaseException] = []
    elapsed: list[float] = []
    external = ThreadPoolExecutor(max_workers=1)

    @server.on_client_connect
    def return_external_stop(_: ClientHandle) -> Future[None]:
        def stop() -> None:
            started = time.monotonic()
            try:
                server.stop()
            except BaseException as error:
                failures.append(error)
            finally:
                elapsed.append(time.monotonic() - started)
                returned.set()

        return external.submit(stop)

    websocket = None
    try:
        websocket = connect(
            f"ws://127.0.0.1:{server.port}",
            subprotocols=[PROTOCOL],
            open_timeout=2,
        )
        assert returned.wait(2.0)
        assert failures == []
        assert elapsed and elapsed[0] < 1.0
        deadline = time.monotonic() + 2.0
        while (
            server._websock_server._server_thread is not None
            and server._websock_server._server_thread.is_alive()
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert server._websock_server._server_thread is not None
        assert not server._websock_server._server_thread.is_alive()
    finally:
        if websocket is not None:
            websocket.close()
        server.stop()
        external.shutdown(wait=True)


def test_immediate_connect_callback_skips_a_disconnected_snapshot(
    server: leika.Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = ClientId(99)
    stale = SimpleNamespace(client_id=client_id)
    with server._client_lock:
        server._connected_clients[client_id] = stale  # type: ignore[assignment]

    scheduled: list[Any] = []

    def capture(coroutine: Any, _: Any) -> Future[Any]:
        scheduled.append(coroutine)
        completed: Future[Any] = Future()
        completed.set_result(None)
        return completed

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", capture)
    seen: list[Any] = []
    server.on_client_connect(seen.append)
    assert len(scheduled) == 1

    with server._client_lock:
        server._connected_clients.pop(client_id)
    asyncio.run(scheduled[0])
    assert seen == []


def test_workspace_id_obeys_browser_utf16_layout_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds = 0

    def built() -> None:
        nonlocal builds
        builds += 1

    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", built)
    with pytest.raises(ValueError, match="1024 UTF-16"):
        leika.Server(
            host="127.0.0.1",
            port=0,
            workspace_id="😀" * 512 + "x",
            verbose=False,
        )
    with pytest.raises(ValueError, match="surrogate"):
        leika.Server(
            host="127.0.0.1",
            port=0,
            workspace_id="bad\ud800",
            verbose=False,
        )
    for reserved in ("__proto__", "prototype", "constructor"):
        with pytest.raises(ValueError, match="reserved browser"):
            leika.Server(
                host="127.0.0.1",
                port=0,
                workspace_id=reserved,
                verbose=False,
            )
    assert builds == 0

    server = leika.Server(
        host="127.0.0.1",
        port=0,
        workspace_id="😀" * 512,
        verbose=False,
    )
    try:
        assert server.workspace_id == "😀" * 512
    finally:
        server.stop()


def test_tunnel_close_failure_does_not_skip_owned_shutdown_cleanup() -> None:
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    server.on_client_connect(lambda _: None)
    server.on_client_disconnect(lambda _: None)

    class FailingTunnel:
        url = "https://example.invalid"

        def close(self) -> None:
            raise OSError("tunnel close failed")

    server._share_tunnel = FailingTunnel()  # type: ignore[assignment]
    with pytest.raises(OSError, match="tunnel close failed"):
        server.stop()

    assert server._share_tunnel is None
    assert server._thread_executor._shutdown
    server_thread = server._websock_server._server_thread
    assert server_thread is not None and not server_thread.is_alive()
    server.stop()


def test_delivery_backpressure_rejects_non_boolean_before_start() -> None:
    with pytest.raises(TypeError, match="delivery_backpressure must be a bool"):
        leika.Server(host="127.0.0.1", port=0, delivery_backpressure="yes")  # type: ignore[arg-type]
