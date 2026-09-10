"""Bounded background work shared by callback and file-transfer owners."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


class BoundedThreadPoolExecutor(ThreadPoolExecutor):
    """Thread pool with explicit job and captured-payload admission bounds."""

    def __init__(
        self,
        max_workers: int,
        *,
        max_pending: int = 256,
        max_retained_bytes: int | None = None,
    ) -> None:
        if type(max_pending) is not int or max_pending < max_workers:
            raise ValueError("max_pending must be an integer at least max_workers")
        if max_retained_bytes is not None and (
            type(max_retained_bytes) is not int or max_retained_bytes < 0
        ):
            raise ValueError("max_retained_bytes must be a non-negative integer or None")
        super().__init__(max_workers=max_workers)
        self._max_pending = max_pending
        self._max_retained_bytes = max_retained_bytes
        self._pending_lock = threading.RLock()
        self._pending_futures: set[Future[Any]] = set()
        self._retained_bytes_from_future: dict[Future[Any], int] = {}
        self._retained_bytes = 0

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        return self.submit_retained(fn, *args, retained_bytes=0, **kwargs)

    def submit_retained(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        retained_bytes: int,
        **kwargs: Any,
    ) -> Future[Any]:
        if type(retained_bytes) is not int or retained_bytes < 0:
            raise ValueError("retained_bytes must be a non-negative integer")
        with self._pending_lock:
            if len(self._pending_futures) >= self._max_pending:
                raise RuntimeError("executor pending-work limit reached")
            if (
                self._max_retained_bytes is not None
                and self._retained_bytes + retained_bytes > self._max_retained_bytes
            ):
                raise RuntimeError("executor retained-payload limit reached")
            future = super().submit(fn, *args, **kwargs)
            self._pending_futures.add(future)
            self._retained_bytes_from_future[future] = retained_bytes
            self._retained_bytes += retained_bytes
            future.add_done_callback(self._discard)
            return future

    def _discard(self, future: Future[Any]) -> None:
        with self._pending_lock:
            self._pending_futures.discard(future)
            self._retained_bytes -= self._retained_bytes_from_future.pop(future, 0)

    def shutdown_cancel_pending(self) -> None:
        """Reject new work, cancel queued work, and let running work finish."""
        with self._pending_lock:
            for future in tuple(self._pending_futures):
                future.cancel()
            super().shutdown(wait=False, cancel_futures=True)
