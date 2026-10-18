from __future__ import annotations

import asyncio
import inspect
import sys
import traceback
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
            result = await asyncio.wrap_future(executor.submit(callback, *args))

        await await_callback_result(result)
    except Exception as exc:
        # Cancellation is a BaseException and deliberately passes through so
        # connection and server teardown can retire in-flight user work.
        print_async_exception(exc)
