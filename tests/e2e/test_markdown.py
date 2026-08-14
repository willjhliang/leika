"""How rendered markdown is spaced, and that a real document renders at all.

The renderer is shared: `add_text(markdown=True)` draws with it and so does a
previewed .md file. These drive the GUI form of it, which is the one that has
to sit in a panel row without pushing its neighbours around.

What a document may *contain* is pinned in the client's own
`src/markdown.test.ts`, which can assert against HTML. The one case here is
the end-to-end version of it: a page that the browser really rendered.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

import leika

DOC = """\
# Title

An opening paragraph.

## Section

The text the section names.
"""

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


#: One of every block a document is built from, each preceded by a paragraph
#: so that every one of them has something to be spaced away from.
BLOCKS_DOC = """\
Opening paragraph.

## A heading

Before a list.

- first
- second

Before a quote.

> quoted

Before a fence.

```
code
```

Before a table.

| what | detail |
|---|---|
| a | b |

Before a rule.

---

After the rule.
"""


def _margin_top(page: Page, selector: str) -> float:
    return page.evaluate(
        "(selector) => parseFloat(getComputedStyle(document.querySelector(selector)).marginTop)",
        selector,
    )


def test_a_heading_takes_more_room_above_it_than_below(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    leika_server.gui.add_text(None, DOC, editable=False, markdown=True, multiline=True)
    expect(leika_page.get_by_role("heading", name="Section")).to_be_visible(timeout=15_000)

    heading_gap = _margin_top(leika_page, "h2")
    # Both paragraphs, which carry the ordinary gap between blocks: the one
    # under the opening heading and the one under this section's.
    paragraph_gaps = leika_page.evaluate(
        """() => [...document.querySelectorAll("p")].map(
          (el) => parseFloat(getComputedStyle(el).marginTop),
        )"""
    )

    assert len(paragraph_gaps) == 2
    assert len(set(paragraph_gaps)) == 1, paragraph_gaps
    # The space over a heading belongs to the break it makes; the text under
    # it is what it names, and reads as part of it. Equal spacing on both
    # sides would leave the heading floating between two blocks.
    assert heading_gap > paragraph_gaps[0]
    assert page_errors == []


def test_a_document_opening_with_a_heading_starts_flush(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # Otherwise every markdown row in a panel would begin with a gap that the
    # row above it has to absorb.
    leika_server.gui.add_text(None, DOC, editable=False, markdown=True, multiline=True)
    expect(leika_page.get_by_role("heading", name="Title")).to_be_visible(timeout=15_000)

    assert _margin_top(leika_page, "h1") == 0.0
    assert page_errors == []


def test_every_block_carries_its_own_gap_above_and_none_below(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # The spacing rule the whole stylesheet follows. A block that only had the
    # following paragraph's gap under it would sit against the text above it,
    # which is what a table and a rule used to do.
    leika_server.gui.add_text(None, BLOCKS_DOC, editable=False, markdown=True, multiline=True)
    expect(leika_page.get_by_role("heading", name="A heading")).to_be_visible(timeout=15_000)

    spacing = leika_page.evaluate(
        """() => Object.fromEntries(
          ["h2", "ul", "blockquote", "pre", "table", "hr"].map((tag) => {
            // A table is wrapped in the box it scrolls inside, and typeset
            // puts the space above a block on whichever element is the block.
            const el = tag === "table"
              ? document.querySelector(".typeset-scroll")
              : document.querySelector(tag);
            const style = getComputedStyle(el);
            return [tag, [parseFloat(style.marginTop), parseFloat(style.marginBottom)]];
          }),
        )"""
    )

    for tag, (above, below) in spacing.items():
        assert above > 0.0, (tag, spacing)
        assert below == 0.0, (tag, spacing)
    # A break in the document takes more room than a continuation of it, and a
    # rule -- which is nothing but the break -- takes the most of all.
    assert spacing["hr"][0] > spacing["h2"][0]
    assert spacing["h2"][0] > spacing["ul"][0]
    assert page_errors == []


def test_text_is_led_the_same_wherever_it_sits_in_the_document(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # A list item, a quote and a paragraph are all prose and are read the same
    # way. Only the document says how far apart its lines are: left to
    # inherit, these would take the leading of the UI around them, which is
    # set for labels beside inputs and reads tighter than the prose above.
    leika_server.gui.add_text(None, BLOCKS_DOC, editable=False, markdown=True, multiline=True)
    expect(leika_page.get_by_role("heading", name="A heading")).to_be_visible(timeout=15_000)

    leading = leika_page.evaluate(
        """() => Object.fromEntries(
          ["p", "li", "td", "pre", "blockquote", "h2"].map((tag) => {
            const style = getComputedStyle(document.querySelector(tag));
            return [tag, parseFloat(style.lineHeight) / parseFloat(style.fontSize)];
          }),
        )"""
    )

    prose = [leading["p"], leading["li"], leading["blockquote"]]
    assert max(prose) - min(prose) < 0.01, leading
    # A heading is short and large; the body's spacing would pull its own two
    # lines apart.
    assert leading["h2"] < leading["p"]
    # And what is not prose is set tighter than it. A cell is found by the
    # column it is under, and a line of code is read as a line rather than as
    # part of a paragraph, so neither is helped by the room between lines that
    # keeps the eye on a running text.
    assert leading["td"] < leading["p"], leading
    assert leading["pre"] < leading["p"], leading
    assert page_errors == []


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
