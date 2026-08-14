from __future__ import annotations

import asyncio
import inspect
import sys
import threading
import traceback
from collections.abc import Awaitable
from concurrent.futures import Executor, Future
from typing import Any, Callable


def print_async_exception(exc: BaseException) -> None:
    """Report one exception with the shared asynchronous-task format."""
    print("Task failed with exception:", file=sys.stderr)
    traceback.print_exception(type(exc), exc, exc.__traceback__)


def print_async_errors(future: Future[Any] | asyncio.Future[Any]) -> None:
    """Report errors from executor futures and event-loop tasks."""
    if future.cancelled():
        # Cancellation is an expected part of server shutdown.
        return

    exc = future.exception()
    if exc is not None:
        print_async_exception(exc)


async def await_async_errors(awaitable: Awaitable[Any]) -> None:
    """Await one user callback, reporting its failure without aborting peers.

    ``CancelledError`` deliberately remains outside the ``Exception`` catch:
    connection and server teardown must still be able to cancel a callback
    that is in flight.
    """
    try:
        await awaitable
    except Exception as exc:
        print_async_exception(exc)


_user_callback_context = threading.local()


def in_sync_user_callback() -> bool:
    """Whether this thread is executing Leika-owned synchronous user code."""
    return bool(getattr(_user_callback_context, "depth", 0))


def _invoke_sync_user_callback(callback: Callable[..., Any], args: tuple[Any, ...]) -> Any:
    """Invoke one callback while marking its executor thread as server-owned."""
    depth = getattr(_user_callback_context, "depth", 0)
    _user_callback_context.depth = depth + 1
    try:
        return callback(*args)
    finally:
        if depth:
            _user_callback_context.depth = depth
        else:
            del _user_callback_context.depth


def callback_result_is_awaitable(result: object) -> bool:
    """Whether a callback result needs event-loop ownership."""
    return isinstance(result, Future) or inspect.isawaitable(result)


async def await_callback_result(result: object) -> None:
    """Await concurrent and asyncio/custom awaitables through one boundary."""
    if isinstance(result, Future):
        await asyncio.wrap_future(result)
    elif inspect.isawaitable(result):
        await result


async def await_user_callback(executor: Executor, callback: Callable[..., Any], *args: Any) -> None:
    """Run one callback in its proper context and await any returned work.

    Coroutine functions, including callable objects with an async ``__call__``,
    begin on the owning event loop. Ordinary callables run in ``executor`` so
    they cannot block that loop. Either kind may return another awaitable; that
    result is awaited before the next callback is dispatched.
    """
    try:
        call = getattr(callback, "__call__", None)
        if inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(call):
            result = callback(*args)
        else:
            result = await asyncio.wrap_future(
                executor.submit(_invoke_sync_user_callback, callback, args)
            )

        await await_callback_result(result)
    except Exception as exc:
        # Cancellation is a BaseException and deliberately passes through so
        # connection and server teardown can retire in-flight user work.
        print_async_exception(exc)
