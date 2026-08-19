from __future__ import annotations

import contextlib
import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import leika._client_autobuild as autobuild


def test_build_lock_ignores_stale_file_contents(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lock_path = tmp_path / ".leika-build.lock"
    lock_path.write_text("interrupted process", encoding="utf-8")
    monkeypatch.setattr(autobuild, "_lock_path", lock_path)

    with autobuild._build_lock():
        assert lock_path.is_file()


def test_build_lock_serializes_threads(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(autobuild, "_lock_path", tmp_path / ".leika-build.lock")
    attempting = threading.Event()
    acquired = threading.Event()

    def contend() -> None:
        attempting.set()
        with autobuild._build_lock():
            acquired.set()

    with autobuild._build_lock():
        thread = threading.Thread(target=contend)
        thread.start()
        assert attempting.wait(1.0)
        assert not acquired.wait(0.1)

    assert acquired.wait(1.0)
    thread.join(timeout=1.0)
    assert not thread.is_alive()


def _configure_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    client = tmp_path / "client"
    build = client / "build"
    client.mkdir()
    (client / ".nvmrc").write_text("20.0.0")
    (client / "package.json").write_text("{}")
    (client / "package-lock.json").write_text("{}")
    monkeypatch.setattr(autobuild, "client_dir", client)
    monkeypatch.setattr(autobuild, "build_dir", build)
    monkeypatch.setattr(autobuild, "_stamp_path", build / ".leika-sources")
    monkeypatch.setattr(autobuild, "_install_stamp_path", client / "node_modules/.leika-install")
    monkeypatch.setattr(autobuild, "_lock_path", client / ".leika-build.lock")
    return client, build


def _write_complete_outputs(build: Path) -> None:
    build.mkdir(parents=True, exist_ok=True)
    (build / "index.html").write_bytes(b"i" * autobuild._CLIENT_INDEX_MIN_BYTES)
    (build / "THIRD_PARTY_NOTICES.txt").write_bytes(b"n" * autobuild._THIRD_PARTY_NOTICES_MIN_BYTES)


def _vite_output(command: list[str]) -> Path:
    return Path(command[command.index("--outDir") + 1])


def _configure_fake_build_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "npm").write_text("")
    monkeypatch.setattr(autobuild, "_build_lock", contextlib.nullcontext)
    monkeypatch.setattr(autobuild, "_resolve_node", lambda: (bin_dir, None))
    monkeypatch.setattr(autobuild, "_install_dependencies", lambda *_, **__: None)
    return bin_dir


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("index.html", None),
        ("index.html", 0),
        ("index.html", autobuild._CLIENT_INDEX_MIN_BYTES - 1),
        ("THIRD_PARTY_NOTICES.txt", None),
        ("THIRD_PARTY_NOTICES.txt", 0),
        (
            "THIRD_PARTY_NOTICES.txt",
            autobuild._THIRD_PARTY_NOTICES_MIN_BYTES - 1,
        ),
    ],
)
def test_current_build_rejects_missing_empty_and_truncated_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    size: int | None,
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    output = build / name
    if size is None:
        output.unlink()
    else:
        output.write_bytes(b"x" * size)
    autobuild._write_stamp(autobuild._stamp_path, autobuild._source_hash())

    assert not autobuild._is_current()
    assert autobuild._invalid_build_output() == output


def test_complete_outputs_and_matching_source_stamp_are_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, autobuild._source_hash())
    assert autobuild._is_current()


def test_builder_source_changes_invalidate_a_stamped_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    builder = tmp_path / "_client_autobuild.py"
    builder.write_text("first", encoding="utf-8")
    monkeypatch.setattr(autobuild, "_autobuild_source_path", builder)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, autobuild._source_hash())
    assert autobuild._is_current()

    builder.write_text("second", encoding="utf-8")
    assert not autobuild._is_current()


@pytest.mark.parametrize("target_kind", ["file", "directory"])
def test_source_hash_rejects_symlink_inputs_without_following_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    client, _ = _configure_tree(tmp_path, monkeypatch)
    target = tmp_path / "outside"
    if target_kind == "directory":
        target.mkdir()
        (target / "outside.ts").write_text("outside", encoding="utf-8")
    else:
        target.write_text("outside", encoding="utf-8")
    link = client / "linked-source"
    try:
        link.symlink_to(target, target_is_directory=target_kind == "directory")
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are not available to this test process")

    with pytest.raises(RuntimeError, match="build inputs must not be symlinks"):
        autobuild._source_hash()


def test_stamp_replacement_failure_preserves_prior_complete_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stamp = tmp_path / ".leika-sources"
    stamp.write_text("old", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("simulated stamp replacement failure")

    monkeypatch.setattr(autobuild.os, "replace", fail_replace)
    with pytest.raises(OSError, match="stamp replacement failure"):
        autobuild._write_stamp(stamp, "new")

    assert stamp.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [stamp]


@pytest.mark.parametrize("extra_kind", ["file", "directory"])
def test_complete_generation_rejects_unexpected_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_kind: str,
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, "a" * 64)
    extra = build / "unexpected"
    if extra_kind == "directory":
        extra.mkdir()
    else:
        extra.write_text("debris", encoding="utf-8")

    assert not autobuild._is_complete_generation(build)


def test_complete_generation_rejects_symlinks_and_special_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, "a" * 64)
    unexpected = build / "unexpected"
    try:
        unexpected.symlink_to(build / "index.html")
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are not available to this test process")
    assert not autobuild._is_complete_generation(build)

    unexpected.unlink()
    if not hasattr(os, "mkfifo"):
        return
    os.mkfifo(unexpected)
    assert not autobuild._is_complete_generation(build)


def test_install_digest_distinguishes_file_boundaries_and_stamps_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _configure_tree(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text("")
    calls: list[list[str]] = []

    def succeed(command, **kwargs):
        del kwargs
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", succeed)
    (client / "package.json").write_bytes(b"a")
    (client / "package-lock.json").write_bytes(b"bc")
    autobuild._install_dependencies(bin_dir, {})
    first_stamp = autobuild._read_stamp(autobuild._install_stamp_path)
    assert first_stamp is not None

    # The raw concatenation remains b"abc", but the structured filename +
    # per-file hashes must invalidate the install.
    (client / "package.json").write_bytes(b"ab")
    (client / "package-lock.json").write_bytes(b"c")
    autobuild._install_dependencies(bin_dir, {})
    assert len(calls) == 2
    assert autobuild._read_stamp(autobuild._install_stamp_path) != first_stamp


def test_failed_npm_ci_never_writes_install_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _ = _configure_tree(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "npm").write_text("")

    def fail(*args, **kwargs):
        del args, kwargs
        raise subprocess.CalledProcessError(1, ["npm", "ci"])

    monkeypatch.setattr(autobuild.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        autobuild._install_dependencies(bin_dir, {})
    assert not autobuild._install_stamp_path.exists()


def test_build_does_not_stamp_truncated_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _configure_fake_build_runtime(tmp_path, monkeypatch)

    def run(command, **kwargs):
        del kwargs
        if "--outDir" in command:
            staging = _vite_output(command)
            (staging / "index.html").write_bytes(b"tiny")
            (staging / "THIRD_PARTY_NOTICES.txt").write_bytes(b"tiny")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="complete required artifact"):
        autobuild.build_client(force=True)
    assert not autobuild._stamp_path.exists()
    assert not build.exists()
    assert not list(build.parent.glob(f"{autobuild._BUILD_STAGE_PREFIX}*"))


def test_build_does_not_publish_unexpected_vite_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _configure_fake_build_runtime(tmp_path, monkeypatch)

    def run(command, **kwargs):
        del kwargs
        if "--outDir" in command:
            staging = _vite_output(command)
            _write_complete_outputs(staging)
            (staging / "unexpected.js").write_text("debris", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="complete required artifact.*unexpected.js"):
        autobuild.build_client(force=True)
    assert not build.exists()
    assert not list(build.parent.glob(f"{autobuild._BUILD_STAGE_PREFIX}*"))


def test_failed_build_preserves_the_complete_live_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    old_index = b"o" * autobuild._CLIENT_INDEX_MIN_BYTES
    (build / "index.html").write_bytes(old_index)
    old_stamp = autobuild._source_hash()
    autobuild._write_stamp(autobuild._stamp_path, old_stamp)
    _configure_fake_build_runtime(tmp_path, monkeypatch)

    def fail(command, **kwargs):
        del kwargs
        if "--outDir" in command:
            staging = _vite_output(command)
            (staging / "index.html").write_bytes(b"partial")
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        autobuild.build_client(force=True)

    assert (build / "index.html").read_bytes() == old_index
    assert autobuild._read_stamp(autobuild._stamp_path) == old_stamp
    assert not autobuild._build_backup_dir().exists()
    assert not list(build.parent.glob(f"{autobuild._BUILD_STAGE_PREFIX}*"))


def test_successful_build_atomically_replaces_the_old_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    (build / "old-only.js").write_text("stale")
    autobuild._write_stamp(autobuild._stamp_path, autobuild._source_hash())
    _configure_fake_build_runtime(tmp_path, monkeypatch)
    new_index = b"2" * autobuild._CLIENT_INDEX_MIN_BYTES

    def succeed(command, **kwargs):
        del kwargs
        if "--outDir" in command:
            staging = _vite_output(command)
            _write_complete_outputs(staging)
            (staging / "index.html").write_bytes(new_index)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", succeed)
    autobuild.build_client(force=True)

    assert (build / "index.html").read_bytes() == new_index
    assert not (build / "old-only.js").exists()
    assert autobuild._is_current()
    assert not autobuild._build_backup_dir().exists()
    assert not list(build.parent.glob(f"{autobuild._BUILD_STAGE_PREFIX}*"))


def test_live_publication_flushes_payload_and_each_parent_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, "1" * 64)
    staging = build.with_name(f"{autobuild._BUILD_STAGE_PREFIX}durability")
    _write_complete_outputs(staging)
    autobuild._write_stamp(staging / ".leika-sources", "2" * 64)
    events: list[str] = []
    replace = autobuild.os.replace

    def observed_replace(source: Path, destination: Path) -> None:
        source = Path(source)
        destination = Path(destination)
        events.append(f"replace:{source.name}->{destination.name}")
        replace(source, destination)

    monkeypatch.setattr(autobuild.os, "replace", observed_replace)
    monkeypatch.setattr(
        autobuild,
        "_fsync_tree",
        lambda path: events.append(f"tree:{path.name}"),
    )
    monkeypatch.setattr(
        autobuild,
        "_fsync_directory",
        lambda path: events.append(f"directory:{path.name}"),
    )

    autobuild._publish_staged_build(staging)

    assert events == [
        f"tree:{staging.name}",
        f"tree:{build.name}",
        f"replace:{build.name}->{autobuild._BUILD_BACKUP_DIR_NAME}",
        f"directory:{build.parent.name}",
        f"replace:{staging.name}->{build.name}",
        f"directory:{build.parent.name}",
        f"directory:{build.parent.name}",
    ]
    assert autobuild._read_stamp(autobuild._stamp_path) == "2" * 64


def test_successful_build_replaces_an_incomplete_live_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    build.mkdir()
    (build / "partial.js").write_text("not a committed generation")
    _configure_fake_build_runtime(tmp_path, monkeypatch)

    def succeed(command, **kwargs):
        del kwargs
        if "--outDir" in command:
            _write_complete_outputs(_vite_output(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", succeed)
    autobuild.build_client(force=True)

    assert autobuild._is_current()
    assert not (build / "partial.js").exists()
    assert not autobuild._build_backup_dir().exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permission semantics")
def test_published_build_is_traversable_after_tempfile_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _configure_fake_build_runtime(tmp_path, monkeypatch)

    def succeed(command, **kwargs):
        del kwargs
        if "--outDir" in command:
            _write_complete_outputs(_vite_output(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", succeed)
    autobuild.build_client(force=True)

    assert build.stat().st_mode & 0o777 == 0o755


def test_publish_rename_failure_rolls_back_to_the_old_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    old_index = b"o" * autobuild._CLIENT_INDEX_MIN_BYTES
    (build / "index.html").write_bytes(old_index)
    old_stamp = autobuild._source_hash()
    autobuild._write_stamp(autobuild._stamp_path, old_stamp)
    _configure_fake_build_runtime(tmp_path, monkeypatch)

    def build_outputs(command, **kwargs):
        del kwargs
        if "--outDir" in command:
            _write_complete_outputs(_vite_output(command))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", build_outputs)
    replace = autobuild.os.replace

    def fail_new_generation(source, destination):
        source = Path(source)
        destination = Path(destination)
        if source.name.startswith(autobuild._BUILD_STAGE_PREFIX) and destination == build:
            raise OSError("simulated publication failure")
        replace(source, destination)

    monkeypatch.setattr(autobuild.os, "replace", fail_new_generation)
    with pytest.raises(OSError, match="publication failure"):
        autobuild.build_client(force=True)

    assert (build / "index.html").read_bytes() == old_index
    assert autobuild._read_stamp(autobuild._stamp_path) == old_stamp
    assert not autobuild._build_backup_dir().exists()


def test_interrupted_publication_restores_or_finishes_a_complete_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, "1" * 64)
    backup = autobuild._build_backup_dir()
    autobuild.os.replace(build, backup)

    autobuild._recover_interrupted_publication()
    assert build.is_dir()
    assert not backup.exists()

    autobuild.os.replace(build, backup)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, "2" * 64)
    autobuild._recover_interrupted_publication()
    assert autobuild._read_stamp(autobuild._stamp_path) == "2" * 64
    assert not backup.exists()


def test_windows_nodeenv_cache_uses_npm_cmd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _configure_tree(tmp_path, monkeypatch)
    env = client / ".nodeenv"
    scripts = env / "Scripts"
    scripts.mkdir(parents=True)
    (env / ".leika-node").write_text("20.0.0")
    (scripts / "npm.cmd").write_text("")
    monkeypatch.setattr(autobuild.sys, "platform", "win32")
    monkeypatch.setattr(autobuild.shutil, "which", lambda _: None)

    assert autobuild._resolve_node() == (scripts, env)


def test_matching_path_node_without_sibling_npm_falls_back_to_nodeenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = _configure_tree(tmp_path, monkeypatch)
    path_bin = tmp_path / "path-bin"
    path_bin.mkdir()
    node = path_bin / "node"
    node.write_text("")
    env = client / ".nodeenv"
    if autobuild.sys.platform == "win32":
        env_bin, npm_name = env / "Scripts", "npm.cmd"
    else:
        env_bin, npm_name = env / "bin", "npm"
    env_bin.mkdir(parents=True)
    (env / ".leika-node").write_text("20.0.0")
    (env_bin / npm_name).write_text("")
    monkeypatch.setattr(autobuild.shutil, "which", lambda _: str(node))
    monkeypatch.setattr(autobuild, "_installed_node_version", lambda _: "20.0.0")

    assert autobuild._resolve_node() == (env_bin, env)


def test_forced_install_ignores_a_matching_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _ = _configure_tree(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "npm").write_text("")
    calls: list[list[str]] = []

    def run(command, **kwargs):
        del kwargs
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", run)
    autobuild._install_dependencies(bin_dir, {})
    autobuild._install_dependencies(bin_dir, {}, force=True)
    assert [command[-1] for command in calls] == ["ci", "ci"]


def test_source_change_during_build_is_unstamped_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, build = _configure_tree(tmp_path, monkeypatch)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "npm").write_text("")
    source = client / "src.ts"
    source.write_text("first")
    monkeypatch.setattr(autobuild, "_build_lock", contextlib.nullcontext)
    monkeypatch.setattr(autobuild, "_resolve_node", lambda: (bin_dir, None))
    install_forces: list[bool] = []
    monkeypatch.setattr(
        autobuild,
        "_install_dependencies",
        lambda *_, force=False, **__: install_forces.append(force),
    )
    mutate = True

    def run(command, **kwargs):
        nonlocal mutate
        del kwargs
        if "--outDir" in command:
            _write_complete_outputs(_vite_output(command))
            if mutate:
                source.write_text("changed during build")
                mutate = False
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(autobuild.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="sources changed.*Retry"):
        autobuild.build_client(force=True, clean_install=True)
    assert not autobuild._stamp_path.exists()
    assert not build.exists()

    autobuild.build_client(force=True, clean_install=True)
    assert autobuild._is_current()
    assert install_forces == [True, True]


def test_out_dir_is_an_exact_snapshot_copied_under_the_build_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    current_index = b"c" * autobuild._CLIENT_INDEX_MIN_BYTES
    (build / "index.html").write_bytes(current_index)
    autobuild._write_stamp(autobuild._stamp_path, autobuild._source_hash())
    output = tmp_path / "release-client"
    output.mkdir()
    (output / "stale.js").write_text("stale")
    lock_held = False

    @contextlib.contextmanager
    def observed_lock():
        nonlocal lock_held
        lock_held = True
        try:
            yield
        finally:
            lock_held = False

    copy_snapshot = autobuild._copy_build_snapshot

    def copy_while_locked(destination: Path) -> None:
        assert lock_held
        copy_snapshot(destination)

    monkeypatch.setattr(autobuild, "_build_lock", observed_lock)
    monkeypatch.setattr(autobuild, "_copy_build_snapshot", copy_while_locked)
    autobuild.build_client(out_dir=output)

    assert (output / "index.html").read_bytes() == current_index
    assert not (output / "stale.js").exists()
    assert {path.relative_to(build) for path in build.rglob("*")} == {
        path.relative_to(output) for path in output.rglob("*")
    }


def test_interrupted_snapshot_publication_restores_old_or_keeps_new_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_tree(tmp_path, monkeypatch)
    output = tmp_path / "release-client"
    backup = autobuild._snapshot_backup_dir(output)
    transaction = autobuild._snapshot_transaction_path(output)

    output.mkdir()
    (output / "old-only.txt").write_text("old")
    transaction.write_text(autobuild._SNAPSHOT_TRANSACTION_CONTENT)
    autobuild.os.replace(output, backup)

    autobuild._recover_snapshot_publication(output)
    assert (output / "old-only.txt").read_text() == "old"
    assert not backup.exists()
    assert not transaction.exists()

    transaction.write_text(autobuild._SNAPSHOT_TRANSACTION_CONTENT)
    autobuild.os.replace(output, backup)
    _write_complete_outputs(output)
    autobuild._write_stamp(output / ".leika-sources", "a" * 64)

    autobuild._recover_snapshot_publication(output)
    assert autobuild._is_complete_generation(output)
    assert not (output / "old-only.txt").exists()
    assert not backup.exists()
    assert not transaction.exists()


def test_snapshot_flushes_marker_before_renames_and_each_terminal_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    autobuild._write_stamp(autobuild._stamp_path, "1" * 64)
    output = tmp_path / "release-client"
    output.mkdir()
    (output / "old.txt").write_text("old")
    events: list[str] = []
    replace = autobuild.os.replace

    def observed_replace(source: Path, destination: Path) -> None:
        source = Path(source)
        destination = Path(destination)
        events.append(f"replace:{source.name}->{destination.name}")
        replace(source, destination)

    monkeypatch.setattr(autobuild.os, "replace", observed_replace)
    monkeypatch.setattr(
        autobuild,
        "_fsync_tree",
        lambda path: events.append(f"tree:{path.name}"),
    )
    monkeypatch.setattr(
        autobuild,
        "_fsync_directory",
        lambda path: events.append(f"directory:{path.name}"),
    )

    autobuild._copy_build_snapshot(output)

    staging_name = events[0].split(":", 1)[1]
    assert events == [
        f"tree:{staging_name}",
        f"tree:{output.name}",
        f"directory:{tmp_path.name}",
        f"replace:{output.name}->{autobuild._snapshot_backup_dir(output).name}",
        f"directory:{tmp_path.name}",
        f"replace:{staging_name}->{output.name}",
        f"directory:{tmp_path.name}",
        f"directory:{tmp_path.name}",
        f"directory:{tmp_path.name}",
    ]
    assert autobuild._is_complete_generation(output)
    assert not autobuild._snapshot_backup_dir(output).exists()
    assert not autobuild._snapshot_transaction_path(output).exists()


def test_file_fsync_uses_a_writable_descriptor_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "payload"
    opened: list[tuple[Path, int]] = []
    fsynced: list[int] = []
    closed: list[int] = []

    def open_file(candidate: Path, flags: int) -> int:
        opened.append((candidate, flags))
        return 17

    monkeypatch.setattr(autobuild.os, "name", "nt")
    monkeypatch.setattr(autobuild.os, "open", open_file)
    monkeypatch.setattr(autobuild.os, "fsync", fsynced.append)
    monkeypatch.setattr(autobuild.os, "close", closed.append)

    autobuild._fsync_file(path)

    expected_flags = autobuild.os.O_RDWR | getattr(autobuild.os, "O_BINARY", 0)
    assert opened == [(path, expected_flags)]
    assert fsynced == [17]
    assert closed == [17]


def test_directory_fsync_is_an_explicit_noop_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autobuild.os, "name", "nt")
    monkeypatch.setattr(
        autobuild.os,
        "open",
        lambda *_: pytest.fail("Windows must not use POSIX directory handles"),
    )

    autobuild._fsync_directory(tmp_path)


@pytest.mark.parametrize("relative", [Path("."), Path(".."), Path("release-inside-client")])
def test_snapshot_refuses_to_replace_or_write_inside_the_client_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: Path,
) -> None:
    client, _ = _configure_tree(tmp_path, monkeypatch)
    output = client / relative

    with pytest.raises(RuntimeError, match="separate directory"):
        autobuild._copy_build_snapshot(output)


def test_build_entrypoint_forwards_release_rebuild_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        autobuild,
        "build_client",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        autobuild.sys,
        "argv",
        ["_client_autobuild.py", "--force", "--clean-install", "--out-dir", str(tmp_path)],
    )

    autobuild.build_client_entrypoint()

    assert calls == [{"out_dir": tmp_path, "force": True, "clean_install": True}]


def test_wheel_entrypoint_validates_and_copies_bundled_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, build = _configure_tree(tmp_path, monkeypatch)
    for source in (client / "package.json", client / "package-lock.json", client / ".nvmrc"):
        source.unlink()
    _write_complete_outputs(build)
    output = tmp_path / "exported-client"
    monkeypatch.setattr(
        autobuild.sys,
        "argv",
        ["leika-build-client", "--out-dir", str(output)],
    )
    monkeypatch.setattr(
        autobuild,
        "build_client",
        lambda **_: pytest.fail("a source-less wheel must not invoke npm"),
    )
    monkeypatch.setattr(
        autobuild,
        "_build_lock",
        lambda: pytest.fail("a source-less wheel must not write beside site-packages"),
    )
    acquired_locks: list[Path] = []
    file_lock = autobuild._file_lock

    @contextlib.contextmanager
    def observed_file_lock(path: Path):
        acquired_locks.append(path)
        with file_lock(path):
            yield

    monkeypatch.setattr(autobuild, "_file_lock", observed_file_lock)

    autobuild.build_client_entrypoint()

    assert (output / "index.html").read_bytes() == (build / "index.html").read_bytes()
    assert (output / "THIRD_PARTY_NOTICES.txt").read_bytes() == (
        build / "THIRD_PARTY_NOTICES.txt"
    ).read_bytes()
    assert not (output / ".leika-sources").exists()
    assert acquired_locks == [autobuild._snapshot_export_lock_path(output)]
    assert not acquired_locks[0].is_relative_to(client)


def test_wheel_entrypoint_without_export_is_a_validating_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, build = _configure_tree(tmp_path, monkeypatch)
    for source in (client / "package.json", client / "package-lock.json", client / ".nvmrc"):
        source.unlink()
    _write_complete_outputs(build)
    monkeypatch.setattr(autobuild.sys, "argv", ["leika-build-client"])
    monkeypatch.setattr(
        autobuild,
        "build_client",
        lambda **_: pytest.fail("a source-less wheel must not invoke npm"),
    )
    monkeypatch.setattr(
        autobuild,
        "_build_lock",
        lambda: pytest.fail("a source-less wheel must not create a checkout lock"),
    )

    autobuild.build_client_entrypoint()


@pytest.mark.parametrize("extra_kind", ["file", "directory", "symlink"])
def test_wheel_ensure_rejects_unexpected_bundled_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_kind: str
) -> None:
    client, build = _configure_tree(tmp_path, monkeypatch)
    _write_complete_outputs(build)
    extra = build / "unexpected"
    if extra_kind == "directory":
        extra.mkdir()
    elif extra_kind == "symlink":
        try:
            extra.symlink_to(build / "index.html")
        except (NotImplementedError, OSError):
            pytest.skip("symlinks are not available to this test process")
    else:
        extra.write_text("unexpected", encoding="utf-8")
    monkeypatch.delenv("LEIKA_CLIENT_BUILD", raising=False)

    with pytest.raises(RuntimeError, match="no complete built browser client"):
        autobuild.ensure_client_is_built()


@pytest.mark.parametrize("flag", ["--force", "--clean-install"])
def test_wheel_entrypoint_rejects_source_only_rebuild_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    client, build = _configure_tree(tmp_path, monkeypatch)
    for source in (client / "package.json", client / "package-lock.json", client / ".nvmrc"):
        source.unlink()
    _write_complete_outputs(build)
    monkeypatch.setattr(autobuild.sys, "argv", ["leika-build-client", flag])

    with pytest.raises(SystemExit, match="2"):
        autobuild.build_client_entrypoint()
