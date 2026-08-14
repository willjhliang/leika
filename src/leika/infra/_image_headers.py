"""The size a picture declares, read from its header alone.

A browser handed an ``<img>`` with no dimensions has to fetch the picture
before it knows how much room to leave for it, so a document full of figures
lays itself out again as each one lands -- under the reader, if they have
started reading. Telling it the size up front turns that into one layout,
with the figures filling boxes that were already the right shape.

Header parsing rather than decoding, and no new dependency, because the only
thing wanted is two numbers that every format puts within the first few dozen
bytes of the file. Anything not recognized is ``None``, and the caller is
expected to carry on without it.
"""

from __future__ import annotations

import struct
from typing import Literal, Optional, Tuple

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_GIF_SIGNATURES = (b"GIF87a", b"GIF89a")

# The JPEG markers that introduce a frame header, whose payload is the sample
# precision and then the two dimensions. The gaps in the run are the markers
# that share its numbering without being frames: DHT, JPG and DAC.
_JPEG_FRAME_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)
# The markers that are the whole segment, with no length following to skip
# past: start and end of image, and the eight restart markers.
_JPEG_STANDALONE_MARKERS = frozenset({0x01, 0xD8, 0xD9}) | frozenset(range(0xD0, 0xD8))
# Start of scan, after which the file is entropy-coded data rather than
# segments. A frame always precedes it, so reaching it means there was none.
_JPEG_START_OF_SCAN = 0xDA

_MAX_IMAGE_DIMENSION = 16_384
_MAX_IMAGE_PIXELS = 32 * 1024 * 1024
_MAX_IMAGE_STRUCTURE_ITEMS = 65_536
"""Bundled-browser decoded raster limits (about 128 MiB at RGBA)."""


def validate_image_pixel_size(width: int, height: int) -> tuple[int, int]:
    """Return a browser-safe raster size or raise a stable boundary error."""
    if width <= 0 or height <= 0:
        raise ValueError("image width and height must be positive")
    if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
        raise ValueError(f"image dimensions must not exceed {_MAX_IMAGE_DIMENSION} pixels per side")
    if width * height > _MAX_IMAGE_PIXELS:
        raise ValueError(f"image must not exceed {_MAX_IMAGE_PIXELS} decoded pixels")
    return width, height


def safe_image_info(
    data: bytes,
) -> tuple[Literal["png", "jpeg", "gif", "webp"], tuple[int, int]]:
    """Return content-derived kind and dimensions for one safe static raster.

    Animated containers are rejected: their canvas size doesn't bound the
    decoded work or retained frame memory. Generic asset downloads remain
    byte-only and don't use this stricter admission path.
    """
    size = image_pixel_size(data)
    if size is None:
        raise ValueError("image must have a recognized, valid raster header")
    safe_size = validate_image_pixel_size(*size)
    if data[:8] == _PNG_SIGNATURE:
        _validate_static_png(data)
        kind: Literal["png", "jpeg", "gif", "webp"] = "png"
    elif data[:6] in _GIF_SIGNATURES:
        _validate_static_gif(data, safe_size)
        kind = "gif"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        _validate_static_webp(data, safe_size)
        kind = "webp"
    elif data[:2] == b"\xff\xd8":
        kind = "jpeg"
    else:
        raise ValueError("image must have a recognized, valid raster header")
    return kind, safe_size


def safe_image_pixel_size(data: bytes) -> tuple[int, int]:
    """Return validated dimensions for one safe static encoded raster."""
    return safe_image_info(data)[1]


def _validate_static_png(data: bytes) -> None:
    """Require a structurally bounded PNG container with no APNG control."""
    offset = 8
    saw_header = False
    saw_image_data = False
    structure_items = 0
    while offset + 12 <= len(data):
        structure_items += 1
        if structure_items > _MAX_IMAGE_STRUCTURE_ITEMS:
            raise ValueError("image contains too many structural items")
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            break
        if not saw_header:
            if chunk_type != b"IHDR" or length != 13:
                break
            saw_header = True
        elif chunk_type == b"IHDR":
            break
        if chunk_type in (b"acTL", b"fcTL", b"fdAT"):
            raise ValueError("animated PNG images are not supported for inline rendering")
        if chunk_type == b"IDAT":
            saw_image_data = True
        offset = chunk_end
        if chunk_type == b"IEND" and length == 0 and saw_image_data and offset == len(data):
            return
    raise ValueError("image must have a recognized, valid raster header")


def _skip_gif_subblocks(data: bytes, offset: int, structure_items: int) -> tuple[int, int]:
    while offset < len(data):
        structure_items += 1
        if structure_items > _MAX_IMAGE_STRUCTURE_ITEMS:
            raise ValueError("image contains too many structural items")
        length = data[offset]
        offset += 1
        if length == 0:
            return offset, structure_items
        offset += length
        if offset > len(data):
            break
    raise ValueError("image must have a recognized, valid raster header")


def _validate_static_gif(data: bytes, canvas: tuple[int, int]) -> None:
    """Require exactly one contained GIF image descriptor."""
    if len(data) < 13:
        raise ValueError("image must have a recognized, valid raster header")
    offset = 13
    packed = data[10]
    if packed & 0x80:
        offset += 3 * (1 << ((packed & 0x07) + 1))
    frame_count = 0
    structure_items = 0
    while offset < len(data):
        structure_items += 1
        if structure_items > _MAX_IMAGE_STRUCTURE_ITEMS:
            raise ValueError("image contains too many structural items")
        marker = data[offset]
        offset += 1
        if marker == 0x3B:
            if frame_count != 1 or offset != len(data):
                raise ValueError("animated or empty GIF images are not supported inline")
            return
        if marker == 0x21:
            if offset >= len(data):
                break
            offset += 1
            offset, structure_items = _skip_gif_subblocks(data, offset, structure_items)
            continue
        if marker != 0x2C or offset + 9 > len(data):
            break
        left, top, width, height = struct.unpack("<HHHH", data[offset : offset + 8])
        frame_packed = data[offset + 8]
        offset += 9
        if width <= 0 or height <= 0 or left + width > canvas[0] or top + height > canvas[1]:
            break
        validate_image_pixel_size(width, height)
        frame_count += 1
        if frame_count > 1:
            raise ValueError("animated GIF images are not supported for inline rendering")
        if frame_packed & 0x80:
            offset += 3 * (1 << ((frame_packed & 0x07) + 1))
        if offset >= len(data):
            break
        offset += 1
        offset, structure_items = _skip_gif_subblocks(data, offset, structure_items)
    raise ValueError("image must have a recognized, valid raster header")


def _webp_payload_size(chunk_type: bytes, payload: bytes) -> Optional[Tuple[int, int]]:
    """Validate and return one VP8/VP8L payload size."""
    if chunk_type == b"VP8 ":
        if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
            return None
        width = int.from_bytes(payload[6:8], "little") & 0x3FFF
        height = int.from_bytes(payload[8:10], "little") & 0x3FFF
        return (width, height) if width and height else None
    if chunk_type == b"VP8L":
        if len(payload) < 5 or payload[0] != 0x2F:
            return None
        packed = int.from_bytes(payload[1:5], "little")
        return ((packed & 0x3FFF) + 1, ((packed >> 14) & 0x3FFF) + 1)
    return None


def _validate_static_webp(data: bytes, canvas: tuple[int, int]) -> None:
    """Require one static, dimension-consistent image payload."""
    if len(data) < 20 or int.from_bytes(data[4:8], "little") + 8 != len(data):
        raise ValueError("image must have a recognized, valid raster header")
    end = len(data)
    offset = 12
    structure_items = 0
    image_payloads = 0
    saw_extended_header = False
    payload_size: tuple[int, int] | None = None
    while offset + 8 <= end:
        structure_items += 1
        if structure_items > _MAX_IMAGE_STRUCTURE_ITEMS:
            raise ValueError("image contains too many structural items")
        chunk_type = data[offset : offset + 4]
        length = int.from_bytes(data[offset + 4 : offset + 8], "little")
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        if chunk_end > end:
            break
        payload = data[chunk_start:chunk_end]
        if chunk_type == b"VP8X":
            if saw_extended_header or offset != 12 or length != 10:
                break
            saw_extended_header = True
            if payload[0] & 0x02:
                raise ValueError("animated WebP images are not supported for inline rendering")
            declared_canvas = (
                int.from_bytes(payload[4:7], "little") + 1,
                int.from_bytes(payload[7:10], "little") + 1,
            )
            if declared_canvas != canvas:
                break
        elif chunk_type in (b"ANIM", b"ANMF"):
            raise ValueError("animated WebP images are not supported for inline rendering")
        elif chunk_type in (b"VP8 ", b"VP8L"):
            image_payloads += 1
            if image_payloads > 1:
                raise ValueError("WebP images must contain exactly one image payload")
            payload_size = _webp_payload_size(chunk_type, payload)
            if payload_size is None:
                break
            validate_image_pixel_size(*payload_size)
        offset = chunk_end + (length & 1)
    if offset != end or image_payloads != 1 or payload_size != canvas:
        raise ValueError("image must have a recognized, valid raster header")


def image_pixel_size(data: bytes) -> Optional[Tuple[int, int]]:
    """The ``(width, height)`` an encoded image declares, or ``None``.

    Reads PNG, JPEG, GIF and WebP, which is every format a plotting library
    writes and every one a browser will lay out from an intrinsic size.
    ``None`` covers the rest honestly: a format not read here, a file
    truncated before its header finishes, and SVG, which need not have a pixel
    size to declare at all.
    """
    if data[:8] == _PNG_SIGNATURE and data[12:16] == b"IHDR":
        return _dimensions(">II", data[16:24])
    if data[:6] in _GIF_SIGNATURES:
        return _dimensions("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def _dimensions(layout: str, chunk: bytes) -> Optional[Tuple[int, int]]:
    """Two packed integers as a size, if there are two and they are a size."""
    if len(chunk) != struct.calcsize(layout):
        return None
    width, height = struct.unpack(layout, chunk)
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def _webp_size(data: bytes) -> Optional[Tuple[int, int]]:
    """The canvas size of any of WebP's three payloads.

    Each stores it differently and none of them stores it as two plain
    integers, which is why this is spelled out rather than unpacked.
    """
    chunk_type = data[12:16]
    if len(data) < 20:
        return None
    length = int.from_bytes(data[16:20], "little")
    chunk_end = 20 + length
    if chunk_end > len(data):
        return None
    payload = data[20:chunk_end]
    if chunk_type == b"VP8X":
        # Extended: the canvas, as two 24-bit values each holding size - 1.
        if length != 10:
            return None
        return (
            int.from_bytes(payload[4:7], "little") + 1,
            int.from_bytes(payload[7:10], "little") + 1,
        )
    return _webp_payload_size(chunk_type, payload)


def _jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    """Walk JPEG's segments to its frame header.

    The size is not at a fixed offset: a frame sits behind however much
    metadata the encoder wrote first, and an EXIF block or a colour profile is
    routinely tens of kilobytes of it. So the segments are stepped through by
    their own lengths until the frame turns up.
    """
    at = 2
    structure_items = 0
    while at + 3 < len(data):
        structure_items += 1
        if structure_items > _MAX_IMAGE_STRUCTURE_ITEMS:
            return None
        if data[at] != 0xFF:
            return None
        marker = data[at + 1]
        at += 2
        if marker == 0xFF:
            # A fill byte: the marker is whatever follows the last of them.
            at -= 1
            continue
        if marker in _JPEG_STANDALONE_MARKERS:
            continue
        if marker == _JPEG_START_OF_SCAN:
            return None
        length = int.from_bytes(data[at : at + 2], "big")
        if length < 2:
            return None
        if marker in _JPEG_FRAME_MARKERS:
            # [length][precision][height][width][component count][components].
            # A declared short segment must not borrow dimensions from bytes
            # belonging to a later marker.
            if length < 11 or at + length > len(data):
                return None
            component_count = data[at + 7]
            if component_count == 0 or length != 8 + 3 * component_count:
                return None
            size = _dimensions(">HH", data[at + 3 : at + 7])
            return None if size is None else (size[1], size[0])
        at += length
    return None
