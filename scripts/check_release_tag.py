"""Check that a release tag matches the source or built distribution version."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

WHEEL_NAME = re.compile(r"^leika-(?P<version>[^-]+)-py3-none-any\.whl$")
ROOT = Path(__file__).resolve().parents[1]
TAG_NAME = re.compile(r"^v[0-9]+(?:\.[0-9]+){2}(?:[a-zA-Z0-9.+-]*)?$")


def _source_version() -> str:
    source = (ROOT / "src/leika/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    if match is None:
        raise SystemExit("cannot read authoritative Leika version")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, for example v0.1.0")
    parser.add_argument(
        "wheel",
        type=Path,
        nargs="?",
        help="built wheel to verify; omit to check the authoritative source version",
    )
    args = parser.parse_args()

    if TAG_NAME.fullmatch(args.tag) is None:
        raise SystemExit(f"release tag {args.tag!r} is not in vX.Y.Z form")
    if args.wheel is None:
        version = _source_version()
        subject = "source"
    else:
        match = WHEEL_NAME.fullmatch(args.wheel.name)
        if match is None:
            raise SystemExit(f"{args.wheel.name} is not a Leika wheel filename")
        version = match.group("version")
        subject = "packaged"
    expected = f"v{version}"
    if args.tag != expected:
        raise SystemExit(
            f"release tag {args.tag} does not match the {subject} version {version}. "
            f"Tag the release {expected}, or update __version__ in "
            f"src/leika/__init__.py and rerun sync_client_server.py."
        )

    print(f"release tag {args.tag} matches {subject} version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
