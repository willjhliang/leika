from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_dependency_audit


class _Distribution:
    def __init__(self, name: str, version: str) -> None:
        self.metadata = {"Name": name}
        self.version = version


def test_inventory_is_exact_sorted_and_excludes_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        check_dependency_audit.importlib.metadata,
        "distributions",
        lambda: [
            _Distribution("Typing_Extensions", "4.16.0"),
            _Distribution("leika", "0.4.0"),
            _Distribution("Pillow", "12.3.0"),
        ],
    )
    current = f"{sys.version_info[0]}.{sys.version_info[1]}"
    output = tmp_path / "requirements.txt"

    assert check_dependency_audit._write_inventory(output, current) == 0

    assert output.read_text(encoding="utf-8") == ("pillow==12.3.0\ntyping-extensions==4.16.0\n")


def test_inventory_write_preserves_mode_and_flushes_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "requirements.txt"
    output.write_text("old\n", encoding="utf-8")
    output.chmod(0o640)
    synced: list[Path] = []
    monkeypatch.setattr(check_dependency_audit, "_fsync_directory", synced.append)

    check_dependency_audit._atomic_write_inventory(output, {"demo": "1"})

    assert output.read_text(encoding="utf-8") == "demo==1\n"
    assert stat.S_IMODE(output.stat().st_mode) == 0o640
    assert synced == [tmp_path]


def test_inventory_rejects_wrong_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        check_dependency_audit.importlib.metadata,
        "distributions",
        lambda: [_Distribution("Pillow", "12.3.0")],
    )
    with pytest.raises(RuntimeError, match="expected 0.0"):
        check_dependency_audit._write_inventory(tmp_path / "requirements.txt", "0.0")


def test_canonicalize_selects_only_target_python_markers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    environment = check_dependency_audit._marker_environment() | {
        "python_full_version": "3.10.19",
        "python_version": "3.10",
    }
    exported = tmp_path / "requirements.txt"
    exported.write_text(
        "numpy==2.2.6 ; python_full_version < '3.11'\n"
        "numpy==2.5.2 ; python_full_version >= '3.12'\n"
        "Pillow==12.3.0\n",
        encoding="utf-8",
    )

    assert check_dependency_audit._canonicalize_requirements(exported, environment) == 0

    assert capsys.readouterr().out == "numpy==2.2.6\npillow==12.3.0\n"


def test_canonicalize_uses_exact_patch_and_implementation_markers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exported = tmp_path / "requirements.txt"
    exported.write_text(
        "patch-match==1 ; python_full_version == '3.10.19'\n"
        "patch-miss==1 ; python_full_version == '3.10.0'\n"
        "implementation-match==1 ; implementation_name == 'cpython'\n",
        encoding="utf-8",
    )
    environment = check_dependency_audit._marker_environment() | {
        "implementation_name": "cpython",
        "python_full_version": "3.10.19",
        "python_version": "3.10",
    }

    check_dependency_audit._canonicalize_requirements(exported, environment)

    assert capsys.readouterr().out == ("implementation-match==1\npatch-match==1\n")


def test_canonicalize_rejects_conflicting_active_locked_versions(tmp_path: Path) -> None:
    exported = tmp_path / "requirements.txt"
    exported.write_text("demo==1\ndemo==2\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="multiple versions for demo"):
        check_dependency_audit._canonicalize_requirements(exported, {})


@pytest.mark.parametrize("extra", ["base", "examples"])
def test_audit_uses_locked_isolated_environments_without_ignores(
    extra: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        if "--inventory" in command:
            Path(command[command.index("--inventory") + 1]).write_bytes(b"demo==1\n")
        if "--print-marker-environment" in command:
            stdout = json.dumps(check_dependency_audit._marker_environment())
        else:
            stdout = b"demo==1\n" if "--canonicalize" in command else b""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(check_dependency_audit.shutil, "which", lambda _name: "/uv")
    monkeypatch.setattr(check_dependency_audit.subprocess, "run", run)

    assert check_dependency_audit._audit("3.10", extra) == 0

    export, create, sync, inventory, markers, canonicalize, audit = calls
    assert export[:6] == [
        "/uv",
        "export",
        "--quiet",
        "--locked",
        "--no-dev",
        "--no-emit-project",
    ]
    assert ("--extra" in export) is (extra == "examples")
    assert create[:4] == ["/uv", "venv", "--quiet", "--python"]
    assert sync[:3] == ["/uv", "pip", "sync"]
    assert "--require-hashes" in sync
    assert "--inventory" in inventory
    assert "--print-marker-environment" in markers
    assert canonicalize[:7] == [
        "/uv",
        "run",
        "--isolated",
        "--locked",
        "--only-group",
        "audit",
        "python",
    ]
    assert audit[:6] == [
        "/uv",
        "run",
        "--isolated",
        "--locked",
        "--only-group",
        "audit",
    ]
    assert "pip-audit" in audit
    assert "--strict" in audit
    assert "--no-deps" in audit
    assert "--disable-pip" in audit
    assert not any(argument.startswith("--ignore-vuln") for argument in audit)


def test_audit_rejects_environment_leakage_before_pip_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        if "--inventory" in command:
            Path(command[command.index("--inventory") + 1]).write_bytes(b"demo==1\nunexpected==2\n")
        if "--print-marker-environment" in command:
            stdout = json.dumps(check_dependency_audit._marker_environment())
        else:
            stdout = b"demo==1\n" if "--canonicalize" in command else b""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(check_dependency_audit.shutil, "which", lambda _name: "/uv")
    monkeypatch.setattr(check_dependency_audit.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="inventory differs"):
        check_dependency_audit._audit("3.10", "base")

    assert not any("pip-audit" in command for command in calls)
