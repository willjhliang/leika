"""Markdown content and outbound links in the live browser."""

from __future__ import annotations

from playwright.sync_api import Page, expect

import leika

#: Every construct that used to fail the whole document when markdown was read
#: as MDX: braces are a JavaScript expression there, and `<br>` an
#: unterminated tag. They are what a README written for GitHub contains.
GITHUB_DOC = """\
# Notes

Paths look like `runs/shift{3,6}`, and sets like {3.0, 6.0}.

| what | detail |
|---|---|
| a table cell | first line<br>second line |
"""


def test_a_link_out_of_a_document_carries_no_referrer(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # The one thing about a document the renderer still decides, everything
    # else about it being the stylesheet's. A document can be opened on a file
    # from anywhere, and a link in one is a link out of Leika.
    leika_server.gui.add_text(
        None,
        "[example](https://example.com)",
        editable=False,
        markdown=True,
        multiline=True,
    )
    link = leika_page.get_by_role("link", name="example")
    expect(link).to_be_visible(timeout=15_000)
    rel = link.get_attribute("rel")
    assert rel is not None
    assert {"noreferrer", "noopener"} <= set(rel.split())
    assert page_errors == []


def test_a_document_written_for_github_renders_here(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # The whole document, not a fallback: authors point Leika at the same file
    # GitHub shows, and a brace or a `<br>` in it is text and a line break,
    # not a parse error that costs them the page.
    leika_server.gui.add_text(None, GITHUB_DOC, editable=False, markdown=True, multiline=True)
    expect(leika_page.get_by_role("heading", name="Notes")).to_be_visible(timeout=15_000)

    expect(leika_page.get_by_text("runs/shift{3,6}")).to_be_visible()
    expect(leika_page.get_by_text("and sets like {3.0, 6.0}")).to_be_visible()
    # The table survived, and the cell that carries a `<br>` really broke.
    expect(leika_page.get_by_role("table")).to_be_visible()
    assert leika_page.locator("td br").count() == 1
    assert page_errors == []
