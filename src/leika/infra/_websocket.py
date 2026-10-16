"""Select the native server API, adapting WebSockets 12 at this boundary only."""

from __future__ import annotations

from importlib.util import find_spec
from typing import TYPE_CHECKING

if TYPE_CHECKING or find_spec("websockets.asyncio") is not None:
    from websockets.asyncio.server import ServerConnection as ServerConnection
    from websockets.asyncio.server import serve as serve
else:
    from ._websocket_legacy import ServerConnection as ServerConnection
    from ._websocket_legacy import serve as serve
