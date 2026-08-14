from __future__ import annotations

from pathlib import Path

from scripts import check_docs


def test_markdown_scanner_handles_balanced_escaped_titled_and_reference_links() -> None:
    text = r"""
[nested](guide_(draft).md "Guide")
[angle](<name with spaces.md> "Title")
[escaped](close\).md)
![image](image.png)
[reference]: reference.md "Reference title"

```text
[ignored](missing.md)
```
```{include} included.md
```
"""
    assert list(check_docs._markdown_targets(text)) == [
        "reference.md",
        "included.md",
        "guide_(draft).md",
        "name with spaces.md",
        "close).md",
        "image.png",
    ]


def test_recursive_markdown_and_rst_links_are_checked_and_contained(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    nested = root / "docs" / "nested"
    nested.mkdir(parents=True)
    (root / "README.md").write_text("[docs](docs/nested/page.md)\n", encoding="utf-8")
    (nested / "asset.txt").write_text("asset\n", encoding="utf-8")
    (nested / "image.png").write_bytes(b"image")
    (nested / "page.md").write_text(
        "[asset](asset.txt)\n![image](image.png)\n",
        encoding="utf-8",
    )
    (nested / "references.rst").write_text(
        ".. include:: asset.txt\n"
        ".. image:: image.png\n"
        "`asset <asset.txt>`_\n"
        ":download:`asset <asset.txt>`\n",
        encoding="utf-8",
    )

    sources, errors = check_docs._link_errors(root)

    assert {path.relative_to(root).as_posix() for path in sources} == {
        "README.md",
        "docs/nested/page.md",
        "docs/nested/references.rst",
    }
    assert errors == []


def test_link_check_rejects_root_escape_directory_and_nonportable_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    docs = root / "docs"
    docs.mkdir(parents=True)
    (tmp_path / "outside.md").write_text("outside\n", encoding="utf-8")
    (docs / "directory").mkdir()
    (docs / "bad.md").write_text(
        "[escape](../../outside.md)\n"
        "[directory](directory)\n"
        "[backslash](sub\\file.md)\n"
        "[windows](C:\\temp\\file.md)\n",
        encoding="utf-8",
    )

    _, errors = check_docs._link_errors(root)

    assert any("escapes repository" in error for error in errors)
    assert any("missing regular file: directory" in error for error in errors)
    assert any("non-portable local target sub\\file.md" in error for error in errors)
    assert any("absolute local target C:\\temp\\file.md" in error for error in errors)


def test_python_fences_ignore_other_languages_and_compile_quickstart() -> None:
    text = """
```bash
if then
```
```python
with open("example") as stream:
    stream.read()
```
"""
    snippets = list(check_docs._python_fences(text))
    assert len(snippets) == 1
    compile(snippets[0], "<documentation>", "exec")


def test_no_root_tailscale_install_verifies_pinned_archive_before_extracting() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "docs/remote-access.md").read_text(encoding="utf-8")
    download = source.index('curl -fsSLo "$TAILSCALE_ARCHIVE"')
    verify = source.index("sha256sum -c -")
    extract = source.index('tar xzf "$TAILSCALE_ARCHIVE"')

    assert (
        "TAILSCALE_SHA256=ad2cde12f8de95f7b93a1e0401e652291c603d42b9d60a33fb1741eb38ab04d8"
        in source
    )
    assert download < verify < extract
    assert "| tar" not in source
