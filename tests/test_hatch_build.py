from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_hook(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    interface = ModuleType("hatchling.builders.hooks.plugin.interface")

    class StubBuildHookInterface:
        pass

    interface.BuildHookInterface = StubBuildHookInterface  # type: ignore[attr-defined]
    for name in (
        "hatchling",
        "hatchling.builders",
        "hatchling.builders.hooks",
        "hatchling.builders.hooks.plugin",
    ):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.setitem(sys.modules, interface.__name__, interface)
    return runpy.run_path(str(ROOT / "hatch_build.py"))


def _set_validation_loader(
    hook: dict[str, Any], monkeypatch: pytest.MonkeyPatch, loader: Any
) -> Any:
    validate = hook["_validate_wheel_build"]
    monkeypatch.setitem(validate.__globals__, "_load_client_validation", loader)
    return validate


def test_loading_real_validator_does_not_start_a_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook = _load_hook(monkeypatch)

    def forbidden_process(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("loading bundle validation must not start a process")

    monkeypatch.setattr(subprocess, "run", forbidden_process)
    monkeypatch.setattr(subprocess, "Popen", forbidden_process)

    namespace = hook["_load_client_validation"](ROOT)

    assert callable(namespace["_is_current"])
    assert callable(namespace["_invalid_generation_tree"])


@pytest.mark.parametrize(
    ("target_name", "version"),
    (("sdist", "standard"), ("wheel", "editable")),
)
def test_nonstandard_distribution_modes_do_not_load_client_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
    version: str,
) -> None:
    hook = _load_hook(monkeypatch)

    def forbidden_loader(_root: Path) -> dict[str, Any]:
        raise AssertionError("editable and sdist builds must not inspect the client bundle")

    validate = _set_validation_loader(hook, monkeypatch, forbidden_loader)

    validate(tmp_path, target_name=target_name, version=version)


def test_unknown_wheel_mode_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _load_hook(monkeypatch)
    validate = hook["_validate_wheel_build"]

    with pytest.raises(RuntimeError, match="Unsupported Leika wheel build mode"):
        validate(tmp_path, target_name="wheel", version="future-mode")


def test_checkout_wheel_requires_current_bundle_without_building_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _load_hook(monkeypatch)
    build_was_called = False

    def forbidden_build() -> None:
        nonlocal build_was_called
        build_was_called = True

    validate = _set_validation_loader(
        hook,
        monkeypatch,
        lambda _root: {"_is_current": lambda: False, "build_client": forbidden_build},
    )

    with pytest.raises(
        RuntimeError,
        match=r"bundle is missing or stale.*leika-build-client --force.*make package",
    ):
        validate(tmp_path, target_name="wheel", version="standard")

    assert build_was_called is False


def test_checkout_wheel_accepts_current_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _load_hook(monkeypatch)
    validate = _set_validation_loader(
        hook,
        monkeypatch,
        lambda _root: {"_is_current": lambda: True},
    )

    validate(tmp_path, target_name="wheel", version="standard")


@pytest.mark.parametrize(
    "checkout_marker",
    (".git", "src/leika/client/build/.leika-sources"),
)
def test_checkout_marker_overrides_stray_pkg_info(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkout_marker: str,
) -> None:
    hook = _load_hook(monkeypatch)
    (tmp_path / "PKG-INFO").write_text("Metadata-Version: 2.4\n", encoding="utf-8")
    marker = tmp_path / checkout_marker
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("checkout state\n", encoding="utf-8")
    current_checks: list[bool] = []

    def is_current() -> bool:
        current_checks.append(True)
        return True

    validate = _set_validation_loader(
        hook,
        monkeypatch,
        lambda _root: {
            "_is_current": is_current,
            "_invalid_generation_tree": lambda *_args, **_kwargs: pytest.fail(
                "checkout markers must not use unstamped sdist validation"
            ),
        },
    )

    validate(tmp_path, target_name="wheel", version="standard")

    assert current_checks == [True]


def test_sdist_wheel_requires_complete_unstamped_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _load_hook(monkeypatch)
    (tmp_path / "PKG-INFO").write_text("Metadata-Version: 2.4\n", encoding="utf-8")
    build_dir = tmp_path / "src/leika/client/build"
    observed: list[tuple[Path, bool]] = []

    def invalid_generation(directory: Path, *, stamped: bool) -> None:
        observed.append((directory, stamped))

    validate = _set_validation_loader(
        hook,
        monkeypatch,
        lambda _root: {
            "_invalid_generation_tree": invalid_generation,
            "_is_current": lambda: pytest.fail("sdist wheels must not require a source stamp"),
            "build_dir": build_dir,
        },
    )

    validate(tmp_path, target_name="wheel", version="standard")

    assert observed == [(build_dir, False)]


def test_sdist_wheel_rejects_incomplete_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = _load_hook(monkeypatch)
    (tmp_path / "PKG-INFO").write_text("Metadata-Version: 2.4\n", encoding="utf-8")
    build_dir = tmp_path / "src/leika/client/build"
    missing = build_dir / "index.html"
    validate = _set_validation_loader(
        hook,
        monkeypatch,
        lambda _root: {
            "_invalid_generation_tree": lambda _directory, *, stamped: missing,
            "build_dir": build_dir,
        },
    )

    with pytest.raises(
        RuntimeError,
        match=r"source distribution.*missing, incomplete, or unexpected.*index\.html",
    ):
        validate(tmp_path, target_name="wheel", version="standard")
