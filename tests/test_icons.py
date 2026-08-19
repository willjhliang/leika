from __future__ import annotations

import json
import re
import stat
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from leika import _icons_generate_enum as generator


def test_icon_archive_generation_is_byte_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "z.svg").write_bytes(b"<svg>z</svg>\n")
    (source / "a-b.svg").write_bytes(b"<svg>a</svg>\n")
    archive_path = tmp_path / "icons.zip"
    monkeypatch.setattr(generator, "SOURCE_DIR", source)
    monkeypatch.setattr(generator, "ICON_DIR", tmp_path)
    monkeypatch.setattr(generator, "ICON_ARCHIVE", archive_path)

    assert generator.build_archive() == ["a-b", "z"]
    first = archive_path.read_bytes()
    assert generator.build_archive() == ["a-b", "z"]
    assert archive_path.read_bytes() == first

    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        assert [info.filename for info in infos] == ["a-b.svg", "z.svg"]
        assert [archive.read(info) for info in infos] == [b"<svg>a</svg>\n", b"<svg>z</svg>\n"]
    assert all(info.date_time == generator._ARCHIVE_TIMESTAMP for info in infos)
    assert all(info.create_system == 3 for info in infos)
    assert all(stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG for info in infos)
    assert all((info.external_attr >> 16) & 0o777 == 0o644 for info in infos)


def test_icon_sources_must_be_regular(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    target = source / "target"
    target.write_text("<svg/>", encoding="utf-8")
    try:
        (source / "linked.svg").symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    monkeypatch.setattr(generator, "SOURCE_DIR", source)
    monkeypatch.setattr(generator, "ICON_ARCHIVE", tmp_path / "icons.zip")

    with pytest.raises(RuntimeError, match="not a regular file"):
        generator.build_archive()


def test_icon_source_names_must_be_portable_and_unique() -> None:
    with pytest.raises(RuntimeError, match="collide portably"):
        generator._validate_portable_source_names(["A.svg", "a.svg"])

    with pytest.raises(RuntimeError, match="not portable"):
        generator._validate_portable_source_names(["bad:name.svg"])


def test_failed_icon_archive_generation_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.svg").write_bytes(b"<svg/>")
    archive_path = tmp_path / "icons.zip"
    archive_path.write_bytes(b"previous")
    monkeypatch.setattr(generator, "SOURCE_DIR", source)
    monkeypatch.setattr(generator, "ICON_DIR", tmp_path)
    monkeypatch.setattr(generator, "ICON_ARCHIVE", archive_path)

    def fail_write(_self: zipfile.ZipFile, _info: object, _data: bytes) -> None:
        raise OSError("simulated archive failure")

    monkeypatch.setattr(generator.zipfile.ZipFile, "writestr", fail_write)
    with pytest.raises(OSError, match="simulated archive failure"):
        generator.build_archive()

    assert archive_path.read_bytes() == b"previous"
    assert {path.name for path in tmp_path.iterdir()} == {"icons.zip", "source"}


def test_generated_source_preserves_mode_and_fsyncs_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "generated.py"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o640)
    synced: list[Path] = []
    monkeypatch.setattr(generator, "_fsync_directory", synced.append)

    generator._write_generated(target, "new")

    assert target.read_text(encoding="utf-8") == "new\n"
    if generator.os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert synced == [tmp_path]


def test_generation_stages_the_complete_set_under_the_client_build_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "leika"
    source = tmp_path / "source"
    package.mkdir()
    source.mkdir()
    (source / "circle.svg").write_text("<svg/>", encoding="utf-8")
    archive_path = package / "_icons" / "lucide-icons.zip"
    targets = [
        archive_path,
        package / "_icons_enum.py",
        package / "_icons_enum.pyi",
    ]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"previous")

    active = False

    @contextmanager
    def lock():
        nonlocal active
        assert not active
        active = True
        try:
            yield
        finally:
            active = False

    original_sources = generator._validated_sources

    def checked_sources() -> list[Path]:
        assert active
        return original_sources()

    monkeypatch.setattr(generator, "HERE_DIR", package)
    monkeypatch.setattr(generator, "ICON_DIR", archive_path.parent)
    monkeypatch.setattr(generator, "ICON_ARCHIVE", archive_path)
    monkeypatch.setattr(generator, "SOURCE_DIR", source)
    monkeypatch.setattr(generator, "_build_lock", lock)
    monkeypatch.setattr(generator, "_validated_sources", checked_sources)

    assert generator.generate_icons() == ["circle"]
    assert not active
    assert zipfile.is_zipfile(archive_path)
    assert b"CIRCLE (IconName)" in targets[1].read_bytes()
    assert b'IconName("circle")' in targets[2].read_bytes()
    assert not list(package.glob(".leika-icons-stage-*"))


def test_staging_failure_preserves_the_whole_previous_icon_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "leika"
    source = tmp_path / "source"
    package.mkdir()
    source.mkdir()
    (source / "circle.svg").write_text("<svg/>", encoding="utf-8")
    archive_path = package / "_icons" / "lucide-icons.zip"
    targets = [
        archive_path,
        package / "_icons_enum.py",
        package / "_icons_enum.pyi",
    ]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"previous")

    original_write = generator._write_generated

    def fail_second_write(path: Path, text: str) -> None:
        if path.name == "_icons_enum.py":
            raise OSError("simulated enum failure")
        original_write(path, text)

    monkeypatch.setattr(generator, "HERE_DIR", package)
    monkeypatch.setattr(generator, "ICON_DIR", archive_path.parent)
    monkeypatch.setattr(generator, "ICON_ARCHIVE", archive_path)
    monkeypatch.setattr(generator, "SOURCE_DIR", source)
    monkeypatch.setattr(generator, "_write_generated", fail_second_write)

    with pytest.raises(OSError, match="simulated enum failure"):
        generator.generate_icons()

    assert [target.read_bytes() for target in targets] == [b"previous"] * 3
    assert not list(package.glob(".leika-icons-stage-*"))


def test_partial_publish_failure_rolls_back_the_whole_icon_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = []
    for index in range(3):
        source = tmp_path / f"staged-{index}"
        target = tmp_path / f"target-{index}"
        source.write_bytes(f"new-{index}".encode())
        target.write_bytes(f"old-{index}".encode())
        staged.append((source, target))

    original_copy = generator._copy_generated
    calls = 0

    def fail_second_copy(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publication failure")
        original_copy(source, target)

    monkeypatch.setattr(generator, "_copy_generated", fail_second_copy)
    with pytest.raises(OSError, match="simulated publication failure"):
        generator._publish_generated_set(staged)

    assert [target.read_bytes() for _source, target in staged] == [
        b"old-0",
        b"old-1",
        b"old-2",
    ]


def test_icon_attribute_collisions_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generator, "HERE_DIR", tmp_path)
    with pytest.raises(ValueError, match="collide"):
        generator.write_enum(["a-b", "a_b"])
    assert not (tmp_path / "_icons_enum.py").exists()
    assert not (tmp_path / "_icons_enum.pyi").exists()


def test_shipped_icon_versions_archive_and_stub_are_in_lockstep() -> None:
    root = Path(__file__).resolve().parents[1]
    client = root / "src/leika/client"
    lock = json.loads((client / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    react_version = packages["node_modules/lucide-react"]["version"]
    static_version = packages["node_modules/lucide-static"]["version"]
    assert react_version == static_version

    archive_path = root / "src/leika/_icons/lucide-icons.zip"
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert archive.testzip() is None
    assert names == sorted(names)
    assert len(names) == len(set(names))
    assert all(name.endswith(".svg") and Path(name).name == name for name in names)
    assert all(info.date_time == generator._ARCHIVE_TIMESTAMP for info in infos)
    assert all((info.external_attr >> 16) & 0o777 == 0o644 for info in infos)

    stub = (root / "src/leika/_icons_enum.pyi").read_text(encoding="utf-8")
    declarations = re.findall(
        r'^    ([A-Z][A-Z0-9_]*): IconName = IconName\("([^"]+)"\)$',
        stub,
        re.MULTILINE,
    )
    expected = [(generator.enum_name_from_icon(Path(name).stem), Path(name).stem) for name in names]
    assert declarations == expected
    assert len({attribute for attribute, _icon in declarations}) == len(declarations)
