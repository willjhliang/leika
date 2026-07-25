from __future__ import annotations

from collections.abc import Generator

import pytest

import leika
import leika._client_autobuild


@pytest.fixture()
def server(monkeypatch: pytest.MonkeyPatch) -> Generator[leika.Server, None, None]:
    monkeypatch.setattr(leika._client_autobuild, "ensure_client_is_built", lambda: None)
    value = leika.Server(host="127.0.0.1", port=0, verbose=False)
    try:
        yield value
    finally:
        value.stop()
