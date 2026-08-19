from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

import leika

from .utils import find_gui_row


@pytest.fixture()
def browser_context_args(browser_context_args: dict) -> dict:
    return {**browser_context_args, "reduced_motion": "no-preference"}


def test_overflowing_read_only_text_scrolls_only_while_hovered(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    long_value = "A read-only value long enough to overflow its narrow control panel row"
    summary = leika_server.gui.add_text("Summary", long_value, editable=False)
    leika_server.gui.add_text("Result", "OK", editable=False)

    long_text = find_gui_row(leika_page, "Summary").locator(
        "[data-leika-text-reading] [data-leika-hover-scroll]"
    )
    short_text = find_gui_row(leika_page, "Result").locator(
        "[data-leika-text-reading] [data-leika-hover-scroll]"
    )
    content = long_text.locator("[data-leika-hover-scroll-content]")

    expect(long_text).to_have_attribute("data-leika-hover-scroll-overflow", "")
    expect(short_text).not_to_have_attribute("data-leika-hover-scroll-overflow", "")
    assert content.evaluate("element => element.scrollWidth > element.parentElement.clientWidth")
    expect(long_text).to_have_css("overflow", "hidden")
    expect(long_text).not_to_have_attribute("data-leika-hover-scroll-active", "")

    long_text.hover()
    expect(long_text).to_have_attribute("data-leika-hover-scroll-active", "")
    handle = content.element_handle()
    assert handle is not None
    leika_page.wait_for_function(
        """element => {
          const transform = getComputedStyle(element).transform;
          return transform !== "none" && new DOMMatrixReadOnly(transform).m41 < -20;
        }""",
        arg=handle,
    )

    # Reconciliation owns content and geometry changes independently of pointer
    # events. Replacing the words, removing overflow, and restoring it all happen
    # beneath the same stationary pointer.
    replacement = "A different read-only value that still overflows the same narrow row"
    summary.value = replacement
    expect(content).to_have_text(replacement)
    assert long_text.evaluate("element => element.matches(':hover')")
    expect(long_text).to_have_attribute("data-leika-hover-scroll-active", "")

    summary.value = "OK"
    expect(content).to_have_text("OK")
    expect(long_text).not_to_have_attribute("data-leika-hover-scroll-overflow", "")
    expect(long_text).not_to_have_attribute("data-leika-hover-scroll-active", "")
    expect(content).to_have_css("transform", "none")

    summary.value = long_value
    expect(content).to_have_text(long_value)
    expect(long_text).to_have_attribute("data-leika-hover-scroll-overflow", "")
    expect(long_text).to_have_attribute("data-leika-hover-scroll-active", "")
    leika_page.wait_for_function(
        """element => {
          const transform = getComputedStyle(element).transform;
          return transform !== "none" && new DOMMatrixReadOnly(transform).m41 < -2;
        }""",
        arg=handle,
    )

    leika_page.mouse.move(800, 650)
    expect(long_text).not_to_have_attribute("data-leika-hover-scroll-active", "")
    expect(content).to_have_css("transform", "none")
    assert page_errors == []


def test_checklist_and_open_selection_option_use_the_same_hover_cycle(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    value = "A shared long value that overflows both checklist and selection rows"
    leika_server.gui.add_checklist("Tasks", [value], frozen=True)
    leika_server.gui.add_dropdown("Choice", options=("Short", value))

    def expect_shared_cycle(surface) -> None:
        expect(surface).to_have_attribute("data-leika-hover-scroll-overflow", "")
        surface.hover()
        expect(surface).to_have_attribute("data-leika-hover-scroll-active", "")
        content = surface.locator("[data-leika-hover-scroll-content]")
        handle = content.element_handle()
        assert handle is not None
        leika_page.wait_for_function(
            """element => {
              const transform = getComputedStyle(element).transform;
              return transform !== "none" && new DOMMatrixReadOnly(transform).m41 < -2;
            }""",
            arg=handle,
        )
        leika_page.mouse.move(800, 650)
        expect(surface).not_to_have_attribute("data-leika-hover-scroll-active", "")

    checklist = find_gui_row(leika_page, "Tasks").locator(
        "[data-leika-checklist-entry] [data-leika-hover-scroll]"
    )
    expect_shared_cycle(checklist)

    find_gui_row(leika_page, "Choice").locator('[data-slot="select-trigger"]').click()
    option = leika_page.get_by_role("option", name=value, exact=True)
    expect(option).to_be_visible()
    expect_shared_cycle(option.locator("[data-leika-hover-scroll]"))
    assert page_errors == []


def test_editable_radio_text_scrolls_on_hover_but_clicks_from_its_prefix(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    value = "An editable value long enough to travel well beyond its narrow field"
    leika_server.gui.add_radio_list("Editable", [value])

    field = leika_page.locator("[data-leika-radio-list-entry]")
    expect(field).to_have_attribute("data-leika-hover-scroll-input", "")
    assert field.evaluate("input => input.scrollWidth > input.clientWidth")
    expect(field).to_have_css("text-overflow", "ellipsis")

    field.hover()
    expect(field).to_have_attribute("data-leika-hover-scroll-active", "")
    expect(field).to_have_css("text-overflow", "clip")
    handle = field.element_handle()
    assert handle is not None
    leika_page.wait_for_function("input => input.scrollLeft > 20", arg=handle)
    assert field.evaluate("input => input.scrollLeft") > 20

    # The moving suffix is only paint for reading. Pointer-down restores the
    # field before the native input performs caret hit-testing.
    field.click(position={"x": 34, "y": 12})
    assert field.evaluate("input => input === document.activeElement")
    assert field.evaluate("input => input.selectionStart") <= 1
    assert field.evaluate("input => input.scrollLeft") < 1

    expect(field).not_to_have_attribute("data-leika-hover-scroll-active", "")
    expect(field).to_have_css("text-overflow", "ellipsis")
    # Focus keeps ownership of the viewport; hover animation does not resume
    # underneath the caret.
    leika_page.wait_for_timeout(800)
    assert field.evaluate("input => input.scrollLeft") < 1

    # Once focused, the native viewport belongs to the field. A pointer-down
    # must not reset a manually scrolled suffix or move its selection.
    focused = field.evaluate(
        """input => {
          const end = input.value.length;
          input.setSelectionRange(end, end);
          input.scrollLeft = input.scrollWidth;
          return {
            scrollLeft: input.scrollLeft,
            selectionStart: input.selectionStart,
            selectionEnd: input.selectionEnd,
          };
        }"""
    )
    assert focused["scrollLeft"] > 20
    field.dispatch_event(
        "pointerdown",
        {"bubbles": True, "cancelable": True, "pointerType": "mouse"},
    )
    assert (
        field.evaluate(
            """input => ({
          scrollLeft: input.scrollLeft,
          selectionStart: input.selectionStart,
          selectionEnd: input.selectionEnd,
        })"""
        )
        == focused
    )

    field.press("Tab")
    leika_page.wait_for_timeout(50)
    assert field.evaluate("input => input.scrollLeft") < 1

    # Blurring under the stationary pointer gives hover ownership back. A
    # later keyboard/programmatic focus may reset that owned viewport, while
    # the already-focused pointer-down above remains untouched.
    expect(field).to_have_attribute("data-leika-hover-scroll-active", "")
    leika_page.wait_for_function("input => input.scrollLeft > 20", arg=handle)
    field.focus()
    expect(field).not_to_have_attribute("data-leika-hover-scroll-active", "")
    # Observe the completed handoff, not the synchronous reset which WebKit
    # may overwrite while it reveals the caret during the next rendering
    # update.
    settled_scroll = field.evaluate(
        """input => new Promise(resolve => {
          requestAnimationFrame(() => {
            requestAnimationFrame(() => resolve(input.scrollLeft));
          });
        })"""
    )
    assert settled_scroll < 1
    assert field.evaluate("input => input.scrollLeft") < 1
    assert page_errors == []
