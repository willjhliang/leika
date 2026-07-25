from __future__ import annotations

import inspect
import re
import socket
import time
from pathlib import Path

import leika

VERSION_INFO = Path(__file__).resolve().parents[1] / "src/leika/client/src/VersionInfo.ts"


def test_version_and_server_signature() -> None:
    # The browser client rejects connections on a version mismatch, so the
    # generated constant must track __version__ rather than a pinned literal.
    generated = re.search(r'LEIKA_VERSION = "([^"]+)"', VERSION_INFO.read_text(encoding="utf-8"))
    assert generated is not None
    assert generated.group(1) == leika.__version__
    signature = inspect.signature(leika.Server)
    assert signature.parameters["host"].default == "0.0.0.0"
    assert signature.parameters["port"].default == 8080
    assert signature.parameters["workspace_id"].default == "default"


def test_server_surface_is_data_only(server: leika.Server) -> None:
    assert server.url.startswith("http://127.0.0.1:")
    assert server.clients == {}
    assert server.panes is not None
    assert server.gui is not None
    assert not hasattr(server, "scene")
    assert not hasattr(server, "camera")
    assert not hasattr(server, "request_share_url")
    assert not hasattr(leika, "SceneApi")
    assert not hasattr(leika, "CameraHandle")


def test_atomic_flush_and_idempotent_stop(server: leika.Server) -> None:
    with server.atomic():
        enabled = server.gui.add_checkbox("Enabled", initial_value=True)
        enabled.value = False
    server.flush()
    assert enabled.value is False

    port = int(server.url.rsplit(":", 1)[1])
    server.stop()
    server.stop()
    time.sleep(0.05)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        assert sock.connect_ex(("127.0.0.1", port)) != 0
