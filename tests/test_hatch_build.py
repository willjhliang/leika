from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def wheel_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path]:
    # Hatch itself is only a build dependency. Exercise our actual hook and
    # bundle validator without importing the packaging backend into unit tests.
    interface = ModuleType("hatchling.builders.hooks.plugin.interface")
    interface.BuildHookInterface = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, interface.__name__, interface)
    hook = runpy.run_path(str(ROOT / "hatch_build.py"))["CustomBuildHook"]()
    hook.root = str(tmp_path)
    hook.target_name = "wheel"

    package = tmp_path / "src/leika"
    package.mkdir(parents=True)
    shutil.copyfile(ROOT / "src/leika/_client_autobuild.py", package / "_client_autobuild.py")
    client = package / "client"
    client.mkdir()
    (client / "app.ts").write_text("export const value = 1;\n")
    validator = runpy.run_path(str(package / "_client_autobuild.py"))
    build = client / "build"
    build.mkdir()
    for name, minimum_bytes in validator["_REQUIRED_BUILD_OUTPUTS"]:
        (build / name).write_bytes(b"x" * minimum_bytes)
    (build / ".leika-sources").write_text(validator["_source_hash"]())

    def unexpected_build(*args: object, **kwargs: object) -> None:
        pytest.fail("wheel validation must work without launching a client build")

    monkeypatch.setattr(subprocess, "run", unexpected_build)
    monkeypatch.setattr(subprocess, "Popen", unexpected_build)
    return hook, client


def test_checkout_wheel_accepts_current_bundle_and_rejects_changed_sources(wheel_project) -> None:
    hook, client = wheel_project
    hook.initialize("standard", {})
    (client / "app.ts").write_text("export const value = 2;\n")
    with pytest.raises(RuntimeError, match="missing or stale"):
        hook.initialize("standard", {})


def test_sdist_wheel_accepts_unstamped_bundle_and_rejects_truncation(wheel_project) -> None:
    hook, client = wheel_project
    (Path(hook.root) / "PKG-INFO").write_text("Metadata-Version: 2.4\n")
    (client / "build/.leika-sources").unlink()
    hook.initialize("standard", {})
    (client / "build/index.html").write_text("truncated")
    with pytest.raises(RuntimeError, match="missing, incomplete, or unexpected"):
        hook.initialize("standard", {})


def test_stray_sdist_metadata_cannot_bypass_checkout_freshness(wheel_project) -> None:
    hook, client = wheel_project
    (Path(hook.root) / "PKG-INFO").write_text("Metadata-Version: 2.4\n")
    (Path(hook.root) / ".git").mkdir()
    (client / "build/.leika-sources").unlink()
    with pytest.raises(RuntimeError, match="missing or stale"):
        hook.initialize("standard", {})


def test_editable_and_sdist_builds_do_not_require_a_client_bundle(wheel_project) -> None:
    hook, client = wheel_project
    shutil.rmtree(client / "build")
    hook.initialize("editable", {})
    hook.target_name = "sdist"
    hook.initialize("standard", {})
