"""Per-browser raster rendering, after transport coalescing.

The persistent stream retains the application's original encoding. Each client
gets a private variant; a slow or performance-oriented viewer cannot reduce
another viewer's detail. No raw snapshots or rendered variants are retained here.
"""

from __future__ import annotations

import dataclasses
import math
from io import BytesIO
from typing import TYPE_CHECKING, Literal

from PIL import Image, JpegImagePlugin

from . import _messages
from ._messages import Message

if TYPE_CHECKING:
    from ._server import Server

RenderingMode = Literal["auto", "performance", "quality"]


def render_image(
    data: bytes,
    mode: RenderingMode,
    size: tuple[int, int] | None,
    fit: str,
    server: Server,
    *,
    delivery_rate: float | None = None,
) -> bytes:
    """Render a canonical JPEG/PNG without ever modifying its source bytes.

    Auto uses measured bulk delivery throughput, independently of display size.
    A half-second source-payload budget selects scale by pixel area. This is a
    heuristic, not a promised transfer time: encoded size depends on content.
    Keep at least 70% of each source dimension and preserve JPEG quantization,
    preferring fewer current frames to severe blur on very slow connections.
    """
    if not data or mode == "quality":
        return data
    scale = 1.0
    if mode == "auto":
        if delivery_rate is None or not math.isfinite(delivery_rate) or delivery_rate <= 0:
            return data
        scale = min(1.0, max(0.7, math.sqrt(0.5 * delivery_rate / len(data))))
        if scale >= 1.0:
            return data
    elif size == (0, 0):
        return data
    with Image.open(BytesIO(data), formats=("JPEG", "PNG")) as source:
        width, height = source.size
        if mode == "performance":
            target = size if size is not None else source.size
            ratios = target[0] / width, target[1] / height
            scale = min(1.0, 0.5 * (max(ratios) if fit == "fill" else min(ratios)))
        dimensions = max(1, round(width * scale)), max(1, round(height * scale))
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
    message: Message,
    mode: RenderingMode,
    size: tuple[int, int] | None,
    fit: str,
    server: Server,
    *,
    delivery_rate: float | None = None,
) -> Message:
    if isinstance(message, _messages.ViewportImageMessage):
        props = message.props
        data = render_image(
            props._data, mode, size, props.fit or fit, server, delivery_rate=delivery_rate
        )
        if data is props._data:
            return message
        return dataclasses.replace(message, props=dataclasses.replace(props, _data=data))
    if isinstance(message, _messages.ViewportPaneUpdateMessage):
        updates = message.updates
        data = updates.get("_data")
        if not isinstance(data, bytes) or updates.get("_format") not in ("jpeg", "png"):
            return message
        rendered = render_image(
            data, mode, size, updates.get("fit") or fit, server, delivery_rate=delivery_rate
        )
        if rendered is data:
            return message
        # Keep the exact selection receipt, loading state, and all other props
        # from this message. Never substitute a newer pane's source snapshot.
        return dataclasses.replace(message, updates={**updates, "_data": rendered})
    return message
