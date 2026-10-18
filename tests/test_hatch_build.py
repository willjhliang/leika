from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_hook_ensures_the_client_for_standard_builds_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hatch is only a build dependency; stand in for its hook base class.
    interface = ModuleType("hatchling.builders.hooks.plugin.interface")
    interface.BuildHookInterface = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, interface.__name__, interface)
    hook = runpy.run_path(str(ROOT / "hatch_build.py"))["CustomBuildHook"]()
    hook.root = str(tmp_path)

    autobuild = tmp_path / "src/leika/_client_autobuild.py"
    autobuild.parent.mkdir(parents=True)
    autobuild.write_text(
        "from pathlib import Path\n"
        "def ensure_client_is_built():\n"
        "    Path(__file__).with_name('ensured').touch()\n"
    )

    hook.initialize("editable", {})
    assert not (autobuild.parent / "ensured").exists()
    hook.initialize("standard", {})
    assert (autobuild.parent / "ensured").exists()
