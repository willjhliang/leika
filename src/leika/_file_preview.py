"""Bounded text streaming, independent of image and download preparation."""

from __future__ import annotations

import codecs
import contextlib
import mimetypes
import os
from collections.abc import Iterator
from pathlib import Path

from ._file_transfer import open_regular_file, validate_unchanged_file_snapshot

PREVIEW_TEXT_LEAD_BYTES = 8192
_TEXT_EXTENSIONS = frozenset(
    ".md .markdown .cfg .conf .csv .diff .ini .log .lock .patch .properties "
    ".rst .tex .toml .tsv .txt .yaml .yml".split()
)
_TEXT_MIME_TYPES = frozenset(
    "application/javascript application/json application/x-ndjson application/x-sh "
    "application/xml application/yaml image/svg+xml".split()
)


def iter_preview_text(
    filename: str, content: bytes | Path, max_bytes: int
) -> Iterator[tuple[str, int, int, str, bool]]:
    """Stream readable text before Markdown images or downloads are prepared.

    The first read stays small. Subsequent reads fill the reader continuously,
    with the existing text/Markdown rendering limits bounding retained data.
    """
    mime = mimetypes.guess_type(filename, strict=False)[0] or "application/octet-stream"
    extension = Path(filename).suffix.lower()
    if not (
        mime.startswith("text/")
        or mime in _TEXT_MIME_TYPES
        or mime.endswith(("+json", "+xml", "+yaml"))
        or extension in _TEXT_EXTENSIONS
    ):
        return
    markdown = extension in (".md", ".markdown") or mime == "text/markdown"
    render_limit = 1024 * 1024 if markdown else 16 * 1024 * 1024
    context = (
        open_regular_file(content) if isinstance(content, Path) else contextlib.nullcontext(None)
    )
    with context as stream:
        before = os.fstat(stream.fileno()) if stream is not None else None
        if before is None:
            assert isinstance(content, bytes)
            size = len(content)
        else:
            size = before.st_size
        if size > max_bytes:
            return
        target = PREVIEW_TEXT_LEAD_BYTES if size > render_limit else size
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        offset = 0
        index = 0
        while True:
            count = min(PREVIEW_TEXT_LEAD_BYTES if index == 0 else 32 * 1024, target - offset)
            if stream is None:
                assert isinstance(content, bytes)
                data = content[offset : offset + count]
            else:
                data = stream.read(count)
                assert before is not None and isinstance(content, Path)
                validate_unchanged_file_snapshot(content, before, os.fstat(stream.fileno()))
            if len(data) != count:
                raise OSError(f"{filename} changed while its preview was being read")
            offset += len(data)
            text = decoder.decode(data, final=offset == size)
            done = offset == target
            yield mime, size, index, text, done
            if done:
                return
            index += 1
