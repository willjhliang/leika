"""Validate the contents of a built Leika source distribution."""

from __future__ import annotations

import argparse
import gzip
import re
import tarfile
import unicodedata
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath

if __package__:
    from ._artifact_metadata import validate_metadata
else:
    from _artifact_metadata import validate_metadata

EXPECTED_LICENSE = "Apache-2.0"
SDIST_NAME = re.compile(r"^leika-(?P<version>[^-]+)\.tar\.gz$")
MAX_SDIST_BYTES = 10_000_000
MAX_SDIST_MEMBERS = 10_000
MAX_SDIST_MEMBER_BYTES = 10_000_000
MAX_SDIST_UNCOMPRESSED_BYTES = 50_000_000
MAX_SDIST_RAW_TAR_BYTES = 64_000_000
MIN_BUNDLE_NOTICE_BYTES = 20_000
BUNDLE_NOTICE = "src/leika/client/build/THIRD_PARTY_NOTICES.txt"
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
REQUIRED = {
    "CHANGELOG.md",
    "Makefile",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "build-constraints.txt",
    "hatch_build.py",
    "uv.lock",
    "pyproject.toml",
    "build-constraints.in",
    "sync_client_server.py",
    "docs/index.md",
    "docs/_static/almarai-OFL.txt",
    "docs/_static/almarai-latin-400.woff2",
    "docs/_static/geist-OFL.txt",
    "docs/_static/geist-latin-ext-wght-normal.woff2",
    "docs/_static/geist-latin-wght-normal.woff2",
    "docs/_static/leika.css",
    "docs/_static/leika.svg",
    "docs/_static/shadcn.css",
    "examples/basic.py",
    "src/leika/client/build/THIRD_PARTY_NOTICES.txt",
    "src/leika/client/build/index.html",
    "scripts/_artifact_metadata.py",
    "scripts/build_release.py",
    "scripts/check_sdist.py",
    "scripts/check_wheel.py",
    "src/leika/__init__.py",
    "src/leika/_server.py",
    "src/leika/py.typed",
    "tests/test_project_quality.py",
    "src/leika/client/third-party-license-overrides/hast-util-to-string-2.0.0.txt",
    "src/leika/client/third-party-license-overrides/react-remove-scroll-bar-2.3.8.txt",
    "src/leika/client/vite-plugin-third-party-notices.mts",
}
FORBIDDEN_PARTS = {
    ".leika-build-backup",
    ".leika-build.lock",
    ".leika-sources",
    ".nodeenv",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}
FORBIDDEN_PREFIXES = {"docs/_build"}
CLIENT_BUILD_STAGE_PREFIX = ".leika-build-stage-"
CLIENT_SNAPSHOT_TRANSACTION_PART = re.compile(r"^\..+\.leika-(?:backup|transaction|stage-.*)$")
ICON_GENERATION_STAGE_PREFIX = ".leika-icons-stage-"
ROOT_CORE_DUMP = re.compile(r"^core(?:\..*)?$")


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


def _contains_client_transaction_part(path: str) -> bool:
    return any(
        part.startswith((CLIENT_BUILD_STAGE_PREFIX, ICON_GENERATION_STAGE_PREFIX))
        or CLIENT_SNAPSHOT_TRANSACTION_PART.fullmatch(part) is not None
        for part in PurePosixPath(path).parts
    )


def _preflight_raw_tar(path: Path) -> None:
    """Bound raw gzip expansion before tar parses PAX/GNU extension records."""
    total = 0
    try:
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(min(1024 * 1024, MAX_SDIST_RAW_TAR_BYTES + 1 - total)):
                total += len(chunk)
                if total > MAX_SDIST_RAW_TAR_BYTES:
                    raise SystemExit(
                        "source distribution raw tar expands past "
                        f"{MAX_SDIST_RAW_TAR_BYTES:,} bytes"
                    )
    except (gzip.BadGzipFile, EOFError) as error:
        raise SystemExit(f"source distribution gzip stream is invalid: {error}") from None


def _bounded_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Read no more archive headers or declared payload bytes than allowed."""
    members: list[tarfile.TarInfo] = []
    uncompressed_size = 0
    while True:
        member = archive.next()
        if member is None:
            return members
        if len(members) >= MAX_SDIST_MEMBERS:
            raise SystemExit(f"source distribution has more than {MAX_SDIST_MEMBERS:,} members")
        if member.size < 0 or member.size > MAX_SDIST_MEMBER_BYTES:
            raise SystemExit(
                f"source distribution member is too large: {member.name} ({member.size:,} bytes)"
            )
        uncompressed_size += member.size
        if uncompressed_size > MAX_SDIST_UNCOMPRESSED_BYTES:
            raise SystemExit(
                f"source distribution expands past {MAX_SDIST_UNCOMPRESSED_BYTES:,} bytes"
            )
        members.append(member)


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


def _reject_ancestor_collisions(members: list[tarfile.TarInfo]) -> None:
    regular = {member.name.rstrip("/") for member in members if member.isfile()}
    portable_regular = {_portable_member_key(name) for name in regular}
    for member in members:
        parts = PurePosixPath(member.name.rstrip("/")).parts
        for length in range(1, len(parts)):
            ancestor = "/".join(parts[:length])
            if ancestor in regular or _portable_member_key(ancestor) in portable_regular:
                raise SystemExit(
                    "source distribution contains a regular-file ancestor collision: "
                    f"{ancestor} and {member.name}"
                )


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path)
    args = parser.parse_args()

    if args.sdist.is_symlink() or not args.sdist.is_file():
        raise SystemExit(f"source distribution is not a regular file: {args.sdist}")
    match = SDIST_NAME.match(args.sdist.name)
    if match is None:
        raise SystemExit(f"invalid Leika source-distribution filename: {args.sdist.name}")
    compressed_size = args.sdist.stat().st_size
    if compressed_size > MAX_SDIST_BYTES:
        raise SystemExit(
            f"source distribution is {compressed_size:,} compressed bytes; "
            f"limit is {MAX_SDIST_BYTES:,}"
        )
    version = match.group("version")
    if version != _expected_version():
        raise SystemExit(
            f"sdist version {version} does not match source version {_expected_version()}"
        )
    expected_root = f"leika-{version}"

    _preflight_raw_tar(args.sdist)
    with tarfile.open(args.sdist, "r:gz") as archive:
        members = _bounded_members(archive)
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise SystemExit("source distribution contains duplicate member names")
        canonical_keys = [name.rstrip("/") for name in names]
        if len(canonical_keys) != len(set(canonical_keys)):
            raise SystemExit("source distribution contains colliding member paths")
        portable_keys = [_portable_member_key(name) for name in names]
        if len(portable_keys) != len(set(portable_keys)):
            raise SystemExit("source distribution contains non-portable colliding member paths")
        unsafe = [
            name
            for name in names
            if "\\" in name
            or PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or _canonical_member_name(name) != name
        ]
        if unsafe:
            raise SystemExit(f"source distribution contains unsafe member path: {unsafe[0]}")
        nonportable = [name for name in names if _has_nonportable_segment(name)]
        if nonportable:
            raise SystemExit(
                f"source distribution contains a non-portable member path: {nonportable[0]}"
            )
        unsupported = [member.name for member in members if not (member.isfile() or member.isdir())]
        if unsupported:
            raise SystemExit(
                f"source distribution contains a link or special file: {unsupported[0]}"
            )
        _reject_ancestor_collisions(members)
        regular_names = {member.name for member in members if member.isfile()}

        members_by_name = {member.name: member for member in members}
        paths = [PurePosixPath(name) for name in names]
        pkg_info_path = f"{expected_root}/PKG-INFO"
        try:
            pkg_info_member = members_by_name[pkg_info_path]
        except KeyError:
            raise SystemExit("source distribution is missing PKG-INFO") from None
        pkg_info_file = archive.extractfile(pkg_info_member)
        if not pkg_info_member.isfile():
            raise SystemExit("source distribution PKG-INFO is not a regular file")
        if pkg_info_file is None:
            raise SystemExit("source distribution PKG-INFO is not a regular file")
        metadata = BytesParser(policy=default).parsebytes(pkg_info_file.read())
        validate_metadata(metadata, version=version, label="sdist PKG-INFO")
        license_files = metadata.get_all("License-File", [])
        expected_license_files = _expected_license_files()
        if (
            len(license_files) != len(set(license_files))
            or set(license_files) != expected_license_files
        ):
            raise SystemExit(
                "sdist PKG-INFO License-File entries do not match the configured license files"
            )
        missing_license_members = [
            path
            for path in sorted(expected_license_files)
            if f"{expected_root}/{path}" not in regular_names
        ]
        if missing_license_members:
            raise SystemExit(
                f"source distribution is missing declared license file: {missing_license_members[0]}"
            )
        notice_path = f"{expected_root}/{BUNDLE_NOTICE}"
        if notice_path in regular_names:
            notice_file = archive.extractfile(members_by_name[notice_path])
            if notice_file is None:
                raise SystemExit("source distribution browser bundle notices are unreadable")
            notice_bytes = notice_file.read()
            try:
                notice_text = notice_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raise SystemExit(
                    "source distribution browser bundle notices are not UTF-8"
                ) from None
            missing_notice_markers = [
                marker for marker in REQUIRED_BUNDLE_NOTICE_MARKERS if marker not in notice_text
            ]
            if len(notice_bytes) < MIN_BUNDLE_NOTICE_BYTES or missing_notice_markers:
                detail = ", ".join(missing_notice_markers) or "full license text"
                raise SystemExit(
                    f"source distribution browser bundle notices are incomplete: {detail}"
                )

    roots = {path.parts[0] for path in paths if path.parts}
    if roots != {expected_root}:
        raise SystemExit(f"expected top-level directory {expected_root}, found {sorted(roots)}")
    relative = {PurePosixPath(*path.parts[1:]).as_posix() for path in paths if len(path.parts) > 1}

    missing = sorted(path for path in REQUIRED if f"{expected_root}/{path}" not in regular_names)
    if missing:
        raise SystemExit(f"source distribution is missing: {', '.join(missing)}")

    forbidden = sorted(
        path
        for path in relative
        if FORBIDDEN_PARTS.intersection(PurePosixPath(path).parts)
        or _contains_client_transaction_part(path)
        or ROOT_CORE_DUMP.fullmatch(path) is not None
        or any(path == prefix or path.startswith(f"{prefix}/") for prefix in FORBIDDEN_PREFIXES)
    )
    if forbidden:
        raise SystemExit(f"source distribution contains generated files: {forbidden[0]}")

    print(f"source distribution contents OK: {args.sdist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
