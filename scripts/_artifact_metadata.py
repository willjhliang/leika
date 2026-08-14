"""Compare built core metadata with the authoritative ``pyproject.toml``."""

from __future__ import annotations

from collections import Counter
from email.message import Message
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
SINGLETON_FIELDS = ("Name", "Version", "Requires-Python", "License-Expression")


def project_metadata() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        return tomllib.load(stream)["project"]


def _requirement_without_marker(requirement: Requirement) -> str:
    value = canonicalize_name(requirement.name)
    if requirement.extras:
        value += (
            "[" + ",".join(sorted(canonicalize_name(extra) for extra in requirement.extras)) + "]"
        )
    if requirement.url is not None:
        value += f" @ {requirement.url}"
    else:
        value += str(requirement.specifier)
    return value


def canonical_requirement(value: str) -> str:
    requirement = Requirement(value)
    normalized = _requirement_without_marker(requirement)
    if requirement.marker is not None:
        normalized += f"; {requirement.marker}"
    return normalized


def expected_requires_dist(project: dict[str, Any] | None = None) -> list[str]:
    project = project_metadata() if project is None else project
    expected: list[str] = []
    for value in project.get("dependencies", []):
        expected.append(canonical_requirement(value))
    for extra, values in project.get("optional-dependencies", {}).items():
        normalized_extra = canonicalize_name(extra)
        for value in values:
            requirement = Requirement(value)
            marker = f"extra == '{normalized_extra}'"
            if requirement.marker is not None:
                marker = f"({requirement.marker}) and {marker}"
            expected.append(
                canonical_requirement(f"{_requirement_without_marker(requirement)}; {marker}")
            )
    duplicates = sorted(value for value, count in Counter(expected).items() if count > 1)
    if duplicates:
        raise RuntimeError(f"pyproject declares duplicate requirements: {duplicates}")
    return sorted(expected)


def expected_extras(project: dict[str, Any] | None = None) -> list[str]:
    project = project_metadata() if project is None else project
    extras = [canonicalize_name(value) for value in project.get("optional-dependencies", {})]
    if len(extras) != len(set(extras)):
        raise RuntimeError("pyproject declares extras that normalize to the same name")
    return sorted(extras)


def expected_project_urls(project: dict[str, Any] | None = None) -> dict[str, str]:
    project = project_metadata() if project is None else project
    return {label: value for label, value in project.get("urls", {}).items()}


def _mismatch(label: str, field: str, expected: object, actual: object) -> SystemExit:
    return SystemExit(
        f"{label} {field} does not match pyproject: expected {expected!r}, got {actual!r}"
    )


def validate_metadata(message: Message, *, version: str, label: str) -> None:
    """Require exact dependency, extra, classifier, URL, and core field metadata."""
    project = project_metadata()
    singleton_expected = {
        "Name": project["name"],
        "Version": version,
        "Requires-Python": project["requires-python"],
        "License-Expression": project["license"],
    }
    for field in SINGLETON_FIELDS:
        values = message.get_all(field, [])
        if len(values) != 1:
            raise SystemExit(f"{label} must contain exactly one {field} field; found {len(values)}")
        if values[0] != singleton_expected[field]:
            raise _mismatch(label, field, singleton_expected[field], values[0])

    try:
        requirements = [
            canonical_requirement(value) for value in message.get_all("Requires-Dist", [])
        ]
    except InvalidRequirement as error:
        raise SystemExit(f"{label} contains invalid Requires-Dist: {error}") from None
    if len(requirements) != len(set(requirements)):
        raise SystemExit(f"{label} contains duplicate normalized Requires-Dist fields")
    expected_requirements = expected_requires_dist(project)
    if sorted(requirements) != expected_requirements:
        raise _mismatch(label, "Requires-Dist", expected_requirements, sorted(requirements))

    extras = [canonicalize_name(value) for value in message.get_all("Provides-Extra", [])]
    if len(extras) != len(set(extras)):
        raise SystemExit(f"{label} contains duplicate normalized Provides-Extra fields")
    expected_extra_values = expected_extras(project)
    if sorted(extras) != expected_extra_values:
        raise _mismatch(label, "Provides-Extra", expected_extra_values, sorted(extras))

    classifiers = message.get_all("Classifier", [])
    if len(classifiers) != len(set(classifiers)):
        raise SystemExit(f"{label} contains duplicate Classifier fields")
    expected_classifiers = sorted(project.get("classifiers", []))
    if sorted(classifiers) != expected_classifiers:
        raise _mismatch(label, "Classifier", expected_classifiers, sorted(classifiers))

    urls: dict[str, str] = {}
    for value in message.get_all("Project-URL", []):
        if "," not in value:
            raise SystemExit(f"{label} contains malformed Project-URL: {value!r}")
        name, url = (part.strip() for part in value.split(",", 1))
        key = name.casefold()
        if not name or not url or key in urls:
            raise SystemExit(f"{label} contains duplicate or malformed Project-URL: {value!r}")
        urls[key] = url
    expected_urls = {name.casefold(): url for name, url in expected_project_urls(project).items()}
    if urls != expected_urls:
        raise _mismatch(label, "Project-URL", expected_urls, urls)
