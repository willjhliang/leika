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
POPOVER = "[data-leika-settings-popover]"
SECTION_ID = "leika-settings"


def open_settings(page: Page) -> Locator:
    page.locator(TRIGGER).click()
    expect(page.locator(TRIGGER)).to_have_attribute("aria-expanded", "true")
    popover = page.locator(POPOVER)
    expect(popover).to_be_visible(timeout=5_000)
    # It zooms in, so geometry read before that settles is a frame of the
    # animation -- and the frames are SMALLER than the popup, being scaled. The
    # starting style is dropped when the transition begins rather than when it
    # ends, so what says it is over is the scale being back to 1.
    page.wait_for_function(
        """selector => {
            const popup = document.querySelector(selector);
            if (popup === null) return false;
            const transform = getComputedStyle(popup).transform;
            return transform === "none" || transform === "matrix(1, 0, 0, 1, 0, 0)";
        }""",
        arg=POPOVER,
        timeout=5_000,
    )
    return page.locator(f"{PANE}:visible")


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
    # The pill is a button of its own now -- it opens the connection popout --
    # so it answers to that rather than to the badge slot it renders as.
    pill = leika_page.locator("[data-leika-connection-trigger]")
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
    open_settings(leika_page)
    leika_page.mouse.move(2, 2)
    expect(trigger).to_have_css("background-color", checked_fill)
    assert trigger.locator("svg").evaluate("e => getComputedStyle(e).color") == checkbox.evaluate(
        "e => getComputedStyle(e).color"
    )

    close_settings(leika_page)
    leika_page.mouse.move(2, 2)
    expect(trigger).to_have_css("background-color", idle_fill)
    assert page_errors == []


def test_settings_open_in_a_popout_off_the_gear(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A layer over the panel, not part of it: the browser's settings are not
    the app's controls, so they open off the gear the way a color picker or a
    form does and leave the panel underneath exactly as it was.

    The header the gear sits in is also the floating window's drag handle and
    its click-to-collapse target, so neither may fire on the way in.
    """
    with leika_server.gui.add_folder("Controls"):
        leika_server.gui.add_checkbox("Enabled", initial_value=True)
    checkbox = leika_page.get_by_role("checkbox", name="Enabled", exact=True)
    expect(checkbox).to_be_visible(timeout=5_000)

    panel = leika_page.locator("[data-dock-group]").first
    before_panel = panel.bounding_box()
    before_checkbox = checkbox.bounding_box()
    assert before_panel is not None and before_checkbox is not None
    # No settings markup at all until it is asked for.
    assert leika_page.locator(PANE).count() == 0

    pane = open_settings(leika_page)

    # The panel is where it was, at the size it was, with its controls in the
    # same place: nothing was pushed down to make room.
    after_panel = panel.bounding_box()
    after_checkbox = checkbox.bounding_box()
    assert after_panel is not None and after_checkbox is not None
    assert abs(after_panel["x"] - before_panel["x"]) < 1
    assert abs(after_panel["y"] - before_panel["y"]) < 1
    assert abs(after_panel["height"] - before_panel["height"]) < 1
    assert abs(after_checkbox["y"] - before_checkbox["y"]) < 1
    # The panel body is still there: the click did not toggle it collapsed.
    expect(checkbox).to_be_visible()

    # It says what it is: arriving beside the panel rather than inside it, it
    # has nothing around it to explain itself and the gear is behind it.
    expect(leika_page.locator(POPOVER).get_by_text("Settings", exact=True)).to_be_visible()

    # Hung off the panel the way every other popout is: its end lines up with
    # the end of the rows, not with the 20px gear somewhere along the header.
    popout_box = leika_page.locator(POPOVER).bounding_box()
    row_box = leika_page.locator("[data-leika-gui-row]").first.bounding_box()
    gear_box = leika_page.locator(TRIGGER).bounding_box()
    assert popout_box is not None and row_box is not None and gear_box is not None
    assert abs((popout_box["x"] + popout_box["width"]) - (row_box["x"] + row_box["width"])) < 1.0, (
        popout_box,
        row_box,
    )
    assert popout_box["x"] + popout_box["width"] > gear_box["x"] + gear_box["width"]

    # It is its own surface, over the panel rather than in it: portalled out
    # of the panel entirely, and painted on the popover's own colour.
    popover = leika_page.locator(POPOVER)
    expect(popover).to_have_attribute("data-slot", "popover-content")
    assert pane.evaluate("""pane => pane.closest('[data-testid="control-panel"]') === null""")
    surfaces = popover.evaluate(
        """popup => ({
            popover: getComputedStyle(popup).backgroundColor,
            panel: getComputedStyle(
                document.querySelector('[data-testid="control-panel"]'),
            ).backgroundColor,
        })"""
    )
    assert surfaces["popover"] != "rgba(0, 0, 0, 0)", surfaces

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


def test_the_gear_reaches_the_docked_and_mobile_chromes(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """The floating chrome is covered above; these are the other two places the
    panel can be. Docked, the header is the same cluster; on the phone the
    handle is itself one big button and cannot hold the gear."""
    leika_server.gui.configure_theme(control_layout="right")
    leika_server.gui.add_checkbox("Enabled", initial_value=True)
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    expect(page.get_by_test_id("control-panel")).to_have_attribute(
        "data-dock-side", "right", timeout=5_000
    )

    # Docked: same cluster as the floating header, gear before the pill.
    expect(page.locator(TRIGGER)).to_be_visible(timeout=5_000)
    # Both edges in ONE read: the header re-renders as the connection settles,
    # and two separate measurements can land either side of that, leaving the
    # second one measuring an element that has just been replaced.
    cluster = page.evaluate(
        """(trigger) => {
            const gear = document.querySelector(trigger);
            const pill = document.querySelector("[data-leika-connection-trigger]");
            if (gear === null || pill === null) return null;
            return {
                gearRight: gear.getBoundingClientRect().right,
                pillLeft: pill.getBoundingClientRect().left,
            };
        }""",
        TRIGGER,
    )
    assert cluster is not None
    assert cluster["gearRight"] <= cluster["pillLeft"] + 0.5, cluster
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


def choose_scheme(page: Page, pane: Locator, name: str) -> None:
    """Pick one of Auto, Light or Dark from the color scheme dropdown."""
    pane.locator("[data-leika-settings-color-scheme]").click()
    page.get_by_role("option", name=name, exact=True).click()


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
    # The dropdown starts on the choice nobody has made yet, not on the scheme
    # that choice happens to resolve to.
    expect(pane.locator("[data-leika-settings-color-scheme]")).to_contain_text("Auto")
    choose_scheme(page, pane, "Dark")

    page.wait_for_function("() => document.documentElement.classList.contains('dark')")
    assert (
        page.evaluate("() => getComputedStyle(document.body).backgroundColor") != light_background
    )

    choose_scheme(page, pane, "Light")
    page.wait_for_function("() => !document.documentElement.classList.contains('dark')")
    assert page_errors == []


def test_auto_hands_the_scheme_back_to_the_browser(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """A pinned scheme has to be unpinnable.

    Otherwise the first visit to these settings is a one-way door out of
    `dark_mode="auto"`: whatever the viewer picks -- including the scheme the
    page was already showing -- outranks the OS from then on, and the page
    stops following it with nothing on screen to say why.
    """
    page.emulate_media(color_scheme="light")
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )

    pane = open_settings(page)
    # Pin light -- the scheme it is already on, which is the case that used to
    # look like nothing had happened.
    choose_scheme(page, pane, "Light")
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(250)
    assert not is_dark(page), "a pinned scheme must ignore the OS"

    choose_scheme(page, pane, "Auto")
    page.wait_for_function("() => document.documentElement.classList.contains('dark')")

    # And it keeps following it, rather than having simply resolved once.
    page.emulate_media(color_scheme="light")
    page.wait_for_function("() => !document.documentElement.classList.contains('dark')")
    stored = page.evaluate("() => localStorage.getItem('leika.settings.v2')")
    assert '"darkMode":null' in stored
    assert page_errors == []


def test_a_scheme_choice_survives_a_reload(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    del leika_server
    was_dark = is_dark(leika_page)
    choose_scheme(leika_page, open_settings(leika_page), "Light" if was_dark else "Dark")
    leika_page.wait_for_function(
        "was => document.documentElement.classList.contains('dark') !== was",
        arg=was_dark,
    )

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
    pane.locator("[data-leika-color-reset]").click()
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


def test_the_accent_reset_stays_inside_a_panel_dragged_to_its_minimum(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The dock lets the panel down to 220px, which is inside the width where
    the trigger and the button stop fitting side by side. The trigger gives way
    instead of pushing the button off the panel."""
    pane = open_settings(leika_page)
    leika_page.get_by_test_id("control-panel").evaluate("el => (el.style.width = '220px')")

    accent = leika_page.locator("#leika-settings-accent")
    accent.click()
    picker = leika_page.locator("[data-leika-color-popover]:visible")
    expect(picker).to_be_visible(timeout=5_000)
    selection = picker.locator("[data-leika-color-selection]")
    bounds = selection.bounding_box()
    assert bounds is not None
    selection.click(position={"x": bounds["width"] - 12, "y": 12})
    selection.press("Escape")

    reset = leika_page.locator("[data-leika-color-reset]")
    expect(reset).to_be_visible(timeout=5_000)
    reset_box = reset.bounding_box()
    pane_box = pane.bounding_box()
    assert reset_box is not None and pane_box is not None
    assert reset_box["x"] + reset_box["width"] <= pane_box["x"] + pane_box["width"] + 0.5, (
        reset_box,
        pane_box,
    )
    assert page_errors == []


def test_the_footer_names_the_version_and_links_to_the_project(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The version is baked into the client at build time, so this also catches a
    build made from a `VersionInfo.ts` that Python has since moved past."""
    about = open_settings(leika_page).locator("[data-leika-settings-about]")
    expect(about.locator("[data-leika-settings-version]")).to_have_text(
        f"Leika v{leika.__version__}"
    )
    expect(about).to_have_text(f"Leika v{leika.__version__}. Source, docs, and examples.")

    source = about.locator("[data-leika-settings-source]")
    docs = about.locator("[data-leika-settings-docs]")
    examples = about.locator("[data-leika-settings-examples]")
    expect(source).to_have_attribute("href", "https://github.com/willjhliang/leika")
    expect(docs).to_have_attribute("href", "https://willjhliang.github.io/leika/")
    expect(examples).to_have_attribute(
        "href", "https://github.com/willjhliang/leika/tree/main/examples"
    )
    # External destinations out of an app that holds live state, so they open
    # beside the workspace rather than navigating away from it.
    for link in (source, docs, examples):
        expect(link).to_have_attribute("target", "_blank")

    # One line: the sentence fits the panel at its default width, so the footer
    # is no taller than the single line of text inside it.
    footer = about.bounding_box()
    link = source.bounding_box()
    assert footer is not None and link is not None
    assert footer["height"] < link["height"] * 2, (footer, link)
    assert page_errors == []


def test_the_handle_folds_the_panel_without_taking_the_gear_with_it(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The handle shows or hides the app's controls, and the panel folds with
    them. The gear is not part of that: its settings are a layer over the
    panel, so they open whether the body is up or folded away, and closing them
    leaves the body where it was."""
    leika_server.gui.add_checkbox("Enabled", initial_value=True)
    generated = leika_page.locator("[data-leika-generated-gui]")
    settings = leika_page.locator(f"{PANE}:visible")
    folded = leika_page.locator("[data-dock-collapsed]")
    expect(generated).to_be_visible(timeout=5_000)

    box = leika_page.get_by_test_id("control-panel-handle").bounding_box()
    assert box is not None

    def click_handle() -> None:
        """One deliberate click, spaced clear of the double-click window."""
        leika_page.wait_for_timeout(450)
        leika_page.mouse.click(box["x"] + 40, box["y"] + box["height"] / 2)

    # Opening the settings leaves the controls alone.
    open_settings(leika_page)
    expect(generated).to_be_visible()
    expect(folded).to_have_count(0)
    close_settings(leika_page)
    expect(generated).to_be_visible()

    # Folding the panel is the handle's, and the gear goes on working over a
    # folded panel -- the header it sits in is still there.
    click_handle()
    expect(folded).to_have_count(1, timeout=5_000)
    expect(generated).to_be_hidden()
    open_settings(leika_page)
    expect(settings).to_be_visible()
    expect(folded).to_have_count(1)

    # Closing them leaves the panel folded: the settings were never what was
    # holding it open.
    close_settings(leika_page)
    expect(folded).to_have_count(1)
    click_handle()
    expect(folded).to_have_count(0, timeout=5_000)
    expect(generated).to_be_visible()
    assert page_errors == []


def _theme_color(page: Page) -> str:
    return page.evaluate("() => document.querySelector('meta[name=\"theme-color\"]').content")


def _panel_surface(page: Page) -> str:
    return page.evaluate(
        """() => getComputedStyle(document.documentElement)
             .getPropertyValue("--leika-panel-surface").trim()"""
    )


def test_the_browser_chrome_is_tinted_like_the_dock(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """`theme-color` follows the scheme the viewer is actually in.

    The OS is asked for light throughout, so the Dark leg also pins the reason
    this is resolved in JS rather than declared with a `prefers-color-scheme`
    media query on the tag: the viewer's choice outranks the OS, and a media
    query would go on answering to the OS.
    """
    page.emulate_media(color_scheme="light")
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    pane = open_settings(page)

    for scheme, dark in (("Dark", True), ("Light", False)):
        choose_scheme(page, pane, scheme)
        page.wait_for_function(
            "dark => document.documentElement.classList.contains('dark') === dark",
            arg=dark,
        )
        surface = _panel_surface(page)
        # The dock's own surface, not a second copy of it that could drift.
        page.wait_for_function(
            """surface => document.querySelector('meta[name="theme-color"]')
                 .content === surface""",
            arg=surface,
            timeout=5_000,
        )
        assert _theme_color(page) == surface

    # The two schemes must not agree, or the assertions above would hold for a
    # tag nobody was updating.
    choose_scheme(page, pane, "Dark")
    page.wait_for_function("() => document.documentElement.classList.contains('dark')")
    in_dark = _theme_color(page)
    choose_scheme(page, pane, "Light")
    page.wait_for_function("() => !document.documentElement.classList.contains('dark')")
    assert in_dark != _theme_color(page)
    assert page_errors == []
