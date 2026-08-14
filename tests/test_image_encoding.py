from __future__ import annotations

import sys
import warnings
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

import leika._image_encoding as image_encoding_impl
from leika._image_encoding import encode_image_binary
from leika.infra._image_headers import safe_image_pixel_size, validate_image_pixel_size


def test_rgb_and_rgba_auto_formats() -> None:
    rgb = np.zeros((4, 5, 3), dtype=np.uint8)
    rgba = np.zeros((4, 5, 4), dtype=np.uint8)
    rgb_format, rgb_bytes = encode_image_binary(rgb, "auto", jpeg_quality=90)
    rgba_format, rgba_bytes = encode_image_binary(rgba, "auto", jpeg_quality=None)
    assert rgb_format == "jpeg"
    assert rgb_bytes.startswith(b"\xff\xd8")
    assert rgba_format == "png"
    assert rgba_bytes.startswith(b"\x89PNG")


def test_float_images_are_normalized() -> None:
    image = np.linspace(0.0, 1.0, 60, dtype=np.float32).reshape(4, 5, 3)
    image_format, payload = encode_image_binary(image, "png", jpeg_quality=None)
    assert image_format == "png"
    assert payload


def test_encoding_options_reject_builtin_subclasses_before_image_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class String(str):
        pass

    class Integer(int):
        pass

    def unexpected_normalization(_: np.ndarray) -> np.ndarray:
        raise AssertionError("invalid encoding option reached image normalization")

    monkeypatch.setattr(image_encoding_impl, "colors_to_uint8", unexpected_normalization)
    image = np.zeros((1, 1, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="format must be"):
        encode_image_binary(image, cast(Any, String("png")))
    with pytest.raises(ValueError, match="jpeg_quality must be"):
        encode_image_binary(image, "jpeg", cast(Any, Integer(85)))


@pytest.mark.parametrize(
    "shape", [(4, 5), (4, 5, 1), (4, 5, 2), (4, 5, 5), (4,), (0, 5, 3), (5, 0, 4)]
)
def test_invalid_shapes_raise(shape: tuple[int, ...]) -> None:
    image = np.zeros(shape, dtype=np.uint8)
    with pytest.raises(ValueError, match="height, width"):
        encode_image_binary(image, "png", None)


def test_extreme_float16_image_values_saturate_without_overflow_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        _, payload = encode_image_binary(
            np.array([[[np.finfo(np.float16).max, 0.5, -100.0]]], dtype=np.float16),
            "png",
            None,
        )
    assert payload


def test_opencv_jpeg_drops_rgba_alpha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded_shapes: list[tuple[int, ...]] = []

    def imencode(extension: str, image: np.ndarray, options: list[int]):
        assert extension == ".jpeg"
        assert options == [1, 85]
        encoded_shapes.append(image.shape)
        return True, np.frombuffer(b"jpeg", dtype=np.uint8)

    monkeypatch.setitem(
        sys.modules,
        "cv2",
        SimpleNamespace(IMWRITE_JPEG_QUALITY=1, imencode=imencode),
    )
    _, payload = encode_image_binary(np.zeros((2, 3, 4), dtype=np.uint8), "jpeg", None)

    assert encoded_shapes == [(2, 3, 3)]
    assert payload == b"jpeg"


def _png_header(width: int, height: int) -> bytes:
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + len(ihdr).to_bytes(4, "big")
        + b"IHDR"
        + ihdr
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IDAT\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00"
    )


def test_browser_decoded_image_dimension_and_pixel_boundaries() -> None:
    assert validate_image_pixel_size(16_384, 2_048) == (16_384, 2_048)
    assert safe_image_pixel_size(_png_header(16_384, 2_048)) == (16_384, 2_048)

    with pytest.raises(ValueError, match="per side"):
        validate_image_pixel_size(16_385, 1)
    with pytest.raises(ValueError, match="decoded pixels"):
        validate_image_pixel_size(8_193, 4_096)
    with pytest.raises(ValueError, match="recognized"):
        safe_image_pixel_size(b"not an image")


def test_oversized_ndarray_is_rejected_before_normalization_allocates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backing = np.zeros((1, 1, 3), dtype=np.uint8)
    oversized = np.lib.stride_tricks.as_strided(
        backing, shape=(4_096, 8_193, 3), strides=(0, 0, 1), writeable=False
    )

    def unexpected_normalization(_: np.ndarray) -> np.ndarray:
        raise AssertionError("oversized image reached allocating normalization")

    monkeypatch.setattr(image_encoding_impl, "colors_to_uint8", unexpected_normalization)
    with pytest.raises(ValueError, match="decoded pixels"):
        encode_image_binary(oversized, "png")


def _gif_image(*, frames: int) -> bytes:
    descriptor = b"," + b"\x00\x00\x00\x00" + b"\x01\x00\x01\x00" + b"\x00" + b"\x02\x02L\x01\x00"
    return b"GIF89a\x01\x00\x01\x00\x00\x00\x00" + descriptor * frames + b";"


def _webp_extended(
    *,
    animated: bool,
    canvas: tuple[int, int] = (1, 1),
    image_size: tuple[int, int] = (1, 1),
    valid_payload: bool = True,
) -> bytes:
    flags = 0x02 if animated else 0
    canvas_payload = (
        bytes((flags, 0, 0, 0))
        + (canvas[0] - 1).to_bytes(3, "little")
        + (canvas[1] - 1).to_bytes(3, "little")
    )
    packed_size = (image_size[0] - 1) | ((image_size[1] - 1) << 14)
    image_payload = bytes((0x2F if valid_payload else 0x00,)) + packed_size.to_bytes(4, "little")
    body = (
        b"WEBPVP8X"
        + len(canvas_payload).to_bytes(4, "little")
        + canvas_payload
        + b"VP8L"
        + len(image_payload).to_bytes(4, "little")
        + image_payload
        + b"\x00"
    )
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def test_safe_inline_image_admission_rejects_animated_containers() -> None:
    png = _png_header(1, 1)
    apng_control = (
        (8).to_bytes(4, "big")
        + b"acTL"
        + (2).to_bytes(4, "big")
        + (0).to_bytes(4, "big")
        + b"\x00\x00\x00\x00"
    )
    apng = png[:-12] + apng_control + png[-12:]

    assert safe_image_pixel_size(_gif_image(frames=1)) == (1, 1)
    assert safe_image_pixel_size(_webp_extended(animated=False)) == (1, 1)
    with pytest.raises(ValueError, match="animated PNG"):
        safe_image_pixel_size(apng)
    with pytest.raises(ValueError, match="animated GIF"):
        safe_image_pixel_size(_gif_image(frames=2))
    with pytest.raises(ValueError, match="animated WebP"):
        safe_image_pixel_size(_webp_extended(animated=True))


def test_safe_png_requires_image_data() -> None:
    png = _png_header(1, 1)
    without_image_data = png[:33] + png[-12:]
    with pytest.raises(ValueError, match="recognized"):
        safe_image_pixel_size(without_image_data)


def test_safe_webp_requires_valid_payload_matching_extended_canvas() -> None:
    with pytest.raises(ValueError, match="recognized"):
        safe_image_pixel_size(_webp_extended(animated=False, canvas=(2, 1), image_size=(1, 1)))
    with pytest.raises(ValueError, match="recognized"):
        safe_image_pixel_size(_webp_extended(animated=False, valid_payload=False))


def test_safe_jpeg_rejects_short_frame_that_borrows_later_bytes() -> None:
    short_frame = b"\xff\xd8\xff\xc0\x00\x02"
    real_frame = b"\xff\xc0\x00\x0b\x08\x20\x00\x20\x00\x01\x01\x11\x00"
    with pytest.raises(ValueError, match="recognized"):
        safe_image_pixel_size(short_frame + real_frame + b"\xff\xd9")
