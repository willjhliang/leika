"""Immutable runtime HTTP assets with bounded loading and retention."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import NamedTuple

from .._file_transfer import read_regular_file_snapshot
from ._image_headers import image_pixel_size, safe_image_info

_HTTP_ASSET_URL_PREFIX = "/leika-assets/"
"""Where runtime-registered files are served, apart from the static tree."""

_HTTP_ASSET_MAX_BYTES = 64 * 1024 * 1024
"""Largest runtime asset accepted into the bounded snapshot registry."""

_HTTP_ASSET_CACHE_MAX_BYTES = 128 * 1024 * 1024
"""Maximum runtime-asset bytes retained and shared by all responses."""

_HTTP_ASSET_LOAD_MAX_BYTES = 128 * 1024 * 1024
"""Maximum aggregate asset snapshots being read before registry admission."""

_HTTP_ASSET_LIMIT = 1024
"""How many registered assets are remembered. Registrations past this evict
the oldest; a URL that has been evicted answers 404, the same as one that was
never registered."""

_HTTP_ASSET_SUFFIX_PATTERN = re.compile(r"\.[a-z0-9]{1,16}\Z")


class HttpAsset(NamedTuple):
    """Where a registered file is served, and how big it is if it is a picture.

    The size travels with the URL because both fall out of the same read: a
    caller writing an ``<img>`` wants the address and the box to leave for it
    at the same moment, and asking twice would mean reading the file twice.
    """

    url: str
    """Root-relative URL path the file is served at."""
    pixel_size: tuple[int, int] | None
    """``(width, height)`` if the file's header declares one, else ``None``."""


class HttpAssetRegistry:
    """Own snapshots independently of HTTP requests and websocket connections.

    Registration may run in user threads. Closing is terminal and wakes every
    blocked registration; an in-flight load can never publish after close.
    """

    def __init__(self) -> None:
        # Runtime assets are immutable, content-addressed byte snapshots. A
        # bounded shared snapshot avoids repeated event-loop disk reads and
        # makes concurrent responses reuse one payload object.
        self._snapshots: dict[str, bytes] = {}
        self._bytes = 0
        self._lock = threading.Lock()
        self._terminal = False
        self._load_condition = threading.Condition()
        self._load_bytes = 0

    def close(self) -> None:
        """Close runtime-asset admission and release every cached snapshot."""
        with self._lock:
            self._terminal = True
            self._snapshots.clear()
            self._bytes = 0
        # Wake registrations waiting for load headroom so they can observe the
        # terminal state instead of remaining blocked behind abandoned work.
        with self._load_condition:
            self._load_condition.notify_all()

    def get(self, name: str) -> bytes | None:
        """Return one shared immutable payload under its exact registered name."""
        with self._lock:
            return self._snapshots.get(name)

    def register(
        self,
        path: Path,
        *,
        _expected_metadata: os.stat_result | None = None,
        _require_safe_image: bool = False,
    ) -> HttpAsset:
        """Snapshot, identify, and admit a file under an immutable URL.

        The load reservation covers reading, hashing, image inspection, and
        cache admission. Safe-image callers derive MIME suffix and dimensions
        from those same authenticated bytes.
        """
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        with self._lock:
            if self._terminal:
                raise RuntimeError("Cannot register HTTP assets after server shutdown.")
        # Resolve once: HTTP requests may be served after the process changes
        # working directory, but a registered source must keep its identity.
        path = path.resolve()
        # Reserve from the regular file's current size before loading. This
        # bounds simultaneous snapshots without holding the lookup lock used by
        # live HTTP GETs. Descriptor-based reading still verifies the source.
        estimated_metadata = path.stat()
        if estimated_metadata.st_size > _HTTP_ASSET_MAX_BYTES:
            raise ValueError(f"File is larger than the {_HTTP_ASSET_MAX_BYTES}-byte limit.")
        with self._load_condition:
            while self._load_bytes + _HTTP_ASSET_MAX_BYTES > _HTTP_ASSET_LOAD_MAX_BYTES:
                with self._lock:
                    if self._terminal:
                        raise RuntimeError("Cannot register HTTP assets after server shutdown.")
                self._load_condition.wait()
            with self._lock:
                if self._terminal:
                    raise RuntimeError("Cannot register HTTP assets after server shutdown.")
            # Charge the per-file ceiling, not the racy pre-open stat size: a
            # concurrent writer can grow the file before descriptor reading.
            self._load_bytes += _HTTP_ASSET_MAX_BYTES
        try:
            content = read_regular_file_snapshot(
                path,
                _HTTP_ASSET_MAX_BYTES,
                expected_metadata=(
                    _expected_metadata if _expected_metadata is not None else estimated_metadata
                ),
            )
            digest = hashlib.sha256(content).hexdigest()
            # Read from the bytes already in hand for the hash, so knowing the
            # shape of a picture costs nothing over not knowing it. The load
            # reservation remains owned until this immutable snapshot enters
            # the bounded cache; hashing and image parsing may retain it too.
            if _require_safe_image:
                image_kind, pixel_size = safe_image_info(content)
                width, height = pixel_size
                # The suffix is authenticated by the same bytes as the digest and
                # dimensions. A misleading or absent source suffix cannot change
                # MIME interpretation under nosniff.
                suffix = f".{image_kind}"
                name = f"{digest}-{width}x{height}{suffix}"
            else:
                pixel_size = image_pixel_size(content)
                suffix = path.suffix.lower()
                if _HTTP_ASSET_SUFFIX_PATTERN.fullmatch(suffix) is None:
                    suffix = ""
                name = f"{digest}{suffix}"
            with self._lock:
                if self._terminal:
                    raise RuntimeError("Cannot register HTTP assets after server shutdown.")
                previous = self._snapshots.pop(name, None)
                if previous is not None:
                    self._bytes -= len(previous)
                # Re-registration refreshes this content key's eviction order.
                self._snapshots[name] = content
                self._bytes += len(content)
                while self._snapshots and (
                    len(self._snapshots) > _HTTP_ASSET_LIMIT
                    or self._bytes > _HTTP_ASSET_CACHE_MAX_BYTES
                ):
                    oldest_name = next(iter(self._snapshots))
                    evicted = self._snapshots.pop(oldest_name)
                    self._bytes -= len(evicted)
            return HttpAsset(f"{_HTTP_ASSET_URL_PREFIX}{name}", pixel_size)
        finally:
            with self._load_condition:
                self._load_bytes -= _HTTP_ASSET_MAX_BYTES
                self._load_condition.notify_all()
