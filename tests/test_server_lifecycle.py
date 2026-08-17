from __future__ import annotations

import asyncio
import gc
import socket
import sys
import threading
import time
import types
import weakref
from collections.abc import Sequence
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from websockets.sync.client import connect
from websockets.typing import Subprotocol

import leika
import leika._client_autobuild
import leika._messages
import leika._pages as pages_impl
import leika._server as server_impl
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


def test_high_level_stop_from_sync_connection_callback_returns_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
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

    protocol = Subprotocol(
        f"leika-v{leika.__version__}+p{protocol_fingerprint(leika._messages.Message)}"
    )
    try:
        with connect(
            f"ws://127.0.0.1:{server.port}",
            subprotocols=[protocol],
            open_timeout=2,
        ):
            assert callback_returned.wait(2.0)
    finally:
        server.stop()

    assert failures == []
    assert elapsed and elapsed[0] < 1.0
    assert server._websock_server._server_thread is not None
    assert not server._websock_server._server_thread.is_alive()


def test_stop_finalizer_start_failure_can_be_retried_while_callback_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    original_start = threading.Thread.start
    failed = False

    def fail_finalizer_once(thread: threading.Thread) -> None:
        nonlocal failed
        if thread.name == "leika-stop-finalizer" and not failed:
            failed = True
            raise RuntimeError("cannot start finalizer")
        original_start(thread)

    with server._stop_lock:
        server._active_user_callbacks += 1
    monkeypatch.setattr(threading.Thread, "start", fail_finalizer_once)
    try:
        with pytest.raises(RuntimeError, match="cannot start finalizer"):
            server.stop()
        assert server._stop_finalizer is None

        monkeypatch.setattr(threading.Thread, "start", original_start)
        server.stop()
        deadline = time.monotonic() + 2.0
        while (
            not server._executor_shutdown or server._stop_finalizer is not None
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server._executor_shutdown
        assert server._stop_finalizer is None
    finally:
        with server._stop_lock:
            server._active_user_callbacks -= 1
        server.stop()


def test_stop_finalizer_target_failure_clears_ownership_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    original_finish = server._finish_stop
    first_failed = threading.Event()
    attempts = 0

    def fail_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_failed.set()
            raise RuntimeError("finalizer target failed")
        original_finish()

    # The failure is intentional; this tests ownership release and retry rather
    # than the standard thread exception hook.
    monkeypatch.setattr(threading, "excepthook", lambda _: None)
    monkeypatch.setattr(server, "_finish_stop", fail_once)
    with server._stop_lock:
        server._active_user_callbacks += 1
    try:
        server.stop()
        assert first_failed.wait(1.0)
        deadline = time.monotonic() + 1.0
        while server._stop_finalizer is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server._stop_finalizer is None

        server.stop()
        deadline = time.monotonic() + 2.0
        while (
            not server._executor_shutdown or server._stop_finalizer is not None
        ) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert attempts == 2
        assert server._executor_shutdown
        assert server._stop_finalizer is None
    finally:
        with server._stop_lock:
            server._active_user_callbacks -= 1
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


def test_callback_executor_bounds_pending_jobs_and_releases_admission() -> None:
    executor = _CallbackExecutor(max_workers=1, max_pending=2)
    running_started = threading.Event()
    release_running = threading.Event()

    def block() -> None:
        running_started.set()
        release_running.wait()

    running = executor.submit(block)
    assert running_started.wait(1.0)
    queued = executor.submit(lambda: None)
    with pytest.raises(RuntimeError, match="pending-work limit"):
        executor.submit(lambda: None)

    release_running.set()
    running.result(timeout=1.0)
    queued.result(timeout=1.0)
    executor.submit(lambda: None).result(timeout=1.0)
    executor.shutdown_cancel_pending()


def test_transfer_executor_bounds_and_releases_retained_payload_bytes() -> None:
    executor = _CallbackExecutor(max_workers=1, max_pending=4, max_retained_bytes=5)
    running_started = threading.Event()
    release_running = threading.Event()

    def block() -> None:
        running_started.set()
        release_running.wait()

    running = executor.submit_retained(block, retained_bytes=3)
    assert running_started.wait(1.0)
    with pytest.raises(RuntimeError, match="retained-payload limit"):
        executor.submit_retained(lambda: None, retained_bytes=3)
    accepted = executor.submit_retained(lambda: None, retained_bytes=2)

    release_running.set()
    running.result(timeout=1.0)
    accepted.result(timeout=1.0)
    assert executor._retained_bytes == 0
    executor.submit_retained(lambda: None, retained_bytes=5).result(timeout=1.0)
    executor.shutdown_cancel_pending()


def test_client_handle_uses_the_live_connection_loop_before_server_start_returns() -> None:
    loop = asyncio.new_event_loop()
    executor = _CallbackExecutor(max_workers=1)
    server = SimpleNamespace(
        _thread_executor=executor,
        _next_gui_order=lambda: 1.0,
    )

    async def make_buffer() -> infra_impl.AsyncMessageBuffer:
        # Build the buffer on its owning loop, matching production.
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

    protocol = Subprotocol(
        f"leika-v{leika.__version__}+p{protocol_fingerprint(leika._messages.Message)}"
    )
    with connect(
        f"ws://127.0.0.1:{server.port}",
        subprotocols=[protocol],
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
    "kwargs",
    [
        {"host": ""},
        {"host": "bad_host"},
        {"port": -1},
        {"port": 65_536},
        {"port": True},
        {"password": 1},
        {"verbose": 1},
        {"allow_embedding": 1},
        {"message_class": object},
        {"message_class": "Message"},
    ],
)
def test_invalid_low_level_constructor_inputs_fail_before_start(
    kwargs: dict[str, Any],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        infra_impl.WebsockServer(**{"host": "127.0.0.1", "port": 0, **kwargs})


@pytest.mark.parametrize(
    ("level", "field", "exception_type", "message"),
    [
        ("high", "host", ValueError, "host must be a valid"),
        ("high", "password", TypeError, "password must be a string"),
        ("low", "host", ValueError, "host must be a valid"),
        ("low", "password", TypeError, "password must be a string"),
    ],
)
def test_server_constructors_reject_string_subclasses_before_allocation(
    monkeypatch: pytest.MonkeyPatch,
    level: str,
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
        if level == "high":
            leika.Server(**arguments)
        else:
            infra_impl.WebsockServer(**arguments)
    assert not built


def test_low_level_http_root_detaches_path_subclasses(tmp_path: Path) -> None:
    class Payload:
        pass

    class RichPath(type(Path())):
        def resolve(self, *args: Any, **kwargs: Any) -> Path:
            del args, kwargs
            raise AssertionError("Path subclass resolve hook must not run")

    root = tmp_path / "served"
    root.mkdir()
    payload = Payload()
    payload_ref = weakref.ref(payload)
    rich_root = RichPath(root)
    rich_root.payload = payload

    server = infra_impl.WebsockServer(
        host="127.0.0.1",
        port=0,
        http_server_root=rich_root,
        verbose=False,
    )
    assert server._http_server_root == root.resolve()
    assert type(server._http_server_root) is type(Path())

    del rich_root, payload
    gc.collect()
    assert payload_ref() is None


def test_low_level_stop_before_start_is_terminal() -> None:
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    server.stop()

    assert server._lifecycle_state == "stopped"
    assert server._stop_requested.is_set()
    with pytest.raises(RuntimeError, match="only be started once"):
        server.start()


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
    monkeypatch.setattr(server_impl, "_CallbackExecutor", ForbiddenExecutor)
    with pytest.raises(RuntimeError, match="client build failed") as captured:
        leika.Server(host="127.0.0.1", port=0, verbose=False)
    assert captured.value is failure
    assert not allocated


def test_late_constructor_failure_stops_server_and_executors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    servers: list[infra_impl.WebsockServer] = []
    executors: list[_CallbackExecutor] = []
    real_server = infra_impl.WebsockServer
    real_executor = server_impl._CallbackExecutor

    class RecordingServer(real_server):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            servers.append(self)

    class RecordingExecutor(real_executor):
        def __init__(self, max_workers: int, **kwargs: Any) -> None:
            super().__init__(max_workers, **kwargs)
            executors.append(self)

    def fail_panes(owner: Any, **_: Any) -> None:
        del owner
        raise RuntimeError("late pane initialization failure")

    monkeypatch.setattr(server_impl.infra, "WebsockServer", RecordingServer)
    monkeypatch.setattr(server_impl, "_CallbackExecutor", RecordingExecutor)
    monkeypatch.setattr(pages_impl, "Panes", fail_panes)

    with pytest.raises(RuntimeError, match="late pane initialization failure"):
        leika.Server(host="127.0.0.1", port=0, verbose=False)

    assert len(servers) == 1
    assert servers[0]._server_thread is not None
    assert not servers[0]._server_thread.is_alive()
    assert len(executors) == 2
    assert all(executor._shutdown for executor in executors)


def test_constructor_failure_is_not_masked_by_executor_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    primary = RuntimeError("primary pane construction failure")
    executors: list[_CallbackExecutor] = []
    real_executor = server_impl._CallbackExecutor

    class FailingCleanupExecutor(real_executor):
        def __init__(self, max_workers: int, **kwargs: Any) -> None:
            super().__init__(max_workers, **kwargs)
            self.cleanup_calls = 0
            executors.append(self)

        def shutdown_cancel_pending(self) -> None:
            self.cleanup_calls += 1
            super().shutdown_cancel_pending()
            raise RuntimeError("secondary executor cleanup failure")

    def fail_panes(_: Any, **__: Any) -> None:
        raise primary

    monkeypatch.setattr(server_impl, "_CallbackExecutor", FailingCleanupExecutor)
    monkeypatch.setattr(pages_impl, "Panes", fail_panes)

    with pytest.raises(RuntimeError, match="primary pane construction failure") as captured:
        leika.Server(host="127.0.0.1", port=0, verbose=False)

    assert captured.value is primary
    assert len(executors) == 2
    assert [executor.cleanup_calls for executor in executors] == [1, 1]
    assert all(executor._shutdown for executor in executors)


def test_workspace_publication_failure_rolls_back_started_server_and_executors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    servers: list[infra_impl.WebsockServer] = []
    executors: list[_CallbackExecutor] = []
    real_server = infra_impl.WebsockServer
    real_executor = server_impl._CallbackExecutor

    class RejectingServer(real_server):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            servers.append(self)

        def queue_message(self, message: infra_impl.Message) -> bool:
            del message
            return False

    class RecordingExecutor(real_executor):
        def __init__(self, max_workers: int, **kwargs: Any) -> None:
            super().__init__(max_workers, **kwargs)
            executors.append(self)

    monkeypatch.setattr(server_impl.infra, "WebsockServer", RejectingServer)
    monkeypatch.setattr(server_impl, "_CallbackExecutor", RecordingExecutor)

    with pytest.raises(RuntimeError, match="closed connection"):
        leika.Server(host="127.0.0.1", port=0, verbose=False)

    assert len(servers) == 1
    assert servers[0]._server_thread is not None
    assert not servers[0]._server_thread.is_alive()
    assert len(executors) == 2
    assert all(executor._shutdown for executor in executors)


def test_allowed_hosts_sequence_is_normalized_once_before_worker_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)

    class SingleUseHosts(Sequence[str]):
        def __init__(self) -> None:
            self.iterations = 0

        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> str:
            if index != 0:
                raise IndexError
            return "dashboard.example"

        def __iter__(self):
            self.iterations += 1
            if self.iterations > 1:
                raise RuntimeError("allowed hosts were consumed twice")
            yield "dashboard.example"

    hosts = SingleUseHosts()
    server = leika.Server(
        host="127.0.0.1",
        port=0,
        verbose=False,
        allowed_hosts=hosts,  # type: ignore[arg-type]
    )
    try:
        assert hosts.iterations == 1
        assert server._websock_server._allowed_hosts == frozenset({"dashboard.example"})
    finally:
        server.stop()


def test_allowed_hosts_are_bounded_even_when_a_sequence_lies_about_length() -> None:
    exact = tuple(f"host-{index}.example" for index in range(infra_impl._ALLOWED_HOSTS_MAX))
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, allowed_hosts=exact, verbose=False)
    assert len(server._allowed_hosts) == infra_impl._ALLOWED_HOSTS_MAX

    with pytest.raises(ValueError, match="more than 256"):
        infra_impl.WebsockServer(
            host="127.0.0.1",
            port=0,
            allowed_hosts=exact + ("one-too-many.example",),
            verbose=False,
        )

    class LyingHosts(Sequence[str]):
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> str:
            return f"host-{index}.example"

        def __iter__(self):
            for index in range(infra_impl._ALLOWED_HOSTS_MAX + 1):
                yield f"host-{index}.example"

    with pytest.raises(ValueError, match="length changed"):
        infra_impl.WebsockServer(
            host="127.0.0.1",
            port=0,
            allowed_hosts=LyingHosts(),
            verbose=False,
        )


def test_start_stop_race_never_erases_the_stop_request() -> None:
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    entered_clear = threading.Event()
    release_clear = threading.Event()
    stop_returned = threading.Event()

    class PausingEvent(threading.Event):
        def clear(self) -> None:
            super().clear()
            entered_clear.set()
            assert release_clear.wait(2)

    server._stop_requested = PausingEvent()
    failures: list[BaseException] = []

    def start() -> None:
        try:
            server.start()
        except BaseException as error:
            failures.append(error)

    def stop() -> None:
        try:
            server.stop()
        except BaseException as error:
            failures.append(error)
        finally:
            stop_returned.set()

    starter = threading.Thread(target=start)
    stopper = threading.Thread(target=stop)
    starter.start()
    assert entered_clear.wait(1)
    stopper.start()
    # stop() waits for start() to finish its locked publication instead of
    # returning while a not-yet-launched listener can still appear.
    assert not stop_returned.wait(0.05)
    release_clear.set()
    starter.join(timeout=3)
    stopper.join(timeout=3)
    server.stop()

    assert not starter.is_alive()
    assert not stopper.is_alive()
    assert failures == []
    assert server._stop_requested.is_set()
    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_stop_waits_for_a_paused_worker_thread_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    worker_start_entered = threading.Event()
    release_worker_start = threading.Event()
    stop_returned = threading.Event()
    failures: list[BaseException] = []
    original_start = threading.Thread.start

    def pause_server_worker(thread: threading.Thread) -> None:
        if thread is server._server_thread:
            worker_start_entered.set()
            assert release_worker_start.wait(2)
        original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", pause_server_worker)

    def start() -> None:
        try:
            server.start()
        except BaseException as error:
            failures.append(error)

    def stop() -> None:
        try:
            server.stop()
        except BaseException as error:
            failures.append(error)
        finally:
            stop_returned.set()

    starter = threading.Thread(target=start)
    stopper = threading.Thread(target=stop)
    original_start(starter)
    assert worker_start_entered.wait(1)
    original_start(stopper)
    assert not stop_returned.wait(0.05)
    release_worker_start.set()
    starter.join(timeout=3)
    stopper.join(timeout=3)

    assert failures == []
    assert stop_returned.is_set()
    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_quiet_low_level_lifecycle_prints_no_shutdown_banner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    server.start()
    server.stop()
    assert "Server stopped" not in capsys.readouterr().out


def test_stop_snapshots_connection_registry_under_its_lock() -> None:
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    values_entered = threading.Event()
    release_values = threading.Event()
    mutation_finished = threading.Event()

    class PausingRegistry(dict[int, Any]):
        def values(self):  # type: ignore[override]
            values_entered.set()
            assert release_values.wait(2)
            return super().values()

    server._client_state_from_id = PausingRegistry()
    signaler = threading.Thread(target=server._signal_stop)

    def mutate() -> None:
        with server._client_state_lock:
            server._client_state_from_id[1] = SimpleNamespace(
                message_buffer=SimpleNamespace(set_done=lambda: None)
            )
        mutation_finished.set()

    mutator = threading.Thread(target=mutate)
    signaler.start()
    assert values_entered.wait(1)
    mutator.start()
    assert not mutation_finished.wait(0.05)
    release_values.set()
    signaler.join(timeout=1)
    mutator.join(timeout=1)
    assert mutation_finished.is_set()


def test_low_level_server_is_one_shot() -> None:
    server = infra_impl.WebsockServer(host="127.0.0.1", port=0, verbose=False)
    server.start()
    try:
        with pytest.raises(RuntimeError, match="only be started once"):
            server.start()
    finally:
        server.stop()
    with pytest.raises(RuntimeError, match="only be started once"):
        server.start()


def test_requested_occupied_port_fails_without_scanning() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        server = infra_impl.WebsockServer(host="127.0.0.1", port=port, verbose=False)
        with pytest.raises(OSError):
            server.start()
    assert server._port == port
    assert server._server_thread is not None
    assert not server._server_thread.is_alive()


def test_localhost_ephemeral_multi_bind_fails_with_actionable_guidance() -> None:
    server = infra_impl.WebsockServer(host="localhost", port=0, verbose=False)
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


def test_stop_from_external_future_returned_by_callback_never_joins_its_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
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

    protocol = Subprotocol(
        f"leika-v{leika.__version__}+p{protocol_fingerprint(leika._messages.Message)}"
    )
    websocket = None
    try:
        websocket = connect(
            f"ws://127.0.0.1:{server.port}",
            subprotocols=[protocol],
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
    client_id = infra_impl.ClientId(99)
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


def test_tunnel_close_failure_does_not_skip_owned_shutdown_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
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
    assert server._client_connect_cb == []
    assert server._client_disconnect_cb == []
    assert server._executor_shutdown
    server.stop()


def test_callback_stop_hands_slow_share_tunnel_to_finalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    server = leika.Server(host="127.0.0.1", port=0, verbose=False)
    close_started = threading.Event()
    release_close = threading.Event()
    close_finished = threading.Event()

    class SlowTunnel:
        url = "https://example.invalid"

        def close(self) -> None:
            close_started.set()
            assert release_close.wait(2.0)
            close_finished.set()

    server._share_tunnel = SlowTunnel()  # type: ignore[assignment]
    with server._stop_lock:
        server._active_user_callbacks += 1
    started = time.monotonic()
    try:
        server.stop()
        elapsed = time.monotonic() - started
        assert elapsed < 0.5
        assert close_started.wait(2.0)
        assert not close_finished.is_set()
        release_close.set()
        assert close_finished.wait(2.0)
    finally:
        with server._stop_lock:
            server._active_user_callbacks -= 1
        release_close.set()
        server.stop()
    assert server._share_tunnel is None
