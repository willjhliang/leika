"""Per-browser raster rendering, after transport coalescing.

The persistent stream retains the application's original encoding. Each client
gets a private variant; a slow or performance-oriented viewer cannot reduce
another viewer's detail. No raw snapshots or rendered variants are retained here.
"""

from __future__ import annotations

import dataclasses
from io import BytesIO
from typing import TYPE_CHECKING, Literal

from PIL import Image, JpegImagePlugin

from . import _messages
from .infra._messages import Message

if TYPE_CHECKING:
    from ._server import Server

RenderingMode = Literal["auto", "performance", "quality"]


def render_image(
    data: bytes, mode: RenderingMode, size: tuple[int, int] | None, fit: str, server: Server
) -> bytes:
    """Fit a canonical JPEG/PNG without ever modifying its source bytes."""
    if not data or mode == "quality" or size == (0, 0):
        return data
    if mode == "auto" and size is None:
        return data
    with Image.open(BytesIO(data)) as source:
        width, height = source.size
        target = size if size is not None else source.size
        ratios = target[0] / width, target[1] / height
        scale = max(ratios) if fit == "fill" else min(ratios)
        if mode == "performance":
            scale *= 0.5
        scale = min(1.0, scale)
        if mode == "auto" and scale >= 1.0:
            return data
        dimensions = max(1, round(width * scale)), max(1, round(height * scale))
        # Header inspection above does not decode pixels. Charge the decoded
        # source and encode/resize headroom through the existing server budget.
        with server._reserve_image_preparation(width * height * len(source.getbands())):
            output = BytesIO()
            with source.resize(dimensions, Image.Resampling.LANCZOS) as resized:
                if isinstance(source, JpegImagePlugin.JpegImageFile):
                    if mode == "performance":
                        resized.save(output, format="JPEG", quality=50)
                    else:
                        # Retain the original quantization and chroma sampling;
                        # do not silently lower an application's JPEG quality.
                        resized.save(
                            output,
                            format="JPEG",
                            qtables=source.quantization,
                            subsampling=JpegImagePlugin.get_sampling(source),
                        )
                else:
                    resized.save(output, format="PNG")
            return output.getvalue()


def render_message(
    message: Message, mode: RenderingMode, size: tuple[int, int] | None, fit: str, server: Server
) -> Message:
    if isinstance(message, _messages.ViewportImageMessage):
        props = message.props
        data = render_image(props._data, mode, size, props.fit or fit, server)
        if data is props._data:
            return message
        return dataclasses.replace(message, props=dataclasses.replace(props, _data=data))
    if isinstance(message, _messages.ViewportPaneUpdateMessage):
        updates = message.updates
        data = updates.get("_data")
        if not isinstance(data, bytes) or updates.get("_format") not in ("jpeg", "png"):
            return message
        rendered = render_image(data, mode, size, updates.get("fit") or fit, server)
        if rendered is data:
            return message
        # Keep the exact selection receipt, loading state, and all other props
        # from this message. Never substitute a newer pane's source snapshot.
        return dataclasses.replace(message, updates={**updates, "_data": rendered})
    return message
