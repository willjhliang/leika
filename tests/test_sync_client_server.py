from __future__ import annotations

import stat
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

import sync_client_server as sync


def test_write_or_check_replaces_generated_file_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "Generated.ts"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(0o640)
    original_replace = sync.os.replace
    observed_source: list[Path] = []
    synced: list[Path] = []

    def inspect_replace(source: Path, destination: Path) -> None:
        assert Path(destination) == target
        assert target.read_text(encoding="utf-8") == "old\n"
        temporary = Path(source)
        assert temporary.read_text(encoding="utf-8") == "new\n"
        observed_source.append(temporary)
        original_replace(source, destination)

    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync.os, "replace", inspect_replace)
    monkeypatch.setattr(sync, "_fsync_directory", synced.append)

    assert sync._write_or_check(target, "new\n", check=False)
    assert target.read_text(encoding="utf-8") == "new\n"
    if sync.os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert len(observed_source) == 1
    assert not observed_source[0].exists()
    assert synced == [tmp_path]


def test_new_generated_file_uses_portable_source_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "Generated.ts"
    monkeypatch.setattr(sync, "ROOT", tmp_path)

    assert sync._write_or_check(target, "new\n", check=False)

    if sync.os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_write_or_check_preserves_generated_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "Generated.ts"
    target.write_text("old\n", encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(sync, "ROOT", tmp_path)
    monkeypatch.setattr(sync.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        sync._write_or_check(target, "new\n", check=False)

    assert target.read_text(encoding="utf-8") == "old\n"
    assert {path.name for path in tmp_path.iterdir()} == {target.name}


def test_check_rejects_matching_symlink_and_non_regular_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.ts"
    source.write_text("current\n", encoding="utf-8")
    symlink = tmp_path / "Symlink.ts"
    try:
        symlink.symlink_to(source)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are not available to this test process")
    directory = tmp_path / "Directory.ts"
    directory.mkdir()
    monkeypatch.setattr(sync, "ROOT", tmp_path)

    assert not sync._write_or_check(symlink, "current\n", check=True)
    assert not sync._write_or_check(directory, "current\n", check=True)


def test_prettier_runtime_uses_pinned_node_environment(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    virtual_env = tmp_path / "nodeenv"
    prettier = tmp_path / "client/node_modules/.bin/prettier"
    prettier.parent.mkdir(parents=True)
    prettier.touch()
    expected_env = {"PATH": str(bin_dir)}
    monkeypatch.setattr(sync, "PRETTIER_PATH", prettier)
    monkeypatch.setattr(sync.client_autobuild, "_resolve_node", lambda: (bin_dir, virtual_env))
    monkeypatch.setattr(
        sync.client_autobuild,
        "_node_env",
        lambda resolved_bin, resolved_env: (
            expected_env if (resolved_bin, resolved_env) == (bin_dir, virtual_env) else {}
        ),
    )

    executable, env = sync._prettier_runtime()

    assert executable == prettier
    assert env is expected_env


def test_prettier_runtime_never_falls_back_to_npx(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(sync, "PRETTIER_PATH", tmp_path / "missing-prettier")
    monkeypatch.setattr(sync.client_autobuild, "_resolve_node", lambda: (bin_dir, None))

    with pytest.raises(RuntimeError, match="not installed from package-lock.json"):
        sync._prettier_runtime()


def test_format_source_invokes_resolved_prettier(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "Generated.ts"
    prettier = tmp_path / "prettier"
    env = {"PATH": str(tmp_path)}
    observed: dict[str, object] = {}

    def run(command, **kwargs):
        observed.update(command=command, kwargs=kwargs)
        return subprocess.CompletedProcess(command, 0, stdout="formatted\n", stderr="")

    monkeypatch.setattr(sync.subprocess, "run", run)

    assert sync._format_source(source, "raw", prettier=prettier, env=env) == "formatted\n"
    assert observed["command"] == [str(prettier), "--stdin-filepath", str(source)]
    kwargs = observed["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["cwd"] == sync.CLIENT_DIR
    assert kwargs["env"] is env
    assert kwargs["input"] == "raw"
    assert kwargs["check"] is True


def test_main_holds_client_build_lock_through_prettier_and_publication(monkeypatch) -> None:
    lock_held = False
    observed = []

    @contextmanager
    def build_lock():
        nonlocal lock_held
        assert not lock_held
        lock_held = True
        try:
            yield
        finally:
            lock_held = False

    def runtime():
        assert lock_held
        return Path("prettier"), {}

    def format_source(path, content, **_kwargs):
        assert lock_held
        observed.append(path)
        return content

    def write_or_check(*_args, **_kwargs):
        assert lock_held
        return True

    monkeypatch.setattr(sync.client_autobuild, "_build_lock", build_lock)
    monkeypatch.setattr(sync, "_prettier_runtime", runtime)
    monkeypatch.setattr(sync, "_format_source", format_source)
    monkeypatch.setattr(sync, "_write_or_check", write_or_check)
    monkeypatch.setattr(
        sync.argparse.ArgumentParser,
        "parse_args",
        lambda _self: sync.argparse.Namespace(messages=True, version=True, check=True),
    )

    assert sync.main() == 0
    assert observed == [sync.MESSAGES_PATH, sync.VERSION_PATH]
    assert not lock_held


def test_build_lock_cannot_observe_a_partial_generated_pair(monkeypatch) -> None:
    mutex = threading.Lock()
    first_published = threading.Event()
    allow_second = threading.Event()
    build_acquired = threading.Event()
    published: list[Path] = []
    errors: list[BaseException] = []

    @contextmanager
    def build_lock():
        with mutex:
            yield

    def write_or_check(path, _content, **_kwargs):
        assert mutex.locked()
        published.append(path)
        if len(published) == 1:
            first_published.set()
            assert allow_second.wait(1.0)
        return True

    def run_sync() -> None:
        try:
            assert sync.main() == 0
        except BaseException as error:
            errors.append(error)

    observed_after_build_lock: list[Path] = []

    def inspect_as_build() -> None:
        with build_lock():
            observed_after_build_lock.extend(published)
            build_acquired.set()

    monkeypatch.setattr(sync.client_autobuild, "_build_lock", build_lock)
    monkeypatch.setattr(sync, "_prettier_runtime", lambda: (Path("prettier"), {}))
    monkeypatch.setattr(sync, "_format_source", lambda _path, content, **_kwargs: content)
    monkeypatch.setattr(sync, "_write_or_check", write_or_check)
    monkeypatch.setattr(
        sync.argparse.ArgumentParser,
        "parse_args",
        lambda _self: sync.argparse.Namespace(messages=True, version=True, check=False),
    )

    sync_thread = threading.Thread(target=run_sync)
    sync_thread.start()
    assert first_published.wait(1.0)
    build_thread = threading.Thread(target=inspect_as_build)
    build_thread.start()
    assert not build_acquired.wait(0.1)
    allow_second.set()
    sync_thread.join(timeout=1.0)
    build_thread.join(timeout=1.0)

    assert not sync_thread.is_alive()
    assert not build_thread.is_alive()
    assert errors == []
    assert observed_after_build_lock == [sync.MESSAGES_PATH, sync.VERSION_PATH]
