"""Build the bundled Lucide icon archive and the `Icon` name enum.

Run after changing the pinned `lucide-static` version in the browser client:

    python -m leika._icons_generate_enum
    ruff format src/leika/_icons_enum.py src/leika/_icons_enum.pyi

The client chrome uses `lucide-react`; this packages the same icon set as
plain SVG so the Python API can send icon markup to the browser. Keep the two
on the same Lucide version.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from ._client_autobuild import _build_lock

HERE_DIR = Path(__file__).resolve().parent
ICON_DIR = HERE_DIR / "_icons"
ICON_ARCHIVE = ICON_DIR / "lucide-icons.zip"
SOURCE_DIR = HERE_DIR / "client" / "node_modules" / "lucide-static" / "icons"

# ZIP's earliest representable timestamp. Keeping generated-member metadata
# fixed makes a repeated archive build byte-for-byte stable instead of
# recording the wall clock once per icon.
_ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _archive_member(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_ARCHIVE_TIMESTAMP)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace_generated(path: Path, write: Callable[[Path], None]) -> None:
    """Stage, fsync, and replace one generated regular file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"refusing to replace generated-file symlink: {path}")
    if path.exists() and not path.is_file():
        raise RuntimeError(f"generated-file target is not regular: {path}")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    os.close(descriptor)
    try:
        write(temporary)
        os.chmod(temporary, mode)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_generated(path: Path, source: str) -> None:
    """Write generated Python with stable UTF-8/LF encoding and a final LF."""

    def write(temporary: Path) -> None:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            output.write(source + "\n")

    _replace_generated(path, write)


def enum_name_from_icon(name: str) -> str:
    """Capitalize an icon name for use as an enum name."""
    name = name.upper()
    name = name.replace("-", "_")
    if name[0].isdigit():
        name = "ICON_" + name
    return name


def _portable_source_key(name: str) -> str:
    normalized = unicodedata.normalize("NFC", name)
    if any(ord(character) < 32 or ord(character) == 127 for character in name):
        raise RuntimeError(f"icon source name contains a control character: {name!r}")
    if any(character in '<>:"/\\|?*' for character in name):
        raise RuntimeError(f"icon source name is not portable: {name!r}")
    if name.endswith((".", " ")) or normalized != name:
        raise RuntimeError(f"icon source name is not portable: {name!r}")
    stem = Path(name).stem
    if stem.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
        r"(?:COM|LPT)[1-9]", stem, re.IGNORECASE
    ):
        raise RuntimeError(f"icon source name is reserved on Windows: {name!r}")
    return normalized.casefold()


def _validated_sources() -> list[Path]:
    if SOURCE_DIR.is_symlink() or not SOURCE_DIR.is_dir():
        raise SystemExit(f"{SOURCE_DIR} not found; run `npm ci` in src/leika/client first.")
    sources = sorted(path for path in SOURCE_DIR.iterdir() if path.suffix == ".svg")
    if not sources:
        raise SystemExit(f"no SVGs found in {SOURCE_DIR}")
    keys: dict[str, str] = {}
    for path in sources:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"icon source is not a regular file: {path}")
        key = _portable_source_key(path.name)
        previous = keys.setdefault(key, path.name)
        if previous != path.name:
            raise RuntimeError(f"icon source names collide portably: {previous!r}, {path.name!r}")
    return sources


def _write_archive_file(target: Path, sources: list[Path]) -> None:
    with zipfile.ZipFile(
        target,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sources:
            archive.writestr(_archive_member(path.name), path.read_bytes())


def _build_archive(target: Path) -> list[str]:
    """Repack the installed Lucide SVGs into ``target``."""
    sources = _validated_sources()
    _replace_generated(target, lambda temporary: _write_archive_file(temporary, sources))
    return [path.stem for path in sources]


def build_archive() -> list[str]:
    """Repack the installed Lucide SVGs and return the icon names."""
    with _build_lock():
        return _build_archive(ICON_ARCHIVE)


def write_enum(icon_names: list[str], directory: Path | None = None) -> None:
    directory = HERE_DIR if directory is None else directory
    enum_names = [enum_name_from_icon(icon) for icon in icon_names]
    duplicates = sorted(name for name, count in Counter(enum_names).items() if count > 1)
    if duplicates:
        raise ValueError(f"icon names collide as Python attributes: {duplicates}")

    header_doc = [
        "# Automatically generated by `_icons_generate_enum.py`",
        "# Icons from Lucide (https://lucide.dev), ISC licensed.",
    ]
    summary = "'Enum' class for referencing Lucide icons."
    # Why this isn't an enum belongs next to the code rather than in the
    # docstring, which is published as user-facing API documentation.
    class_comment = [
        "# Not an enum.Enum subclass: importing an enum with thousands of names can cost",
        "# hundreds of milliseconds at import time.",
    ]

    # Stub file. This is used by type checkers.
    _write_generated(
        directory / "_icons_enum.pyi",
        "\n".join(
            header_doc
            + [
                "from typing import NewType",
                "",
                'IconName = NewType("IconName", str)',
                '"""Name of an icon. Should be generated via `leika.Icon.*`."""',
                "",
            ]
            + class_comment
            + [
                "class Icon:",
                f'    """{summary}"""',
                "",
            ]
            + [
                # Prefix names that start with a digit, which can't be Python
                # identifiers on their own.
                f'    {enum_name_from_icon(icon)}: IconName = IconName("{icon}")'
                for icon in icon_names
            ]
        ),
    )

    # Source. This is used at runtime + by Sphinx for documentation.
    _write_generated(
        directory / "_icons_enum.py",
        "\n".join(
            header_doc
            + [
                "from typing import NewType",
                "",
                'IconName = NewType("IconName", str)',
                '"""Name of an icon. Should be generated via `leika.Icon.*`."""',
                "",
                "",
                "class _IconStringConverter(type):",
                "    def __getattr__(self, __name: str) -> IconName:",
                '        if not __name.startswith("_"):',
                '            return IconName(__name.lower().replace("_", "-"))',
                "        else:",
                "            raise AttributeError()",
                "",
                "",
            ]
            + class_comment
            + [
                "class Icon(metaclass=_IconStringConverter):",
                f'    """{summary}',
                "",
                "    Attributes:",
            ]
            + [
                f"        {enum_name_from_icon(icon)} (IconName): The :code:`{icon}` icon."
                for icon in icon_names
            ]
            + ['    """']
        ),
    )


def _copy_generated(source: Path, target: Path) -> None:
    def copy(temporary: Path) -> None:
        shutil.copyfile(source, temporary)

    _replace_generated(target, copy)


def _restore_generated(path: Path, snapshot: tuple[bytes, int] | None) -> None:
    if snapshot is None:
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"cannot roll back unexpected generated target: {path}")
            path.unlink()
            _fsync_directory(path.parent)
        return
    payload, _mode = snapshot

    def write(temporary: Path) -> None:
        temporary.write_bytes(payload)

    _replace_generated(path, write)


def _publish_generated_set(staged: list[tuple[Path, Path]]) -> None:
    """Publish a validated generated set, rolling the whole set back on failure."""
    snapshots: dict[Path, tuple[bytes, int] | None] = {}
    for source, target in staged:
        if source.is_symlink() or not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f"staged generated file is invalid: {source}")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RuntimeError(f"generated-file target is not regular: {target}")
        snapshots[target] = (
            (target.read_bytes(), stat.S_IMODE(target.stat().st_mode)) if target.exists() else None
        )

    try:
        for source, target in staged:
            _copy_generated(source, target)
    except BaseException:
        rollback_errors: list[Exception] = []
        for _source, target in reversed(staged):
            try:
                _restore_generated(target, snapshots[target])
            except Exception as error:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(error)
        if rollback_errors:
            raise RuntimeError(
                "icon generation failed and rollback was incomplete"
            ) from rollback_errors[0]
        raise


def generate_icons() -> list[str]:
    """Stage, validate, and publish the archive and both Python enum files."""
    with _build_lock():
        HERE_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".leika-icons-stage-", dir=HERE_DIR) as name:
            stage = Path(name)
            archive_path = stage / ICON_ARCHIVE.name
            names = _build_archive(archive_path)
            write_enum(names, stage)
            with zipfile.ZipFile(archive_path) as archive:
                if archive.testzip() is not None or archive.namelist() != [
                    f"{icon}.svg" for icon in names
                ]:
                    raise RuntimeError("staged Lucide archive failed validation")
            _publish_generated_set(
                [
                    (archive_path, ICON_ARCHIVE),
                    (stage / "_icons_enum.py", HERE_DIR / "_icons_enum.py"),
                    (stage / "_icons_enum.pyi", HERE_DIR / "_icons_enum.pyi"),
                ]
            )
            return names


if __name__ == "__main__":
    names = generate_icons()
    print(f"packaged {len(names)} Lucide icons into {ICON_ARCHIVE.name}")
