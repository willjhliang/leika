"""Project-shape invariants: packaging, dependency boundaries, and scope.

These tests guard properties that are hard to notice breaking during ordinary
work -- what the wheel ships, which dependency layers may import each other,
and the deliberate absence of a 3D surface. Appearance and layout are
covered behaviorally by the Playwright suite in ``tests/e2e``, not by matching
source text here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "src/leika/client"


def test_metadata_is_leika_and_base_is_lightweight() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "leika"' in metadata
    assert 'path = "src/leika/__init__.py"' in metadata
    assert "Apache Software License" in metadata
    dependencies = metadata.split("dependencies = [", 1)[1].split("]", 1)[0]
    for forbidden in ("plotly", "matplotlib", "trimesh", "requests", "torch"):
        assert forbidden not in dependencies.lower()
    assert re.search(r"plotly\s*=\s*\[", metadata)


def test_client_ui_is_configured_for_shadcn() -> None:
    config = json.loads((CLIENT / "components.json").read_text(encoding="utf-8"))
    assert config["style"] == "base-nova"
    assert config["iconLibrary"] == "lucide"
    assert config["tailwind"]["baseColor"] == "neutral"
    assert config["tailwind"]["css"] == "src/index.css"

    package = json.loads((CLIENT / "package.json").read_text(encoding="utf-8"))
    dependencies = {**package["dependencies"], **package["devDependencies"]}
    for required in (
        "@base-ui/react",
        "class-variance-authority",
        "lucide-react",
        "shadcn",
        "tailwindcss",
    ):
        assert required in dependencies
    # Superseded UI stacks must not creep back in alongside shadcn.
    for forbidden in (
        "@mantine/core",
        "@hugeicons/react",
        "@tabler/icons-react",
        "@vanilla-extract/css",
        "@vanilla-extract/vite-plugin",
        "framer-motion",
    ):
        assert forbidden not in dependencies


def test_base_ui_is_reached_only_through_the_registry() -> None:
    """App components compose `components/ui`; only those wrap Base UI.

    This is what keeps a shadcn component's styling and behavior in one
    editable place instead of being re-derived at each call site.
    """
    ui_dir = CLIENT / "src/components/ui"
    offenders = [
        path.relative_to(CLIENT)
        for path in sorted((CLIENT / "src").rglob("*.tsx"))
        if ui_dir not in path.parents and "@base-ui/react" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_browser_client_licenses_ship_with_the_package() -> None:
    licenses = ROOT / "src/leika/_licenses"
    for name in (
        "shadcn-ui-LICENSE.md",
        "shadcn-ui-PROVENANCE.md",
        "base-ui-LICENSE.txt",
        "geist-OFL.txt",
        "lucide-LICENSE.txt",
        "cmdk-next-themes-MIT-LICENSE.txt",
    ):
        path = licenses / name
        assert path.is_file(), name
        # Guards against a truncated or placeholder license file.
        assert len(path.read_bytes()) > 500, name


def test_no_3d_public_source_or_examples() -> None:
    assert not (ROOT / "src/leika/_scene_api.py").exists()
    assert not (ROOT / "src/leika/_scene_handles.py").exists()
    assert not (ROOT / "src/leika/transforms").exists()
    assert not (ROOT / "src/leika/extras").exists()
    package_json = (CLIENT / "package.json").read_text(encoding="utf-8")
    for dependency in ("three", "@react-three/fiber", "@react-three/drei"):
        assert f'"{dependency}"' not in package_json
    example_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "examples").glob("*.py")
    )
    for forbidden in ("add_matplotlib", "add_url", ".scene"):
        assert forbidden not in example_text


def test_examples_compile() -> None:
    for path in (ROOT / "examples").glob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_local_workflow_action_references_exist() -> None:
    local_references = []
    workflow_files = sorted((ROOT / ".github").rglob("*.yml")) + sorted(
        (ROOT / ".github").rglob("*.yaml")
    )
    pattern = re.compile(
        r"^\s*-\s+uses:\s*[\"\x27]?(\./[^\"\x27\s]+)",
        re.MULTILINE,
    )
    for source in workflow_files:
        for relative in pattern.findall(source.read_text(encoding="utf-8")):
            local_references.append((source, relative))
            target = (ROOT / relative).resolve()
            assert target == ROOT or ROOT in target.parents, (source, relative)
            assert target.exists(), f"{source}: missing local uses target {relative}"
            if target.is_dir():
                assert (target / "action.yml").is_file() or (target / "action.yaml").is_file(), (
                    f"{source}: {relative} has no action.yml or action.yaml"
                )
    assert local_references, "expected at least one repository-local workflow action"
