from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts import build_release
from scripts.build_release import _only


def test_only_artifact_isolated_from_stale_distributions(tmp_path: Path) -> None:
    expected = tmp_path / "leika-0.4.0-py3-none-any.whl"
    expected.touch()

    assert _only(tmp_path, "*.whl") == expected


def test_only_artifact_rejects_ambiguous_build_output(tmp_path: Path) -> None:
    (tmp_path / "leika-0.3.0-py3-none-any.whl").touch()
    (tmp_path / "leika-0.4.0-py3-none-any.whl").touch()

    with pytest.raises(RuntimeError, match=r"expected one \*\.whl artifact"):
        _only(tmp_path, "*.whl")


def test_build_once_uses_project_root_not_empty_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    output = tmp_path / "artifacts"
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == project_root
        assert check is True
        assert output.is_dir()
        assert list(output.iterdir()) == []
        calls.append((command, cwd))
        (output / "leika-0.4.0-py3-none-any.whl").touch()
        (output / "leika-0.4.0.tar.gz").touch()

    monkeypatch.setattr(build_release, "ROOT", project_root)
    monkeypatch.setattr(build_release.subprocess, "run", fake_run)

    wheel, sdist = build_release._build_once("/usr/bin/uv", output)

    command = calls[0][0]
    assert command[command.index("--out-dir") + 1] == str(output)
    assert str(project_root) in command
    assert str(output) not in command[command.index("--out-dir") + 2 :]
    assert wheel.name == "leika-0.4.0-py3-none-any.whl"
    assert sdist.name == "leika-0.4.0.tar.gz"


def test_cleanup_owned_staging_removes_only_validated_internal_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_stage = tmp_path / ".leika-dist-stage-deadbeef"
    dist_stage.mkdir()
    (dist_stage / "partial").write_bytes(b"partial")
    backup_root = tmp_path / ".release-artifact-backups"
    backup_stage = backup_root / ".previous-dist-stage-deadbeef"
    backup_stage.mkdir(parents=True)
    (backup_stage / "partial").write_bytes(b"partial")
    unrelated_root = tmp_path / "user-staging"
    unrelated_root.mkdir()
    unrelated_backup = backup_root / "user-notes"
    unrelated_backup.write_bytes(b"keep")

    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    build_release._cleanup_owned_staging()

    assert not dist_stage.exists()
    assert not backup_stage.exists()
    assert unrelated_root.is_dir()
    assert unrelated_backup.read_bytes() == b"keep"


def test_cleanup_owned_staging_refuses_unexpected_entry_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = tmp_path / ".leika-dist-stage-deadbeef"
    stale.write_bytes(b"not a directory")
    monkeypatch.setattr(build_release, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="unexpected release staging path"):
        build_release._cleanup_owned_staging()


def test_copy_file_durable_flushes_the_replacement_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.write_bytes(b"release bytes")
    fsynced_inodes: list[int] = []

    monkeypatch.setattr(
        build_release.os,
        "fsync",
        lambda descriptor: fsynced_inodes.append(os.fstat(descriptor).st_ino),
    )
    build_release._copy_file_durable(source, target)

    assert target.read_bytes() == b"release bytes"
    assert target.stat().st_ino in fsynced_inodes


def test_publish_preserves_existing_artifacts_if_staging_is_interrupted(
    tmp_path: Path, monkeypatch
) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    sdist = source_directory / "leika-0.4.0.tar.gz"
    wheel.write_bytes(b"new wheel")
    sdist.write_bytes(b"new sdist")

    old_wheel = distribution_directory / wheel.name
    old_sdist = distribution_directory / sdist.name
    old_wheel.write_bytes(b"old wheel")
    old_sdist.write_bytes(b"old sdist")

    original_copy = build_release.shutil.copyfileobj
    copies = 0

    def fail_during_second_copy(source, target) -> None:
        nonlocal copies
        copies += 1
        if copies == 2:
            raise OSError("simulated interrupted copy")
        original_copy(source, target)

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release.shutil, "copyfileobj", fail_during_second_copy)

    with pytest.raises(OSError, match="simulated interrupted copy"):
        build_release._publish((wheel, sdist))

    assert old_wheel.read_bytes() == b"old wheel"
    assert old_sdist.read_bytes() == b"old sdist"


def test_publish_rehashes_staged_artifacts_before_replacing_dist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    wheel.write_bytes(b"validated wheel")

    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    old_wheel = distribution_directory / "leika-0.3.0-py3-none-any.whl"
    old_wheel.write_bytes(b"old wheel")

    original_copy = build_release.shutil.copyfileobj

    def corrupt_staged_copy(source, target) -> None:
        original_copy(source, target)
        target.write(b"corruption")

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release.shutil, "copyfileobj", corrupt_staged_copy)

    with pytest.raises(RuntimeError, match="contents changed while copying"):
        build_release._publish((wheel,))

    assert old_wheel.read_bytes() == b"old wheel"
    assert not (tmp_path / ".release-artifact-backups").exists()
    assert not any(path.name.startswith(".leika-dist-stage-") for path in tmp_path.iterdir())


def test_publish_replaces_dist_with_exact_validated_pair(tmp_path: Path, monkeypatch) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    (distribution_directory / "leika-0.3.0-py3-none-any.whl").write_bytes(b"stale")

    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    sdist = source_directory / "leika-0.4.0.tar.gz"
    wheel.write_bytes(b"new wheel")
    sdist.write_bytes(b"new sdist")

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    build_release._publish((wheel, sdist))

    assert {path.name for path in distribution_directory.iterdir()} == {
        wheel.name,
        sdist.name,
    }
    assert (distribution_directory / wheel.name).read_bytes() == b"new wheel"
    if os.name != "nt":
        assert distribution_directory.stat().st_mode & 0o777 == 0o755
    backups = list((tmp_path / ".release-artifact-backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "leika-0.3.0-py3-none-any.whl").read_bytes() == b"stale"


def test_publish_refuses_file_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    wheel.write_bytes(b"new")
    distribution_path = tmp_path / "dist"
    distribution_path.write_bytes(b"unrelated")
    monkeypatch.setattr(build_release, "DIST", distribution_path)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="non-directory dist path"):
        build_release._publish((wheel,))
    assert distribution_path.read_bytes() == b"unrelated"


def test_publish_refuses_symlink_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    wheel.write_bytes(b"new")
    outside = tmp_path / "outside"
    outside.mkdir()
    distribution_path = tmp_path / "dist"
    distribution_path.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(build_release, "DIST", distribution_path)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="non-directory dist path"):
        build_release._publish((wheel,))
    assert distribution_path.is_symlink()
    assert list(outside.iterdir()) == []
    assert not any(path.name.startswith(".leika-dist-stage-") for path in tmp_path.iterdir())


def test_publish_refuses_symlink_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wheel = tmp_path / "leika-0.4.0-py3-none-any.whl"
    wheel.write_bytes(b"payload")
    original_is_symlink = Path.is_symlink

    def mark_artifact_as_symlink(path: Path) -> bool:
        return path == wheel or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", mark_artifact_as_symlink)
    monkeypatch.setattr(build_release, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_release, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="not a regular package file"):
        build_release._publish((wheel,))


def test_publish_refuses_unowned_previous_backup(tmp_path: Path, monkeypatch) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    wheel.write_bytes(b"new wheel")

    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    current = distribution_directory / "leika-0.3.0-py3-none-any.whl"
    current.write_bytes(b"current")
    backup_root = tmp_path / ".release-artifact-backups"
    previous = backup_root / "previous-dist"
    previous.mkdir(parents=True)
    (previous / "older").write_bytes(b"older")

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="unowned backup path"):
        build_release._publish((wheel,))

    assert current.read_bytes() == b"current"
    assert (previous / "older").read_bytes() == b"older"


def test_publish_refuses_fabricated_marker_for_nonartifact_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    wheel.write_bytes(b"new wheel")

    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    current = distribution_directory / "leika-0.3.0-py3-none-any.whl"
    current.write_bytes(b"current")
    previous = tmp_path / ".release-artifact-backups" / "previous-dist"
    previous.mkdir(parents=True)
    notes = previous / "notes.txt"
    notes.write_bytes(b"unrelated")
    (previous / build_release.BACKUP_MARKER).write_text(
        build_release.json.dumps(
            {"files": {notes.name: build_release._file_hash(notes)}, "version": 1}
        )
    )

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="invalid release backup marker"):
        build_release._publish((wheel,))

    assert current.read_bytes() == b"current"
    assert notes.read_bytes() == b"unrelated"


def test_publish_replaces_only_marker_owned_backup(tmp_path: Path, monkeypatch) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    sdist = source_directory / "leika-0.4.0.tar.gz"
    wheel.write_bytes(b"first wheel")
    sdist.write_bytes(b"first sdist")

    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    stale = distribution_directory / "leika-0.3.0-py3-none-any.whl"
    stale.write_bytes(b"stale")
    backup_root = tmp_path / ".release-artifact-backups"
    backup_root.mkdir()
    unrelated = backup_root / "user-notes"
    unrelated.write_bytes(b"keep me")

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    build_release._publish((wheel, sdist))

    wheel.write_bytes(b"second wheel")
    sdist.write_bytes(b"second sdist")
    build_release._publish((wheel, sdist))

    previous = backup_root / "previous-dist"
    assert unrelated.read_bytes() == b"keep me"
    assert not (previous / stale.name).exists()
    assert (previous / wheel.name).read_bytes() == b"first wheel"
    assert (previous / sdist.name).read_bytes() == b"first sdist"
    assert (previous / build_release.BACKUP_MARKER).is_file()


def test_publish_restores_previous_dist_if_directory_swap_fails(
    tmp_path: Path, monkeypatch
) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    old_artifact = distribution_directory / "leika-0.3.0-py3-none-any.whl"
    old_artifact.write_bytes(b"old wheel")

    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    sdist = source_directory / "leika-0.4.0.tar.gz"
    wheel.write_bytes(b"new wheel")
    sdist.write_bytes(b"new sdist")

    original_replace = Path.replace

    def fail_staging_swap(path: Path, target: Path) -> Path:
        if path.name.startswith(".leika-dist-stage-") and target == distribution_directory:
            raise OSError("simulated directory-swap failure")
        return original_replace(path, target)

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(Path, "replace", fail_staging_swap)

    with pytest.raises(OSError, match="simulated directory-swap failure"):
        build_release._publish((wheel, sdist))

    assert {path.name for path in distribution_directory.iterdir()} == {old_artifact.name}
    assert (distribution_directory / old_artifact.name).read_bytes() == b"old wheel"


def test_publish_restart_recovers_fault_after_live_dist_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    distribution_directory = tmp_path / "dist"
    distribution_directory.mkdir()
    old_artifact = distribution_directory / "leika-0.3.0-py3-none-any.whl"
    old_artifact.write_bytes(b"old wheel")
    old_digest = build_release._file_hash(old_artifact)

    wheel = source_directory / "leika-0.4.0-py3-none-any.whl"
    sdist = source_directory / "leika-0.4.0.tar.gz"
    wheel.write_bytes(b"new wheel")
    sdist.write_bytes(b"new sdist")
    replacement_manifest = {
        wheel.name: build_release._file_hash(wheel),
        sdist.name: build_release._file_hash(sdist),
    }

    monkeypatch.setattr(build_release, "DIST", distribution_directory)
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    original_replace = Path.replace
    durable_backup_observed = False

    def interrupt_after_live_rename(path: Path, target: Path) -> Path:
        nonlocal durable_backup_observed
        result = original_replace(path, target)
        if path == distribution_directory and target == tmp_path / build_release.RETIRED_DIST:
            backup = tmp_path / ".release-artifact-backups" / "previous-dist"
            old_manifest, recorded_replacement = build_release._owned_backup_metadata(backup)
            assert old_manifest == {old_artifact.name: old_digest}
            assert recorded_replacement == replacement_manifest
            durable_backup_observed = True
            raise RuntimeError("simulated process death")
        return result

    with monkeypatch.context() as fault:
        fault.setattr(Path, "replace", interrupt_after_live_rename)
        with pytest.raises(RuntimeError, match="simulated process death"):
            build_release._publish((wheel, sdist))

    retired = tmp_path / build_release.RETIRED_DIST
    assert durable_backup_observed
    assert not distribution_directory.exists()
    assert (retired / old_artifact.name).read_bytes() == b"old wheel"

    build_release._recover_interrupted_publication()

    assert not retired.exists()
    assert (distribution_directory / old_artifact.name).read_bytes() == b"old wheel"
    assert (
        tmp_path / ".release-artifact-backups" / "previous-dist" / build_release.BACKUP_MARKER
    ).is_file()


def test_main_does_not_publish_when_client_build_fails(monkeypatch) -> None:
    calls = []
    published = []

    def fail_client_build(command, **kwargs) -> None:
        calls.append((command, kwargs))
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(build_release.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(build_release.subprocess, "run", fail_client_build)
    monkeypatch.setattr(build_release, "_publish", published.append)

    with pytest.raises(subprocess.CalledProcessError):
        build_release.main()

    assert calls[0][0][1].endswith("src/leika/_client_autobuild.py")
    assert not published

    assert calls[0][0][-2:] == ["--force", "--clean-install"]


def test_main_does_not_publish_when_generated_protocol_check_fails(monkeypatch) -> None:
    calls = []
    published = []

    def fail_protocol_check(command, **_kwargs) -> None:
        calls.append(command)
        if command[-1] == "--check":
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(build_release.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(build_release.subprocess, "run", fail_protocol_check)
    monkeypatch.setattr(build_release, "_publish", published.append)

    with pytest.raises(subprocess.CalledProcessError):
        build_release.main()

    assert calls[0][1].endswith("src/leika/_client_autobuild.py")
    assert calls[1][1].endswith("sync_client_server.py")
    assert calls[1][-1] == "--check"
    assert not published


def test_main_runs_twine_strict_before_publish(tmp_path: Path, monkeypatch) -> None:
    calls = []
    published = []

    def fake_run(command, **_kwargs) -> None:
        calls.append(command)
        if len(command) > 1 and command[1] == "build":
            output = Path(command[command.index("--out-dir") + 1])
            (output / "leika-0.4.0-py3-none-any.whl").touch()
            (output / "leika-0.4.0.tar.gz").touch()

    def record_publish(artifacts) -> None:
        assert any(command[1:5] == ["-m", "twine", "check", "--strict"] for command in calls)
        published.append(tuple(artifact.name for artifact in artifacts))

    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(build_release.subprocess, "run", fake_run)
    monkeypatch.setattr(build_release, "_release_input_manifest", lambda: {})
    monkeypatch.setattr(build_release, "_publish", record_publish)

    assert build_release.main() == 0
    assert published == [("leika-0.4.0-py3-none-any.whl", "leika-0.4.0.tar.gz")]
    assert sum(command[1:2] == ["build"] for command in calls) == 2


def test_main_does_not_publish_nonreproducible_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builds = 0
    published = []

    def fake_run(command, **_kwargs) -> None:
        nonlocal builds
        if len(command) > 1 and command[1] == "build":
            builds += 1
            output = Path(command[command.index("--out-dir") + 1])
            (output / "leika-0.4.0-py3-none-any.whl").write_bytes(f"wheel build {builds}".encode())
            (output / "leika-0.4.0.tar.gz").write_bytes(b"same sdist")

    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(build_release.subprocess, "run", fake_run)
    monkeypatch.setattr(build_release, "_release_input_manifest", lambda: {})
    monkeypatch.setattr(build_release, "_publish", published.append)

    with pytest.raises(
        RuntimeError,
        match=r"not byte-for-byte reproducible: leika-0\.4\.0-py3-none-any\.whl",
    ):
        build_release.main()

    assert builds == 2
    assert not published


def test_main_does_not_publish_an_artifact_changed_during_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = []

    def fake_run(command, **_kwargs) -> None:
        if len(command) > 1 and command[1] == "build":
            output = Path(command[command.index("--out-dir") + 1])
            (output / "leika-0.4.0-py3-none-any.whl").write_bytes(b"wheel")
            (output / "leika-0.4.0.tar.gz").write_bytes(b"sdist")
        elif command[1:5] == ["-m", "twine", "check", "--strict"]:
            wheel = next(Path(argument) for argument in command if str(argument).endswith(".whl"))
            wheel.write_bytes(b"changed after custom validation")

    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(build_release.subprocess, "run", fake_run)
    monkeypatch.setattr(build_release, "_release_input_manifest", lambda: {})
    monkeypatch.setattr(build_release, "_publish", published.append)

    with pytest.raises(RuntimeError, match="changed while the validation gates were running"):
        build_release.main()

    assert not published


def test_main_does_not_publish_when_source_changes_after_second_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = []
    manifests = iter(
        (
            {"src/leika/_server.py": "before"},
            {"src/leika/_server.py": "after"},
        )
    )

    def fake_run(command, **_kwargs) -> None:
        if len(command) > 1 and command[1] == "build":
            output = Path(command[command.index("--out-dir") + 1])
            (output / "leika-0.4.0-py3-none-any.whl").write_bytes(b"wheel")
            (output / "leika-0.4.0.tar.gz").write_bytes(b"sdist")

    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build_release.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(build_release.subprocess, "run", fake_run)
    monkeypatch.setattr(build_release, "_release_input_manifest", lambda: next(manifests))
    monkeypatch.setattr(build_release, "_publish", published.append)

    with pytest.raises(
        RuntimeError,
        match=r"release inputs changed.*src/leika/_server\.py",
    ):
        build_release.main()

    assert not published


def test_release_input_manifest_includes_bundle_and_ignores_only_tool_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "src/leika"
    client = source_root / "client"
    build = client / "build"
    docs = tmp_path / "docs"
    build.mkdir(parents=True)
    (source_root / "_server.py").write_text("source\n", encoding="utf-8")
    (build / "index.html").write_text("bundle\n", encoding="utf-8")
    (build / "THIRD_PARTY_NOTICES.txt").write_text("notices\n", encoding="utf-8")
    (build / ".leika-sources").write_text("stamp\n", encoding="utf-8")
    (client / ".leika-build.lock").write_text("lock\n", encoding="utf-8")
    for transaction_directory in (
        client / ".leika-build-backup",
        client / ".leika-build-stage-deadbeef",
        source_root / ".export.leika-backup",
        source_root / ".export.leika-stage-deadbeef",
        source_root / ".leika-icons-stage-deadbeef",
    ):
        transaction_directory.mkdir()
        (transaction_directory / "index.html").write_text("transaction\n", encoding="utf-8")
    (source_root / ".export.leika-transaction").write_text("marker\n", encoding="utf-8")
    (docs / "_build").mkdir(parents=True)
    (docs / "_build/output.html").write_text("generated\n", encoding="utf-8")
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text("[project]\n", encoding="utf-8")

    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    monkeypatch.setattr(build_release, "INPUT_ROOTS", (source_root, docs))
    monkeypatch.setattr(build_release, "INPUT_FILES", (metadata,))

    manifest = build_release._release_input_manifest()

    assert set(manifest) == {
        "pyproject.toml",
        "src/leika/_server.py",
        "src/leika/client/build/THIRD_PARTY_NOTICES.txt",
        "src/leika/client/build/index.html",
    }
