from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from leika._gui_handles import (
    _get_data_url,
    _link_markdown_assets,
    _resolve_markdown_asset_path,
)


@pytest.mark.parametrize(
    "url",
    [
        "../secret.png",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "figure.png:alternate-stream",
        r"\\server\share\secret.png",
    ],
)
def test_markdown_asset_paths_cannot_leave_their_root(tmp_path: Path, url: str) -> None:
    with pytest.raises(ValueError):
        _resolve_markdown_asset_path(tmp_path / "docs", url)


def test_markdown_asset_symlinks_cannot_leave_their_root(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"secret")
    docs.joinpath("linked.png").symlink_to(secret)

    with pytest.raises(ValueError):
        _resolve_markdown_asset_path(docs, "linked.png")


def test_http_backed_markdown_keeps_refused_reference(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    register = Mock()

    with pytest.warns(UserWarning, match="outside image_root"):
        result = _link_markdown_assets(
            "![secret](../secret.png)",
            docs,
            register,
        )

    assert result == "![secret](../secret.png)"
    register.assert_not_called()


def test_inlined_markdown_cannot_read_outside_image_root(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    tmp_path.joinpath("secret.png").write_bytes(b"secret")

    with pytest.warns(UserWarning, match="outside image_root"):
        result = _get_data_url("../secret.png", docs)

    assert result == "../secret.png"
