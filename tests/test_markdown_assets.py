from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from leika import _markdown as markdown_impl
from leika import infra
from leika._markdown import (
    _get_data_url,
    _link_markdown_assets,
    _parse_markdown,
    _resolve_markdown_asset,
)
from leika.infra._http_assets import HttpAsset


def _png_header(width: int = 1, height: int = 1) -> bytes:
    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + len(ihdr).to_bytes(4, "big")
        + b"IHDR"
        + ihdr
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IDAT\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\x00\x00\x00\x00"
    )


def test_markdown_asset_resolver_captures_canonical_identity(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    path = docs / "figure.png"
    payload = b"image"
    path.write_bytes(payload)

    resolved = _resolve_markdown_asset(docs, "figure.png")

    assert resolved.path == path.resolve()
    assert os.path.samestat(resolved.metadata, path.stat())
    assert resolved.metadata.st_size == len(payload)


@pytest.mark.parametrize("reference", ["../figure.png", "absolute", "symlink"])
def test_markdown_assets_resolve_paths_outside_the_document_directory(
    tmp_path: Path, reference: str
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    figure = tmp_path / "figure.png"
    figure.write_bytes(_png_header())
    if reference == "absolute":
        reference = str(figure)
    elif reference == "symlink":
        docs.joinpath("linked.png").symlink_to(figure)
        reference = "linked.png"

    resolved = _resolve_markdown_asset(docs, reference)

    assert resolved.path == figure.resolve()
    assert os.path.samestat(resolved.metadata, figure.stat())


@pytest.mark.parametrize("reference", ["../figure.png", "../figure%2Epng"])
def test_markdown_loads_parent_directory_images(tmp_path: Path, reference: str) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    figure = tmp_path / "figure.png"
    figure.write_bytes(_png_header())
    register = Mock(return_value=HttpAsset("/asset/figure", None))

    linked = _link_markdown_assets(f"![figure]({reference})", docs, register)
    inlined = _get_data_url(reference, docs)

    assert linked == "![figure](/asset/figure)"
    assert register.call_args.args[0] == figure.resolve()
    assert inlined.startswith("data:image/png;base64,")


def test_markdown_keeps_missing_image_references(tmp_path: Path) -> None:
    register = Mock()
    with pytest.warns(UserWarning, match="Failed to read image"):
        linked = _link_markdown_assets("![missing](../missing.png)", tmp_path, register)
    with pytest.warns(UserWarning, match="Failed to read image"):
        inlined = _get_data_url("../missing.png", tmp_path)

    assert linked == "![missing](../missing.png)"
    assert inlined == "../missing.png"
    register.assert_not_called()


def test_inlined_markdown_refuses_one_oversized_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    docs.joinpath("large.png").write_bytes(_png_header())
    monkeypatch.setattr(markdown_impl, "_MARKDOWN_INLINE_MAX_ASSET_BYTES", 4)

    with pytest.warns(UserWarning, match="byte limit"):
        result = _get_data_url("large.png", docs)

    assert result == "large.png"


def test_inlined_markdown_enforces_one_aggregate_output_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    docs.joinpath("one.png").write_bytes(_png_header())
    docs.joinpath("two.png").write_bytes(_png_header())
    monkeypatch.setattr(markdown_impl, "_MARKDOWN_INLINE_MAX_TOTAL_BYTES", 100)

    with pytest.warns(UserWarning, match="byte limit"):
        result = _parse_markdown("![one](one.png) ![two](two.png)", docs)

    assert "![one](data:image/png;base64," in result
    assert result.endswith("![two](two.png)")


def test_markdown_rewriter_handles_balanced_escaped_and_angle_destinations(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    filenames = ("plot_(1).png", "close).png", "name with spaces.png")
    for filename in filenames:
        (docs / filename).write_bytes(b"image")
    registered: list[Path] = []

    def register(path: Path, _: object) -> HttpAsset:
        registered.append(path)
        return HttpAsset(f"/asset/{len(registered)}", None)

    source = (
        "![balanced](plot_(1).png)\n"
        r"![escaped](close\).png)"
        "\n"
        '![angle](<name with spaces.png> "a title")'
    )
    rewritten = _link_markdown_assets(source, docs, register)  # type: ignore[arg-type]

    assert rewritten == (
        '![balanced](/asset/1)\n![escaped](/asset/2)\n![angle](</asset/3> "a title")'
    )
    assert [path.name for path in registered] == list(filenames)


def test_markdown_rewriter_ignores_inline_and_fenced_code(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "image.png").write_bytes(b"image")
    calls: list[Path] = []

    def register(path: Path, _: object) -> HttpAsset:
        calls.append(path)
        return HttpAsset("/asset/image", None)

    source = "`![inline](image.png)`\n```markdown\n![fenced](image.png)\n```\n![visible](image.png)"
    rewritten = _link_markdown_assets(source, docs, register)  # type: ignore[arg-type]

    assert rewritten.startswith("`![inline](image.png)`\n```markdown\n![fenced](image.png)\n```\n")
    assert rewritten.endswith("![visible](/asset/image)")
    assert calls == [docs / "image.png"]


def test_markdown_rewriter_only_loads_true_relative_file_destinations(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "http-chart.png").write_bytes(b"image")
    calls: list[Path] = []

    def register(path: Path, _: object) -> HttpAsset:
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
    rewritten = _link_markdown_assets(source, docs, register)  # type: ignore[arg-type]

    assert rewritten.startswith("![local](/asset/chart)")
    assert "![web](https://example.com/image.png)" in rewritten
    assert "![mail](mailto:image@example.com)" in rewritten
    assert "![custom](example+asset:value)" in rewritten
    assert "![network](//example.com/image.png)" in rewritten
    assert "![fragment](#figure)" in rewritten
    assert calls == [docs / "http-chart.png"]


@pytest.mark.parametrize("mode", ["inline", "registered"])
def test_markdown_asset_identity_rejects_post_resolution_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "image.png"
    source.write_bytes(b"inside")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"secret")
    displaced = tmp_path / "inside.png"
    original_resolve = markdown_impl._resolve_markdown_asset
    swapped = False

    def resolve_then_swap(root: Path, url: str) -> object:
        nonlocal swapped
        resolved = original_resolve(root, url)
        if not swapped:
            swapped = True
            source.rename(displaced)
            try:
                source.symlink_to(outside)
            except (NotImplementedError, OSError):
                pytest.skip("symlink creation is unavailable on this platform")
        return resolved

    monkeypatch.setattr(markdown_impl, "_resolve_markdown_asset", resolve_then_swap)
    with pytest.warns(UserWarning, match="Failed to read image"):
        if mode == "inline":
            rewritten = _parse_markdown("![image](image.png)", docs)
        else:
            server = infra.WebsockServer("127.0.0.1", 0, verbose=False)

            def register(path: Path, metadata: object) -> HttpAsset:
                return server.register_http_asset(
                    path,
                    _expected_metadata=metadata,  # type: ignore[arg-type]
                )

            rewritten = _link_markdown_assets(
                "![image](image.png)",
                docs,
                register,
            )

    assert swapped
    assert rewritten == "![image](image.png)"


def test_http_backed_markdown_keeps_asset_when_registration_rejects_size(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "large.png").write_bytes(b"large")

    def reject(_: Path, __: object) -> HttpAsset:
        raise ValueError("asset too large")

    with pytest.warns(UserWarning, match="Failed to read image"):
        rewritten = _link_markdown_assets("![large](large.png)", docs, reject)  # type: ignore[arg-type]
    assert rewritten == "![large](large.png)"


def test_inline_markdown_snapshot_rejects_same_size_in_place_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "image.png"
    source.write_bytes(_png_header())
    replacement = bytearray(source.read_bytes())
    replacement[-1] ^= 1
    real_fstat = markdown_impl.os.fstat
    calls = 0

    def rewrite_between_descriptor_stats(descriptor: int) -> os.stat_result:
        nonlocal calls
        metadata = real_fstat(descriptor)
        calls += 1
        if calls == 2:
            source.write_bytes(replacement)
            timestamp = metadata.st_mtime_ns + 1_000_000_000
            os.utime(source, ns=(timestamp, timestamp))
        return metadata if calls == 2 else real_fstat(descriptor)

    monkeypatch.setattr(markdown_impl.os, "fstat", rewrite_between_descriptor_stats)
    with pytest.warns(UserWarning, match="Failed to read image"):
        assert _get_data_url("image.png", docs) == "image.png"


def test_inline_markdown_uses_content_derived_image_mime(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    misleading = docs / "picture.svg"
    misleading.write_bytes(_png_header())

    data_url = _get_data_url("picture.svg", docs)
    assert data_url.startswith("data:image/png;base64,")
    assert "image/svg" not in data_url
