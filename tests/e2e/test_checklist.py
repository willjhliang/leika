"""A checklist, from the tick to what Python reads.

``Checklist.test.ts`` pins what the component draws for a given value, and
``test_gui.py`` pins what the handle makes of what it is given. What is left is
the pair travelling: a box ticked in the browser arriving as ``(text, True)``,
and the tick staying with its words when the words move.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect

import leika

from .utils import wait_until


def _entries(page: Page) -> Locator:
    return page.locator("[data-leika-checklist-entry]")


def _boxes(page: Page) -> Locator:
    return page.locator("[data-leika-checklist-box]")


def test_a_tick_is_reported_with_the_words_it_is_against(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    items = leika_server.gui.add_checklist("Preflight", ["Fuel", ("Doors", True), "Lights"])

    boxes = _boxes(leika_page)
    expect(boxes).to_have_count(3, timeout=5_000)
    # The value arrived as it was declared: the second is ticked, and only it.
    expect(boxes.nth(0)).not_to_be_checked()
    expect(boxes.nth(1)).to_be_checked()

    boxes.nth(0).click()
    wait_until(lambda: items.value[0] == ("Fuel", True))
    # One box, one item: the others are left exactly as they were.
    assert items.value == (("Fuel", True), ("Doors", True), ("Lights", False))
    assert items.checked == ("Fuel", "Doors")

    boxes.nth(1).click()
    wait_until(lambda: items.checked == ("Fuel",))

    # And the other way: Python ticks, the browser shows it.
    items.value = [("Fuel", False), ("Doors", False), ("Lights", True)]
    expect(boxes.nth(2)).to_be_checked(timeout=5_000)
    expect(boxes.nth(0)).not_to_be_checked()

    assert page_errors == []


def test_a_tick_travels_with_its_entry(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A checklist's rows carry an answer, so what moves is the pair. Reordering
    the words while the ticks stayed at their row numbers would silently answer
    a different question."""
    items = leika_server.gui.add_checklist(
        "Tasks", [("Write", True), ("Review", False), ("Ship", False)]
    )
    rows = leika_page.locator("[data-leika-list-item]")
    expect(rows).to_have_count(3, timeout=5_000)

    # Dragged from the top to the bottom, the ticked entry takes its tick.
    rows.first.hover()
    grip = leika_page.get_by_label("Reorder entry 1").bounding_box()
    last = rows.nth(2).bounding_box()
    assert grip is not None and last is not None
    leika_page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    leika_page.mouse.down()
    leika_page.mouse.move(grip["x"] + grip["width"] / 2, last["y"] + last["height"] / 2, steps=6)
    leika_page.mouse.up()
    wait_until(lambda: items.value == (("Review", False), ("Ship", False), ("Write", True)))
    expect(_boxes(leika_page).nth(2)).to_be_checked()

    # Retyping an entry leaves its tick alone -- it is the same item, said
    # differently.
    _entries(leika_page).nth(2).fill("Written")
    wait_until(lambda: items.value[2] == ("Written", True))

    # And removing one takes its tick off the list with it, rather than
    # leaving it on whatever slides up into its place.
    rows.nth(2).hover()
    leika_page.get_by_label("Remove entry 3").click()
    wait_until(lambda: items.value == (("Review", False), ("Ship", False)))
    assert items.checked == ()

    # A new entry is empty and unticked, which is where the viewer was going.
    leika_page.locator("[data-leika-list-add]").click()
    wait_until(lambda: items.value[-1] == ("", False))

    assert page_errors == []


def test_an_empty_checklist_is_filled_a_pair_at_a_time(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Empty, there is no item to say what an item looks like -- so the pairs
    the browser sends have to be read as pairs on their own account, rather
    than cast to the shape of one that is already there."""
    items = leika_server.gui.add_checklist("Tasks")
    add = leika_page.locator("[data-leika-list-add]")
    expect(add).to_be_visible(timeout=5_000)
    assert items.value == ()

    add.click()
    wait_until(lambda: items.value == (("", False),))
    # A pair, not a list that merely prints like one: `checked` unpacks it, and
    # so does anything else Python does with the value.
    assert all(isinstance(item, tuple) for item in items.value)

    _entries(leika_page).first.fill("Write the draft")
    _boxes(leika_page).first.click()
    wait_until(lambda: items.checked == ("Write the draft",))

    assert page_errors == []


def test_a_box_fills_like_every_other_checkbox_in_the_panel(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A checklist's box is the panel's checkbox. Whatever a reorder needs, it
    is not paid for by this: the same animation, from the same stylesheet, and
    a tick that eases into its colour rather than snapping to it."""
    items = leika_server.gui.add_checklist("Tasks", ["Write", "Review"])
    leika_server.gui.add_checkbox("Plain", False)
    expect(_boxes(leika_page)).to_have_count(2, timeout=5_000)

    # Not merely similar: the same computed transition, which is what says the
    # animation is shared rather than reimplemented next door.
    same = leika_page.evaluate(
        """() => {
          const of = (el) => {
            const style = getComputedStyle(el);
            return [
              style.transitionProperty,
              style.transitionDuration,
              style.transitionTimingFunction,
            ].join(" / ");
          };
          const box = document.querySelector("[data-leika-checklist-box]");
          const plain = [...document.querySelectorAll('[data-slot="checkbox"]')]
            .find((el) => !el.hasAttribute("data-leika-checklist-box"));
          return { box: of(box), plain: of(plain) };
        }"""
    )
    assert same["box"] == same["plain"], same
    # And it is an animation at all, not an instant change both happen to share.
    assert same["box"].split(" / ")[1] not in ("0s", ""), same

    # Ticked, the fill is caught on its way in: the states between empty and
    # full are the animation, and there is no other way to observe it.
    leika_page.evaluate(
        """() => {
            window.__leikaPartial = 0;
            window.__leikaWatching = true;
            const tick = () => {
              for (const box of document.querySelectorAll("[data-leika-checklist-box]")) {
                const alpha = getComputedStyle(box).backgroundColor
                  .match(/\\/\\s*([0-9.]+)\\s*\\)/);
                if (alpha !== null && Number(alpha[1]) > 0.01 && Number(alpha[1]) < 0.99) {
                  window.__leikaPartial += 1;
                }
              }
              if (window.__leikaWatching) requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        }"""
    )
    _boxes(leika_page).first.click()
    wait_until(lambda: items.checked == ("Write",))
    leika_page.wait_for_timeout(400)
    partial = leika_page.evaluate(
        "() => { window.__leikaWatching = false; return window.__leikaPartial; }"
    )
    assert partial > 0, "the box snapped to its colour instead of easing into it"

    assert page_errors == []


def test_no_box_is_caught_half_filled_when_an_entry_lands(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Rows are keyed by their place, so a reorder rewrites what each row
    HOLDS. A box that eases between colours therefore eases between two
    different items' answers: drop a ticked entry somewhere else and the row it
    came from wears its tick for a moment before shedding it, which reads as
    the wrong item having been ticked and then unticked."""
    # Two entries reading the SAME, since the words cannot tell those apart:
    # keyed by what a row says, the ticked "Write" and the unticked one are one
    # control, and dropping either onto the other's row eases between their
    # answers exactly as before. An entry has to be identified by being itself.
    items = leika_server.gui.add_checklist(
        "Tasks", [("Write", True), ("Write", False), ("Ship", False)]
    )
    rows = leika_page.locator("[data-leika-list-item]")
    expect(rows).to_have_count(3, timeout=5_000)

    rows.first.hover()
    grip = leika_page.get_by_label("Reorder entry 1").bounding_box()
    last = rows.nth(2).bounding_box()
    assert grip is not None and last is not None
    leika_page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    leika_page.mouse.down()
    leika_page.mouse.move(grip["x"] + grip["width"] / 2, last["y"] + last["height"] / 2, steps=8)

    # Watching starts BEFORE the drop: the frames in question are the ones
    # right after it, and they are gone in a third of a second.
    leika_page.evaluate(
        """() => {
            window.__leikaHalfFilled = 0;
            window.__leikaWatching = true;
            // A box is filled or it is not. Anything in between is a colour on
            // its way somewhere, which is the whole complaint.
            const midway = (paint) => {
              const alpha = paint.match(/\\/\\s*([0-9.]+)\\s*\\)/);
              return alpha !== null && Number(alpha[1]) > 0.01 && Number(alpha[1]) < 0.99;
            };
            const tick = () => {
              for (const box of document.querySelectorAll("[data-leika-checklist-box]")) {
                if (midway(getComputedStyle(box).backgroundColor)) {
                  window.__leikaHalfFilled += 1;
                }
              }
              if (window.__leikaWatching) requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        }"""
    )
    leika_page.mouse.up()
    wait_until(lambda: items.value == (("Write", False), ("Ship", False), ("Write", True)))
    leika_page.wait_for_timeout(600)

    half_filled = leika_page.evaluate(
        "() => { window.__leikaWatching = false; return window.__leikaHalfFilled; }"
    )
    assert half_filled == 0, f"{half_filled} frames of a half-filled box"
    # The tick did land where the entry did, and nowhere else.
    expect(_boxes(leika_page).nth(2)).to_be_checked()
    expect(_boxes(leika_page).nth(0)).not_to_be_checked()
    assert page_errors == []


def test_a_box_sits_the_same_distance_from_every_border(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The box rides inside the entry, at its start, and a 16px box in a 24px
    field is 4px off the top and the bottom whatever anyone does -- so it is
    4px off the left as well, or it reads as a box with a left margin instead
    of a box set into a field."""
    leika_server.gui.add_checklist("Tasks", ["Write", "Review"])
    leika_server.gui.add_checklist("Preflight", ["Fuel", "Doors"], frozen=True)
    expect(_boxes(leika_page)).to_have_count(4, timeout=5_000)

    inset = leika_page.evaluate(
        """() => {
          const field = document.querySelector("input[data-leika-checklist-entry]");
          const box = document.querySelector("[data-leika-checklist-box]");
          const f = field.getBoundingClientRect();
          const b = box.getBoundingClientRect();
          return {
            left: Math.round(b.left - f.left),
            top: Math.round(b.top - f.top),
            bottom: Math.round(f.bottom - b.bottom),
          };
        }"""
    )
    assert inset["left"] == inset["top"] == inset["bottom"], inset
    # Inside the field, not beside it: a box in its own column would leave the
    # field's left edge to the right of the box rather than left of it.
    assert inset["left"] > 0, inset

    # And the two kinds line up with each other, since they sit one above the
    # other in a panel: same box, same first letter.
    columns = leika_page.evaluate(
        """() => {
          const of = (label) => {
            const row = [...document.querySelectorAll("[data-leika-gui-row]")]
              .find((r) => r.textContent.startsWith(label));
            const item = row.querySelector("[data-leika-list-item]");
            const stack = item.getBoundingClientRect();
            const box = item.querySelector("[data-leika-checklist-box]");
            const entry = item.querySelector("[data-leika-checklist-entry]");
            const words = entry.tagName === "INPUT"
              ? entry.getBoundingClientRect().left
                + parseFloat(getComputedStyle(entry).paddingLeft)
              : entry.getBoundingClientRect().left;
            return {
              box: Math.round(box.getBoundingClientRect().left - stack.left),
              words: Math.round(words - stack.left),
            };
          };
          return { writable: of("Tasks"), frozen: of("Preflight") };
        }"""
    )
    assert columns["writable"] == columns["frozen"], columns

    assert page_errors == []


def test_both_kinds_sit_at_the_same_rhythm(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Whether an item's words can be typed in is not a reason for a checklist
    to be spaced differently: the two read as one kind of thing, and side by
    side an extra six pixels a row is plain to see."""
    leika_server.gui.add_checklist("Tasks", ["Write", "Review", "Ship"])
    leika_server.gui.add_checklist("Preflight", ["Fuel", "Doors", "Lights"], frozen=True)
    expect(_boxes(leika_page)).to_have_count(6, timeout=5_000)

    shape = leika_page.evaluate(
        """() => {
          const of = (label) => {
            const row = [...document.querySelectorAll("[data-leika-gui-row]")]
              .find((r) => r.textContent.startsWith(label));
            const rects = [...row.querySelectorAll("[data-leika-list-item]")]
              .map((item) => item.getBoundingClientRect());
            return {
              height: Math.round(rects[0].height),
              pitch: rects.slice(1).map((r, i) => Math.round(r.top - rects[i].top)),
            };
          };
          return { writable: of("Tasks"), frozen: of("Preflight") };
        }"""
    )
    assert shape["writable"] == shape["frozen"], shape
    # Non-vacuous: a pitch that collapsed to nothing would also compare equal.
    assert shape["frozen"]["pitch"] == [23, 23], shape

    assert page_errors == []


def test_frozen_is_a_list_to_work_through_rather_than_to_write(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """What a checklist is asked for is the ticks, so frozen fixes the words as
    well as the number and the order -- and with nothing to write, nothing is
    drawn as writable."""
    items = leika_server.gui.add_checklist("Preflight", ["Fuel", "Doors", "Lights"], frozen=True)
    boxes = _boxes(leika_page)
    expect(boxes).to_have_count(3, timeout=5_000)

    # No field, and none of the controls that would change the list: an entry
    # is the words themselves rather than a box holding them.
    expect(leika_page.locator("input[data-leika-checklist-entry]")).to_have_count(0)
    expect(leika_page.locator("label[data-leika-checklist-entry]")).to_have_count(3)
    expect(leika_page.locator("[data-leika-list-grip]")).to_have_count(0)
    expect(leika_page.locator("[data-leika-list-remove]")).to_have_count(0)
    expect(leika_page.locator("[data-leika-list-add]")).to_have_count(0)

    # The words are still the target: a 16px box is a small thing to hit for a
    # row that is one thing to answer.
    _entries(leika_page).nth(1).click()
    wait_until(lambda: items.checked == ("Doors",))
    expect(boxes.nth(1)).to_be_checked()

    # Frozen is not disabled: unticking works the same way back.
    _entries(leika_page).nth(1).click()
    wait_until(lambda: items.checked == ())

    assert page_errors == []
