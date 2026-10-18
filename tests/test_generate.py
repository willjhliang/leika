from __future__ import annotations

import runpy
import sys
import zipfile
from pathlib import Path

import pytest

from leika import _icons
from scripts import generate


@pytest.fixture
def package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "lucide"
    source.mkdir()
    (source / "circle.svg").write_text("<svg>circle</svg>")
    (source / "arrow-up.svg").write_text("<svg>arrow</svg>")
    package = tmp_path / "leika"
    (package / "_icons").mkdir(parents=True)
    monkeypatch.setattr(generate, "LUCIDE_ICONS", source)
    monkeypatch.setattr(generate, "PACKAGE", package)
    return package


def test_generated_icons_load_their_svg(package: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for path, content in generate._icons().items():
        path.write_bytes(content.encode() if isinstance(content, str) else content)
    icon = runpy.run_path(str(package / "_icons_enum.py"))["Icon"].ARROW_UP
    assert icon == "arrow-up"
    monkeypatch.setattr(_icons, "ICONS_ARCHIVE", package / "_icons/lucide-icons.zip")
    _icons.svg_from_icon.cache_clear()
    try:
        assert _icons.svg_from_icon(icon) == "<svg>arrow</svg>"
    finally:
        _icons.svg_from_icon.cache_clear()


def test_icon_archive_is_byte_stable_and_compared_by_members(package: Path) -> None:
    path = package / "_icons/lucide-icons.zip"
    archive = generate._icons()[path]
    assert generate._icons()[path] == archive

    # Another zlib build may deflate differently; the same members are current.
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as stored:
        stored.writestr("arrow-up.svg", "<svg>arrow</svg>")
        stored.writestr("circle.svg", "<svg>circle</svg>")
    assert generate._is_current(path, archive)
    (package.parent / "lucide/circle.svg").write_text("<svg>changed</svg>")
    assert not generate._is_current(path, generate._icons()[path])


def test_check_reports_stale_files_and_generate_rewrites_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    current = tmp_path / "Current.ts"
    stale = tmp_path / "Stale.ts"
    current.write_text("same\n")
    stale.write_text("old\n")
    monkeypatch.setattr(generate, "ROOT", tmp_path)
    monkeypatch.setattr(generate, "PRETTIER", current)
    monkeypatch.setattr(generate, "_typescript", lambda: {current: "same\n", stale: "new\n"})
    monkeypatch.setattr(generate, "_icons", dict)

    monkeypatch.setattr(sys, "argv", ["generate.py", "--check"])
    assert generate.main() == 1
    assert stale.read_text() == "old\n"
    assert capsys.readouterr().out.splitlines()[0] == "out of date: Stale.ts"

    monkeypatch.setattr(sys, "argv", ["generate.py"])
    assert generate.main() == 0
    assert stale.read_text() == "new\n"
    assert capsys.readouterr().out == "updated: Stale.ts\n"
