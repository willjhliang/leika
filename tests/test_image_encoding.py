from __future__ import annotations

import warnings
from io import BytesIO
from typing import Any, cast

import numpy as np
import pytest
from PIL import Image

from leika._image_encoding import _validate_image_encoding_options, prepare_image


def test_rgb_and_rgba_auto_formats() -> None:
    rgb = np.zeros((4, 5, 3), dtype=np.uint8)
    rgba = np.zeros((4, 5, 4), dtype=np.uint8)
    _, rgb_format, rgb_bytes = prepare_image(rgb, "auto", 90)
    _, rgba_format, rgba_bytes = prepare_image(rgba, "auto", None)
    assert rgb_format == "jpeg"
    assert rgb_bytes.startswith(b"\xff\xd8")
    assert rgba_format == "png"
    assert rgba_bytes.startswith(b"\x89PNG")


def test_prepared_snapshot_is_private_and_keeps_the_source_dtype() -> None:
    image = np.linspace(0.0, 1.0, 60, dtype=np.float32).reshape(4, 5, 3)
    snapshot, image_format, payload = prepare_image(image, "png", None)
    assert image_format == "png" and payload
    assert snapshot.dtype == np.float32
    assert not np.shares_memory(snapshot, image)
    np.testing.assert_array_equal(snapshot, image)


def test_jpeg_drops_rgba_alpha_with_a_warning() -> None:
    with pytest.warns(UserWarning, match="alpha"):
        _, image_format, payload = prepare_image(np.zeros((2, 3, 4), np.uint8), "jpeg", None)
    assert image_format == "jpeg"
    with Image.open(BytesIO(payload)) as decoded:
        assert decoded.mode == "RGB" and decoded.size == (3, 2)


def test_encoding_options_reject_builtin_subclasses() -> None:
    class String(str):
        pass

    class Integer(int):
        pass

    with pytest.raises(ValueError, match="format must be"):
        _validate_image_encoding_options(cast(Any, String("png")), None)
    with pytest.raises(ValueError, match="jpeg_quality must be"):
        _validate_image_encoding_options("jpeg", cast(Any, Integer(85)))


@pytest.mark.parametrize(
    "shape", [(4, 5), (4, 5, 1), (4, 5, 2), (4, 5, 5), (4,), (0, 5, 3), (5, 0, 4)]
)
def test_invalid_shapes_raise(shape: tuple[int, ...]) -> None:
    image = np.zeros(shape, dtype=np.uint8)
    with pytest.raises(ValueError, match="height, width"):
        prepare_image(image, "png", None)


def test_non_numeric_images_raise() -> None:
    with pytest.raises(TypeError, match="numpy array"):
        prepare_image(cast(Any, [[[0, 0, 0]]]), "png", None)
    with pytest.raises(TypeError, match="integer or floating"):
        prepare_image(np.zeros((1, 1, 3), dtype=bool), "png", None)


def test_extreme_float16_image_values_saturate_without_overflow_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        _, _, payload = prepare_image(
            np.array([[[np.finfo(np.float16).max, 0.5, -100.0]]], dtype=np.float16),
            "png",
            None,
        )
    assert payload


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
