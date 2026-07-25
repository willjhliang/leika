from __future__ import annotations

import numpy as np
import pytest

from leika._image_encoding import encode_image_binary


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


@pytest.mark.parametrize("shape", [(4, 5), (4, 5, 1), (4, 5, 2), (4, 5, 5), (4,)])
def test_invalid_shapes_raise(shape: tuple[int, ...]) -> None:
    image = np.zeros(shape, dtype=np.uint8)
    with pytest.raises(ValueError, match="height, width"):
        encode_image_binary(image, "png", None)
