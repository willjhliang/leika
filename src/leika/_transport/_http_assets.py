"""Immutable, content-addressed runtime HTTP assets."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import NamedTuple

from .._file_transfer import read_regular_file_snapshot
from ._image_headers import image_pixel_size

_HTTP_ASSET_URL_PREFIX = "/leika-assets/"
"""Where runtime-registered files are served."""

_HTTP_ASSET_MAX_BYTES = 64 * 1024 * 1024
"""Largest file one registration snapshots."""

_HTTP_ASSET_CACHE_MAX_BYTES = 128 * 1024 * 1024
"""Snapshot bytes retained before the oldest registrations are evicted; an
evicted URL answers 404, like one never registered."""

_HTTP_ASSET_SUFFIX_PATTERN = re.compile(r"\.[a-z0-9]{1,16}\Z")


class HttpAsset(NamedTuple):
    """Where a registered file is served, and its size if it is a picture."""

    url: str
    """Root-relative URL path the file is served at."""
    pixel_size: tuple[int, int] | None
    """``(width, height)`` if the file's header declares one, else ``None``."""


class HttpAssetRegistry:
    """Snapshots of registered files, shared by every response.

    A file is served at ``/leika-assets/<sha256>[-<width>x<height>]<suffix>``.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, bytes] = {}
        self._bytes = 0
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        """Release every snapshot and refuse later registrations."""
        with self._lock:
            self._closed = True
            self._snapshots.clear()
            self._bytes = 0

    def get(self, name: str) -> bytes | None:
        with self._lock:
            return self._snapshots.get(name)

    def register(
        self, path: Path, *, _expected_metadata: os.stat_result | None = None
    ) -> HttpAsset:
        """Snapshot a file under a URL named by its content hash.

        A changed file registers under a different URL, so responses can be
        cached forever. ``_expected_metadata`` pins the file a caller already
        resolved. Raises ``OSError`` if the file cannot be read.
        """
        if not isinstance(path, Path):
            raise TypeError("path must be a pathlib.Path")
        content = read_regular_file_snapshot(
            path, _HTTP_ASSET_MAX_BYTES, expected_metadata=_expected_metadata
        )
        suffix = path.suffix.lower()
        if _HTTP_ASSET_SUFFIX_PATTERN.fullmatch(suffix) is None:
            suffix = ""
        # A picture's name carries its size, which the browser reserves for
        # it before the bytes arrive.
        pixel_size = image_pixel_size(content)
        size = "" if pixel_size is None else f"-{pixel_size[0]}x{pixel_size[1]}"
        name = hashlib.sha256(content).hexdigest() + size + suffix
        with self._lock:
            if self._closed:
                raise RuntimeError("Cannot register HTTP assets after server shutdown.")
            previous = self._snapshots.pop(name, None)
            if previous is not None:
                self._bytes -= len(previous)
            self._snapshots[name] = content
            self._bytes += len(content)
            while self._bytes > _HTTP_ASSET_CACHE_MAX_BYTES:
                oldest = next(iter(self._snapshots))
                self._bytes -= len(self._snapshots.pop(oldest))
        return HttpAsset(_HTTP_ASSET_URL_PREFIX + name, pixel_size)
