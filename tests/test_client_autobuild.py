from __future__ import annotations

import threading
from pathlib import Path

import leika._client_autobuild as autobuild


def test_build_lock_ignores_stale_file_contents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / ".leika-build.lock"
    lock_path.write_text("interrupted process", encoding="utf-8")
    monkeypatch.setattr(autobuild, "_lock_path", lock_path)

    with autobuild._build_lock():
        assert lock_path.is_file()


def test_build_lock_serializes_threads(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(autobuild, "_lock_path", tmp_path / ".leika-build.lock")
    attempting = threading.Event()
    acquired = threading.Event()

    def contend() -> None:
        attempting.set()
        with autobuild._build_lock():
            acquired.set()

    with autobuild._build_lock():
        thread = threading.Thread(target=contend)
        thread.start()
        assert attempting.wait(1.0)
        assert not acquired.wait(0.1)

    assert acquired.wait(1.0)
    thread.join(timeout=1.0)
    assert not thread.is_alive()
