"""Check that a release tag matches the version of the built distributions."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

WHEEL_NAME = re.compile(r"^leika-(?P<version>.+?)-py3-none-any\.whl$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="release tag, for example v0.1.0")
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    match = WHEEL_NAME.match(args.wheel.name)
    if match is None:
        raise SystemExit(f"{args.wheel.name} is not a Leika wheel filename")

    version = match.group("version")
    expected = f"v{version}"
    if args.tag != expected:
        raise SystemExit(
            f"release tag {args.tag} does not match the packaged version {version}. "
            f"Tag the release {expected}, or update __version__ in "
            f"src/leika/__init__.py and rerun sync_client_server.py."
        )

    print(f"release tag {args.tag} matches packaged version {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
