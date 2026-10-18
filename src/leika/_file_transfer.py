"""Argument checks and chunked sources for files sent to browsers."""

from __future__ import annotations

import contextlib
import os
import unicodedata
from pathlib import Path
from typing import BinaryIO, Iterator

from ._transport._message_buffer import _FILE_TRANSFER_BUFFER_BYTES
from ._validation import validate_positive_integer

PREVIEW_MAX_BYTES = 64 * 1024 * 1024
"""Default size past which a preview is not sent. The browser still applies
lower renderer-specific limits (1 MiB Markdown and 16 MiB plain text)."""

_FILE_DISPLAY_NAME_MAX_CHARS = 255
_FILE_DISPLAY_NAME_MAX_UTF8_BYTES = 1024


def validate_file_display_name(filename: object) -> str:
    """Return a display basename or raise a clear argument error."""
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


def validate_file_send(
    filename: str, content: bytes | Path, chunk_size: int
) -> tuple[str, bytes | Path]:
    """Check the arguments of one public file send."""
    filename = validate_file_display_name(filename)
    if type(content) is not bytes and not isinstance(content, Path):
        raise TypeError(
            "content must be bytes or a Path; a str is neither a file's contents"
            " (encode it) nor a path we would guess at (wrap it in Path)."
        )
    if type(chunk_size) is not int:
        raise TypeError("chunk_size must be an integer")
    validate_positive_integer(chunk_size, "chunk_size")
    # A part must fit the connection's file buffer, or it would wait forever.
    if chunk_size > _FILE_TRANSFER_BUFFER_BYTES:
        raise ValueError(f"chunk_size must be at most {_FILE_TRANSFER_BUFFER_BYTES} bytes (8 MiB).")
    return filename, content


def format_bytes(count: int) -> str:
    """A byte count as something to read in a notification."""
    size = float(count)
    for unit in ("B", "KiB", "MiB"):
        if size < 1024.0:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GiB"


def _read_parts(file: BinaryIO, size_bytes: int, chunk_size: int, path: Path) -> Iterator[bytes]:
    """Exactly ``size_bytes`` from an open file, ``chunk_size`` at a time."""
    for offset in range(0, size_bytes, chunk_size):
        expected = min(chunk_size, size_bytes - offset)
        part = file.read(expected)
        if len(part) != expected:
            # The transfer announced its length before the first byte went
            # out and the browser waits for exactly that many.
            raise OSError(f"{path} shrank while it was being sent.")
        yield part


@contextlib.contextmanager
def file_parts(content: bytes | Path, chunk_size: int) -> Iterator[tuple[int, Iterator[bytes]]]:
    """The size of a file to send and its parts, from memory or from disk.

    A path is opened once and its size taken from the open file, so a file
    replaced mid-send -- a rotated log, say -- is still sent whole.
    """
    if isinstance(content, bytes):
        yield (
            len(content),
            (content[i : i + chunk_size] for i in range(0, len(content), chunk_size)),
        )
        return
    with open(content, "rb") as file:
        size_bytes = os.fstat(file.fileno()).st_size
        yield size_bytes, _read_parts(file, size_bytes, chunk_size, content)
