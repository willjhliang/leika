"""Build and validate release distributions without relying on a clean ``dist/``."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BACKUP_MARKER = ".leika-release-backup-v1.json"
RETIRED_DIST = ".leika-dist-being-replaced"
DIST_STAGE_PREFIX = ".leika-dist-stage-"
BACKUP_STAGE_PREFIX = ".previous-dist-stage-"
ARTIFACT_NAME = re.compile(r"^leika-[^-]+(?:-py3-none-any\.whl|\.tar\.gz)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CLIENT_SNAPSHOT_TRANSACTION_PART = re.compile(r"^\..+\.leika-(?:backup|transaction|stage-.*)$")
ICON_GENERATION_STAGE_PREFIX = ".leika-icons-stage-"
# This is deliberately the shipped source surface, not every repository file.
# In particular, CI workflows are validated separately and are absent from an
# unpacked sdist; every entry below is required to ship by a project-shape test.
INPUT_ROOTS = (
    ROOT / "docs",
    ROOT / "examples",
    ROOT / "scripts",
    ROOT / "src/leika",
    ROOT / "tests",
)
INPUT_FILES = (
    ROOT / "CHANGELOG.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "LICENSE",
    ROOT / "Makefile",
    ROOT / "README.md",
    ROOT / "build-constraints.in",
    ROOT / "build-constraints.txt",
    ROOT / "hatch_build.py",
    ROOT / "pyproject.toml",
    ROOT / "sync_client_server.py",
    ROOT / "uv.lock",
)
INPUT_EXCLUDED_PARTS = {
    "__pycache__",
    ".leika-build-backup",
    ".nodeenv",
    "node_modules",
}
INPUT_EXCLUDED_PATHS = {
    Path("docs/_build"),
    Path("src/leika/client/.leika-build.lock"),
    Path("src/leika/client/build/.leika-sources"),
}


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _client_transaction_part(part: str) -> bool:
    return part.startswith((".leika-build-stage-", ICON_GENERATION_STAGE_PREFIX)) or (
        CLIENT_SNAPSHOT_TRANSACTION_PART.fullmatch(part) is not None
    )


def _release_input_is_excluded(relative: Path) -> bool:
    return (
        bool(INPUT_EXCLUDED_PARTS.intersection(relative.parts))
        or any(_client_transaction_part(part) for part in relative.parts)
        or any(
            relative == excluded or excluded in relative.parents
            for excluded in INPUT_EXCLUDED_PATHS
        )
    )


def _release_input_manifest() -> dict[str, str]:
    """Hash every source/build input while excluding only mutable tool state."""
    candidates = list(INPUT_FILES)
    for directory in INPUT_ROOTS:
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(f"release input directory is unavailable: {directory}")
        for current, directory_names, filenames in os.walk(directory, followlinks=False):
            current_path = Path(current)
            retained_directories = []
            for name in directory_names:
                path = current_path / name
                relative = path.relative_to(ROOT)
                if _release_input_is_excluded(relative):
                    continue
                if path.is_symlink():
                    raise RuntimeError(f"release input is a symlink: {relative}")
                retained_directories.append(name)
            directory_names[:] = retained_directories
            candidates.extend(current_path / name for name in filenames)
    manifest: dict[str, str] = {}
    for path in sorted(set(candidates)):
        relative = path.relative_to(ROOT)
        if _release_input_is_excluded(relative):
            continue
        if path.is_symlink():
            raise RuntimeError(f"release input is a symlink: {relative}")
        if not path.is_file():
            raise RuntimeError(f"release input is unavailable or not regular: {relative}")
        manifest[relative.as_posix()] = _file_hash(path)
    return manifest


def _changed_manifest_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
    )


def _dist_manifest(directory: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file() or ARTIFACT_NAME.fullmatch(path.name) is None:
            raise RuntimeError(f"refusing unexpected dist entry: {path}")
        manifest[path.name] = _file_hash(path)
    return manifest


def _owned_backup_metadata(
    backup: Path,
) -> tuple[dict[str, str], dict[str, str] | None]:
    marker = backup / BACKUP_MARKER
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError(f"refusing to replace unowned backup path: {backup.relative_to(ROOT)}")
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"invalid release backup marker: {marker.relative_to(ROOT)}") from error
    if (
        not isinstance(payload, dict)
        or payload.get("version") not in (1, 2)
        or not isinstance(payload.get("files"), dict)
    ):
        raise RuntimeError(f"invalid release backup marker: {marker.relative_to(ROOT)}")
    expected = payload["files"]
    if any(
        not isinstance(name, str)
        or ARTIFACT_NAME.fullmatch(name) is None
        or not isinstance(digest, str)
        or SHA256.fullmatch(digest) is None
        for name, digest in expected.items()
    ):
        raise RuntimeError(f"invalid release backup marker: {marker.relative_to(ROOT)}")
    replacement = payload.get("replacement")
    if payload["version"] == 2:
        if not isinstance(replacement, dict) or any(
            not isinstance(name, str)
            or ARTIFACT_NAME.fullmatch(name) is None
            or not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
            for name, digest in replacement.items()
        ):
            raise RuntimeError(f"invalid release backup marker: {marker.relative_to(ROOT)}")
    elif replacement is not None:
        raise RuntimeError(f"invalid release backup marker: {marker.relative_to(ROOT)}")
    actual_names = {path.name for path in backup.iterdir()}
    if actual_names != set(expected) | {BACKUP_MARKER}:
        raise RuntimeError(f"release backup contents changed: {backup.relative_to(ROOT)}")
    if any(
        (backup / name).is_symlink()
        or not (backup / name).is_file()
        or _file_hash(backup / name) != digest
        for name, digest in expected.items()
    ):
        raise RuntimeError(f"release backup contents changed: {backup.relative_to(ROOT)}")
    return dict(expected), None if replacement is None else dict(replacement)


def _remove_owned_backup(backup: Path) -> None:
    _owned_backup_metadata(backup)
    shutil.rmtree(backup)
    _fsync_directory(backup.parent)


def _fsync_directory(directory: Path) -> None:
    """Persist a directory entry change where directory fsync is supported."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _copy_file_durable(source_path: Path, target_path: Path) -> None:
    """Copy and flush one artifact before its containing directory is renamed."""
    with source_path.open("rb") as source, target_path.open("wb") as target:
        shutil.copyfileobj(source, target)
        target.flush()
        os.fsync(target.fileno())


def _cleanup_stage_parent(parent: Path, prefix: str) -> None:
    """Remove only tempfile-shaped staging directories owned by this builder."""
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise RuntimeError(f"refusing unexpected staging parent: {parent}")
    if not parent.exists():
        return

    removed = False
    shape = re.compile(rf"{re.escape(prefix)}[A-Za-z0-9_-]{{6,}}")
    for child in parent.iterdir():
        if not child.name.startswith(prefix):
            continue
        if shape.fullmatch(child.name) is None or child.is_symlink() or not child.is_dir():
            raise RuntimeError(f"refusing unexpected release staging path: {child}")
        shutil.rmtree(child)
        removed = True
    if removed:
        _fsync_directory(parent)


def _cleanup_owned_staging() -> None:
    """Clean crash debris after validating its narrow internal path shape."""
    _cleanup_stage_parent(ROOT, DIST_STAGE_PREFIX)
    backup_root = ROOT / ".release-artifact-backups"
    _cleanup_stage_parent(backup_root, BACKUP_STAGE_PREFIX)


def _write_backup_marker(
    backup: Path,
    files: dict[str, str],
    replacement: dict[str, str],
) -> None:
    marker = backup / BACKUP_MARKER
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{BACKUP_MARKER}.", dir=backup)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {"files": files, "replacement": replacement, "version": 2},
                stream,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(marker)
        _fsync_directory(backup)
    finally:
        if temporary.exists():
            temporary.unlink()


def _recover_interrupted_publication() -> None:
    """Finish or roll back the exact crash-visible directory-rename states."""
    retired = ROOT / RETIRED_DIST
    if not retired.exists() and not retired.is_symlink():
        return
    if retired.is_symlink() or not retired.is_dir():
        raise RuntimeError(f"refusing unexpected interrupted dist path: {retired}")

    backup = ROOT / ".release-artifact-backups" / "previous-dist"
    if backup.is_symlink() or not backup.is_dir():
        raise RuntimeError("cannot recover interrupted dist publication without its owned backup")
    old_manifest, replacement_manifest = _owned_backup_metadata(backup)
    if replacement_manifest is None or _dist_manifest(retired) != old_manifest:
        raise RuntimeError("interrupted dist publication does not match its owned backup")

    if DIST.is_symlink() or (DIST.exists() and not DIST.is_dir()):
        raise RuntimeError(f"refusing to recover over non-directory dist path: {DIST}")
    if DIST.exists():
        if _dist_manifest(DIST) != replacement_manifest:
            raise RuntimeError(
                "refusing to discard interrupted dist copy: published contents changed"
            )
        shutil.rmtree(retired)
        _fsync_directory(ROOT)
        print(f"completed interrupted dist publication recovery: {DIST.relative_to(ROOT)}")
        return

    retired.replace(DIST)
    _fsync_directory(ROOT)
    print(f"restored interrupted dist publication: {DIST.relative_to(ROOT)}")


def _only(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        names = ", ".join(path.name for path in matches) or "none"
        raise RuntimeError(f"expected one {pattern} artifact, found {names}")
    return matches[0]


def _publish(artifacts: tuple[Path, ...]) -> None:
    """Publish one canonical pair, preserving the old directory for recovery."""
    _cleanup_owned_staging()
    _recover_interrupted_publication()
    artifact_names = [artifact.name for artifact in artifacts]
    if len(artifact_names) != len(set(artifact_names)):
        raise RuntimeError("release artifacts must have unique filenames")
    invalid_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.is_symlink()
        or not artifact.is_file()
        or ARTIFACT_NAME.fullmatch(artifact.name) is None
    ]
    if invalid_artifacts:
        raise RuntimeError(
            f"release artifact is not a regular package file: {invalid_artifacts[0]}"
        )
    artifact_manifest = {artifact.name: _file_hash(artifact) for artifact in artifacts}

    if DIST.is_symlink() or (DIST.exists() and not DIST.is_dir()):
        raise RuntimeError(f"refusing to replace non-directory dist path: {DIST}")
    old_manifest = _dist_manifest(DIST) if DIST.exists() else None

    backup_root = ROOT / ".release-artifact-backups"
    staging = Path(tempfile.mkdtemp(prefix=DIST_STAGE_PREFIX, dir=ROOT))
    if os.name != "nt":
        staging.chmod(0o755)

    backup_staging: Path | None = None
    try:
        for artifact in artifacts:
            _copy_file_durable(artifact, staging / artifact.name)
        _fsync_directory(staging)
        if _dist_manifest(staging) != artifact_manifest:
            raise RuntimeError(
                "release artifact contents changed while copying into the publication staging area"
            )

        backup: Path | None = None
        retired: Path | None = None
        if old_manifest is not None:
            if backup_root.is_symlink() or (backup_root.exists() and not backup_root.is_dir()):
                raise RuntimeError(
                    f"refusing to use non-directory backup path: {backup_root.relative_to(ROOT)}"
                )
            backup_root_created = not backup_root.exists()
            backup_root.mkdir(exist_ok=True)
            if backup_root_created:
                _fsync_directory(ROOT)
            backup = backup_root / "previous-dist"
            if backup.exists() or backup.is_symlink():
                if backup.is_symlink() or not backup.is_dir():
                    raise RuntimeError(
                        f"refusing to replace unexpected backup path: {backup.relative_to(ROOT)}"
                    )
                _remove_owned_backup(backup)

            backup_staging = Path(tempfile.mkdtemp(prefix=BACKUP_STAGE_PREFIX, dir=backup_root))
            if os.name != "nt":
                backup_staging.chmod(0o755)
            for name in old_manifest:
                _copy_file_durable(DIST / name, backup_staging / name)
            _fsync_directory(backup_staging)
            if _dist_manifest(backup_staging) != old_manifest:
                raise RuntimeError("dist contents changed while creating the recovery copy")
            _write_backup_marker(backup_staging, old_manifest, artifact_manifest)
            backup_staging.replace(backup)
            backup_staging = None
            _fsync_directory(backup_root)
            _owned_backup_metadata(backup)

            if _dist_manifest(DIST) != old_manifest:
                raise RuntimeError("dist contents changed before publication")
            retired = ROOT / RETIRED_DIST
            if retired.exists() or retired.is_symlink():
                raise RuntimeError(f"interrupted dist path was not recovered: {retired}")
            DIST.replace(retired)
            _fsync_directory(ROOT)
        try:
            staging.replace(DIST)
            _fsync_directory(ROOT)
        except BaseException:
            if retired is not None and retired.is_dir() and not retired.is_symlink():
                if DIST.exists():
                    if _dist_manifest(DIST) != artifact_manifest:
                        raise RuntimeError(
                            "publication failed and the replacement dist changed before rollback"
                        )
                    shutil.rmtree(DIST)
                retired.replace(DIST)
                _fsync_directory(ROOT)
            raise

        if retired is not None:
            shutil.rmtree(retired)
            _fsync_directory(ROOT)

        for artifact in artifacts:
            print(f"wrote: {(DIST / artifact.name).relative_to(ROOT)}")
        if backup is not None:
            print(f"previous dist preserved at: {backup.relative_to(ROOT)}")
    finally:
        if staging.exists():
            shutil.rmtree(staging)
            _fsync_directory(ROOT)
        if backup_staging is not None and backup_staging.exists():
            shutil.rmtree(backup_staging)
            _fsync_directory(backup_root)


def _build_once(uv: str, output: Path) -> tuple[Path, Path]:
    output.mkdir()
    subprocess.run(
        [
            uv,
            "build",
            "--out-dir",
            str(output),
            str(ROOT),
            "--build-constraint",
            str(ROOT / "build-constraints.txt"),
            "--require-hashes",
        ],
        cwd=ROOT,
        check=True,
    )
    return _only(output, "*.whl"), _only(output, "*.tar.gz")


def _artifact_manifest(artifacts: tuple[Path, ...]) -> dict[str, str]:
    return {artifact.name: _file_hash(artifact) for artifact in artifacts}


@contextlib.contextmanager
def _release_lock() -> Iterator[None]:
    """Serialize full release builds so dist and its recovery copy cannot race."""
    path = ROOT / ".leika-release.lock"
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if not handle.read(1):
                handle.seek(0)
                handle.write(b"\0")
                handle.flush()
            while True:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.2)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@_release_lock()
def main() -> int:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "release packaging requires Python 3.10 or newer (Leika's supported floor)"
        )

    _cleanup_owned_staging()
    _recover_interrupted_publication()
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to build release artifacts")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "src/leika/_client_autobuild.py"),
            "--force",
            "--clean-install",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "sync_client_server.py"), "--check"],
        cwd=ROOT,
        check=True,
    )
    release_inputs = _release_input_manifest()
    with tempfile.TemporaryDirectory(prefix="leika-dist-") as temporary:
        output = Path(temporary)
        artifacts = _build_once(uv, output / "first")
        reproduction = _build_once(uv, output / "second")
        built_manifest = _artifact_manifest(artifacts)
        reproduced_manifest = _artifact_manifest(reproduction)
        if reproduced_manifest != built_manifest:
            changed = sorted(
                name
                for name in built_manifest.keys() | reproduced_manifest.keys()
                if built_manifest.get(name) != reproduced_manifest.get(name)
            )
            raise RuntimeError(
                "release builds are not byte-for-byte reproducible: " + ", ".join(changed)
            )
        for name, digest in sorted(built_manifest.items()):
            print(f"reproducible sha256: {digest}  {name}")
        wheel, sdist = artifacts
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_wheel.py"), str(wheel)], check=True
        )
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_sdist.py"), str(sdist)], check=True
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "twine",
                "check",
                "--strict",
                str(wheel),
                str(sdist),
            ],
            check=True,
        )
        if _artifact_manifest(artifacts) != built_manifest:
            raise RuntimeError(
                "release artifact contents changed while the validation gates were running"
            )

        changed_inputs = _changed_manifest_paths(release_inputs, _release_input_manifest())
        if changed_inputs:
            raise RuntimeError(
                "release inputs changed while the artifacts were being built: "
                + ", ".join(changed_inputs)
            )

        _publish(artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
