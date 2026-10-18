"""Check the sdist and wheel in a directory (default `dist`) before publishing them."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 5_000_000
BUNDLE = {"leika/client/build/index.html", "leika/client/build/THIRD_PARTY_NOTICES.txt"}


def _check_wheel(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    version = wheel.name.split("-")[1]
    notices = {f"leika/_licenses/{path.name}" for path in (ROOT / "src/leika/_licenses").iterdir()}
    required = BUNDLE | notices | {f"leika-{version}.dist-info/licenses/LICENSE"}
    problems = [f"{wheel.name} is missing {name}" for name in sorted(required - names)]
    # Only the built client belongs in the package: no client sources or node_modules.
    problems += [
        f"{wheel.name} should not contain {name}"
        for name in sorted(names)
        if name.startswith("leika/client/") and name not in BUNDLE
    ]
    return problems


def _check_sdist(sdist: Path) -> list[str]:
    with tarfile.open(sdist) as archive:
        names = {name.partition("/")[2] for name in archive.getnames()}
    required = {f"src/{name}" for name in BUNDLE}
    problems = [f"{sdist.name} is missing {name}" for name in sorted(required - names)]
    problems += [
        f"{sdist.name} should not contain {name}"
        for name in sorted(names)
        if name.startswith(("src/leika/client/src/", "src/leika/client/node_modules/"))
    ]
    return problems


def main() -> int:
    dist = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    wheels = list(dist.glob("leika-*.whl"))
    sdists = list(dist.glob("leika-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit(f"expected one leika wheel and one sdist in {dist}/")
    problems = _check_wheel(wheels[0]) + _check_sdist(sdists[0])
    problems += [
        f"{path.name} is {path.stat().st_size:,} bytes, over the {MAX_BYTES:,}-byte cap"
        for path in (*wheels, *sdists)
        if path.stat().st_size > MAX_BYTES
    ]
    for problem in problems:
        print(problem)
    if not problems:
        print(f"{wheels[0].name} and {sdists[0].name} look complete")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
