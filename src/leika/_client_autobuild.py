"""Build the browser client the server serves.

A source checkout rebuilds `client/build` whenever the client sources no
longer match the hash stamped by the last build. What a build *is* lives in
the client's `package.json`; this module only decides when to run it. An
installed wheel ships the build without its sources, so it never builds.

Imports nothing outside the standard library and nothing from `leika`, so the
Hatch build hook can load it from a bare source tree.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

client_dir = Path(__file__).resolve().parent / "client"
build_dir = client_dir / "build"
BUILD_OUTPUTS = ("index.html", "THIRD_PARTY_NOTICES.txt")

_source_stamp = build_dir / ".leika-sources"
_install_stamp = client_dir / "node_modules" / ".leika-install"
_lock_path = build_dir / ".leika-build.lock"

# Unused; infra/_http_server.py still imports it until its rewrite lands.
_BUILD_BACKUP_DIR_NAME = ".leika-build-backup"


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _source_hash() -> str:
    """Hash every file a build reads: the client tree minus `build` and `node_modules`."""
    digest = hashlib.sha256()
    for root, directories, names in os.walk(client_dir):
        if root == str(client_dir):
            directories[:] = [name for name in directories if name not in ("build", "node_modules")]
        directories.sort()
        for name in sorted(names):
            path = Path(root, name)
            digest.update(path.relative_to(client_dir).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def is_current() -> bool:
    """Whether `build/` holds every output, built from the sources beside it."""
    return all((build_dir / name).is_file() for name in BUILD_OUTPUTS) and (
        _read(_source_stamp) == _source_hash()
    )


@contextlib.contextmanager
def _build_lock() -> Iterator[None]:
    """Serialize builds across processes, such as parallel test workers."""
    build_dir.mkdir(exist_ok=True)
    with open(_lock_path, "w") as lock:
        if os.name == "posix":
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def build_client() -> None:
    """Build the client into `build/` unless it already matches its sources."""
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError(
            "Building the Leika client needs npm on PATH. Install Node.js 24 "
            "(see docs/development.md) and retry."
        )
    with _build_lock():
        # Re-checked under the lock: whoever held it may have just built this.
        if is_current():
            return
        source_hash = _source_hash()
        lock_hash = hashlib.sha256((client_dir / "package-lock.json").read_bytes()).hexdigest()
        if _read(_install_stamp) != lock_hash:
            subprocess.run([npm, "ci"], cwd=client_dir, check=True)
            _install_stamp.write_text(lock_hash, encoding="utf-8")
        with tempfile.TemporaryDirectory(dir=build_dir) as staging:
            # npm appends these arguments to the build script's final command, `vite build`.
            subprocess.run(
                [npm, "run", "build", "--", "--outDir", staging], cwd=client_dir, check=True
            )
            for name in BUILD_OUTPUTS:
                os.replace(Path(staging, name), build_dir / name)
        _source_stamp.write_text(source_hash, encoding="utf-8")


def ensure_client_is_built() -> None:
    """Build the client if this is a source checkout whose build is stale."""
    if (client_dir / "src").is_dir() and not is_current():
        print("(leika) Building the browser client...", file=sys.stderr)
        build_client()


if __name__ == "__main__":
    build_client()
