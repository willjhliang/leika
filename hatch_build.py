"""Hatch build hook that puts a current browser client into every distribution."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        # An editable install builds the client when a server first starts.
        if version == "editable":
            return
        # Loaded by path: importing the `leika` package would need its runtime
        # dependencies, which the isolated build environment does not have.
        path = Path(self.root, "src/leika/_client_autobuild.py")
        spec = importlib.util.spec_from_file_location("_leika_client_autobuild", path)
        assert spec is not None and spec.loader is not None
        autobuild = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(autobuild)
        autobuild.ensure_client_is_built()
