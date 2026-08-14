"""Shared regular-file and file-transfer validation at trust boundaries."""

from __future__ import annotations

import contextlib
import os
import stat
import unicodedata
from pathlib import Path
from typing import BinaryIO, Iterator

_FILE_DISPLAY_NAME_MAX_CHARS = 255
_FILE_DISPLAY_NAME_MAX_UTF8_BYTES = 1024


@contextlib.contextmanager
def open_regular_file(
    path: Path, *, expected_metadata: os.stat_result | None = None
) -> Iterator[BinaryIO]:
    """Open a regular file without letting a FIFO or device block the caller.

    The path check gives special files a clear error before opening them. The
    descriptor check closes the replacement race, and ``O_NONBLOCK`` keeps a
    special file swapped in between those checks from blocking the thread.
    Symlinks to regular files remain supported.
    """
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{path} is not a regular file")
    if expected_metadata is not None and not os.path.samestat(metadata, expected_metadata):
        raise OSError(f"{path} changed after it was validated")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        opened_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(opened_metadata.st_mode):
            raise ValueError(f"{path} is not a regular file")
        if not os.path.samestat(metadata, opened_metadata):
            raise OSError(f"{path} was replaced before it could be opened")
        with os.fdopen(descriptor, "rb") as file:
            descriptor = -1
            yield file
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def validate_unchanged_file_snapshot(
    path: Path, before: os.stat_result, after: os.stat_result
) -> None:
    """Reject a descriptor whose contents may have changed during one read.

    Identity alone is not enough: an in-place writer can replace bytes without
    changing the inode or final length. Modification and status-change times
    make that race observable, while the byte-count check at each caller still
    catches short reads on filesystems with unusually coarse timestamps.
    """
    if not os.path.samestat(before, after) or (
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise OSError(f"{path} changed while it was being read")


def read_regular_file_snapshot(
    path: Path,
    max_bytes: int,
    *,
    expected_metadata: os.stat_result | None = None,
) -> bytes:
    """Read one stable regular-file snapshot within an explicit byte limit."""
    if type(max_bytes) is not int or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    with open_regular_file(path, expected_metadata=expected_metadata) as file:
        before = os.fstat(file.fileno())
        if before.st_size > max_bytes:
            raise ValueError(f"{path} is larger than the {max_bytes} byte limit")
        payload = file.read(max_bytes + 1)
        after = os.fstat(file.fileno())
    if len(payload) > max_bytes:
        raise ValueError(f"{path} grew beyond the {max_bytes} byte limit")
    validate_unchanged_file_snapshot(path, before, after)
    if len(payload) != before.st_size:
        raise OSError(f"{path} changed size while it was being read")
    return payload


def validate_file_display_name(filename: object) -> str:
    """Return a safe display basename or raise a clear boundary error."""
    if type(filename) is not str:
        raise TypeError("filename must be a string")
    try:
        encoded = filename.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("filename must contain valid Unicode") from error
    if (
        not filename
        or not filename.strip()
        or len(filename) > _FILE_DISPLAY_NAME_MAX_CHARS
        or len(encoded) > _FILE_DISPLAY_NAME_MAX_UTF8_BYTES
        or filename in (".", "..")
        or "/" in filename
        or "\\" in filename
        or any(unicodedata.category(character).startswith("C") for character in filename)
    ):
        raise ValueError(
            "filename must be a non-empty display name of at most 255 characters, "
            "without path separators or control characters"
        )
    return filename
