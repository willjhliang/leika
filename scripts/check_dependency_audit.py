"""Audit the exact locked production dependency set in an isolated environment."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_NAME = "leika"


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _inventory() -> dict[str, str]:
    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if not name:
            raise RuntimeError("installed distribution has no Name metadata")
        canonical = _canonical_name(name)
        if canonical == PROJECT_NAME:
            continue
        installed = distribution.version
        previous = packages.setdefault(canonical, installed)
        if previous != installed:
            raise RuntimeError(
                f"multiple installed versions for {canonical}: {previous}, {installed}"
            )
    if not packages:
        raise RuntimeError("locked production dependency inventory is empty")
    return packages


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_inventory(path: Path, packages: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError(f"inventory target is not a regular file: {path}")
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for name in sorted(packages):
                stream.write(f"{name}=={packages[name]}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_inventory(path: Path, expected_python: str) -> int:
    expected = tuple(int(part) for part in expected_python.split("."))
    if sys.version_info[:2] != expected:
        raise RuntimeError(
            f"dependency inventory uses Python {sys.version_info[0]}.{sys.version_info[1]}, "
            f"expected {expected_python}"
        )

    packages = _inventory()
    _atomic_write_inventory(path, packages)
    print(f"locked {expected_python} production inventory: {len(packages)} distributions -> {path}")
    return 0


def _python_executable(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _implementation_version() -> str:
    info = sys.implementation.version
    value = f"{info.major}.{info.minor}.{info.micro}"
    if info.releaselevel != "final":
        value += f"{info.releaselevel[0]}{info.serial}"
    return value


def _marker_environment() -> dict[str, str]:
    """Return the PEP 508 environment for this exact target interpreter."""
    return {
        "extra": "",
        "implementation_name": sys.implementation.name,
        "implementation_version": _implementation_version(),
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "platform_release": platform.release(),
        "platform_system": platform.system(),
        "platform_version": platform.version(),
        "python_full_version": platform.python_version(),
        "platform_python_implementation": platform.python_implementation(),
        "python_version": ".".join(platform.python_version_tuple()[:2]),
        "sys_platform": sys.platform,
    }


def _canonicalize_requirements(path: Path, marker_environment: dict[str, str]) -> int:
    # ``uv export`` retains every lockfile marker branch. Evaluate those
    # branches in the separately locked audit-tool environment so this list is
    # an independent expectation for the target production environment.
    from packaging.requirements import Requirement

    packages: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line.removesuffix("\\").rstrip())
        if requirement.marker is not None and not requirement.marker.evaluate(marker_environment):
            continue
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != "==" or pins[0].version.endswith(".*"):
            raise RuntimeError(f"locked export is not exactly pinned: {requirement}")
        version = pins[0].version
        canonical = _canonical_name(requirement.name)
        previous = packages.setdefault(canonical, version)
        if previous != version:
            raise RuntimeError(f"active locked export has multiple versions for {canonical}")
    if not packages:
        raise RuntimeError("marker-selected locked export is empty")
    sys.stdout.write("".join(f"{name}=={packages[name]}\n" for name in sorted(packages)))
    return 0


def _audit(python_version: str, extra: str) -> int:
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for the locked dependency audit")

    with tempfile.TemporaryDirectory(prefix="leika-dependency-audit-") as temporary_name:
        temporary = Path(temporary_name)
        exported = temporary / "locked-requirements.txt"
        environment = temporary / "environment"
        audited = temporary / f"{extra}-{python_version}.txt"

        export = [
            uv,
            "export",
            "--quiet",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--python",
            python_version,
            "--output-file",
            str(exported),
        ]
        if extra == "examples":
            export.extend(("--extra", "examples"))
        subprocess.run(export, cwd=ROOT, check=True)
        subprocess.run(
            [uv, "venv", "--quiet", "--python", python_version, str(environment)],
            cwd=ROOT,
            check=True,
        )
        python = _python_executable(environment)
        subprocess.run(
            [
                uv,
                "pip",
                "sync",
                "--quiet",
                "--python",
                str(python),
                "--require-hashes",
                str(exported),
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                str(Path(__file__).resolve()),
                "--inventory",
                str(audited),
                "--expect-python",
                python_version,
            ],
            cwd=ROOT,
            check=True,
        )
        marker_environment = subprocess.run(
            [
                str(python),
                str(Path(__file__).resolve()),
                "--print-marker-environment",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        parsed_environment = json.loads(marker_environment)
        if not isinstance(parsed_environment, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in parsed_environment.items()
        ):
            raise RuntimeError("target interpreter returned an invalid marker environment")
        expected = subprocess.run(
            [
                uv,
                "run",
                "--isolated",
                "--locked",
                "--only-group",
                "audit",
                "python",
                str(Path(__file__).resolve()),
                "--canonicalize",
                str(exported),
                "--marker-environment-json",
                marker_environment,
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        if audited.read_bytes() != expected:
            raise RuntimeError(
                "installed production inventory differs from the marker-selected locked export"
            )
        subprocess.run(
            [
                uv,
                "run",
                "--isolated",
                "--locked",
                "--only-group",
                "audit",
                "pip-audit",
                "--strict",
                "--no-deps",
                "--disable-pip",
                "--progress-spinner",
                "off",
                "--requirement",
                str(audited),
            ],
            cwd=ROOT,
            check=True,
        )
    print(f"no known vulnerabilities: Python {python_version}, {extra} dependencies")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", choices=("3.10", "3.14"), default="3.10")
    parser.add_argument("--extra", choices=("base", "examples"), default="base")
    parser.add_argument("--inventory", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--expect-python", help=argparse.SUPPRESS)
    parser.add_argument("--canonicalize", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--marker-environment-json", help=argparse.SUPPRESS)
    parser.add_argument("--print-marker-environment", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.print_marker_environment:
        print(json.dumps(_marker_environment(), sort_keys=True))
        return 0
    if args.canonicalize is not None:
        if args.marker_environment_json is None:
            parser.error("--canonicalize requires --marker-environment-json")
        marker_environment = json.loads(args.marker_environment_json)
        if not isinstance(marker_environment, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in marker_environment.items()
        ):
            parser.error("--marker-environment-json must be a string mapping")
        return _canonicalize_requirements(args.canonicalize, marker_environment)
    if args.inventory is not None:
        if args.expect_python is None:
            parser.error("--inventory requires --expect-python")
        return _write_inventory(args.inventory, args.expect_python)
    return _audit(args.python, args.extra)


if __name__ == "__main__":
    raise SystemExit(main())
