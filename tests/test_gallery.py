from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from scripts import gallery


def _write_png(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (4, 3), color).save(path)


def _write_generation(directory: Path, names: frozenset[str], color: tuple[int, int, int]) -> None:
    for name in names:
        _write_png(directory / name, color)


def _use_test_registry(monkeypatch: pytest.MonkeyPatch, *slugs: str) -> frozenset[str]:
    entries = [
        gallery.Entry(
            slug=slug,
            title=slug.title(),
            ref="add_button",
            code=f'gui.add_button("{slug}")',
        )
        for slug in slugs
    ]
    monkeypatch.setattr(gallery, "ENTRIES", [("Test", entries)])
    return gallery._expected_asset_names()


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
    if gallery.os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o640
    assert not any(path.name.startswith(".gallery.md.") for path in tmp_path.iterdir())


def test_capture_failure_preserves_existing_gallery_generation(tmp_path: Path) -> None:
    target = tmp_path / "gallery"
    target.mkdir()
    _write_generation(
        target,
        frozenset({"previous-light.png", "previous-dark.png"}),
        (12, 34, 56),
    )
    previous = {path.name: path.read_bytes() for path in target.iterdir()}

    with pytest.raises(RuntimeError, match="simulated capture failure"):
        with gallery._staged_gallery_directory(target) as staging:
            _write_png(staging / "partial-light.png", (200, 10, 10))
            raise RuntimeError("simulated capture failure")

    assert {path.name: path.read_bytes() for path in target.iterdir()} == previous
    assert not list(tmp_path.glob(".gallery.leika-*"))


def test_incomplete_staged_gallery_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _use_test_registry(monkeypatch, "current")
    target = tmp_path / "gallery"
    target.mkdir()
    _write_generation(
        target,
        frozenset({"previous-light.png", "previous-dark.png"}),
        (12, 34, 56),
    )
    previous = {path.name: path.read_bytes() for path in target.iterdir()}

    with gallery._staged_gallery_directory(target) as staging:
        _write_png(staging / "current-light.png", (100, 110, 120))
        _write_png(staging / "removed-dark.png", (100, 110, 120))
        with pytest.raises(
            RuntimeError,
            match=r"missing current-dark\.png; unexpected removed-dark\.png",
        ):
            with gallery._published_gallery_directory(staging, target):
                pass

    assert expected == frozenset({"current-light.png", "current-dark.png"})
    assert {path.name: path.read_bytes() for path in target.iterdir()} == previous
    assert not list(tmp_path.glob(".gallery.leika-*"))


def test_gallery_publication_prunes_stale_owned_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _use_test_registry(monkeypatch, "current")
    target = tmp_path / "gallery"
    target.mkdir()
    target.chmod(0o750)
    _write_generation(
        target,
        expected | {"removed-light.png", "removed-dark.png"},
        (12, 34, 56),
    )

    with gallery._staged_gallery_directory(target) as staging:
        _write_generation(staging, expected, (100, 110, 120))
        with gallery._published_gallery_directory(staging, target):
            assert {path.name for path in target.iterdir()} == expected

    assert {path.name for path in target.iterdir()} == expected
    if gallery.os.name != "nt":
        assert target.stat().st_mode & 0o777 == 0o750
    for name in expected:
        with Image.open(target / name) as image:
            assert image.getpixel((0, 0)) == (100, 110, 120)
    assert not list(tmp_path.glob(".gallery.leika-*"))


def test_followup_failure_rolls_back_gallery_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _use_test_registry(monkeypatch, "current")
    target = tmp_path / "gallery"
    target.mkdir()
    _write_generation(
        target,
        expected | {"removed-light.png", "removed-dark.png"},
        (12, 34, 56),
    )
    previous = {path.name: path.read_bytes() for path in target.iterdir()}

    with pytest.raises(RuntimeError, match="simulated page failure"):
        with gallery._staged_gallery_directory(target) as staging:
            _write_generation(staging, expected, (100, 110, 120))
            with gallery._published_gallery_directory(staging, target):
                raise RuntimeError("simulated page failure")

    assert {path.name: path.read_bytes() for path in target.iterdir()} == previous
    assert not list(tmp_path.glob(".gallery.leika-*"))
