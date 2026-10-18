from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import check_release_tag


@pytest.fixture(autouse=True)
def project_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "src/leika"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "2.3.4"\n')
    monkeypatch.setattr(check_release_tag, "ROOT", tmp_path)


def test_release_tag_matches_source_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", "v2.3.4"])

    assert check_release_tag.main() == 0
    assert "matches source version 2.3.4" in capsys.readouterr().out


def test_release_tag_matches_wheel_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheel = tmp_path / "leika-2.3.4-py3-none-any.whl"
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", "v2.3.4", str(wheel)])

    assert check_release_tag.main() == 0
    assert "matches packaged version 2.3.4" in capsys.readouterr().out


def test_release_tag_rejects_version_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", "v2.3.3"])

    with pytest.raises(SystemExit, match="does not match the source version 2.3.4"):
        check_release_tag.main()


@pytest.mark.parametrize("tag", ["2.3.4", "release-2.3.4", "v2.3"])
def test_release_tag_rejects_malformed_tag(monkeypatch: pytest.MonkeyPatch, tag: str) -> None:
    monkeypatch.setattr(sys, "argv", ["check_release_tag.py", tag])

    with pytest.raises(SystemExit, match="not in vX.Y.Z form"):
        check_release_tag.main()
