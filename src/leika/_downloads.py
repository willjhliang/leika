"""Download limits, input validation, and descriptor-backed chunk sources.

This module owns source preparation. ClientHandle owns delivery, cancellation,
and transport reservations; Server owns fan-out and background-work admission.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import BinaryIO, Iterator, Tuple

from ._file_transfer import open_regular_file
from ._validation import validate_positive_integer as _validate_positive_integer
from .infra._async_message_buffer import _FILE_TRANSFER_BUFFER_BYTES

DOWNLOAD_MAX_CHUNK_BYTES = _FILE_TRANSFER_BUFFER_BYTES
"""Maximum download part and per-client queued file payload."""
DOWNLOAD_MAX_BYTES = 256 * 1024 * 1024
DOWNLOAD_MAX_PARTS = 65_536
DOWNLOAD_MAX_ACTIVE = 128
"""Hard limits of the bundled browser download assembler."""


def format_bytes(count: int) -> str:
    """A byte count as something to read in a notification."""
    size = float(count)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    raise RuntimeError("byte-size formatter exhausted its units")


def validate_file_content(content: object) -> bytes | Path:
    if type(content) is bytes:
        return content
    if isinstance(content, Path):
        return Path(os.fspath(content))
    raise TypeError(
        "content must be bytes or a Path; a str is neither a file's contents"
        " (encode it) nor a path we would guess at (wrap it in Path)."
    )


def validate_download_chunk_size(chunk_size: object) -> int:
    if type(chunk_size) is not int:
        raise TypeError("chunk_size must be an integer")
    _validate_positive_integer(chunk_size, "chunk_size")
    if chunk_size > DOWNLOAD_MAX_CHUNK_BYTES:
        raise ValueError(f"chunk_size must be at most {DOWNLOAD_MAX_CHUNK_BYTES} bytes (8 MiB).")
    return chunk_size


def _read_in_chunks(
    file: BinaryIO, size_bytes: int, chunk_size: int, path: Path
) -> Iterator[bytes]:
    """Exactly `size_bytes` from an open file, `chunk_size` at a time."""
    remaining = size_bytes
    while remaining > 0:
        expected = min(chunk_size, remaining)
        pieces: list[bytes] = []
        received = 0
        while received < expected:
            piece = file.read(expected - received)
            if not piece:
                # The transfer announced its length before the first byte went
                # out and the client waits for exactly that many.
                raise OSError(
                    f"{path} shrank while it was being sent: {remaining - received} of"
                    f" {size_bytes} bytes were still expected."
                )
            pieces.append(piece)
            received += len(piece)
        remaining -= received
        yield pieces[0] if len(pieces) == 1 else b"".join(pieces)


@contextlib.contextmanager
def download_source(
    content: bytes | Path, chunk_size: int
) -> Iterator[Tuple[int, Iterator[bytes]]]:
    """How long a download is and how to read it, from memory or from disk.

    The length is settled first because the transfer declares it up front, and
    it is taken from the open descriptor rather than from the path so that a
    file replaced mid-send -- a rotated log, say -- is still sent whole from
    the copy this holds open.
    """
    if type(content) is bytes:
        yield (
            len(content),
            (content[i : i + chunk_size] for i in range(0, len(content), chunk_size)),
        )
        return
    validated_content = validate_file_content(content)
    if not isinstance(validated_content, Path):
        raise TypeError("path download source must be a Path")
    with open_regular_file(validated_content) as file:
        size_bytes = os.fstat(file.fileno()).st_size
        yield size_bytes, _read_in_chunks(file, size_bytes, chunk_size, validated_content)
