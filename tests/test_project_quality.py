"""Project-shape invariants: packaging, dependency boundaries, and scope.

These tests guard properties that are hard to notice breaking during ordinary
work -- what the wheel ships, which dependency layers may import each other,
and the deliberate absence of a 3D surface. Appearance and layout are
covered behaviorally by the Playwright suite in ``tests/e2e``, not by matching
source text here.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from scripts import build_release

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "src/leika/client"


def test_metadata_is_leika_and_base_is_lightweight() -> None:
    with (ROOT / "pyproject.toml").open("rb") as source:
        metadata = tomllib.load(source)
    project = metadata["project"]
    assert project["name"] == "leika"
    assert metadata["build-system"]["requires"] == ["hatchling>=1.27,<2"]
    assert metadata["tool"]["hatch"]["version"]["path"] == "src/leika/__init__.py"
    assert metadata["tool"]["uv"]["required-version"] == "==0.12.3"
    hatch_build = metadata["tool"]["hatch"]["build"]
    assert hatch_build["reproducible"] is True
    assert hatch_build["hooks"]["custom"]["path"] == "hatch_build.py"
    assert "src/leika/client/build/.leika-sources" in hatch_build["exclude"]
    assert {
        "**/.leika-build-backup",
        "**/.leika-build-backup/**",
        "**/.leika-build-stage-*",
        "**/.leika-build-stage-*/**",
        "**/.*.leika-backup",
        "**/.*.leika-backup/**",
        "**/.*.leika-stage-*",
        "**/.*.leika-stage-*/**",
        "**/.*.leika-transaction",
        "src/leika/.leika-icons-stage-*",
        "src/leika/.leika-icons-stage-*/**",
    }.issubset(hatch_build["exclude"])
    assert metadata["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"] == [
        "src/leika/client/build/index.html",
        "src/leika/client/build/THIRD_PARTY_NOTICES.txt",
    ]
    assert "/uv.lock" in metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "/hatch_build.py" in hatch_build["targets"]["sdist"]["include"]
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == [
        "LICENSE",
        "src/leika/_licenses/*",
        "src/leika/client/third-party-license-overrides/*",
        "src/leika/client/build/THIRD_PARTY_NOTICES.txt",
    ]
    dependencies = project["dependencies"]
    assert "typing-extensions>=4.4.0,<5" in dependencies
    for forbidden in ("plotly", "matplotlib", "trimesh", "requests", "torch"):
        assert all(forbidden not in dependency.lower() for dependency in dependencies)
    examples = project["optional-dependencies"]["examples"]
    assert any(dependency.startswith("plotly") for dependency in examples)


def test_canonical_release_inputs_ship_in_the_source_distribution() -> None:
    with (ROOT / "pyproject.toml").open("rb") as source:
        metadata = tomllib.load(source)
    includes = metadata["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]

    for path in (*build_release.INPUT_ROOTS, *build_release.INPUT_FILES):
        relative = "/" + path.relative_to(ROOT).as_posix()
        assert any(
            relative == included or relative.startswith(included.rstrip("/") + "/")
            for included in includes
        ), f"canonical release input is absent from the source distribution: {relative}"


def test_root_core_dumps_are_ignored_and_excluded_from_builds() -> None:
    ignore_patterns = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {"/core", "/core.*"}.issubset(ignore_patterns)

    with (ROOT / "pyproject.toml").open("rb") as source:
        metadata = tomllib.load(source)
    build_excludes = set(metadata["tool"]["hatch"]["build"]["exclude"])
    assert {"/core", "/core.*"}.issubset(build_excludes)


def test_every_explicit_top_level_export_is_in_the_api_reference() -> None:
    module = ast.parse((ROOT / "src/leika/__init__.py").read_text(encoding="utf-8"))
    exports: set[str] = set()
    for statement in module.body:
        if isinstance(statement, ast.ImportFrom):
            exports.update(
                alias.name
                for alias in statement.names
                if alias.asname == alias.name and not alias.name.startswith("_")
            )
        elif isinstance(statement, ast.Assign):
            exports.update(
                target.id
                for target in statement.targets
                if isinstance(target, ast.Name) and not target.id.startswith("_")
            )

    documented: set[str] = set()
    directive = re.compile(
        r"^\.\. (?:autoclass|autodata|data)::\s+([A-Za-z_]\w*)",
        re.MULTILINE,
    )
    for page in (ROOT / "docs/api").glob("*.rst"):
        documented.update(directive.findall(page.read_text(encoding="utf-8")))

    assert exports == documented


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
        "almarai-OFL.txt",
        "shadcn-ui-LICENSE.md",
        "shadcn-ui-PROVENANCE.md",
        "shadcn-io-LICENSE.txt",
        "shadcn-io-PROVENANCE.md",
        "base-ui-LICENSE.txt",
        "geist-OFL.txt",
        "lucide-LICENSE.txt",
        "cmdk-next-themes-MIT-LICENSE.txt",
        "zstddec-LICENSE.txt",
    ):
        path = licenses / name
        assert path.is_file(), name
        # Guards against a truncated or placeholder license file.
        assert len(path.read_bytes()) > 500, name
    for name in ("almarai-OFL.txt", "geist-OFL.txt"):
        assert (ROOT / "docs/_static" / name).read_bytes() == (licenses / name).read_bytes()


def test_no_3d_public_source_or_examples() -> None:
    assert not (ROOT / "src/leika/_scene_api.py").exists()
    assert not (ROOT / "src/leika/_scene_handles.py").exists()
    assert not (ROOT / "src/leika/transforms").exists()
    assert not (ROOT / "src/leika/extras").exists()
    package_json = (CLIENT / "package.json").read_text(encoding="utf-8")
    for dependency in ("three", "@react-three/fiber", "@react-three/drei"):
        assert f'"{dependency}"' not in package_json
    example_texts = [path.read_text(encoding="utf-8") for path in (ROOT / "examples").glob("*.py")]
    # Viser examples legitimately drive viser's own .scene; the guard is
    # about leika's surface staying free of 3D APIs.
    example_text = "\n".join(text for text in example_texts if "import viser" not in text)
    for forbidden in ("add_url", ".scene"):
        assert forbidden not in example_text


def test_examples_compile() -> None:
    for path in (ROOT / "examples").glob("*.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_root_build_hook_is_in_local_and_ci_lint_surfaces() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/python.yml").read_text(encoding="utf-8")

    for source in (makefile, workflow):
        assert re.search(
            r"ruff check [^\n]*\bhatch_build\.py\b[^\n]*\bsync_client_server\.py\b", source
        )
        assert re.search(
            r"ruff format --check [^\n]*\bhatch_build\.py\b[^\n]*\bsync_client_server\.py\b",
            source,
        )


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


def test_pre_commit_ruff_matches_the_locked_ci_version() -> None:
    with (ROOT / "uv.lock").open("rb") as source:
        lock = tomllib.load(source)
    locked_versions = {
        package["version"] for package in lock["package"] if package["name"] == "ruff"
    }
    assert len(locked_versions) == 1

    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    match = re.search(
        r"repo: https://github\.com/astral-sh/ruff-pre-commit\n"
        r"\s+rev: [0-9a-f]{40} # v([^\s]+)",
        config,
    )
    assert match is not None
    assert {match.group(1)} == locked_versions
