"""Check local documentation links and compile shipped Python snippets."""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
_EXTERNAL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_FENCE = re.compile(r"^\s*([\`~]{3,})(.*)$")
_REFERENCE_DEFINITION = re.compile(
    r"^\s{0,3}\[[^]]+\]:\s*(<(?P<angle>(?:\\.|[^>])*)>|(?P<plain>(?:\\.|\S)+))"
)
_MYST_INCLUDE = re.compile(r"^\{(?:include|literalinclude)\}\s+(.+?)\s*$")
_RST_DIRECTIVE = re.compile(
    r"^\s*\.\.\s+(?:include|literalinclude|image|figure|download)::\s+(.+?)\s*$"
)
_RST_EXPLICIT_LINK = re.compile(r"\`[^\`\n]*?<((?:\\.|[^>\n])+)>\`_+")
_RST_ROLE_LINK = re.compile(r":[\w:-]+:\`[^\`\n]*?<((?:\\.|[^>\n])+)>\`")
_HTML_LINK = re.compile(r"\b(?:href|src)\s*=\s*([\"'])(.*?)\1", re.IGNORECASE)
_MARKDOWN_ESCAPE = re.compile(r"\\([\\\`*_[\]{}()#+\-.!<> ])")


def _documentation_files(root: Path) -> list[Path]:
    files = [path for path in (root / "README.md", root / "CONTRIBUTING.md") if path.is_file()]
    docs = root / "docs"
    if docs.is_dir():
        files.extend(
            path
            for path in docs.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".rst"}
        )
    return sorted(files)


def _unescape_markdown(value: str) -> str:
    return _MARKDOWN_ESCAPE.sub(r"\1", value)


def _inline_markdown_targets(text: str) -> Iterator[str]:
    """Yield inline link/image destinations, including balanced parentheses."""
    index = 0
    while True:
        close_label = text.find("](", index)
        if close_label < 0:
            return
        if close_label and text[close_label - 1] == "\\":
            index = close_label + 2
            continue

        cursor = close_label + 2
        while cursor < len(text) and text[cursor] in " \t\r\n":
            cursor += 1
        if cursor >= len(text):
            return

        if text[cursor] == "<":
            cursor += 1
            destination: list[str] = []
            while cursor < len(text):
                character = text[cursor]
                if character == "\\" and cursor + 1 < len(text):
                    destination.extend((character, text[cursor + 1]))
                    cursor += 2
                    continue
                if character == ">":
                    break
                destination.append(character)
                cursor += 1
            if cursor < len(text):
                yield _unescape_markdown("".join(destination))
                index = cursor + 1
            else:
                index = close_label + 2
            continue

        depth = 0
        destination = []
        while cursor < len(text):
            character = text[cursor]
            if character == "\\" and cursor + 1 < len(text):
                destination.extend((character, text[cursor + 1]))
                cursor += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    break
                depth -= 1
            elif character.isspace() and depth == 0:
                break
            destination.append(character)
            cursor += 1
        if destination:
            yield _unescape_markdown("".join(destination))
        index = max(cursor + 1, close_label + 2)


def _markdown_targets(text: str) -> Iterator[str]:
    """Yield Markdown/MyST destinations while ignoring ordinary fenced code."""
    retained: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if fence_character is not None:
            if (
                match is not None
                and match.group(1)[0] == fence_character
                and len(match.group(1)) >= fence_length
                and not match.group(2).strip()
            ):
                fence_character = None
            retained.append("\n")
            continue
        if match is not None:
            marker, info = match.groups()
            include = _MYST_INCLUDE.fullmatch(info.strip())
            if include is not None:
                yield include.group(1).strip().strip("<>")
            fence_character = marker[0]
            fence_length = len(marker)
            retained.append("\n")
            continue

        definition = _REFERENCE_DEFINITION.match(line)
        if definition is not None:
            yield _unescape_markdown(
                definition.group("angle")
                if definition.group("angle") is not None
                else definition.group("plain")
            )
        retained.append(line)

    visible = "".join(retained)
    yield from _inline_markdown_targets(visible)
    for match in _HTML_LINK.finditer(visible):
        yield html.unescape(match.group(2))


def _rst_targets(text: str) -> Iterator[str]:
    for line in text.splitlines():
        directive = _RST_DIRECTIVE.match(line)
        if directive is not None:
            yield directive.group(1).strip().strip("<>")
    for pattern in (_RST_EXPLICIT_LINK, _RST_ROLE_LINK):
        for match in pattern.finditer(text):
            yield match.group(1)
    for match in _HTML_LINK.finditer(text):
        yield html.unescape(match.group(2))


def _local_target_error(source: Path, raw_target: str, root: Path) -> str | None:
    target = html.unescape(raw_target.strip())
    if not target or target.startswith(("#", "//")):
        return None
    if _WINDOWS_ABSOLUTE.match(target):
        return f"absolute local target {target}"
    if _EXTERNAL_SCHEME.match(target):
        return None
    if "\\" in target:
        return f"non-portable local target {target}"

    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    candidate = Path(target)
    if candidate.is_absolute():
        return f"absolute local target {target}"

    root = root.resolve()
    resolved = (source.parent / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return f"local target escapes repository: {target}"
    if not resolved.is_file():
        return f"missing regular file: {target}"
    return None


def _link_errors(root: Path) -> tuple[list[Path], list[str]]:
    sources = _documentation_files(root)
    errors: list[str] = []
    for source in sources:
        text = source.read_text(encoding="utf-8")
        targets = _markdown_targets(text) if source.suffix.lower() == ".md" else _rst_targets(text)
        for target in targets:
            error = _local_target_error(source, target, root)
            if error is not None:
                errors.append(f"{source.relative_to(root)}: {error}")
    return sources, errors


def _python_fences(text: str) -> Iterator[str]:
    marker: str | None = None
    length = 0
    python = False
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _FENCE.match(line)
        if marker is None:
            if match is not None:
                fence, info = match.groups()
                marker = fence[0]
                length = len(fence)
                python = info.strip().lower() in {"python", "py"}
                lines = []
            continue
        if (
            match is not None
            and match.group(1)[0] == marker
            and len(match.group(1)) >= length
            and not match.group(2).strip()
        ):
            if python:
                yield "".join(lines)
            marker = None
            python = False
            continue
        if python:
            lines.append(line)


def main() -> int:
    documentation, errors = _link_errors(ROOT)
    for source in documentation:
        if source.suffix.lower() != ".md":
            continue
        for number, snippet in enumerate(_python_fences(source.read_text(encoding="utf-8")), 1):
            try:
                compile(snippet, f"{source}#python-{number}", "exec")
            except SyntaxError as error:
                errors.append(f"{source.relative_to(ROOT)} Python block {number}: {error}")

    examples = sorted((ROOT / "examples").glob("*.py"))
    for example in examples:
        try:
            compile(example.read_text(encoding="utf-8"), str(example), "exec")
        except SyntaxError as error:
            errors.append(f"{example.relative_to(ROOT)}: {error}")

    if errors:
        print("\n".join(errors))
        return 1
    print(
        f"checked {len(documentation)} documentation files, "
        f"{len(examples)} examples, and all Markdown Python snippets"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
