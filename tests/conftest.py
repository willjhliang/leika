from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

import leika
import leika._client_autobuild


@pytest.fixture(autouse=True)
def isolate_user_host_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer's trusted endpoints must not affect security test defaults."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))


@pytest.fixture()
def server(monkeypatch: pytest.MonkeyPatch) -> Generator[leika.Server, None, None]:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    value = leika.Server(host="127.0.0.1", port=0, verbose=False)
    try:
        yield value
    finally:
        value.stop()
