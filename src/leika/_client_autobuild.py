"""Build the browser client the server serves.

What a build *is* lives in the client's own `package.json`; this module is the
only thing that invokes it, so a client built by CI, by `make build-client`,
and by a script that found no build are the same artifact. Everything else
here exists to make that invocation reproducible from an arbitrary process:
Node is pinned by the client's `.nvmrc`, installs come from the lock file and
never rewrite it, and a stamp recording the hash of the sources a build came
from decides when to build again.

The stamp is also the commit marker. A build is written to a sibling staging
directory, validated and stamped there, then published by directory rename.
The prior complete generation remains available as a recoverable backup until
that rename succeeds, so neither a failed build nor an interrupted publication
destroys the bundle a running server is already serving.

Imports nothing outside the standard library and nothing from `leika`, so CI
can run it as a plain script before anything is installed.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterator, Optional, Tuple

client_dir = Path(__file__).resolve().parent / "client"
build_dir = client_dir / "build"
_autobuild_source_path = Path(__file__).resolve()

_stamp_path = build_dir / ".leika-sources"
_install_stamp_path = client_dir / "node_modules" / ".leika-install"
_lock_path = client_dir / ".leika-build.lock"

# Directory names used for transactional build publication. The HTTP server
# knows the backup name so requests already in flight can finish across the
# brief old-generation -> new-generation directory rename.
_BUILD_STAGE_PREFIX = ".leika-build-stage-"
_BUILD_BACKUP_DIR_NAME = ".leika-build-backup"
_SNAPSHOT_TRANSACTION_CONTENT = "leika-client-snapshot-v1\n"
_UNSTAMPED_SNAPSHOT_TRANSACTION_CONTENT = "leika-client-snapshot-unstamped-v1\n"

# Directories under the client that a build writes rather than reads.
_NOT_SOURCES = {
    "build",
    "node_modules",
    ".nodeenv",
    "__pycache__",
    _BUILD_BACKUP_DIR_NAME,
}

_CLIENT_INDEX_MIN_BYTES = 10_000
_THIRD_PARTY_NOTICES_MIN_BYTES = 20_000
_REQUIRED_BUILD_OUTPUTS = (
    ("index.html", _CLIENT_INDEX_MIN_BYTES),
    ("THIRD_PARTY_NOTICES.txt", _THIRD_PARTY_NOTICES_MIN_BYTES),
)


def _node_version() -> str:
    """The one pinned Node version, shared with CI's `setup-node`.

    Lives beside `package.json` rather than at the repository root so that it
    travels with the client sources into an sdist, where the root is gone but a
    build may still have to happen.
    """
    nvmrc = client_dir / ".nvmrc"
    if not nvmrc.exists():
        raise RuntimeError(
            f"Cannot build the Leika client: {nvmrc} is missing, so there is no "
            "pinned Node version to build with."
        )
    return nvmrc.read_text(encoding="utf-8").strip()


def _source_files() -> Iterator[Path]:
    """Every file a build reads: the client tree, minus what a build writes."""
    stack = [client_dir]
    while stack:
        for entry in sorted(stack.pop().iterdir()):
            generated_name = entry.name in _NOT_SOURCES or entry.name.startswith(
                _BUILD_STAGE_PREFIX
            )
            if entry.is_symlink():
                if generated_name:
                    continue
                raise RuntimeError(
                    f"Client build inputs must not be symlinks: {entry.relative_to(client_dir)}."
                )
            if entry.is_dir():
                if not generated_name:
                    stack.append(entry)
            elif entry.is_file() and entry != _lock_path:
                yield entry


def _source_hash() -> str:
    """Hash every build input so copied and cache-restored trees stay deterministic."""
    digest = hashlib.sha256()
    inputs = [
        (f"client/{path.relative_to(client_dir).as_posix()}", path)
        for path in sorted(_source_files())
    ]
    # This module defines the npm/Vite invocation and publication format. A
    # change to those semantics must invalidate a bundle even though the file
    # sits next to, rather than inside, the client source directory.
    inputs.append(("builder/_client_autobuild.py", _autobuild_source_path))
    for name, path in sorted(inputs):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Client build input is not a regular file: {path}.")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _read_stamp(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_stamp(path: Path, value: str) -> None:
    """Atomically replace and durably publish one small build-control stamp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _invalid_build_output(directory: Path | None = None) -> Path | None:
    """Return the first missing/truncated required output, if any."""
    directory = build_dir if directory is None else directory
    for name, minimum_bytes in _REQUIRED_BUILD_OUTPUTS:
        output = directory / name
        try:
            if output.is_symlink() or not output.is_file() or output.stat().st_size < minimum_bytes:
                return output
        except OSError:
            return output
    return None


def _is_current() -> bool:
    return _is_complete_generation(build_dir) and _read_stamp(_stamp_path) == _source_hash()


def _generation_stamp_path(directory: Path) -> Path:
    return directory / _stamp_path.name


def _has_generation_stamp(directory: Path) -> bool:
    path = _generation_stamp_path(directory)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size != 64:
            return False
    except OSError:
        return False
    stamp = _read_stamp(path)
    return (
        stamp is not None
        and len(stamp) == 64
        and all(character in "0123456789abcdef" for character in stamp)
    )


def _is_complete_generation(directory: Path) -> bool:
    return _invalid_generation_tree(directory, stamped=True) is None


def _invalid_generation_tree(directory: Path, *, stamped: bool) -> Path | None:
    """Validate the exact portable file set a generated bundle may contain."""
    if directory.is_symlink() or not directory.is_dir():
        return directory
    expected = {name for name, _ in _REQUIRED_BUILD_OUTPUTS}
    if stamped:
        expected.add(_stamp_path.name)
    try:
        entries = list(directory.iterdir())
    except OSError:
        return directory
    for entry in entries:
        if entry.name not in expected or entry.is_symlink() or not entry.is_file():
            return entry
    for name in sorted(expected):
        if not (directory / name).exists():
            return directory / name
    invalid_output = _invalid_build_output(directory)
    if invalid_output is not None:
        return invalid_output
    if stamped and not _has_generation_stamp(directory):
        return _generation_stamp_path(directory)
    return None


def _build_backup_dir() -> Path:
    return build_dir.with_name(_BUILD_BACKUP_DIR_NAME)


def _remove_owned_tree(path: Path) -> None:
    """Remove one exact internal tree without ever following a symlink."""
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        if not path.is_dir():
            raise RuntimeError(f"Refusing to remove unexpected build path: {path}.")
        shutil.rmtree(path)


def _normalize_published_directory_mode(path: Path) -> None:
    """Make a tempfile-backed generation traversable after publication."""
    if os.name != "nt":
        path.chmod(0o755)


def _fsync_directory(directory: Path) -> None:
    """Persist directory-entry changes where the platform exposes that API.

    POSIX requires the containing directory itself to be synced after a
    create, unlink, or rename. Python's Windows runtime cannot open directory
    handles for ``os.fsync``; file contents are still flushed, and the
    transaction marker/backup retains process-crash recovery there.
    """
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    unsupported = {
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    try:
        descriptor = os.open(directory, flags)
    except OSError as error:
        if error.errno in unsupported:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def _fsync_tree(directory: Path) -> None:
    """Flush a completed generation before publishing its directory entry."""
    directories: list[Path] = []
    for root, _, filenames in os.walk(directory):
        root_path = Path(root)
        directories.append(root_path)
        for filename in filenames:
            path = root_path / filename
            if path.is_symlink():
                continue
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    for path in reversed(directories):
        _fsync_directory(path)


def _remove_owned_tree_durable(path: Path) -> None:
    """Remove a transaction-owned top-level tree and persist that removal."""
    existed = path.exists() or path.is_symlink()
    _remove_owned_tree(path)
    if existed:
        _fsync_directory(path.parent)


def _cleanup_staged_builds() -> None:
    for path in build_dir.parent.iterdir():
        if path.name.startswith(_BUILD_STAGE_PREFIX):
            _remove_owned_tree_durable(path)


def _recover_interrupted_publication() -> None:
    """Finish or roll back the only two crash-visible rename states."""
    backup = _build_backup_dir()
    if not backup.exists() and not backup.is_symlink():
        return
    if not _is_complete_generation(backup):
        raise RuntimeError(
            "Refusing to replace an unexpected client-build backup at "
            f"{backup}. Move it aside and retry."
        )

    if not build_dir.exists() and not build_dir.is_symlink():
        os.replace(backup, build_dir)
        _fsync_directory(build_dir.parent)
        return

    if _is_complete_generation(build_dir):
        # The new generation was published and only backup cleanup was
        # interrupted. It is safe to retain the committed live generation.
        _remove_owned_tree_durable(backup)
        return

    if build_dir.is_symlink() or not build_dir.is_dir():
        raise RuntimeError(f"Refusing to replace unexpected client build path: {build_dir}.")
    _remove_owned_tree_durable(build_dir)
    os.replace(backup, build_dir)
    _fsync_directory(build_dir.parent)


def _publish_staged_build(staging: Path) -> None:
    """Atomically replace the live build, rolling back on any rename failure."""
    if not _is_complete_generation(staging):
        raise RuntimeError(f"Refusing to publish incomplete client build: {staging}.")
    _fsync_tree(staging)
    backup = _build_backup_dir()
    if backup.exists() or backup.is_symlink():
        raise RuntimeError(f"Client-build backup was not recovered: {backup}.")

    live_path_exists = build_dir.exists() or build_dir.is_symlink()
    if live_path_exists:
        if not build_dir.is_dir() or build_dir.is_symlink():
            raise RuntimeError(f"Refusing to replace unexpected client build path: {build_dir}.")
    had_live_build = live_path_exists and _is_complete_generation(build_dir)
    if had_live_build:
        # A generation built by an older Leika may predate explicit fsyncs.
        # Make the rollback copy durable before changing its directory entry.
        _fsync_tree(build_dir)
        os.replace(build_dir, backup)
        try:
            _fsync_directory(build_dir.parent)
        except BaseException:
            os.replace(backup, build_dir)
            _fsync_directory(build_dir.parent)
            raise
    elif live_path_exists:
        # Only a committed generation belongs in the crash-recovery slot. An
        # incomplete directory was never safe to serve and cannot be mistaken
        # for a recoverable generation after an interrupted rename.
        _remove_owned_tree_durable(build_dir)
    try:
        os.replace(staging, build_dir)
    except BaseException as publish_error:
        if had_live_build:
            try:
                os.replace(backup, build_dir)
                _fsync_directory(build_dir.parent)
            except BaseException as rollback_error:
                raise RuntimeError(
                    "Publishing the client build failed and its prior generation "
                    f"could not be restored. The recoverable copy remains at {backup}: "
                    f"{rollback_error}."
                ) from publish_error
        raise
    else:
        _fsync_directory(build_dir.parent)
        if had_live_build:
            try:
                _remove_owned_tree_durable(backup)
            except OSError:
                # A Windows HTTP reader can briefly keep the renamed tree open.
                # The next locked build call recognizes and removes this valid
                # backup; the committed live generation is already complete.
                pass


def _snapshot_stage_prefix(out_dir: Path) -> str:
    return f".{out_dir.name}.leika-stage-"


def _snapshot_backup_dir(out_dir: Path) -> Path:
    return out_dir.with_name(f".{out_dir.name}.leika-backup")


def _snapshot_transaction_path(out_dir: Path) -> Path:
    return out_dir.with_name(f".{out_dir.name}.leika-transaction")


def _snapshot_export_lock_path(out_dir: Path) -> Path:
    """Return a stable lock outside a potentially read-only installation.

    A wheel has no client sources and its bundled build commonly lives in a
    read-only site-packages directory. Exporting that build still needs to
    serialize callers targeting the same output, but must not create the
    checkout's ``.leika-build.lock`` beside the bundled files.
    """
    canonical_output = os.path.normcase(str(out_dir.resolve()))
    digest = hashlib.sha256(os.fsencode(canonical_output)).hexdigest()
    return Path(tempfile.gettempdir()) / f"leika-client-snapshot-{digest}.lock"


def _path_is_within(path: Path, parent: Path) -> bool:
    return path.is_relative_to(parent)


def _recover_snapshot_publication(out_dir: Path, *, stamped: bool = True) -> None:
    """Recover the deterministic old-output -> new-snapshot transaction."""
    backup = _snapshot_backup_dir(out_dir)
    transaction = _snapshot_transaction_path(out_dir)
    backup_exists = backup.exists() or backup.is_symlink()
    transaction_exists = transaction.exists() or transaction.is_symlink()

    if backup_exists and not transaction_exists:
        raise RuntimeError(f"Refusing to replace unexpected snapshot backup: {backup}.")
    if not transaction_exists:
        return
    expected_transaction = (
        _SNAPSHOT_TRANSACTION_CONTENT if stamped else _UNSTAMPED_SNAPSHOT_TRANSACTION_CONTENT
    ).strip()
    if (
        transaction.is_symlink()
        or not transaction.is_file()
        or _read_stamp(transaction) != expected_transaction
    ):
        raise RuntimeError(f"Refusing to recover unexpected snapshot transaction: {transaction}.")
    if backup_exists and (backup.is_symlink() or not backup.is_dir()):
        raise RuntimeError(f"Refusing to recover unexpected snapshot backup: {backup}.")

    output_exists = out_dir.exists() or out_dir.is_symlink()
    if backup_exists:
        if not output_exists:
            os.replace(backup, out_dir)
            _fsync_directory(out_dir.parent)
        elif _invalid_generation_tree(out_dir, stamped=stamped) is None:
            # The new snapshot was committed; only old-output cleanup was
            # interrupted.
            _remove_owned_tree_durable(backup)
        else:
            if out_dir.is_symlink() or not out_dir.is_dir():
                raise RuntimeError(f"Refusing to replace unexpected output path: {out_dir}.")
            _remove_owned_tree_durable(out_dir)
            os.replace(backup, out_dir)
            _fsync_directory(out_dir.parent)
    transaction.unlink()
    _fsync_directory(transaction.parent)


def _cleanup_snapshot_staging(out_dir: Path) -> None:
    prefix = _snapshot_stage_prefix(out_dir)
    for path in out_dir.parent.iterdir():
        if path.name.startswith(prefix):
            _remove_owned_tree_durable(path)


def _copy_build_snapshot(
    out_dir: Path,
    *,
    source_dir: Path | None = None,
    stamped: bool = True,
) -> None:
    """Publish an exact, rollback-safe copy of the locked live generation."""
    source_dir = build_dir if source_dir is None else source_dir
    resolved_output = out_dir.resolve()
    resolved_client = client_dir.resolve()
    if (
        resolved_output == Path(resolved_output.anchor)
        or _path_is_within(resolved_output, resolved_client)
        or _path_is_within(resolved_client, resolved_output)
    ):
        raise RuntimeError(
            "Client snapshot output must be a separate directory outside the "
            f"client source tree, not {out_dir}."
        )
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    _recover_snapshot_publication(out_dir, stamped=stamped)
    _cleanup_snapshot_staging(out_dir)
    staging = Path(tempfile.mkdtemp(prefix=_snapshot_stage_prefix(out_dir), dir=out_dir.parent))
    backup = _snapshot_backup_dir(out_dir)
    transaction = _snapshot_transaction_path(out_dir)
    try:
        # `staging` is freshly created and empty; copying into it cannot retain
        # stale files from an earlier caller-owned output directory.
        shutil.copytree(source_dir, staging, dirs_exist_ok=True)
        invalid_output = _invalid_generation_tree(staging, stamped=stamped)
        if invalid_output is not None:
            raise RuntimeError(
                f"Cannot copy an incomplete client-build snapshot: {invalid_output}."
            )
        _normalize_published_directory_mode(staging)
        _fsync_tree(staging)

        had_output = out_dir.exists() or out_dir.is_symlink()
        if had_output:
            if not out_dir.is_dir() or out_dir.is_symlink():
                raise RuntimeError(f"Refusing to replace unexpected output path: {out_dir}.")
        if backup.exists() or backup.is_symlink():
            raise RuntimeError(f"Snapshot backup was not recovered: {backup}.")
        if transaction.exists() or transaction.is_symlink():
            raise RuntimeError(f"Snapshot transaction was not recovered: {transaction}.")
        if had_output:
            # The caller's prior snapshot can become the recovery generation,
            # so flush it before the durable marker says that backup exists.
            _fsync_tree(out_dir)
        transaction_content = (
            _SNAPSHOT_TRANSACTION_CONTENT if stamped else _UNSTAMPED_SNAPSHOT_TRANSACTION_CONTENT
        )
        with transaction.open("x", encoding="utf-8") as handle:
            handle.write(transaction_content)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(transaction.parent)
        if had_output:
            os.replace(out_dir, backup)
            try:
                _fsync_directory(out_dir.parent)
            except BaseException:
                os.replace(backup, out_dir)
                _fsync_directory(out_dir.parent)
                transaction.unlink()
                _fsync_directory(transaction.parent)
                raise
        try:
            os.replace(staging, out_dir)
        except BaseException as publish_error:
            if had_output:
                try:
                    os.replace(backup, out_dir)
                    _fsync_directory(out_dir.parent)
                except BaseException as rollback_error:
                    raise RuntimeError(
                        "Publishing the copied client snapshot failed and its prior "
                        f"output could not be restored. It remains at {backup}: "
                        f"{rollback_error}."
                    ) from publish_error
            try:
                transaction.unlink()
                _fsync_directory(transaction.parent)
            except OSError:
                # Recovery can remove the durable marker on the next call.
                pass
            raise
        else:
            _fsync_directory(out_dir.parent)
            if had_output:
                try:
                    _remove_owned_tree_durable(backup)
                except OSError:
                    # Leave the marker with the exact old copy; the next locked
                    # call recognizes that the committed output wins.
                    return
            try:
                transaction.unlink()
                _fsync_directory(transaction.parent)
            except OSError:
                # The committed output is complete. Recovery recognizes this
                # no-backup terminal state and removes the marker next time.
                pass
    finally:
        _remove_owned_tree_durable(staging)


@contextlib.contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Hold one advisory file lock until this context exits."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
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


@contextlib.contextmanager
def _build_lock() -> Iterator[None]:
    """Hold the sole right to build, so concurrent callers cannot race.

    The end-to-end suite runs under `pytest -n auto` and a Leika script may be
    started several times at once; without this they interleave `npm ci` and
    `nodeenv` in the same directories. The operating system releases the lock
    when a process exits, so an interrupted build cannot strand a stale lock.
    """
    with _file_lock(_lock_path):
        yield


def _nodeenv_bin_dir(env_dir: Path) -> Path:
    """On Windows, nodeenv installs to `Scripts` rather than `bin`."""
    candidate = env_dir / "bin"
    return candidate if candidate.exists() else env_dir / "Scripts"


def _installed_node_version(node: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            [str(node), "--version"], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return result.stdout.strip().lstrip("v") if result.returncode == 0 else None


def _resolve_node() -> Tuple[Path, Optional[Path]]:
    """Find the pinned Node, downloading it only if it is not already here.

    Returns its bin directory, and the nodeenv root when we installed it --
    nodeenv's shims need `NODE_VIRTUAL_ENV`, a system Node must not see it.

    Preferring a Node that is already present is what lets CI, `make
    build-client`, and a bare `python _client_autobuild.py` all take this one
    path: CI's `setup-node` has already put the pinned version on `PATH`, so
    this finds it instead of spending a download on a second copy.
    """
    version = _node_version()

    on_path = shutil.which("node")
    if on_path is not None and _installed_node_version(Path(on_path)) == version:
        path_bin = Path(on_path).resolve().parent
        if _npm(path_bin).exists():
            return path_bin, None

    env_dir = client_dir / ".nodeenv"
    bin_dir = _nodeenv_bin_dir(env_dir)
    if _read_stamp(env_dir / ".leika-node") == version and _npm(bin_dir).exists():
        return bin_dir, env_dir

    # A version change makes the old environment useless, and nodeenv will not
    # install over one that already exists.
    if env_dir.exists():
        shutil.rmtree(env_dir)
    result = subprocess.run(
        [sys.executable, "-m", "nodeenv", f"--node={version}", str(env_dir)], check=False
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to install Node {version} using nodeenv. To rebuild the Leika "
            "client, either put that Node version on your PATH or install nodeenv "
            "with: pip install 'nodeenv>=1.9.1'"
        )
    _write_stamp(env_dir / ".leika-node", version)
    return _nodeenv_bin_dir(env_dir), env_dir


def _npm(bin_dir: Path) -> Path:
    npm = bin_dir / "npm"
    return npm.with_suffix(".cmd") if sys.platform == "win32" else npm


def _node_env(bin_dir: Path, virtual_env: Optional[Path]) -> "dict[str, str]":
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    if virtual_env is not None:
        env["NODE_VIRTUAL_ENV"] = str(virtual_env)
    return env


def _install_dependencies(bin_dir: Path, env: "dict[str, str]", *, force: bool = False) -> None:
    """Run ``npm ci`` when inputs change, or unconditionally when forced."""
    inputs = (client_dir / "package.json", client_dir / "package-lock.json")
    missing = next((path for path in inputs if not path.exists()), None)
    if missing is not None:
        raise RuntimeError(f"Cannot build the Leika client: {missing} is missing.")

    digest = hashlib.sha256()
    for path in inputs:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    want = digest.hexdigest() + "-" + _node_version()
    if not force and _read_stamp(_install_stamp_path) == want:
        return
    _install_stamp_path.unlink(missing_ok=True)
    subprocess.run([str(_npm(bin_dir)), "ci"], env=env, cwd=client_dir, check=True)
    _write_stamp(_install_stamp_path, want)


def build_client(
    out_dir: Optional[Path] = None,
    *,
    force: bool = False,
    clean_install: bool = False,
) -> None:
    """Build the client, optionally forcing a clean dependency install.

    A source tree that changes while npm is building is deliberately left
    unpublished and reported. A later invocation can then retry from one
    stable snapshot while the prior complete generation remains live.
    """
    with _build_lock():
        _recover_interrupted_publication()
        _cleanup_staged_builds()
        # Re-checked under the lock: whoever held it may have just built this.
        if force or not _is_current():
            expected = _source_hash()
            bin_dir, virtual_env = _resolve_node()
            env = _node_env(bin_dir, virtual_env)
            _install_dependencies(bin_dir, env, force=clean_install)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=_BUILD_STAGE_PREFIX,
                    dir=build_dir.parent,
                )
            )
            try:
                # A failed build must fail HERE, leaving the complete live
                # generation untouched. npm appends these arguments to Vite
                # (the final command in the build script).
                subprocess.run(
                    [
                        str(_npm(bin_dir)),
                        "run",
                        "build",
                        "--",
                        "--outDir",
                        str(staging),
                        "--emptyOutDir",
                    ],
                    env=env,
                    cwd=client_dir,
                    check=True,
                )
                invalid_output = _invalid_generation_tree(staging, stamped=False)
                if invalid_output is not None:
                    raise RuntimeError(
                        "Client build completed without a complete required artifact: "
                        f"{invalid_output}."
                    )
                if _source_hash() != expected:
                    raise RuntimeError(
                        "Client sources changed while the build was running; output was "
                        "not published. Retry after the source tree is stable."
                    )
                _write_stamp(_generation_stamp_path(staging), expected)
                _normalize_published_directory_mode(staging)
                _publish_staged_build(staging)
            finally:
                _remove_owned_tree_durable(staging)

        # Keep the source generation immutable while it is copied. A merge
        # after releasing the build lock could mix a concurrent generation and
        # retain stale files in an existing destination.
        if out_dir is not None and out_dir.resolve() != build_dir.resolve():
            _copy_build_snapshot(out_dir)


def ensure_client_is_built(*, ignore_dev_server: bool = False) -> None:
    """Make sure `build/` holds a client built from the sources beside it.

    Args:
        ignore_dev_server: Build even while `npm run dev` is running. For
            callers served the BUILD rather than the dev server -- the
            end-to-end tests -- for which the usual skip means silently running
            against whatever was built last.
    """
    mode = os.environ.get("LEIKA_CLIENT_BUILD", "auto").strip().lower()
    if mode not in ("auto", "never", "always"):
        raise ValueError(f"LEIKA_CLIENT_BUILD is {mode!r}; expected 'auto', 'never', or 'always'.")
    if mode == "never":
        return

    if not (client_dir / "src").exists():
        # A wheel ships the build and leaves out the sources, so there is
        # nothing to build from and nothing that could have gone stale.
        if _invalid_generation_tree(build_dir, stamped=False) is not None:
            raise RuntimeError(
                "This Leika installation has no complete built browser client and no "
                "sources to rebuild it. Reinstall Leika from a wheel, or work from a "
                "source checkout."
            )
        return

    if mode == "auto":
        if not ignore_dev_server and _check_leika_dev_running():
            import rich

            rich.print(
                "[bold](leika)[/bold] The Leika viewer looks like it has been launched via"
                " `npm run dev`. Skipping build check..."
            )
            return
        if _is_current():
            return

    import rich

    rich.print("[bold](leika)[/bold] Building the Leika client...")
    build_client(force=mode == "always")


def _check_leika_dev_running() -> bool:
    """Returns True if the viewer client has been launched via `npm run dev`."""
    try:
        import psutil
    except ImportError:
        # Only development runs the dev server, and only development installs
        # psutil; without it, treat the dev server as absent.
        return False

    for process in psutil.process_iter():
        try:
            if Path(process.cwd()).resolve() != client_dir.resolve():
                continue
            cmdline = process.cmdline()
            # `vite --host` is the dev script; `vite build` is not.
            if (
                any("vite" in part for part in cmdline)
                and any("--host" in part for part in cmdline)
                and not any("build" in part for part in cmdline)
            ):
                return True
        except (psutil.AccessDenied, psutil.ZombieProcess, psutil.NoSuchProcess):
            pass
    return False


def build_client_entrypoint() -> None:
    """Build from a checkout, or validate/copy a wheel's bundled client."""
    parser = argparse.ArgumentParser(description="Build the Leika client.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Also copy the build here.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the build already matches the sources.",
    )
    parser.add_argument(
        "--clean-install",
        action="store_true",
        help="Run npm ci even when the dependency-install stamp matches.",
    )
    args = parser.parse_args()
    if not (client_dir / "src").exists():
        invalid = _invalid_generation_tree(build_dir, stamped=False)
        if invalid is not None:
            parser.error(
                "this installation has no complete bundled browser client and no "
                f"client sources to rebuild it (invalid or missing: {invalid})"
            )
        if args.force or args.clean_install:
            parser.error(
                "--force and --clean-install require client sources; this wheel "
                "contains only the prebuilt browser client"
            )
        if args.out_dir is not None and args.out_dir.resolve() != build_dir.resolve():
            with _file_lock(_snapshot_export_lock_path(args.out_dir)):
                _copy_build_snapshot(
                    args.out_dir,
                    source_dir=build_dir,
                    stamped=False,
                )
        return
    build_client(
        out_dir=args.out_dir,
        force=args.force,
        clean_install=args.clean_install,
    )


if __name__ == "__main__":
    build_client_entrypoint()
