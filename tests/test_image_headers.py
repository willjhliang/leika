"""The size a picture declares, read from its header."""

from __future__ import annotations

import io
import struct
import zlib

import numpy as np
import pytest

from leika._image_encoding import encode_image_binary
from leika.infra._image_headers import image_pixel_size


def _png(width: int, height: int) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 7


def test_a_png_says_its_size() -> None:
    assert image_pixel_size(_png(640, 360)) == (640, 360)


def test_a_gif_says_its_size() -> None:
    assert image_pixel_size(_gif(12, 34)) == (12, 34)


@pytest.mark.parametrize("shape", [(360, 640), (1, 1), (17, 3)])
def test_a_real_encoding_round_trips_its_shape(shape: tuple) -> None:
    # The encoder Leika already ships is the honest source of test images:
    # whatever imageio writes is what a figure on disk actually looks like.
    height, width = shape
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for encoding in ("png", "jpeg"):
        _, data = encode_image_binary(image, encoding)  # type: ignore[arg-type]
        assert image_pixel_size(data) == (width, height), encoding


def test_a_jpeg_is_found_behind_its_metadata() -> None:
    # The frame header sits behind however much the encoder wrote first, and
    # an EXIF or colour-profile block is routinely tens of kilobytes of it.
    # The segments have to be stepped through, not counted past.
    image = np.zeros((8, 16, 3), dtype=np.uint8)
    _, data = encode_image_binary(image, "jpeg")
    padding = b"\xff\xe1" + struct.pack(">H", 40_002) + b"\x00" * 40_000
    with_metadata = data[:2] + padding + data[2:]
    assert image_pixel_size(with_metadata) == (16, 8)


def test_a_webp_says_its_size() -> None:
    pillow = pytest.importorskip("PIL.Image", reason="WebP encoders are not a dependency")
    for lossless in (True, False):
        buffer = io.BytesIO()
        pillow.new("RGB", (23, 45)).save(buffer, format="WEBP", lossless=lossless)
        assert image_pixel_size(buffer.getvalue()) == (23, 45), lossless


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x89PNG\r\n\x1a\n",  # A signature and nothing after it.
        _png(4, 4)[:20],  # Truncated mid-header.
        b"<svg xmlns='http://www.w3.org/2000/svg'/>",  # No pixel size to give.
        b"\xff\xd8\xff\xd9",  # A JPEG that ends before any frame.
        b"RIFF\x00\x00\x00\x00WEBPVP8 ",  # A WebP header with no payload.
        b"not an image at all",
    ],
)
def test_what_cannot_be_read_is_none_rather_than_a_guess(data: bytes) -> None:
    # None is what the caller falls back on, and falling back means letting
    # the browser discover the size -- which is what it did before.
    assert image_pixel_size(data) is None


def test_a_zero_dimension_is_not_a_size() -> None:
    assert image_pixel_size(_gif(0, 10)) is None
