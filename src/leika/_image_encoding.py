from __future__ import annotations

from io import BytesIO
from typing import Literal

import numpy as np
from typing_extensions import assert_never

from ._assignable_props_api import colors_to_uint8
from .infra._image_headers import validate_image_pixel_size


def _validate_image_encoding_options(
    format: object,
    jpeg_quality: object,
) -> None:
    """Reject noncanonical or unsupported image encoding settings."""
    if type(format) is not str or format not in ("auto", "png", "jpeg"):
        raise ValueError(f"format must be 'auto', 'png', or 'jpeg'; got {format!r}.")
    if jpeg_quality is not None and (type(jpeg_quality) is not int or not 0 <= jpeg_quality <= 100):
        raise ValueError("jpeg_quality must be an integer from 0 to 100.")


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

    _validate_image_encoding_options(format, jpeg_quality)
    if (
        not isinstance(image, np.ndarray)
        or image.ndim != 3
        or image.shape[0] <= 0
        or image.shape[1] <= 0
        or image.shape[2] not in (3, 4)
    ):
        shape = getattr(image, "shape", None)
        raise ValueError(
            f"Expected a non-empty image with shape (height, width, 3|4), got {shape}."
        )
    validate_image_pixel_size(image.shape[1], image.shape[0])
    image = colors_to_uint8(image)
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
    """Encode RGB or RGBA bytes, preferring OpenCV and falling back to Pillow."""
    if jpeg_quality is None:
        jpeg_quality = 85

    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        from PIL import Image

        output = BytesIO()
        if format == "jpeg":
            Image.fromarray(image[..., :3], mode="RGB").save(
                output,
                format="JPEG",
                quality=jpeg_quality,
            )
        else:
            mode = "RGBA" if image.shape[-1] == 4 else "RGB"
            Image.fromarray(image, mode=mode).save(output, format="PNG")
        return output.getvalue()

    # OpenCV reads channels as BGR. JPEG cannot represent alpha, so both
    # encoder branches deliberately drop it before channel reordering.
    channels = (2, 1, 0, 3) if format == "png" and image.shape[-1] == 4 else (2, 1, 0)
    image = image[:, :, np.array(channels)]
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

    # Drop the channel-reordered raw copy before materializing immutable bytes;
    # otherwise it needlessly overlaps both encoded representations.
    del image
    return encoded_image.tobytes()
