from __future__ import annotations

from typing import Literal

import numpy as np
from typing_extensions import assert_never

from ._assignable_props_api import colors_to_uint8


def encode_image_binary(
    image: np.ndarray,
    format: Literal["auto", "png", "jpeg"],
    jpeg_quality: int | None = None,
) -> tuple[Literal["jpeg", "png"], bytes]:
    """Normalize and encode an RGB or RGBA image for browser transport.

    Raises:
        ValueError: If the image is not (height, width, 3|4), the format is
            not one of the three named in the signature, or the quality is
            outside 0..100.
    """

    if jpeg_quality is not None and (
        isinstance(jpeg_quality, bool)
        or not isinstance(jpeg_quality, int)
        or not 0 <= jpeg_quality <= 100
    ):
        raise ValueError("jpeg_quality must be an integer from 0 to 100.")
    image = colors_to_uint8(image)
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError(f"Expected an image with shape (height, width, 3|4), got {image.shape}.")
    resolved_format: Literal["jpeg", "png"]
    if format == "auto":
        resolved_format = "png" if image.shape[2] == 4 else "jpeg"
    elif format in ("png", "jpeg"):
        resolved_format = format
    else:
        raise ValueError(f"format must be 'auto', 'png', or 'jpeg'; got {format!r}.")
    return resolved_format, cv2_imencode_with_fallback(resolved_format, image, jpeg_quality)


def cv2_imencode_with_fallback(
    format: Literal["png", "jpeg"],
    image: np.ndarray,
    jpeg_quality: int | None,
) -> bytes:
    """Encode an RGB or RGBA image to bytes, using OpenCV when available
    (usually faster) and falling back to imageio -- which keeps OpenCV out of
    the strict dependencies, since it can be annoying to install.
    """
    if jpeg_quality is None:
        jpeg_quality = 85

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        import imageio.v3 as iio

        return (
            iio.imwrite("<bytes>", image, extension=".jpeg", quality=jpeg_quality)
            if format == "jpeg"
            else iio.imwrite("<bytes>", image, extension=".png")
        )

    # OpenCV reads channels as BGR.
    image = image[:, :, np.array((2, 1, 0, 3) if image.shape[-1] == 4 else (2, 1, 0))]
    if format == "png":
        success, encoded_image = cv2.imencode(".png", image)
    elif format == "jpeg":
        success, encoded_image = cv2.imencode(
            ".jpeg", image, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
        )
    else:
        assert_never(format)

    if not success:
        raise RuntimeError("Failed to encode image.")

    return encoded_image.tobytes()
