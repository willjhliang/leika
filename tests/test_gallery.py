from __future__ import annotations

from pathlib import Path

import pytest

from scripts import gallery


def test_atomic_page_write_failure_preserves_existing_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "gallery.md"
    target.write_text("old page\n", encoding="utf-8")
    target.chmod(0o640)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(gallery.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated interrupted publication"):
        gallery._atomic_write_text(target, "new page\n")

    assert target.read_text(encoding="utf-8") == "old page\n"
    assert target.stat().st_mode & 0o777 == 0o640
    assert not any(path.name.startswith(".gallery.md.") for path in tmp_path.iterdir())
