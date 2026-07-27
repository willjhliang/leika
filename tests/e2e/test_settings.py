"""The browser's own settings, as a section of the control panel.

Everything here is a viewer preference rather than something Python asked for,
so the assertions read the effect out of the live document -- the `dark` class,
computed styles, measured geometry -- rather than trusting the control that set
it.
"""

from __future__ import annotations

import numpy as np
from playwright.sync_api import Locator, Page, expect

import leika

TRIGGER = "[data-leika-settings-trigger]"
PANE = "[data-leika-settings-pane]"
SECTION_ID = "leika-settings"


def open_settings(page: Page) -> Locator:
    page.locator(TRIGGER).click()
    expect(page.locator(TRIGGER)).to_have_attribute("aria-expanded", "true")
    pane = page.locator(f"{PANE}:visible")
    expect(pane).to_be_visible(timeout=5_000)
    # It unfolds over 200ms, so geometry read before the transition ends is a
    # frame of the animation. While it runs, the panel pins its own height into
    # a variable and transitions to it; once settled that goes back to `auto`.
    page.wait_for_function(
        """id => {
            const panel = document.getElementById(id);
            if (panel === null) return false;
            const height = getComputedStyle(panel).getPropertyValue(
                "--collapsible-panel-height",
            );
            return height.trim() === "auto";
        }""",
        arg=SECTION_ID,
        timeout=5_000,
    )
    return pane


def close_settings(page: Page) -> None:
    page.locator(TRIGGER).click()
    expect(page.locator(TRIGGER)).to_have_attribute("aria-expanded", "false")
    expect(page.locator(f"{PANE}:visible")).to_have_count(0, timeout=5_000)


def is_dark(page: Page) -> bool:
    return page.evaluate("() => document.documentElement.classList.contains('dark')")


def css_variable(page: Page, name: str) -> str:
    return page.evaluate(
        "name => getComputedStyle(document.documentElement).getPropertyValue(name).trim()",
        name,
    )


def test_the_gear_is_a_circle_the_size_of_the_status_pill(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """It reads as one cluster with the pill, so it is measured against it."""
    del leika_server
    trigger = leika_page.locator(TRIGGER)
    pill = leika_page.locator('[data-slot="badge"]', has_text="Connected").first
    expect(trigger).to_be_visible(timeout=5_000)
    expect(pill).to_be_visible(timeout=5_000)

    gear = trigger.bounding_box()
    status = pill.bounding_box()
    assert gear is not None and status is not None

    assert abs(gear["height"] - status["height"]) < 0.5
    assert abs(gear["width"] - gear["height"]) < 0.5
    radius = trigger.evaluate(
        "element => parseFloat(getComputedStyle(element).borderTopLeftRadius)"
    )
    assert radius >= gear["height"] / 2 - 0.5

    # To the left of the pill, and on the same line as it.
    assert gear["x"] + gear["width"] <= status["x"] + 0.5
    assert abs((gear["y"] + gear["height"] / 2) - (status["y"] + status["height"] / 2)) < 1.5

    # Idle, it is typed like the pill: the glyph inherits the label's color.
    glyph_color = trigger.locator("svg").evaluate("e => getComputedStyle(e).color")
    label_color = pill.get_by_text("Connected").evaluate("e => getComputedStyle(e).color")
    assert glyph_color == label_color
    assert page_errors == []


def test_the_open_gear_fills_with_the_accent(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Open, the gear reads as a checked control, which means the same pair of
    tokens a checked checkbox uses -- accent behind, on-accent glyph -- so a
    chosen accent reaches it without the gear knowing an accent exists."""
    leika_server.gui.add_checkbox("Enabled", initial_value=True)
    checkbox = leika_page.get_by_role("checkbox", name="Enabled")
    expect(checkbox).to_be_visible(timeout=5_000)
    trigger = leika_page.locator(TRIGGER)

    idle_fill = trigger.evaluate("e => getComputedStyle(e).backgroundColor")
    checked_fill = checkbox.evaluate("e => getComputedStyle(e).backgroundColor")
    assert idle_fill != checked_fill

    # Opening it leaves the pointer on it, and the hover state dims the fill to
    # 80%, so the pointer moves off before any of these are read.
    pane = open_settings(leika_page)
    leika_page.mouse.move(2, 2)
    expect(trigger).to_have_css("background-color", checked_fill)
    assert trigger.locator("svg").evaluate("e => getComputedStyle(e).color") == checkbox.evaluate(
        "e => getComputedStyle(e).color"
    )

    # And it follows the accent, since that is the token both are reading.
    swatch = pane.locator("#leika-settings-accent")
    swatch.click()
    picker = leika_page.locator("[data-leika-color-popover]:visible")
    output = picker.locator("[data-leika-color-output]").first
    output.fill("#1A237E")
    output.press("Enter")
    leika_page.keyboard.press("Escape")
    leika_page.mouse.move(2, 2)
    expect(trigger).to_have_css("background-color", "rgb(26, 35, 126)")
    expect(checkbox).to_have_css("background-color", "rgb(26, 35, 126)")

    close_settings(leika_page)
    leika_page.mouse.move(2, 2)
    expect(trigger).to_have_css("background-color", idle_fill)
    assert page_errors == []


def test_settings_unfold_inside_the_panel(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """It is part of the panel, not a layer over it: it takes the width of the
    rows around it and pushes the app's controls down rather than covering
    them, unfolding on a height transition the way the panel's sections do.

    The header the gear sits in is also the floating window's drag handle and
    its click-to-collapse target, so neither may fire on the way in.
    """
    with leika_server.gui.add_folder("Controls"):
        leika_server.gui.add_checkbox("Enabled", initial_value=True)
        leika_server.gui.add_divider()
        leika_server.gui.add_checkbox("Also enabled", initial_value=False)
    checkbox = leika_page.get_by_role("checkbox", name="Enabled", exact=True)
    expect(checkbox).to_be_visible(timeout=5_000)

    panel = leika_page.locator("[data-dock-group]").first
    row = leika_page.locator("[data-leika-gui-row]").first
    before_panel = panel.bounding_box()
    before_checkbox = checkbox.bounding_box()
    row_box = row.bounding_box()
    assert before_panel is not None and before_checkbox is not None
    assert row_box is not None
    # No settings markup at all until it is asked for.
    assert leika_page.locator(PANE).count() == 0

    pane = open_settings(leika_page)

    after_panel = panel.bounding_box()
    assert after_panel is not None
    assert abs(after_panel["x"] - before_panel["x"]) < 1
    assert abs(after_panel["y"] - before_panel["y"]) < 1
    # The panel body is still there: the click did not toggle it collapsed.
    expect(checkbox).to_be_visible()

    pane_box = pane.bounding_box()
    after_checkbox = checkbox.bounding_box()
    assert pane_box is not None and after_checkbox is not None
    assert abs(pane_box["width"] - row_box["width"]) < 1
    assert after_checkbox["y"] > before_checkbox["y"] + pane_box["height"] / 2

    # It unfolds rather than appearing whole.
    panel_wrapper = leika_page.locator(f"#{SECTION_ID}")
    assert panel_wrapper.evaluate("e => getComputedStyle(e).transitionProperty") == "height"

    # The rule under it is the one line in the panel that crosses the body's
    # padding: it separates the browser's controls from the server's. Its rows
    # still line up with the GUI's, so only the line runs wide.
    rule = leika_page.locator(f"#{SECTION_ID}")
    rule_box = rule.bounding_box()
    body_box = leika_page.locator('[data-slot="card-content"]').first.bounding_box()
    assert rule_box is not None and body_box is not None
    assert rule.evaluate("e => parseFloat(getComputedStyle(e).borderBottomWidth)") >= 1
    assert rule_box["width"] > row_box["width"] + 8
    assert rule_box["x"] <= body_box["x"] + 0.5
    assert rule_box["x"] + rule_box["width"] >= body_box["x"] + body_box["width"] - 0.5

    # ...and it is actually painted that wide. A clipping ancestor leaves the
    # layout box above at its full width while cutting the pixels short, which
    # is exactly how this went unnoticed once.
    clipped_by = rule.evaluate(
        """element => {
            const width = element.getBoundingClientRect().width;
            for (let node = element.parentElement; node; node = node.parentElement) {
                const style = getComputedStyle(node);
                if (style.overflowX === "visible") continue;
                if (node.getBoundingClientRect().width < width - 0.5) {
                    return node.tagName + "." + node.className;
                }
            }
            return null;
        }"""
    )
    assert clipped_by is None, clipped_by

    # Every other rule in the panel stops at the column the rows share: a
    # section's own border, and any `add_divider` the server asked for.
    panel_scope = '[data-testid="control-panel"]'
    others = leika_page.locator(
        f'{panel_scope} [data-slot="accordion-item"], '
        f'{panel_scope} [data-slot="separator"][data-orientation="horizontal"]'
        f":not({PANE} *)"
    )
    assert others.count() >= 2
    for index in range(others.count()):
        other_box = others.nth(index).bounding_box()
        assert other_box is not None
        assert other_box["width"] <= row_box["width"] + 0.5

    close_settings(leika_page)
    assert leika_page.locator(PANE).count() == 0
    assert page_errors == []


def test_the_gear_goes_with_the_connection(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A page that has stopped tracking its server offers no settings, and an
    open pane folds away rather than being stranded behind a dead gear."""
    trigger = leika_page.locator(TRIGGER)
    expect(trigger).to_be_enabled(timeout=5_000)
    open_settings(leika_page)

    leika_server.stop()

    expect(trigger).to_be_disabled(timeout=15_000)
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(leika_page.locator(f"{PANE}:visible")).to_have_count(0)
    # Clicking a disabled control does nothing, so the pane stays folded.
    trigger.click(force=True)
    expect(leika_page.locator(f"{PANE}:visible")).to_have_count(0)
    assert page_errors == []


def test_the_gear_reaches_the_sidebar_and_mobile_chromes(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """The control panel has three chromes. The floating one is covered above;
    these two place the gear differently, since the mobile handle is itself one
    big button and cannot hold another."""
    leika_server.gui.configure_theme(control_layout="fixed")
    leika_server.gui.add_checkbox("Enabled", initial_value=True)
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )

    # Sidebar: same cluster as the floating header, gear before the pill.
    trigger = page.locator(TRIGGER)
    expect(trigger).to_have_count(1, timeout=5_000)
    gear = trigger.bounding_box()
    pill = page.locator('[data-slot="badge"]', has_text="Connected").first.bounding_box()
    assert gear is not None and pill is not None
    assert gear["x"] + gear["width"] <= pill["x"] + 0.5
    open_settings(page)
    close_settings(page)

    # Mobile: one gear still, and tapping it must not fold the sheet away.
    page.set_viewport_size({"width": 420, "height": 700})
    handle = page.locator("[data-leika-bottom-panel-handle]")
    expect(handle).to_have_attribute("aria-expanded", "true", timeout=5_000)
    expect(page.locator(TRIGGER)).to_have_count(1)
    assert handle.locator(TRIGGER).count() == 0

    open_settings(page)
    expect(handle).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_role("checkbox", name="Enabled")).to_be_visible()
    assert page_errors == []


def test_dark_mode_outranks_the_server_and_the_browser(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """The app asked for light and the OS agrees; the viewer still wins."""
    leika_server.gui.configure_theme(dark_mode=False)
    page.emulate_media(color_scheme="light")
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    assert not is_dark(page)
    light_background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")

    pane = open_settings(page)
    switch = pane.get_by_role("switch", name="Dark mode")
    # The switch starts where the page already is, not at some default.
    expect(switch).to_have_attribute("aria-checked", "false")
    switch.click()

    page.wait_for_function("() => document.documentElement.classList.contains('dark')")
    assert (
        page.evaluate("() => getComputedStyle(document.body).backgroundColor") != light_background
    )
    expect(switch).to_have_attribute("aria-checked", "true")

    switch.click()
    page.wait_for_function("() => !document.documentElement.classList.contains('dark')")
    assert page_errors == []


def test_a_scheme_choice_survives_a_reload(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    del leika_server
    pane = open_settings(leika_page)
    switch = pane.get_by_role("switch", name="Dark mode")
    was_dark = is_dark(leika_page)
    switch.click()
    leika_page.wait_for_function(
        "was => document.documentElement.classList.contains('dark') !== was",
        arg=was_dark,
    )

    stored = leika_page.evaluate("() => localStorage.getItem('leika.settings.v2')")
    assert stored is not None
    assert '"darkMode":' in stored

    leika_page.reload()
    leika_page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    leika_page.wait_for_function(
        "was => document.documentElement.classList.contains('dark') !== was",
        arg=was_dark,
        timeout=15_000,
    )
    assert page_errors == []


def test_pane_titles_stay_visible_without_a_pointer_on_them(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The setting adds an always-on title without taking hover away: the pane
    under the pointer is titled either way, and only the other one changes.

    The label fades over 150ms, so these read through Playwright's retrying
    assertions rather than sampling the computed style once.
    """
    row = leika_server.panes.add_row()
    row.add_image(np.zeros((24, 32, 3), dtype=np.uint8), pane_id="left", title="Left")
    row.add_image(np.full((24, 32, 3), 255, dtype=np.uint8), pane_id="right", title="Right")
    hovered = leika_page.locator('[data-viewport-pane-title="left"]')
    other = leika_page.locator('[data-viewport-pane-title="right"]')
    expect(hovered).to_have_count(1, timeout=5_000)

    # Park the pointer on the left pane, and leave it there throughout.
    leika_page.mouse.move(4, 4)
    expect(hovered).to_have_css("opacity", "1")
    expect(other).to_have_css("opacity", "0")

    pane = open_settings(leika_page)
    switch = pane.get_by_role("switch", name="Pane titles")
    expect(switch).to_have_attribute("aria-checked", "false")
    switch.click()
    close_settings(leika_page)
    leika_page.mouse.move(4, 4)
    expect(hovered).to_have_css("opacity", "1")
    expect(other).to_have_css("opacity", "1")

    pane = open_settings(leika_page)
    pane.get_by_role("switch", name="Pane titles").click()
    close_settings(leika_page)
    leika_page.mouse.move(4, 4)
    expect(hovered).to_have_css("opacity", "1")
    expect(other).to_have_css("opacity", "0")
    assert page_errors == []


def test_accent_color_repaints_the_controls_that_use_it(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """One accent, one set of tokens: the checkbox fill follows `--primary`
    without knowing an accent exists, and the reset puts the theme back."""
    leika_server.gui.add_checkbox("Enabled", initial_value=True)
    checkbox = leika_page.get_by_role("checkbox", name="Enabled")
    expect(checkbox).to_be_visible(timeout=5_000)
    stock_fill = checkbox.evaluate("e => getComputedStyle(e).backgroundColor")

    pane = open_settings(leika_page)
    swatch = pane.locator("#leika-settings-accent")
    expect(swatch).to_contain_text("Default")
    # The same swatch-and-popover the GUI's own color inputs use, so the picker
    # is portaled out of the panel rather than pushing it open.
    expect(swatch).to_have_attribute("data-leika-color-trigger", "true")
    swatch.click()
    picker = leika_page.locator("[data-leika-color-popover]:visible")
    expect(picker).to_be_visible(timeout=5_000)
    assert picker.locator("[data-leika-settings-accent]").count() == 0
    output = picker.locator("[data-leika-color-output]").first
    expect(output).to_be_visible(timeout=5_000)
    output.fill("#3478F6")
    output.press("Enter")

    expect(swatch).to_contain_text("rgb(52, 120, 246)")
    assert css_variable(leika_page, "--primary") == "rgb(52, 120, 246)"
    expect(checkbox).to_have_css("background-color", "rgb(52, 120, 246)")

    # The foreground follows the accent's luminance, so a pale accent prints
    # the theme's near-black and a deep one its near-white.
    output.fill("#FFF3B0")
    output.press("Enter")
    expect(checkbox).to_have_css("background-color", "rgb(255, 243, 176)")
    assert css_variable(leika_page, "--primary-foreground") == "oklch(0.205 0 0)"

    output.fill("#1A237E")
    output.press("Enter")
    expect(checkbox).to_have_css("background-color", "rgb(26, 35, 126)")
    assert css_variable(leika_page, "--primary-foreground") == "oklch(0.985 0 0)"

    leika_page.keyboard.press("Escape")
    pane.locator("[data-leika-settings-accent-reset]").click()
    expect(swatch).to_contain_text("Default")
    expect(checkbox).to_have_css("background-color", stock_fill)
    assert page_errors == []


def test_image_fit_applies_to_panes_that_did_not_ask_for_one(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The setting is a default, not an override: a pane Python gave a `fit`
    keeps it, and only the ones left open follow the viewer."""
    row = leika_server.panes.add_row()
    row.add_image(np.zeros((24, 32, 3), dtype=np.uint8), pane_id="free", title="Free")
    pinned_handle = row.add_image(
        np.full((24, 32, 3), 255, dtype=np.uint8),
        pane_id="pinned",
        title="Pinned",
        fit="fill",
    )
    free = leika_page.locator('[data-viewport-pane-content="free"] img')
    pinned = leika_page.locator('[data-viewport-pane-content="pinned"] img')
    expect(free).to_be_visible(timeout=5_000)

    # The default setting is Fit, which the browser applies as `contain`.
    expect(free).to_have_css("object-fit", "contain")
    expect(pinned).to_have_css("object-fit", "cover")

    pane = open_settings(leika_page)
    pane.locator("[data-leika-settings-image-fit]").click()
    # The menu says Stretch; CSS calls that one `fill`.
    leika_page.get_by_role("option", name="Stretch", exact=True).click()

    expect(free).to_have_css("object-fit", "fill")
    expect(pinned).to_have_css("object-fit", "cover")

    # Python can hand a pinned pane back to the viewer at any time.
    pinned_handle.fit = None
    expect(pinned).to_have_css("object-fit", "fill")

    stored = leika_page.evaluate("() => localStorage.getItem('leika.settings.v2')")
    assert '"imageFit":"stretch"' in stored
    assert page_errors == []


def test_the_command_palette_button_opens_the_palette(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """It is disabled until there is something for the palette to show, since
    the palette renders nothing without commands."""
    button = open_settings(leika_page).locator("[data-leika-settings-commands]")
    expect(button).to_be_disabled()
    close_settings(leika_page)

    leika_server.gui.add_command("Reset view", description="Recenter the workspace")

    button = open_settings(leika_page).locator("[data-leika-settings-commands]")
    expect(button).to_be_enabled(timeout=5_000)
    button.click()

    palette = leika_page.locator("[data-leika-command-palette]")
    expect(palette).to_be_visible(timeout=5_000)
    expect(palette).to_contain_text("Reset view")
    assert page_errors == []
