from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import check_release_tag


def test_release_tag_matches_source_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", "v0.4.0"])

    assert check_release_tag.main() == 0
    assert "matches source version 0.4.0" in capsys.readouterr().out


def test_release_tag_matches_wheel_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", "v0.4.0", str(wheel)])

    assert check_release_tag.main() == 0
    assert "matches packaged version 0.4.0" in capsys.readouterr().out


def test_release_tag_rejects_version_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", "v0.3.0"])

    with pytest.raises(SystemExit, match="does not match the source version 0.4.0"):
        check_release_tag.main()


@pytest.mark.parametrize("tag", ["0.4.0", "release-0.4.0", "v0.4"])
def test_release_tag_rejects_malformed_tag(monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", tag])

    with pytest.raises(SystemExit, match="not in vX.Y.Z form"):
        check_release_tag.main()
