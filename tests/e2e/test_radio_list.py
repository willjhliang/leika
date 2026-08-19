"""Radio-list selection from the browser through to its Python handle."""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect

import leika

from .utils import wait_until


def _entries(page: Page) -> Locator:
    return page.locator("[data-leika-radio-list-entry]")


def _radios(page: Page) -> Locator:
    return page.locator("[data-leika-radio-list-radio]")


def _assert_radio_shape(radio: Locator) -> None:
    shape = radio.evaluate(
        """radio => {
          const root = radio.closest('[data-slot="radio-group-item"]');
          const dot = root?.querySelector(
            '[data-slot="radio-group-indicator"] span'
          );
          if (root === null || dot === null) return null;
          const rootStyle = getComputedStyle(root);
          const dotStyle = getComputedStyle(dot);
          return {
            slot: root.dataset.slot,
            width: rootStyle.width,
            height: rootStyle.height,
            radius: rootStyle.borderRadius,
            dotWidth: dotStyle.width,
            dotHeight: dotStyle.height,
          };
        }"""
    )
    assert shape is not None
    radius = float(shape.pop("radius").removesuffix("px"))
    assert shape == {
        "slot": "radio-group-item",
        "width": "16px",
        "height": "16px",
        "dotWidth": "8px",
        "dotHeight": "8px",
    }
    assert radius >= 8


def test_selecting_one_radio_clears_the_previous_selection(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    choices = leika_server.gui.add_radio_list(
        "Density", ["Default", ("Comfortable", True), "Compact"]
    )

    radios = _radios(leika_page)
    expect(radios).to_have_count(3, timeout=5_000)
    expect(radios.nth(0)).not_to_be_checked()
    expect(radios.nth(1)).to_be_checked()

    radios.nth(0).click()
    wait_until(
        lambda: choices.value == (("Default", True), ("Comfortable", False), ("Compact", False))
    )
    assert choices.selected == "Default"
    expect(radios.nth(0)).to_be_checked()
    _assert_radio_shape(radios.nth(0))
    expect(radios.nth(1)).not_to_be_checked()

    # A radio is a choice, not a toggle: pressing the selected item leaves it
    # selected and therefore cannot create an empty selection.
    radios.nth(0).click()
    assert choices.selected == "Default"

    # Python can still deliberately set no selection, or choose another item.
    choices.value = ["Default", "Comfortable", ("Compact", True)]
    expect(radios.nth(2)).to_be_checked(timeout=5_000)
    expect(radios.nth(0)).not_to_be_checked()
    assert choices.selected == "Compact"

    choices.value = ["Default", "Comfortable", "Compact"]
    expect(radios.nth(2)).not_to_be_checked(timeout=5_000)
    assert choices.selected is None

    assert page_errors == []


def test_editing_arrows_keep_the_caret_and_radio_arrows_select(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    choices = leika_server.gui.add_radio_list(
        "Density", [("Default", True), "Comfortable", "Compact"]
    )
    entries = _entries(leika_page)
    radios = _radios(leika_page)
    expect(entries).to_have_count(3, timeout=5_000)
    expect(radios).to_have_count(3)

    editor = entries.nth(1)
    editor.focus()
    editor.evaluate("(input, caret) => input.setSelectionRange(caret, caret)", 0)
    editor.press("ArrowLeft")
    expect(editor).to_be_focused()
    assert editor.evaluate("input => input.selectionStart") == 0
    expect(radios.nth(0)).to_be_checked()
    assert choices.selected == "Default"

    end = len("Comfortable")
    editor.evaluate("(input, caret) => input.setSelectionRange(caret, caret)", end)
    editor.press("ArrowRight")
    expect(editor).to_be_focused()
    assert editor.evaluate("input => input.selectionStart") == end
    expect(radios.nth(0)).to_be_checked()
    assert choices.selected == "Default"

    # Vertical arrows have browser-specific caret movement in a one-line
    # field. They must still remain editor keystrokes rather than composite
    # radio navigation.
    for key in ("ArrowUp", "ArrowDown"):
        editor.evaluate("input => input.setSelectionRange(3, 3)")
        editor.press(key)
        expect(editor).to_be_focused()
        expect(radios.nth(0)).to_be_checked()
        assert choices.selected == "Default"

    # Once focus is on a radio, the native same-name group supplies the usual
    # arrow-key selection and focus movement.
    radios.nth(0).focus()
    radios.nth(0).press("ArrowRight")
    wait_until(lambda: choices.selected == "Comfortable")
    expect(radios.nth(1)).to_be_focused()
    expect(radios.nth(1)).to_be_checked()

    assert page_errors == []


def test_same_turn_drag_release_commits_the_latest_pointer_position(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    choices = leika_server.gui.add_radio_list(
        "Density", [("Default", True), "Comfortable", "Compact"]
    )
    rows = leika_page.locator("[data-leika-list-item]")
    grip = leika_page.get_by_label("Reorder entry 1")
    expect(rows).to_have_count(3, timeout=5_000)
    grip_box = grip.bounding_box()
    last_box = rows.nth(2).bounding_box()
    assert grip_box is not None and last_box is not None

    # Dispatch the entire gesture in one JavaScript turn. React cannot commit
    # a movement render between these events, so release must read event-time
    # pointer ownership rather than a closure from the preceding render.
    grip.evaluate(
        """(element, point) => {
          const pointerId = 41;
          const common = {
            bubbles: true,
            pointerId,
            pointerType: "mouse",
            isPrimary: true,
            button: 0,
          };
          element.dispatchEvent(new PointerEvent("pointerdown", {
            ...common,
            buttons: 1,
            clientX: point.x,
            clientY: point.startY,
          }));
          window.dispatchEvent(new PointerEvent("pointermove", {
            ...common,
            buttons: 1,
            clientX: point.x,
            clientY: point.endY,
          }));
          window.dispatchEvent(new PointerEvent("pointerup", {
            ...common,
            buttons: 0,
            clientX: point.x,
            clientY: point.endY,
          }));
        }""",
        {
            "x": grip_box["x"] + grip_box["width"] / 2,
            "startY": grip_box["y"] + grip_box["height"] / 2,
            "endY": last_box["y"] + last_box["height"] / 2,
        },
    )
    wait_until(
        lambda: choices.value == (("Comfortable", False), ("Compact", False), ("Default", True))
    )
    assert page_errors == []


def test_selection_travels_with_an_editable_choice(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    choices = leika_server.gui.add_radio_list(
        "Density", [("Default", True), "Comfortable", "Compact"]
    )
    rows = leika_page.locator("[data-leika-list-item]")
    expect(rows).to_have_count(3, timeout=5_000)

    # Move the selected choice from the top to the bottom. EntryStack moves
    # pairs, so its selection goes with its words.
    rows.first.hover()
    grip = leika_page.get_by_label("Reorder entry 1").bounding_box()
    last = rows.nth(2).bounding_box()
    assert grip is not None and last is not None
    leika_page.mouse.move(
        grip["x"] + grip["width"] / 2,
        grip["y"] + grip["height"] / 2,
    )
    leika_page.mouse.down()
    leika_page.mouse.move(
        grip["x"] + grip["width"] / 2,
        last["y"] + last["height"] / 2,
        steps=6,
    )
    leika_page.mouse.up()
    wait_until(
        lambda: choices.value == (("Comfortable", False), ("Compact", False), ("Default", True))
    )
    expect(_radios(leika_page).nth(2)).to_be_checked()

    _entries(leika_page).nth(2).fill("Standard")
    wait_until(lambda: choices.selected == "Standard")

    rows.nth(2).hover()
    leika_page.get_by_label("Remove entry 3").click()
    wait_until(lambda: choices.selected is None)

    leika_page.locator("[data-leika-list-add]").click()
    wait_until(lambda: choices.value[-1] == ("", False))

    assert page_errors == []


def test_frozen_radio_list_uses_clickable_labels_and_shadcn_radios(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    choices = leika_server.gui.add_radio_list(
        "Density", ["Default", "Comfortable", "Compact"], frozen=True
    )
    leika_server.gui.add_radio_list(None, [("Only choice", True)], frozen=True)

    radios = _radios(leika_page)
    expect(radios).to_have_count(4, timeout=5_000)
    expect(leika_page.locator("input[data-leika-radio-list-entry]")).to_have_count(0)
    expect(leika_page.locator("label[data-leika-radio-list-entry]")).to_have_count(4)
    expect(leika_page.locator("[data-leika-list-add]")).to_have_count(0)

    _entries(leika_page).nth(1).click()
    wait_until(lambda: choices.selected == "Comfortable")
    expect(radios.nth(1)).to_be_checked()

    # Frozen and editable radios share the same public visual contract.
    _assert_radio_shape(radios.nth(1))

    assert page_errors == []
