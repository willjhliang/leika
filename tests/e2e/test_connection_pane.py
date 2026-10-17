"""What the status badge opens, and what it is measuring.

The arithmetic is pinned in `connectionStats.test.ts`, which needs no browser.
What needs one is the loop: a ping leaving the page, the server answering it,
and the answer coming back as a number a reader can act on. None of that is
observable anywhere but here.
"""

from __future__ import annotations

import re

from playwright.sync_api import Locator, Page, expect

import leika
from leika import _messages

TRIGGER = "[data-leika-connection-trigger]"
POPOVER = "[data-leika-connection-popover]"
ROW = "[data-leika-connection-row]"


def open_connection(page: Page) -> Locator:
    page.locator(TRIGGER).click()
    popover = page.locator(POPOVER)
    expect(popover).to_be_visible(timeout=5_000)
    return popover


def row(popover: Locator, label: str) -> Locator:
    return popover.locator(ROW).filter(has_text=re.compile(f"^{label}"))


def test_the_badge_opens_what_the_connection_is_doing(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    del leika_server
    popover = open_connection(leika_page)

    expect(popover.get_by_text("Connection", exact=True)).to_be_visible()
    # A round trip has to happen before there is anything to say, so the
    # verdict starts as "Measuring..." and is replaced by one.
    expect(row(popover, "Quality")).to_contain_text(re.compile(r"Good|Fair|Poor"), timeout=10_000)
    expect(row(popover, "Latency")).to_contain_text("ms")
    assert page_errors == []


def test_the_page_counts_what_crosses_the_socket(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """Bytes are weighed in the worker, before the buffer is handed on -- a
    count taken after that transfer would read zero every time."""
    leika_server.gui.add_slider("Weight", 0.5, min=0.0, max=1.0, step=0.1)
    popover = open_connection(leika_page)

    # The GUI above arrived over this socket, so the page has received bytes
    # and messages; the pings it is sending are what it has sent.
    expect(row(popover, "Down")).to_contain_text(re.compile(r"\d+(\.\d+)? [kMG]?B total\)"))
    expect(row(popover, "Messages")).to_contain_text(
        re.compile(r"[1-9]\d* in, [1-9]\d* out"), timeout=10_000
    )
    expect(row(popover, "Connected")).to_contain_text(re.compile(r"\d+s"))
    assert page_errors == []


def test_the_answers_to_its_own_pings_go_no_further(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """A pong is the worker's business. Forwarded to the app it would reach the
    message handler, which knows nothing about it and says so in the console."""
    del leika_server
    warnings: list[str] = []
    leika_page.on(
        "console",
        lambda message: warnings.append(message.text) if message.type == "warning" else None,
    )

    popover = open_connection(leika_page)
    expect(row(popover, "Latency")).to_contain_text("ms", timeout=10_000)
    # Several ticks, so this is not merely a race the first one won.
    leika_page.wait_for_timeout(2_500)

    assert [text for text in warnings if "unsupported" in text] == []
    assert page_errors == []


def test_nothing_is_measured_until_the_badge_is_opened(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """Pinging a connection nobody is looking at would be traffic the feature
    invented for itself.

    Counted where the pings land rather than where they leave: the socket is
    in a worker, whose globals the page cannot reach to instrument.
    """
    pings: list[float] = []
    leika_server._websock_server.register_handler(
        _messages.ClientPingMessage,
        lambda client_id, message: pings.append(message.sent_ms),
    )

    leika_page.wait_for_timeout(2_500)
    assert pings == []

    open_connection(leika_page)
    expect(row(leika_page.locator(POPOVER), "Latency")).to_contain_text("ms", timeout=10_000)
    assert len(pings) > 0
    assert page_errors == []


def test_the_badge_still_opens_on_a_phone(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """The bottom sheet's handle is one big button, and a button cannot hold
    another, so the badge sits beside it there rather than inside it."""
    del leika_server
    leika_page.set_viewport_size({"width": 420, "height": 700})
    handle = leika_page.locator("[data-leika-bottom-panel-handle]")
    expect(handle).to_be_visible(timeout=5_000)
    assert handle.locator(TRIGGER).count() == 0

    popover = open_connection(leika_page)
    expect(row(popover, "Latency")).to_contain_text("ms", timeout=10_000)
    # Opening it must not have folded the sheet away underneath.
    expect(handle).to_have_attribute("aria-expanded", "true")
    assert page_errors == []


def test_connection_badge_reports_connection_loss(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """The badge reports a lost connection while the browser tab is hidden."""
    badge = leika_page.locator(TRIGGER)
    label = badge.locator("[data-leika-connection-label]")
    expect(label).to_have_text("Connected")
    expect(badge).to_have_attribute("aria-label", "Connected; connection details")
    # Headless browsers do not consistently hide a page when another one is
    # brought forward. Model a hidden tab, whose closed connection is inactive
    # until it becomes visible again.
    leika_page.evaluate(
        """() => Object.defineProperty(document, "visibilityState", {
            configurable: true,
            value: "hidden",
        })"""
    )
    leika_server.stop()
    expect(label).to_have_text("Inactive", timeout=15_000)
    expect(badge).to_have_attribute("aria-label", "Inactive; connection details")
    assert page_errors == []
