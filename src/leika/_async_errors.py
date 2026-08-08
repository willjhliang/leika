from __future__ import annotations

import asyncio
import sys
import traceback
from collections.abc import Awaitable
from concurrent.futures import Future
from typing import Any


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
