"""Bounded Markdown image rewriting and local asset resolution.

This layer prepares document content independently of GUI handle state. The
caller chooses inline data URLs or supplies an HTTP asset registration callback.
"""

from __future__ import annotations

import base64
import dataclasses
import os
import re
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

from ._file_transfer import open_regular_file, validate_unchanged_file_snapshot
from .infra._image_headers import safe_image_info

if TYPE_CHECKING:
    from .infra._http_assets import HttpAsset


@dataclasses.dataclass(frozen=True)
class _ResolvedMarkdownAsset:
    path: Path
    metadata: os.stat_result


def _resolve_markdown_asset(image_root: Path, url: str) -> _ResolvedMarkdownAsset:
    """Resolve a local image using ordinary filesystem path semantics."""
    path = (image_root / url).resolve()
    return _ResolvedMarkdownAsset(path, path.stat())


_MARKDOWN_INLINE_MAX_ASSET_BYTES = 8 * 1024 * 1024
_MARKDOWN_INLINE_MAX_TOTAL_BYTES = 16 * 1024 * 1024
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*_[\]{}()#+\-.!<> ])")
_MARKDOWN_FENCE = re.compile(r"^[ \t]{0,3}([`~]{3,})(.*)$")


@dataclasses.dataclass
class _InlineMarkdownBudget:
    remaining_output_bytes: int


@dataclasses.dataclass(frozen=True)
class _MarkdownImageDestination:
    start: int
    end: int
    value: str


def _markdown_unescape(value: str) -> str:
    return _MARKDOWN_ESCAPE.sub(r"\1", value)


def _fenced_markdown_ranges(markdown: str) -> list[tuple[int, int]]:
    """Return fenced-code spans, preserving offsets for the rewrite pass."""
    ranges: list[tuple[int, int]] = []
    fence_character: str | None = None
    fence_length = 0
    fence_start = 0
    offset = 0
    for line in markdown.splitlines(keepends=True):
        match = _MARKDOWN_FENCE.match(line.rstrip("\r\n"))
        if fence_character is None:
            if match is not None:
                marker = match.group(1)
                fence_character = marker[0]
                fence_length = len(marker)
                fence_start = offset
        elif (
            match is not None
            and match.group(1)[0] == fence_character
            and len(match.group(1)) >= fence_length
            and not match.group(2).strip()
        ):
            ranges.append((fence_start, offset + len(line)))
            fence_character = None
        offset += len(line)
    if fence_character is not None:
        ranges.append((fence_start, len(markdown)))
    return ranges


def _markdown_image_destinations(markdown: str) -> Iterator[_MarkdownImageDestination]:
    """Yield destination spans for inline images outside code constructs."""
    fenced = _fenced_markdown_ranges(markdown)
    fence_index = 0
    index = 0
    length = len(markdown)
    while index < length:
        while fence_index < len(fenced) and index >= fenced[fence_index][1]:
            fence_index += 1
        if fence_index < len(fenced) and fenced[fence_index][0] <= index:
            index = fenced[fence_index][1]
            continue

        if markdown[index] == "`":
            run_end = index + 1
            while run_end < length and markdown[run_end] == "`":
                run_end += 1
            delimiter = markdown[index:run_end]
            closing = markdown.find(delimiter, run_end)
            while closing >= 0 and (
                (closing > 0 and markdown[closing - 1] == "`")
                or (closing + len(delimiter) < length and markdown[closing + len(delimiter)] == "`")
            ):
                closing = markdown.find(delimiter, closing + len(delimiter))
            index = closing + len(delimiter) if closing >= 0 else run_end
            continue

        if not markdown.startswith("![", index):
            index += 1
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and markdown[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            index += 2
            continue

        cursor = index + 2
        label_depth = 1
        while cursor < length and label_depth:
            character = markdown[cursor]
            if character == "\\" and cursor + 1 < length:
                cursor += 2
                continue
            if character == "[":
                label_depth += 1
            elif character == "]":
                label_depth -= 1
                if label_depth == 0:
                    break
            cursor += 1
        if label_depth or cursor + 1 >= length or markdown[cursor + 1] != "(":
            index += 2
            continue

        cursor += 2
        while cursor < length and markdown[cursor].isspace():
            cursor += 1
        if cursor >= length:
            return

        if markdown[cursor] == "<":
            destination_start = cursor + 1
            cursor += 1
            while cursor < length:
                if markdown[cursor] == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if markdown[cursor] == ">":
                    break
                if markdown[cursor] in "\r\n":
                    break
                cursor += 1
            if cursor >= length or markdown[cursor] != ">":
                index += 2
                continue
            destination_end = cursor
            cursor += 1
        else:
            destination_start = cursor
            depth = 0
            destination_end = -1
            while cursor < length:
                character = markdown[cursor]
                if character == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if character == "(":
                    depth += 1
                elif character == ")":
                    if depth == 0:
                        destination_end = cursor
                        break
                    depth -= 1
                elif character.isspace() and depth == 0:
                    destination_end = cursor
                    break
                cursor += 1
            if destination_end < 0:
                index += 2
                continue

        while cursor < length and markdown[cursor].isspace():
            cursor += 1
        if cursor < length and markdown[cursor] in ('"', "'"):
            quote = markdown[cursor]
            cursor += 1
            while cursor < length:
                if markdown[cursor] == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if markdown[cursor] == quote:
                    cursor += 1
                    break
                cursor += 1
            else:
                index += 2
                continue
            while cursor < length and markdown[cursor].isspace():
                cursor += 1
        if cursor >= length or markdown[cursor] != ")":
            index += 2
            continue

        raw_destination = markdown[destination_start:destination_end]
        yield _MarkdownImageDestination(
            destination_start,
            destination_end,
            _markdown_unescape(raw_destination),
        )
        index = cursor + 1


def _rewrite_markdown_images(markdown: str, rewrite: Callable[[str], str | None]) -> str:
    pieces: list[str] = []
    cursor = 0
    for destination in _markdown_image_destinations(markdown):
        replacement = rewrite(destination.value)
        if replacement is None:
            continue
        pieces.extend((markdown[cursor : destination.start], replacement))
        cursor = destination.end
    if not pieces:
        return markdown
    pieces.append(markdown[cursor:])
    return "".join(pieces)


def _relative_markdown_asset(url: str) -> str | None:
    """Return a true relative file destination; leave all URI forms alone."""
    if not url or url.startswith(("#", "//")):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    try:
        return unquote(parsed.path, errors="strict")
    except UnicodeDecodeError:
        return None


def _get_data_url(
    url: str,
    image_root: Path | None,
    budget: _InlineMarkdownBudget | None = None,
) -> str:
    local_url = _relative_markdown_asset(url)
    if local_url is None:
        return url
    if image_root is None:
        warnings.warn(
            (
                "No `image_root` provided. All relative paths will be scoped to the "
                "Leika installation path."
            ),
            stacklevel=2,
        )
        image_root = Path(__file__).parent
    try:
        source = _resolve_markdown_asset(image_root, local_url)
    except OSError:
        warnings.warn(
            f"Failed to read image {url}, with image_root set to {image_root}.",
            stacklevel=2,
        )
        return url
    if budget is None:
        budget = _InlineMarkdownBudget(_MARKDOWN_INLINE_MAX_TOTAL_BYTES)
    try:
        with open_regular_file(source.path, expected_metadata=source.metadata) as file:
            before = os.fstat(file.fileno())
            size = before.st_size
            encoded_size = 4 * ((size + 2) // 3)
            # ``image/png``/``image/gif`` are the shortest supported
            # content-derived prefixes. If even this lower bound cannot fit,
            # avoid the disk read; the exact MIME check follows validation.
            output_size = len("data:image/png;base64,") + encoded_size
            if (
                size > _MARKDOWN_INLINE_MAX_ASSET_BYTES
                or output_size > budget.remaining_output_bytes
            ):
                warnings.warn(
                    f"Refused to inline image {url}: the Markdown image byte limit "
                    "would be exceeded.",
                    stacklevel=2,
                )
                return url
            binary = file.read(_MARKDOWN_INLINE_MAX_ASSET_BYTES + 1)
            after = os.fstat(file.fileno())
        validate_unchanged_file_snapshot(source.path, before, after)
        if len(binary) != size:
            raise OSError(f"{source.path} changed size while it was being read")
        image_kind, _ = safe_image_info(binary)
        mime_type = "image/jpeg" if image_kind == "jpeg" else f"image/{image_kind}"
        exact_output_size = len(f"data:{mime_type};base64,") + 4 * ((len(binary) + 2) // 3)
        if exact_output_size > budget.remaining_output_bytes:
            warnings.warn(
                f"Refused to inline image {url}: the Markdown image byte limit would be exceeded.",
                stacklevel=2,
            )
            return url
        encoded = base64.b64encode(binary).decode("ascii")
        data_url = f"data:{mime_type};base64,{encoded}"
        budget.remaining_output_bytes -= len(data_url)
        return data_url
    except (OSError, ValueError):
        warnings.warn(
            f"Failed to read image {url}, with image_root set to {image_root}.",
            stacklevel=2,
        )
        return url


def _parse_markdown(markdown: str, image_root: Path | None) -> str:
    budget = _InlineMarkdownBudget(_MARKDOWN_INLINE_MAX_TOTAL_BYTES)
    return _rewrite_markdown_images(markdown, lambda url: _get_data_url(url, image_root, budget))


def _link_markdown_assets(
    markdown: str,
    image_root: Path,
    register: Callable[[Path, os.stat_result], HttpAsset],
    on_asset: Callable[[str, str], None] | None = None,
) -> str:
    """Point a document's relative images at server URLs of their own.

    The counterpart of :func:`_parse_markdown` for when there is a server to
    fetch from. Inlining images works anywhere but puts every byte of them in
    front of the text, so nothing shows until all of it has arrived;
    registering them (:meth:`Server.register_http_asset`) leaves the document
    the size of its writing, and the browser fetches the images alongside it.

    Web addresses, fragments, protocol-relative destinations, and every URI
    scheme are already self-contained and pass through untouched. A local
    image that cannot be read keeps its original reference, so the document
    renders with the same broken figure it would show anywhere else.
    ``on_asset`` receives each unique resolved destination immediately, in
    document order, without waiting for later image snapshots.
    """

    linked_urls: dict[str, str] = {}

    def linked(url: str) -> str | None:
        if url in linked_urls:
            return linked_urls[url]
        local_url = _relative_markdown_asset(url)
        if local_url is None:
            return None
        try:
            source = _resolve_markdown_asset(image_root, local_url)
        except OSError:
            warnings.warn(
                f"Failed to read image {url}, relative to {image_root}.",
                stacklevel=2,
            )
            return None
        try:
            asset = register(source.path, source.metadata)
        except (OSError, ValueError):
            warnings.warn(
                f"Failed to read image {url}, relative to {image_root}.",
                stacklevel=2,
            )
            return None
        destination = asset.url
        if asset.pixel_size is not None:
            width, height = asset.pixel_size
            destination = f"{asset.url}?w={width}&h={height}"
        linked_urls[url] = destination
        if on_asset is not None:
            on_asset(url, destination)
        return destination

    return _rewrite_markdown_images(markdown, linked)
