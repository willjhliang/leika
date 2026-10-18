from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import check_dist

NOTICES = [
    f"leika/_licenses/{path.name}" for path in (check_dist.ROOT / "src/leika/_licenses").iterdir()
]


def _write_dist(dist: Path, wheel_names: list[str], sdist_names: list[str]) -> None:
    with zipfile.ZipFile(dist / "leika-1.0-py3-none-any.whl", "w") as wheel:
        for name in wheel_names:
            wheel.writestr(name, "x")
    with tarfile.open(dist / "leika-1.0.tar.gz", "w:gz") as sdist:
        for name in sdist_names:
            sdist.addfile(tarfile.TarInfo(f"leika-1.0/{name}"), io.BytesIO())


def _run(dist: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["check_dist.py", str(dist)])
    return check_dist.main()


def test_complete_distributions_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = [
        *check_dist.BUNDLE,
        *NOTICES,
        "leika/__init__.py",
        "leika-1.0.dist-info/licenses/LICENSE",
    ]
    _write_dist(tmp_path, wheel, [f"src/{name}" for name in check_dist.BUNDLE])
    assert _run(tmp_path, monkeypatch) == 0


def test_missing_bundle_and_client_sources_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wheel = [*NOTICES, "leika-1.0.dist-info/licenses/LICENSE", "leika/client/src/App.tsx"]
    _write_dist(tmp_path, wheel, ["src/leika/client/node_modules/react/index.js"])
    assert _run(tmp_path, monkeypatch) == 1
    output = capsys.readouterr().out
    assert "is missing leika/client/build/index.html" in output
    assert "should not contain leika/client/src/App.tsx" in output
    assert "is missing src/leika/client/build/index.html" in output
    assert "should not contain src/leika/client/node_modules/react/index.js" in output


def test_oversized_distribution_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = [*check_dist.BUNDLE, *NOTICES, "leika-1.0.dist-info/licenses/LICENSE"]
    _write_dist(tmp_path, wheel, [f"src/{name}" for name in check_dist.BUNDLE])
    monkeypatch.setattr(check_dist, "MAX_BYTES", 10)
    assert _run(tmp_path, monkeypatch) == 1
