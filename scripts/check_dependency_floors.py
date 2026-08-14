"""Assert that lowest-direct CI actually exercises declared dependency floors."""

from __future__ import annotations

import argparse
from importlib.metadata import version

EXPECTED = {
    "msgspec": "0.18.6",
    "numpy": "1.21.3",
    "pillow": "12.3.0",
    "pygments": "2.20.0",
    "rich": "13.3.3",
    "typing-extensions": "4.4.0",
    "websockets": "13.1",
    "zstandard": "0.20.0",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pytest",
        action="store_true",
        help="Run the non-browser test suite after checking installed versions.",
    )
    args = parser.parse_args()

    installed = {name: version(name) for name in EXPECTED}
    if installed != EXPECTED:
        mismatches = [
            f"{name}: installed {installed[name]}, expected {expected}"
            for name, expected in EXPECTED.items()
            if installed[name] != expected
        ]
        raise SystemExit("dependency-floor resolution drifted:\n" + "\n".join(mismatches))
    print(f"direct dependency floors: {installed}")

    if args.pytest:
        import pytest

        return pytest.main(["--ignore=tests/e2e"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
