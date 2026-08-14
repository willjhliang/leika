"""Hatch build hook that prevents publishing an unusable Leika wheel.

The browser bundle is an input to a wheel, not something a PEP 517 build is
allowed to download or generate. Release tooling builds it explicitly before
invoking Hatch. This hook only validates that input and never invokes Node,
npm, or the network.
"""

from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_BUILD_HELP = (
    "Run `leika-build-client --force` in a checkout before building a wheel, "
    "or use `make package` for the canonical release build."
)


def _load_client_validation(root: Path) -> dict[str, Any]:
    validator = root / "src/leika/_client_autobuild.py"
    if validator.is_symlink() or not validator.is_file():
        raise RuntimeError(
            f"Leika's client bundle validator is missing or not a regular file: {validator}. "
            f"{_BUILD_HELP}"
        )
    return runpy.run_path(str(validator))


def _validation_callable(namespace: dict[str, Any], name: str) -> Callable[..., Any]:
    value = namespace.get(name)
    if not callable(value):
        raise RuntimeError(
            f"Leika's client bundle validator does not provide {name}(). {_BUILD_HELP}"
        )
    return value


def _is_sdist_tree(root: Path) -> bool:
    """Return whether Hatch is building from its extracted source artifact.

    ``PKG-INFO`` is the standard marker required at an sdist root. PEP 517
    does not expose the archive a source tree came from, so unmistakable
    checkout state wins if a stale/generated ``PKG-INFO`` was left behind.
    """
    pkg_info = root / "PKG-INFO"
    if pkg_info.is_symlink() or (pkg_info.exists() and not pkg_info.is_file()):
        raise RuntimeError(f"Leika source marker is not a regular file: {pkg_info}.")
    if not pkg_info.is_file():
        return False

    checkout_markers = (
        root / ".git",
        root / "src/leika/client/build/.leika-sources",
    )
    return not any(marker.is_symlink() or marker.exists() for marker in checkout_markers)


def _validate_wheel_build(root: Path, *, target_name: str, version: str) -> None:
    """Validate wheel inputs while leaving editable and sdist builds untouched."""
    if target_name != "wheel" or version == "editable":
        return
    if version != "standard":
        raise RuntimeError(f"Unsupported Leika wheel build mode: {version!r}.")
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"Leika build root is not a regular directory: {root}.")

    namespace = _load_client_validation(root)
    if _is_sdist_tree(root):
        invalid_generation = _validation_callable(namespace, "_invalid_generation_tree")
        build_dir = namespace.get("build_dir")
        if not isinstance(build_dir, Path):
            raise RuntimeError(
                "Leika's client bundle validator does not expose its build directory. "
                f"{_BUILD_HELP}"
            )
        invalid = invalid_generation(build_dir, stamped=False)
        if invalid is not None:
            raise RuntimeError(
                "Cannot build a Leika wheel from this source distribution: its bundled "
                f"browser client is missing, incomplete, or unexpected at {invalid}. "
                f"{_BUILD_HELP}"
            )
        return

    is_current = _validation_callable(namespace, "_is_current")
    if not is_current():
        raise RuntimeError(
            "Cannot build a Leika wheel from this checkout: the browser client bundle "
            f"is missing or stale. {_BUILD_HELP}"
        )


class CustomBuildHook(BuildHookInterface):
    """Validate browser artifacts immediately before a standard wheel build."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        _validate_wheel_build(Path(self.root), target_name=self.target_name, version=version)
