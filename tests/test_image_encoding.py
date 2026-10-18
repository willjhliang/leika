from __future__ import annotations

import sys
import warnings
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

import leika._image_encoding as image_encoding_impl
from leika._image_encoding import encode_image_binary
from leika._transport._image_headers import validate_image_pixel_size


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


def test_browser_decoded_image_dimension_and_pixel_boundaries() -> None:
    assert validate_image_pixel_size(16_384, 2_048) == (16_384, 2_048)

    with pytest.raises(ValueError, match="per side"):
        validate_image_pixel_size(16_385, 1)
    with pytest.raises(ValueError, match="decoded pixels"):
        validate_image_pixel_size(8_193, 4_096)


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


@pytest.mark.parametrize("dtype", [np.float16, np.float32, np.float64])
def test_float_normalization_preserves_values_and_caller_storage(dtype: Any) -> None:
    from leika._assignable_props_api import colors_to_uint8

    source = np.linspace(-0.5, 1.5, 120, dtype=dtype).reshape(5, 8, 3)
    before = source.copy()
    # Include strided callers: clipping must own the destination before scaling.
    view = source[:, ::2, :]
    expected = (np.clip(view, 0, 1) * 255.0).astype(np.uint8)
    result = colors_to_uint8(view)
    np.testing.assert_array_equal(result, expected)
    np.testing.assert_array_equal(source, before)
    assert not np.shares_memory(result, source)
