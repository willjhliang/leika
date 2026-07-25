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
        ValueError: If the image is not (height, width, 3) or (height, width, 4).
    """

    image = colors_to_uint8(image)
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ValueError(f"Expected an image with shape (height, width, 3|4), got {image.shape}.")
    resolved_format: Literal["jpeg", "png"]
    if format == "auto":
        resolved_format = "png" if image.shape[2] == 4 else "jpeg"
    else:
        resolved_format = format
    return resolved_format, cv2_imencode_with_fallback(
        resolved_format,
        image,
        jpeg_quality,
        channel_ordering="rgb",
    )


def cv2_imencode_with_fallback(
    format: Literal["png", "jpeg"],
    image: np.ndarray,
    jpeg_quality: int | None,
    channel_ordering: Literal["rgb", "bgr"],
) -> bytes:
    """Helper for encoding images to bytes using OpenCV or imageio.

    We default to OpenCV if available, which we find is usually faster.

    We fall back to imageio if OpenCV is not available. This lets us avoid
    adding OpenCV as a strict dependency, since it can be annoying to install
    on some machines.
    """
    if jpeg_quality is None:
        jpeg_quality = 75  # Default JPEG quality if not specified.

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        # Fall back to imageio if cv2 is not available.
        import imageio.v3 as iio

        if channel_ordering == "bgr":
            # Convert to BGR if needed.
            image = image[:, :, np.array((2, 1, 0, 3) if image.shape[-1] == 4 else (2, 1, 0))]
        return (
            iio.imwrite("<bytes>", image, extension=".jpeg", quality=jpeg_quality)
            if format == "jpeg"
            else iio.imwrite("<bytes>", image, extension=".png")
        )

    # OpenCV is available!
    if channel_ordering == "rgb":
        # Convert to BGR if needed.
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
