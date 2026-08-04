"""Validate the contents of a built Leika source distribution."""

from __future__ import annotations

import argparse
import tarfile
from pathlib import Path, PurePosixPath

REQUIRED = {
    "Makefile",
    "pyproject.toml",
    "sync_client_server.py",
    "src/leika/client/build/index.html",
}
FORBIDDEN_PARTS = {
    ".leika-build.lock",
    ".nodeenv",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}
FORBIDDEN_PREFIXES = {"docs/_build"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist", type=Path)
    args = parser.parse_args()

    with tarfile.open(args.sdist, "r:gz") as archive:
        paths = [PurePosixPath(member.name) for member in archive.getmembers()]

    roots = {path.parts[0] for path in paths if path.parts}
    if len(roots) != 1:
        raise SystemExit(f"expected one top-level directory, found {sorted(roots)}")
    relative = {PurePosixPath(*path.parts[1:]).as_posix() for path in paths if len(path.parts) > 1}

    missing = sorted(REQUIRED - relative)
    if missing:
        raise SystemExit(f"source distribution is missing: {', '.join(missing)}")

    forbidden = sorted(
        path
        for path in relative
        if FORBIDDEN_PARTS.intersection(PurePosixPath(path).parts)
        or any(path == prefix or path.startswith(f"{prefix}/") for prefix in FORBIDDEN_PREFIXES)
    )
    if forbidden:
        raise SystemExit(f"source distribution contains generated files: {forbidden[0]}")

    print(f"source distribution contents OK: {args.sdist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
