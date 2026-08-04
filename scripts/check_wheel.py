"""Validate Leika wheel contents and size."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

MAX_WHEEL_BYTES = 5_000_000
# Browser-client notices that must ship with the wheel. A truncated or
# placeholder file is treated as missing.
MIN_LICENSE_BYTES = 500
REQUIRED_NOTICES = (
    "leika/_licenses/shadcn-ui-LICENSE.md",
    "leika/_licenses/shadcn-ui-PROVENANCE.md",
    "leika/_licenses/shadcn-io-PROVENANCE.md",
    "leika/_licenses/base-ui-LICENSE.txt",
    "leika/_licenses/almarai-OFL.txt",
    "leika/_licenses/geist-OFL.txt",
    "leika/_licenses/lucide-LICENSE.txt",
    "leika/_licenses/cmdk-next-themes-MIT-LICENSE.txt",
    "leika/_licenses/zstddec-LICENSE.txt",
)
FORBIDDEN_PARTS = {
    "node_modules",
    ".nodeenv",
    "ThreeAssets.tsx",
    "GaussianSplats.tsx",
    "_scene_api.py",
    "_scene_handles.py",
    "_tunnel.py",
    "extras",
    "transforms",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()

    size = args.wheel.stat().st_size
    if size >= MAX_WHEEL_BYTES:
        raise SystemExit(f"{args.wheel} is {size:,} bytes; limit is {MAX_WHEEL_BYTES:,} bytes")

    with zipfile.ZipFile(args.wheel) as archive:
        names = archive.namelist()
        missing_notices = [path for path in REQUIRED_NOTICES if path not in names]
        if missing_notices:
            raise SystemExit(
                "wheel does not contain required browser-client licenses/provenance: "
                + ", ".join(missing_notices)
            )
        truncated = [
            path for path in REQUIRED_NOTICES if len(archive.read(path)) < MIN_LICENSE_BYTES
        ]
        if truncated:
            raise SystemExit(
                "wheel contains incomplete licenses/provenance: " + ", ".join(truncated)
            )
    if not any(name.endswith("leika/client/build/index.html") for name in names):
        raise SystemExit("wheel does not contain the built browser client")
    unexpected_client_files = [
        name for name in names if "/client/" in name and "/client/build/" not in name
    ]
    if unexpected_client_files:
        raise SystemExit(
            "wheel contains raw client-development files: " + ", ".join(unexpected_client_files)
        )
    forbidden = [
        name for name in names if any(part in FORBIDDEN_PARTS for part in Path(name).parts)
    ]
    if forbidden:
        raise SystemExit("wheel contains forbidden development/3D files: " + ", ".join(forbidden))
    print(f"{args.wheel}: {size:,} bytes, {len(names)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
