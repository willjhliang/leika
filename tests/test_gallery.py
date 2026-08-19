from __future__ import annotations

import struct
from pathlib import Path

import pytest
from PIL import Image

from leika import GuiApi
from scripts import gallery


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


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


def _plotly_metrics(path: Path) -> tuple[float, float]:
    with Image.open(path) as source:
        pixels = source.convert("RGB").get_flattened_data()
    total = len(pixels)
    trace_pixels = sum(blue > red + 20 and blue > green + 10 for red, green, blue in pixels)
    dark_surface_pixels = sum(max(red, green, blue) < 80 for red, green, blue in pixels)
    return trace_pixels / total, dark_surface_pixels / total


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


def test_gallery_registry_and_assets_are_complete_and_high_density() -> None:
    entries = [entry for _, group_entries in gallery.ENTRIES for entry in group_entries]
    slugs = [entry.slug for entry in entries]

    assert len(slugs) == len(set(slugs))
    gallery_methods = {entry.ref for entry in entries}
    public_add_methods = {name for name in dir(GuiApi) if name.startswith("add_")}
    assert gallery_methods == public_add_methods

    expected = {
        gallery.DEFAULT_OUT / f"{entry.slug}-{scheme}.png"
        for entry in entries
        for scheme in ("light", "dark")
    }
    actual = set(gallery.DEFAULT_OUT.glob("*.png"))
    assert actual == expected

    # Ordinary gallery rows are roughly 300 CSS pixels wide. Requiring that
    # many physical pixels per configured scale catches their stale 1x/2x
    # captures without coupling exceptional overlay widths to exact geometry.
    for path in expected:
        width, height = _png_size(path)
        assert width >= 300 * gallery.SCALE, path
        assert height > 0, path


def test_plotly_gallery_has_trace_content_in_both_leika_themes() -> None:
    light_trace, light_surface = _plotly_metrics(gallery.DEFAULT_OUT / "plotly-light.png")
    dark_trace, dark_surface = _plotly_metrics(gallery.DEFAULT_OUT / "plotly-dark.png")

    # The sample keeps its configured light Plotly template in both files, but
    # its blue trace must survive the Leika scheme repaint. The surrounding
    # component surface is what distinguishes the dark capture from the light.
    assert light_trace > 0.005
    assert dark_trace > 0.005
    assert dark_trace == pytest.approx(light_trace, rel=0.15)
    assert dark_surface > light_surface + 0.1


def test_generated_gallery_page_is_current_and_has_one_final_newline() -> None:
    page_path = gallery.ROOT / "docs" / "gallery.md"
    content = page_path.read_text(encoding="utf-8")

    assert content == gallery._page_content()
    assert content.endswith("\n")
    assert not content.endswith("\n\n")
