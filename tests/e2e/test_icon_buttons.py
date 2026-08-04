"""Icon buttons are the same color wherever they sit.

``iconButtonColor.test.ts`` pins what the button variant declares. This pins
what the app ends up drawing, across the surfaces that each used to say it for
themselves: a notification, a dialog, and a row of GUI inputs. The dialog's
close button was a step darker than the notification's for exactly as long as
those were three separate answers.
"""

from __future__ import annotations

from typing import Dict

from playwright.sync_api import Page, expect

import leika

# Every icon button below, by a selector that finds it once it is on screen.
CHROME_ICONS = {
    "dialog close": '[data-slot="dialog-content"] [data-slot="dialog-close"]',
    "preview download": '[data-slot="dialog-content"] a[download]',
    "toast close": '[data-slot="toast-close"]',
    "form send": "[data-leika-form-send]",
}


def _colors(page: Page) -> Dict[str, str]:
    return page.evaluate(
        """(selectors) => Object.fromEntries(
          Object.entries(selectors).map(([label, selector]) => {
            const el = document.querySelector(selector);
            return [label, el === null ? "missing" : getComputedStyle(el).color];
          }),
        )""",
        CHROME_ICONS,
    )


def _theme_color(page: Page, variable: str) -> str:
    """What a CSS variable resolves to, read off an element that uses it.

    Read from the variable itself it comes back as authored -- percentages,
    `oklch(55.6% 0 0)` -- where a computed color is normalized to
    `oklch(0.556 0 0)`. Painting it on something is what settles the notation.
    """
    return page.evaluate(
        """(variable) => {
          const probe = document.createElement("span");
          probe.style.color = `var(${variable})`;
          document.body.append(probe);
          const color = getComputedStyle(probe).color;
          probe.remove();
          return color;
        }""",
        variable,
    )


def test_icon_buttons_share_one_resting_color(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    with leika_server.gui.add_mini_form():
        leika_server.gui.add_text("Title", "hello")
    leika_server.gui.add_preview_button("Show notes", b"# Hi\n", filename="notes.md")
    leika_server.gui.add_notification("Still here", auto_close_seconds=None)

    leika_page.get_by_role("button", name="Show notes").click()
    expect(leika_page.locator('[data-slot="dialog-content"]')).to_be_visible()
    expect(leika_page.locator('[data-slot="toast-close"]')).to_be_visible()

    colors = _colors(leika_page)
    assert "missing" not in colors.values(), colors
    assert len(set(colors.values())) == 1, colors
    # Muted, not the full-strength text beside them: chrome, not content.
    assert next(iter(colors.values())) == _theme_color(leika_page, "--muted-foreground")
    assert page_errors == []


def test_an_icon_beside_a_label_steps_back_without_taking_the_label(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # The half of the rule that reaches buttons somebody adds from Python:
    # the icon quiets down, the words it labels do not.
    leika_server.gui.add_button("Refresh", icon=leika.Icon.REFRESH_CW, color="default")
    leika_server.gui.add_button("Save workspace", icon=leika.Icon.SAVE, color="inverse")

    outlined = leika_page.get_by_role("button", name="Refresh")
    expect(outlined).to_be_visible()
    icon, label = outlined.evaluate(
        """(el) => [
          getComputedStyle(el.querySelector("[data-icon]")).color,
          getComputedStyle(el).color,
        ]"""
    )
    assert icon == _theme_color(leika_page, "--muted-foreground")
    assert label == _theme_color(leika_page, "--foreground")

    # Not over a fill, though: there the muted foreground is a different
    # color at worse contrast rather than a softer one, so the icon reads
    # exactly as the label does.
    filled = leika_page.get_by_role("button", name="Save workspace")
    icon_style = filled.evaluate(
        """(el) => {
          const s = getComputedStyle(el.querySelector("[data-icon]"));
          return { color: s.color, opacity: s.opacity };
        }"""
    )
    assert icon_style["color"] == filled.evaluate("(el) => getComputedStyle(el).color")
    assert float(icon_style["opacity"]) == 1.0
    assert page_errors == []


def test_a_pressed_toggle_brings_its_icon_forward(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # Pressed fills an outlined toggle with `muted`, which is the color its
    # icon rests at; left there the icon would disappear into its own button.
    leika_server.gui.add_toggle("Grid", icon=leika.Icon.GRID_3X3, color="default")
    toggle = leika_page.get_by_role("button", name="Grid")
    expect(toggle).to_be_visible()

    resting = toggle.evaluate('(el) => getComputedStyle(el.querySelector("[data-icon]")).color')
    assert resting == _theme_color(leika_page, "--muted-foreground")

    toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", "true")
    leika_page.wait_for_function(
        """([target]) => {
          const icon = document.querySelector('[data-leika-toggle] [data-icon]');
          return icon !== null && getComputedStyle(icon).color === target;
        }""",
        arg=[_theme_color(leika_page, "--foreground")],
        timeout=5_000,
    )
    assert page_errors == []


def test_hovering_an_icon_button_brings_it_to_full_strength(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    # The other half of the pair: without it a muted icon just looks disabled.
    leika_server.gui.add_preview_button("Show notes", b"# Hi\n", filename="notes.md")
    leika_page.get_by_role("button", name="Show notes").click()

    close = leika_page.locator('[data-slot="dialog-content"] [data-slot="dialog-close"]')
    expect(close).to_be_visible()
    resting = close.evaluate("(el) => getComputedStyle(el).color")
    close.hover()

    # The button transitions rather than snapping, so the first frame after
    # the pointer arrives is still most of the way back at the resting color.
    foreground = _theme_color(leika_page, "--foreground")
    leika_page.wait_for_function(
        """([selector, target]) => {
          const el = document.querySelector(selector);
          return el !== null && getComputedStyle(el).color === target;
        }""",
        arg=[CHROME_ICONS["dialog close"], foreground],
        timeout=5_000,
    )
    assert foreground != resting
    assert page_errors == []
