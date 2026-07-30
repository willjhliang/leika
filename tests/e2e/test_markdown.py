"""How rendered markdown is spaced.

The renderer is shared: `add_text(markdown=True)` draws with it and so does a
previewed .md file. These drive the GUI form of it, which is the one that has
to sit in a panel row without pushing its neighbours around.
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
