from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from leika._markdown import _link_markdown_assets
from leika._transport._http_assets import HttpAsset


@pytest.mark.parametrize("reference", ["../figure.png", "absolute", "symlink"])
def test_markdown_assets_resolve_paths_outside_the_document_directory(
    tmp_path: Path, reference: str
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    figure = tmp_path / "figure.png"
    figure.write_bytes(b"image")
    if reference == "absolute":
        reference = str(figure)
    elif reference == "symlink":
        docs.joinpath("linked.png").symlink_to(figure)
        reference = "linked.png"
    register = Mock(return_value=HttpAsset("/asset/figure", (4, 3)))

    linked = _link_markdown_assets(f"![figure]({reference})", docs, register)

    assert linked == "![figure](/asset/figure?w=4&h=3)"
    register.assert_called_once_with(figure.resolve())


@pytest.mark.parametrize("reference", ["../figure.png", "../figure%2Epng"])
def test_markdown_loads_parent_directory_images(tmp_path: Path, reference: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    figure = tmp_path / "figure.png"
    figure.write_bytes(b"image")
    register = Mock(return_value=HttpAsset("/asset/figure", None))

    linked = _link_markdown_assets(f"![figure]({reference})", docs, register)

    assert linked == "![figure](/asset/figure)"
    assert register.call_args.args[0] == figure.resolve()


@pytest.mark.parametrize("failure", [FileNotFoundError("missing"), ValueError("too large")])
def test_markdown_keeps_image_references_that_cannot_be_registered(
    tmp_path: Path, failure: Exception
) -> None:
    register = Mock(side_effect=failure)
    with pytest.warns(UserWarning, match="Failed to read image"):
        linked = _link_markdown_assets("![missing](../missing.png)", tmp_path, register)
    assert linked == "![missing](../missing.png)"


def test_markdown_rewriter_handles_balanced_escaped_and_angle_destinations(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    filenames = ("plot_(1).png", "close).png", "name with spaces.png")
    for filename in filenames:
        (docs / filename).write_bytes(b"image")
    registered: list[Path] = []

    def register(path: Path) -> HttpAsset:
        registered.append(path)
        return HttpAsset(f"/asset/{len(registered)}", None)

    source = (
        "![balanced](plot_(1).png)\n"
        r"![escaped](close\).png)"
        "\n"
        '![angle](<name with spaces.png> "a title")'
    )
    rewritten = _link_markdown_assets(source, docs, register)

    assert rewritten == (
        '![balanced](/asset/1)\n![escaped](/asset/2)\n![angle](</asset/3> "a title")'
    )
    assert [path.name for path in registered] == list(filenames)


def test_markdown_rewriter_ignores_inline_and_fenced_code(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "image.png").write_bytes(b"image")
    calls: list[Path] = []

    def register(path: Path) -> HttpAsset:
        calls.append(path)
        return HttpAsset("/asset/image", None)

    source = "`![inline](image.png)`\n```markdown\n![fenced](image.png)\n```\n![visible](image.png)"
    rewritten = _link_markdown_assets(source, docs, register)

    assert rewritten.startswith("`![inline](image.png)`\n```markdown\n![fenced](image.png)\n```\n")
    assert rewritten.endswith("![visible](/asset/image)")
    assert calls == [(docs / "image.png").resolve()]


def test_markdown_rewriter_only_loads_true_relative_file_destinations(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "http-chart.png").write_bytes(b"image")
    calls: list[Path] = []

    def register(path: Path) -> HttpAsset:
        calls.append(path)
        return HttpAsset("/asset/chart", None)

    source = " ".join(
        (
            "![local](http-chart.png)",
            "![web](https://example.com/image.png)",
            "![mail](mailto:image@example.com)",
            "![custom](example+asset:value)",
            "![network](//example.com/image.png)",
            "![fragment](#figure)",
        )
    )
    rewritten = _link_markdown_assets(source, docs, register)

    assert rewritten.startswith("![local](/asset/chart)")
    assert "![web](https://example.com/image.png)" in rewritten
    assert "![mail](mailto:image@example.com)" in rewritten
    assert "![custom](example+asset:value)" in rewritten
    assert "![network](//example.com/image.png)" in rewritten
    assert "![fragment](#figure)" in rewritten
    assert calls == [(docs / "http-chart.png").resolve()]
