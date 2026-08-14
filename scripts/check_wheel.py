"""Validate Leika wheel contents and size."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import stat
import unicodedata
import zipfile
from configparser import ConfigParser
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath

if __package__:
    from ._artifact_metadata import validate_metadata
else:
    from _artifact_metadata import validate_metadata

MAX_WHEEL_BYTES = 5_000_000
MAX_WHEEL_MEMBERS = 10_000
MAX_WHEEL_MEMBER_BYTES = 10_000_000
MAX_WHEEL_UNCOMPRESSED_BYTES = 50_000_000
EXPECTED_LICENSE = "Apache-2.0"
WHEEL_NAME = re.compile(r"^leika-(?P<version>[^-]+)-py3-none-any\.whl$")
# Browser-client notices that must ship with the wheel. A truncated or
# placeholder file is treated as missing.
MIN_LICENSE_BYTES = 500
REQUIRED_NOTICES = (
    "leika/_licenses/shadcn-ui-LICENSE.md",
    "leika/_licenses/shadcn-ui-PROVENANCE.md",
    "leika/_licenses/shadcn-io-LICENSE.txt",
    "leika/_licenses/shadcn-io-PROVENANCE.md",
    "leika/_licenses/base-ui-LICENSE.txt",
    "leika/_licenses/almarai-OFL.txt",
    "leika/_licenses/geist-OFL.txt",
    "leika/_licenses/lucide-LICENSE.txt",
    "leika/_licenses/cmdk-next-themes-MIT-LICENSE.txt",
    "leika/_licenses/zstddec-LICENSE.txt",
)
REQUIRED_PACKAGE_FILES = {
    "leika/__init__.py",
    "leika/_server.py",
    "leika/py.typed",
    "leika/client/build/index.html",
}
BUNDLE_NOTICES = "leika/client/build/THIRD_PARTY_NOTICES.txt"
MIN_BUNDLE_NOTICE_BYTES = 20_000
REQUIRED_BUNDLE_NOTICE_MARKERS = (
    "@fontsource-variable/geist@",
    "@msgpack/msgpack@",
    "await-lock@",
    "esbuild@",
    "fuse.js@",
    "react@",
    "rollup@",
    "shadcn@",
    "vite@",
    "zstddec@",
    "Declared license: Apache-2.0",
)
WINDOWS_INVALID_CHARACTERS = frozenset('<>:"|?*')
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
FORBIDDEN_PARTS = {
    "node_modules",
    ".leika-sources",
    "_icons_generate_enum.py",
    ".nodeenv",
    "ThreeAssets.tsx",
    "GaussianSplats.tsx",
    "_scene_api.py",
    "_scene_handles.py",
    "_tunnel.py",
    "extras",
    "transforms",
}


def _expected_license_files() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    licenses = {"LICENSE", "src/leika/client/build/THIRD_PARTY_NOTICES.txt"}
    for directory in (
        root / "src/leika/_licenses",
        root / "src/leika/client/third-party-license-overrides",
    ):
        licenses.update(
            path.relative_to(root).as_posix() for path in directory.iterdir() if path.is_file()
        )
    return licenses


def _expected_version() -> str:
    source = (Path(__file__).resolve().parents[1] / "src/leika/__init__.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    if match is None:
        raise SystemExit("cannot read authoritative Leika version")
    return match.group(1)


def _canonical_member_name(name: str) -> str:
    canonical = PurePosixPath(name).as_posix()
    return canonical + "/" if name.endswith("/") else canonical


def _portable_member_key(name: str) -> str:
    return unicodedata.normalize("NFC", name.rstrip("/")).casefold()


def _has_nonportable_segment(name: str) -> bool:
    for segment in PurePosixPath(name.rstrip("/")).parts:
        if (
            any(ord(character) < 32 or ord(character) == 127 for character in segment)
            or WINDOWS_INVALID_CHARACTERS.intersection(segment)
            or segment.endswith((" ", "."))
            or segment.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES
        ):
            return True
    return False


def _is_supported_member(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
    return file_type in (0, expected)


def _reject_ancestor_collisions(infos: list[zipfile.ZipInfo]) -> None:
    regular = {info.filename.rstrip("/") for info in infos if not info.is_dir()}
    portable_regular = {_portable_member_key(name) for name in regular}
    for info in infos:
        parts = PurePosixPath(info.filename.rstrip("/")).parts
        for length in range(1, len(parts)):
            ancestor = "/".join(parts[:length])
            if ancestor in regular or _portable_member_key(ancestor) in portable_regular:
                raise SystemExit(
                    "wheel contains a regular-file ancestor collision: "
                    f"{ancestor} and {info.filename}"
                )


def _validate_structure(archive: zipfile.ZipFile, wheel: Path) -> tuple[list[str], str]:
    match = WHEEL_NAME.match(wheel.name)
    if match is None:
        raise SystemExit(f"invalid Leika wheel filename: {wheel.name}")
    version = match.group("version")
    if version != _expected_version():
        raise SystemExit(
            f"wheel version {version} does not match source version {_expected_version()}"
        )

    infos = archive.infolist()
    if len(infos) > MAX_WHEEL_MEMBERS:
        raise SystemExit(f"wheel has {len(infos):,} members; limit is {MAX_WHEEL_MEMBERS:,}")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise SystemExit("wheel contains duplicate member names")
    canonical_keys = [name.rstrip("/") for name in names]
    if len(canonical_keys) != len(set(canonical_keys)):
        raise SystemExit("wheel contains colliding member paths")
    portable_keys = [_portable_member_key(name) for name in names]
    if len(portable_keys) != len(set(portable_keys)):
        raise SystemExit("wheel contains non-portable colliding member paths")
    oversized = [info for info in infos if info.file_size > MAX_WHEEL_MEMBER_BYTES]
    if oversized:
        raise SystemExit(
            f"wheel member is too large: {oversized[0].filename} ({oversized[0].file_size:,} bytes)"
        )
    uncompressed_size = sum(info.file_size for info in infos)
    if uncompressed_size > MAX_WHEEL_UNCOMPRESSED_BYTES:
        raise SystemExit(
            f"wheel expands to {uncompressed_size:,} bytes; "
            f"limit is {MAX_WHEEL_UNCOMPRESSED_BYTES:,}"
        )
    unsafe = [
        name
        for name in names
        if "\\" in name
        or PurePosixPath(name).is_absolute()
        or ".." in PurePosixPath(name).parts
        or _canonical_member_name(name) != name
    ]
    if unsafe:
        raise SystemExit(f"wheel contains unsafe member path: {unsafe[0]}")
    nonportable = [name for name in names if _has_nonportable_segment(name)]
    if nonportable:
        raise SystemExit(f"wheel contains a non-portable member path: {nonportable[0]}")
    corrupt = archive.testzip()
    if corrupt is not None:
        raise SystemExit(f"wheel has a corrupt member: {corrupt}")

    unsupported = [info.filename for info in infos if not _is_supported_member(info)]
    if unsupported:
        raise SystemExit(f"wheel contains a symlink or special file: {unsupported[0]}")
    _reject_ancestor_collisions(infos)

    dist_info = f"leika-{version}.dist-info"
    metadata_path = f"{dist_info}/METADATA"
    dist_info_roots = {
        PurePosixPath(name).parts[0]
        for name in names
        if PurePosixPath(name).parts and PurePosixPath(name).parts[0].endswith(".dist-info")
    }
    if dist_info_roots != {dist_info}:
        raise SystemExit(
            "wheel must contain exactly the expected dist-info tree; "
            f"found {sorted(dist_info_roots)}"
        )
    unexpected_roots = [name for name in names if not name.startswith(("leika/", f"{dist_info}/"))]
    if unexpected_roots:
        raise SystemExit(f"wheel member is outside package namespaces: {unexpected_roots[0]}")
    record_path = f"{dist_info}/RECORD"
    wheel_metadata_path = f"{dist_info}/WHEEL"
    entry_points_path = f"{dist_info}/entry_points.txt"
    required_files = REQUIRED_PACKAGE_FILES | {
        BUNDLE_NOTICES,
        entry_points_path,
        metadata_path,
        record_path,
        wheel_metadata_path,
    }
    missing_files = [
        name
        for name in sorted(required_files)
        if name not in names or archive.getinfo(name).is_dir()
    ]
    if missing_files:
        raise SystemExit(f"wheel is missing required regular file: {missing_files[0]}")

    wheel_metadata = BytesParser(policy=default).parsebytes(archive.read(wheel_metadata_path))
    wheel_expected = {
        "Wheel-Version": "1.0",
        "Root-Is-Purelib": "true",
    }
    for field, expected in wheel_expected.items():
        if wheel_metadata.get(field) != expected:
            raise SystemExit(
                f"wheel WHEEL {field} is {wheel_metadata.get(field)!r}; expected {expected!r}"
            )
    if wheel_metadata.get_all("Tag", []) != ["py3-none-any"]:
        raise SystemExit("wheel WHEEL must declare exactly the py3-none-any tag")

    entry_points = ConfigParser()
    entry_points.read_string(archive.read(entry_points_path).decode("utf-8"))
    expected_entry_point = "leika._client_autobuild:build_client_entrypoint"
    if (
        entry_points.get("console_scripts", "leika-build-client", fallback=None)
        != expected_entry_point
    ):
        raise SystemExit("wheel entry_points.txt has an invalid leika-build-client entry point")

    metadata = BytesParser(policy=default).parsebytes(archive.read(metadata_path))
    validate_metadata(metadata, version=version, label="wheel METADATA")
    license_files = metadata.get_all("License-File", [])
    expected_license_files = _expected_license_files()
    if (
        len(license_files) != len(set(license_files))
        or set(license_files) != expected_license_files
    ):
        raise SystemExit(
            "wheel METADATA License-File entries do not match configured license files"
        )
    missing_license_members = [
        path
        for path in sorted(expected_license_files)
        if f"{dist_info}/licenses/{path}" not in names
        or archive.getinfo(f"{dist_info}/licenses/{path}").is_dir()
    ]
    if missing_license_members:
        raise SystemExit(f"wheel is missing declared license file: {missing_license_members[0]}")

    rows = list(csv.reader(io.StringIO(archive.read(record_path).decode("utf-8"))))
    if any(len(row) != 3 for row in rows):
        raise SystemExit("wheel RECORD contains a malformed row")
    record_names = [row[0] for row in rows]
    if len(record_names) != len(set(record_names)) or set(record_names) != set(names):
        raise SystemExit("wheel RECORD does not contain each archive member exactly once")
    for name, recorded_hash, recorded_size in rows:
        if name == record_path:
            if recorded_hash or recorded_size:
                raise SystemExit("wheel RECORD must not hash itself")
            continue
        payload = archive.read(name)
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()
        if recorded_hash != f"sha256={digest}" or recorded_size != str(len(payload)):
            raise SystemExit(f"wheel RECORD hash or size mismatch: {name}")
    return names, version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    if args.wheel.is_symlink() or not args.wheel.is_file():
        raise SystemExit(f"wheel is not a regular file: {args.wheel}")
    size = args.wheel.stat().st_size
    if size >= MAX_WHEEL_BYTES:
        raise SystemExit(f"{args.wheel} is {size:,} bytes; limit is {MAX_WHEEL_BYTES:,} bytes")

    with zipfile.ZipFile(args.wheel) as archive:
        names, _version = _validate_structure(archive, args.wheel)
        missing_notices = [
            path for path in REQUIRED_NOTICES if path not in names or archive.getinfo(path).is_dir()
        ]
        if missing_notices:
            raise SystemExit(
                "wheel does not contain required browser-client licenses/provenance: "
                + ", ".join(missing_notices)
            )
        truncated = [
            path for path in REQUIRED_NOTICES if len(archive.read(path)) < MIN_LICENSE_BYTES
        ]
        if truncated:
            raise SystemExit(
                "wheel contains incomplete licenses/provenance: " + ", ".join(truncated)
            )
        if BUNDLE_NOTICES not in names:
            raise SystemExit("wheel does not contain generated browser bundle notices")
        bundle_notices = archive.read(BUNDLE_NOTICES)
        if len(bundle_notices) < MIN_BUNDLE_NOTICE_BYTES:
            raise SystemExit(
                f"wheel browser bundle notices are only {len(bundle_notices):,} bytes; "
                f"expected at least {MIN_BUNDLE_NOTICE_BYTES:,}"
            )
        notice_text = bundle_notices.decode("utf-8")
        missing_markers = [
            marker for marker in REQUIRED_BUNDLE_NOTICE_MARKERS if marker not in notice_text
        ]
        if missing_markers:
            raise SystemExit(
                "wheel browser bundle notices are incomplete: " + ", ".join(missing_markers)
            )
    if not any(name.endswith("leika/client/build/index.html") for name in names):
        raise SystemExit("wheel does not contain the built browser client")
    unexpected_client_files = [
        name for name in names if name.startswith("leika/client/") and "/client/build/" not in name
    ]
    if unexpected_client_files:
        raise SystemExit(
            "wheel contains raw client-development files: " + ", ".join(unexpected_client_files)
        )
    forbidden = [
        name for name in names if any(part in FORBIDDEN_PARTS for part in PurePosixPath(name).parts)
    ]
    if forbidden:
        raise SystemExit("wheel contains forbidden development/3D files: " + ", ".join(forbidden))
    print(f"{args.wheel}: {size:,} bytes, {len(names)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
