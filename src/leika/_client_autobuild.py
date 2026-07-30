"""Build the browser client the server serves.

What a build *is* lives in the client's own `package.json`; this module is the
only thing that invokes it, so a client built by CI, by `make build-client`,
and by a script that found no build are the same artifact. Everything else
here exists to make that invocation reproducible from an arbitrary process:
Node is pinned by the client's `.nvmrc`, installs come from the lock file and
never rewrite it, and a stamp recording the hash of the sources a build came
from decides when to build again.

The stamp is also the commit marker. It is removed before a build and written
after, so a build that dies partway leaves no stamp and the next caller
rebuilds instead of serving a half-written bundle.

Imports nothing outside the standard library and nothing from `leika`, so CI
can run it as a plain script before anything is installed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator, Optional, Tuple

client_dir = Path(__file__).resolve().parent / "client"
build_dir = client_dir / "build"

_stamp_path = build_dir / ".leika-sources"
_install_stamp_path = client_dir / "node_modules" / ".leika-install"
_lock_path = client_dir / ".leika-build.lock"

# Directories under the client that a build writes rather than reads.
_NOT_SOURCES = {"build", "node_modules", ".nodeenv", "__pycache__"}

# How long to wait for another process's build before treating it as dead.
_LOCK_TIMEOUT_SECONDS = 900.0


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
            if entry.is_dir():
                if entry.name not in _NOT_SOURCES:
                    stack.append(entry)
            elif entry.is_file() and entry != _lock_path:
                yield entry


def _source_hash() -> str:
    """Identify a build by its inputs.

    The same question CI's cache key asks with `hashFiles`, asked the same way,
    so a build restored from that cache is recognized as current here too.
    Timestamps cannot answer it: the checkout, the cache restore, and pip all
    rewrite them, which is why the previous mtime comparison needed a
    ten-second fudge and still called a restored build stale.
    """
    digest = hashlib.sha256()
    for path in sorted(_source_files()):
        digest.update(path.relative_to(client_dir).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _read_stamp(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_stamp(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _is_current() -> bool:
    return (build_dir / "index.html").exists() and _read_stamp(_stamp_path) == _source_hash()


@contextlib.contextmanager
def _build_lock() -> Iterator[None]:
    """Hold the sole right to build, so concurrent callers wait rather than race.

    The end-to-end suite runs under `pytest -n auto` and a Leika script may be
    started several times at once; without this they interleave `npm ci` and
    `nodeenv` in the same directories.
    """
    _lock_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            handle = os.open(str(_lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                held_for = time.time() - _lock_path.stat().st_mtime
            except OSError:
                continue  # Released while we were looking at it.
            if held_for > _LOCK_TIMEOUT_SECONDS:
                # No build we would still want to wait for lasts this long, so
                # the holder is gone and left the lock behind.
                _lock_path.unlink(missing_ok=True)
                continue
            time.sleep(0.2)

    try:
        os.write(handle, str(os.getpid()).encode("utf-8"))
        os.close(handle)
        yield
    finally:
        _lock_path.unlink(missing_ok=True)


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
        return Path(on_path).resolve().parent, None

    env_dir = client_dir / ".nodeenv"
    bin_dir = _nodeenv_bin_dir(env_dir)
    if _read_stamp(env_dir / ".leika-node") == version and (bin_dir / "npm").exists():
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


def _install_dependencies(bin_dir: Path, env: "dict[str, str]") -> None:
    """Install exactly what the lock file says, and only when it has changed.

    `npm ci`, never `npm install`: a build must not rewrite the lock file it
    built from. That is how a lock file comes to describe one developer's
    platform and fail everywhere else.
    """
    lock_file = client_dir / "package-lock.json"
    if not lock_file.exists():
        raise RuntimeError(f"Cannot build the Leika client: {lock_file} is missing.")

    want = hashlib.sha256(lock_file.read_bytes()).hexdigest() + "-" + _node_version()
    if _read_stamp(_install_stamp_path) == want:
        return
    subprocess.run([str(_npm(bin_dir)), "ci"], env=env, cwd=client_dir, check=True)
    _write_stamp(_install_stamp_path, want)


def build_client(out_dir: Optional[Path] = None, *, force: bool = False) -> None:
    """Build the client into `build/`, then copy it to `out_dir` if one is given."""
    with _build_lock():
        # Re-checked under the lock: whoever held it may have just built this.
        if force or not _is_current():
            expected = _source_hash()
            bin_dir, virtual_env = _resolve_node()
            env = _node_env(bin_dir, virtual_env)
            _install_dependencies(bin_dir, env)
            _stamp_path.unlink(missing_ok=True)
            # A failed build must fail HERE, or the server quietly serves
            # whatever was built last.
            subprocess.run(
                [str(_npm(bin_dir)), "run", "build"], env=env, cwd=client_dir, check=True
            )
            _write_stamp(_stamp_path, expected)

    if out_dir is not None and out_dir.resolve() != build_dir.resolve():
        shutil.copytree(build_dir, out_dir, dirs_exist_ok=True)


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
        if not (build_dir / "index.html").exists():
            raise RuntimeError(
                "This Leika installation has neither a built browser client nor the "
                "sources to build one. Reinstall Leika from a wheel, or work from a "
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
    """Build the Leika client entrypoint, which is used to launch the viewer."""
    parser = argparse.ArgumentParser(description="Build the Leika client.")
    parser.add_argument("--out-dir", type=Path, default=None, help="Also copy the build here.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the build already matches the sources.",
    )
    args = parser.parse_args()
    build_client(out_dir=args.out_dir, force=args.force)


if __name__ == "__main__":
    build_client_entrypoint()
