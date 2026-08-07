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
from typing import Optional, Tuple

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
    payload = data[12:16]
    if payload == b"VP8X":
        # Extended: the canvas, as two 24-bit values each holding size - 1.
        if len(data) < 30:
            return None
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return (width, height)
    if payload == b"VP8 ":
        # Lossy: a keyframe header behind its three-byte start code, with 14
        # bits of each dimension and two of scaling above them.
        if len(data) < 30 or data[23:26] != b"\x9d\x01\x2a":
            return None
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return (width, height) if width and height else None
    if payload == b"VP8L":
        # Lossless: 14 bits of width - 1 then 14 of height - 1, little-endian,
        # packed together behind a one-byte signature.
        if len(data) < 25 or data[20] != 0x2F:
            return None
        packed = int.from_bytes(data[21:25], "little")
        return ((packed & 0x3FFF) + 1, ((packed >> 14) & 0x3FFF) + 1)
    return None


def _jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    """Walk JPEG's segments to its frame header.

    The size is not at a fixed offset: a frame sits behind however much
    metadata the encoder wrote first, and an EXIF block or a colour profile is
    routinely tens of kilobytes of it. So the segments are stepped through by
    their own lengths until the frame turns up.
    """
    at = 2
    while at + 3 < len(data):
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
            # [length][precision][height][width] -- height first, alone among
            # the formats here.
            size = _dimensions(">HH", data[at + 3 : at + 7])
            return None if size is None else (size[1], size[0])
        at += length
    return None
