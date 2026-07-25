"""Check local Markdown links and compile every shipped example."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"\[[^]]*]\(([^)]+)\)")


def main() -> int:
    errors: list[str] = []
    markdown_files = [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "examples/README.md",
        ROOT / "tests/e2e/README.md",
        *sorted((ROOT / "docs").glob("*.md")),
    ]
    for source in markdown_files:
        text = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"{source.relative_to(ROOT)}: missing {target}")

    for example in sorted((ROOT / "examples").glob("*.py")):
        try:
            compile(example.read_text(encoding="utf-8"), str(example), "exec")
        except SyntaxError as error:
            errors.append(f"{example.relative_to(ROOT)}: {error}")

    if errors:
        print("\n".join(errors))
        return 1
    print(f"checked {len(markdown_files)} Markdown files and all examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
