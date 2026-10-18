"""Image preparation shared by GUI images and image panes."""

from __future__ import annotations

import warnings
from io import BytesIO
from typing import Literal

import numpy as np
from PIL import Image

from ._assignable_props_api import colors_to_uint8


def _validate_image_encoding_options(format: object, jpeg_quality: object) -> None:
    """Reject unsupported image encoding settings."""
    if type(format) is not str or format not in ("auto", "png", "jpeg"):
        raise ValueError(f"format must be 'auto', 'png', or 'jpeg'; got {format!r}.")
    if jpeg_quality is not None and (type(jpeg_quality) is not int or not 0 <= jpeg_quality <= 100):
        raise ValueError("jpeg_quality must be an integer from 0 to 100.")


def prepare_image(
    image: np.ndarray,
    format: Literal["auto", "png", "jpeg"],
    jpeg_quality: int | None,
) -> tuple[np.ndarray, Literal["jpeg", "png"], bytes]:
    """Copy an RGB or RGBA array and encode it for the browser.

    Floats are read as 0..1 and integers as 0..255. "auto" picks PNG for RGBA
    and JPEG for RGB; JPEG quality defaults to 85.

    Returns:
        The private copy of ``image``, the resolved format, and its bytes.
    """
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a numpy array.")
    if image.ndim != 3 or image.shape[2] not in (3, 4) or 0 in image.shape:
        raise ValueError(
            "image must have positive height and width and shape (height, width, 3) "
            "for RGB or (height, width, 4) for RGBA."
        )
    if image.dtype.kind not in "iuf":
        raise TypeError("image must have an integer or floating dtype.")
    snapshot = image.copy()
    alpha = snapshot.shape[2] == 4
    resolved: Literal["jpeg", "png"] = ("png" if alpha else "jpeg") if format == "auto" else format
    pixels = colors_to_uint8(snapshot)
    output = BytesIO()
    if resolved == "jpeg":
        if alpha:
            warnings.warn(
                "Encoding an RGBA image as JPEG discards its alpha channel.", stacklevel=3
            )
        quality = 85 if jpeg_quality is None else jpeg_quality
        Image.fromarray(pixels[..., :3]).save(output, format="JPEG", quality=quality)
    else:
        # Fast compression: panes stream frames, and size matters less than time.
        Image.fromarray(pixels).save(output, format="PNG", compress_level=1)
    return snapshot, resolved, output.getvalue()
