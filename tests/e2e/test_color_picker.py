from __future__ import annotations

import re
import time
from collections.abc import Callable

import imageio.v3 as iio
from playwright.sync_api import Locator, Page, expect

import leika

from .utils import find_gui_row


def _wait_for_value(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 2.0
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


def _color_trigger(page: Page, label: str) -> Locator:
    return find_gui_row(page, label).locator("[data-leika-color-trigger]")


def _open_color_picker(page: Page, label: str, *, keyboard: bool = False) -> Locator:
    trigger = _color_trigger(page, label)
    if keyboard:
        trigger.focus()
        trigger.press("Enter")
    else:
        trigger.click()
    popover = page.locator("[data-leika-color-popover]:visible")
    expect(popover).to_be_visible(timeout=5_000)
    return popover


def test_rgb_picker_keyboard_canvas_formats_server_sync_and_disabled_state(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    color = leika_server.gui.add_rgb(
        "Plot color",
        initial_value=(10, 20, 30),
    )
    leika_server.gui.add_rgb(
        "Disabled color",
        initial_value=(40, 50, 60),
        disabled=True,
    )

    trigger = _color_trigger(leika_page, "Plot color")
    disabled_trigger = _color_trigger(leika_page, "Disabled color")
    expect(disabled_trigger).to_be_visible(timeout=5_000)
    expect(trigger).to_have_attribute("data-slot", "popover-trigger")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    popover = _open_color_picker(leika_page, "Plot color", keyboard=True)
    expect(popover).to_have_attribute("data-slot", "popover-content")
    popover_width = popover.evaluate("element => parseFloat(getComputedStyle(element).width)")
    assert 319.5 <= popover_width <= 320.5

    picker = popover.locator("[data-leika-color-picker]")
    selection = picker.locator("[data-leika-color-selection]")
    hue = picker.get_by_role("slider", name="Hue")
    expect(picker).to_have_attribute("data-slot", "color-picker")
    expect(selection).to_be_focused()
    expect(hue).to_have_attribute("min", "0")
    expect(hue).to_have_attribute("max", "360")
    expect(picker.get_by_role("slider", name="Opacity")).to_have_count(0)

    outputs = picker.locator("[data-leika-color-output]")
    expect(outputs).to_have_count(1)
    expect(outputs.first).to_have_value("#0A141E")
    expect(outputs.first).not_to_have_attribute("readonly", "")

    outputs.first.fill("#3478F6")
    _wait_for_value(lambda: color.value == (52, 120, 246))
    expect(trigger).to_contain_text("rgb(52, 120, 246)")
    outputs.first.fill("#invalid")
    expect(outputs.first).to_have_attribute("aria-invalid", "true")
    assert color.value == (52, 120, 246)
    outputs.first.press("Escape")
    expect(outputs.first).to_have_value("#3478F6")

    color.value = (10, 20, 30)
    expect(outputs.first).to_have_value("#0A141E", timeout=5_000)

    format_trigger = picker.locator("[data-leika-color-format]")
    format_trigger.click()
    leika_page.get_by_role("option", name="RGB").click()
    expect(outputs).to_have_count(3)
    for index, channel in enumerate(("10", "20", "30")):
        expect(outputs.nth(index)).to_have_value(channel)

    for index, channel in enumerate(("52", "120", "246")):
        outputs.nth(index).fill(channel)
    _wait_for_value(lambda: color.value == (52, 120, 246))
    outputs.nth(2).press("Enter")

    color.value = (10, 20, 30)
    expect(outputs.first).to_have_value("10", timeout=5_000)

    color.value = (255, 255, 255)
    for index in range(3):
        expect(outputs.nth(index)).to_have_value("255", timeout=5_000)
        output_width = outputs.nth(index).evaluate(
            "element => parseFloat(getComputedStyle(element).width)"
        )
        assert output_width >= 48

    color.value = (10, 20, 30)
    expect(outputs.first).to_have_value("10", timeout=5_000)
    selection.focus()
    selection.press("Shift+ArrowRight")
    _wait_for_value(lambda: color.value != (10, 20, 30))

    color.value = (1, 2, 3)
    for index, channel in enumerate(("1", "2", "3")):
        expect(outputs.nth(index)).to_have_value(channel, timeout=5_000)
    expect(trigger).to_contain_text("rgb(1, 2, 3)")

    format_trigger.click()
    leika_page.get_by_role("option", name="CSS").click()
    expect(outputs).to_have_count(1)
    outputs.first.fill("rgb(12, 34, 56)")
    _wait_for_value(lambda: color.value == (12, 34, 56))

    format_trigger.click()
    leika_page.get_by_role("option", name="HSL").click()
    expect(outputs).to_have_count(3)
    for index, channel in enumerate(("0", "100", "50")):
        outputs.nth(index).fill(channel)
    _wait_for_value(lambda: color.value == (255, 0, 0))

    selection.press("Escape")
    expect(popover).to_be_hidden()
    expect(trigger).to_be_focused()
    expect(trigger).to_have_attribute("aria-expanded", "false")

    expect(disabled_trigger).to_be_disabled()
    expect(find_gui_row(leika_page, "Disabled color")).to_have_attribute("data-disabled", "true")
    assert page_errors == []


def test_rgba_picker_canvas_alpha_formats_geometry_and_opacity_preservation(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(dark_mode=True)
    leika_page.wait_for_function(
        '() => document.documentElement.classList.contains("dark")',
        timeout=5_000,
    )
    color = leika_server.gui.add_rgba(
        "Surface tint",
        initial_value=(10, 20, 30, 128),
    )
    leika_page.set_viewport_size({"width": 240, "height": 700})
    popover = _open_color_picker(leika_page, "Surface tint")
    popover_bounds = popover.bounding_box()
    viewport = leika_page.viewport_size
    assert popover_bounds is not None and viewport is not None
    assert popover_bounds["x"] >= -0.5
    assert popover_bounds["x"] + popover_bounds["width"] <= viewport["width"] + 0.5

    picker = popover.locator("[data-leika-color-picker]")
    selection = picker.locator("[data-leika-color-selection]")
    selection_thumb = picker.locator("[data-leika-color-selection-thumb]")
    hue = picker.get_by_role("slider", name="Hue")
    opacity = picker.get_by_role("slider", name="Opacity")
    expect(selection_thumb).to_be_visible()
    expect(opacity).to_have_attribute("min", "0")
    expect(opacity).to_have_attribute("max", "100")

    selection_bounds = selection.bounding_box()
    assert selection_bounds is not None
    assert selection_bounds["width"] >= popover_bounds["width"] - 34
    selection_height = selection.evaluate("element => parseFloat(getComputedStyle(element).height)")
    assert 159.5 <= selection_height <= 160.5

    format_trigger = picker.locator("[data-leika-color-format]")
    output = picker.locator("[data-leika-color-output]")
    eyedropper = picker.locator("[data-leika-color-eyedropper]")
    expect(output.first).to_have_value("#0A141E")
    expect(output.nth(1)).to_have_value("50")
    for compact_control in (format_trigger, output.first, eyedropper):
        height = compact_control.evaluate("element => parseFloat(getComputedStyle(element).height)")
        assert 23.5 <= height <= 24.5

    output_group = output.first.locator("xpath=parent::*")
    expect(output_group).not_to_have_css("overflow", "hidden")

    def corner_radii(control: Locator) -> dict[str, float]:
        return control.evaluate(
            """element => {
                const value = getComputedStyle(element);
                return {
                    topLeft: parseFloat(value.borderTopLeftRadius),
                    topRight: parseFloat(value.borderTopRightRadius),
                    bottomRight: parseFloat(value.borderBottomRightRadius),
                    bottomLeft: parseFloat(value.borderBottomLeftRadius),
                };
            }"""
        )

    value_corners = corner_radii(output.first)
    opacity_corners = corner_radii(output.nth(1))
    assert value_corners["topLeft"] > 0
    assert value_corners["bottomLeft"] > 0
    assert value_corners["topRight"] == 0
    assert opacity_corners["topLeft"] == 0
    assert opacity_corners["topRight"] > 0
    assert opacity_corners["bottomRight"] > 0

    hue_thumb = hue.locator("xpath=parent::*")
    opacity_thumb = opacity.locator("xpath=parent::*")
    expect(hue_thumb).to_have_css("background-color", "rgb(0, 128, 255)")
    expect(opacity_thumb).to_have_css("background-color", "rgba(10, 20, 30, 0.5)")

    selection_outline = selection_thumb.evaluate(
        "element => getComputedStyle(element).borderTopColor"
    )
    hue_outline = hue_thumb.evaluate("element => getComputedStyle(element).borderTopColor")
    assert selection_outline == hue_outline

    opacity_track = picker.locator('[data-leika-color-slider="alpha"] [data-slot="slider-track"]')
    opacity_background = opacity_track.evaluate(
        "element => getComputedStyle(element).backgroundImage"
    )
    assert "linear-gradient" in opacity_background
    assert "10, 20, 30" in opacity_background
    assert "url(" in opacity_background

    expect(output.first).not_to_have_attribute("readonly", "")
    expect(output.nth(1)).not_to_have_attribute("readonly", "")
    output.nth(1).fill("25")
    _wait_for_value(lambda: color.value == (10, 20, 30, 64))
    output.nth(1).press("Enter")
    color.value = (10, 20, 30, 128)
    expect(output.nth(1)).to_have_value("50", timeout=5_000)

    def drag_slider(slider: Locator, start: float, end: float) -> None:
        bounds = slider.bounding_box()
        assert bounds is not None
        y = bounds["y"] + bounds["height"] / 2
        leika_page.mouse.move(bounds["x"] + bounds["width"] * start, y)
        leika_page.mouse.down()
        leika_page.mouse.move(
            bounds["x"] + bounds["width"] * end,
            y,
            steps=5,
        )
        leika_page.mouse.up()

    format_trigger.click()
    leika_page.get_by_role("option", name="CSS").click()
    expect(output).to_have_count(1)
    output.first.fill("rgba(12, 34, 56, 0.25)")
    _wait_for_value(lambda: color.value == (12, 34, 56, 64))
    output.first.press("Enter")

    color.value = (10, 20, 30, 128)
    format_trigger.click()
    leika_page.get_by_role("option", name="HEX").click()
    expect(output).to_have_count(2)
    expect(output.first).to_have_value("#0A141E")

    hue_bar = picker.locator('[data-leika-color-slider="hue"]')
    drag_slider(hue_bar, 0.2, 0.8)
    expect(hue).to_have_value(re.compile(r"^(?:2[7-9][0-9]|300)(?:\.\d+)?$"))
    _wait_for_value(lambda: color.value[:3] != (10, 20, 30))
    assert color.value[3] == 128

    opacity_bar = picker.locator('[data-leika-color-slider="alpha"]')
    drag_slider(opacity_bar, 0.2, 0.75)
    expect(opacity).to_have_value(re.compile(r"^(?:7[0-9]|80)(?:\.\d+)?$"))
    _wait_for_value(lambda: 175 <= color.value[3] <= 205)

    color.value = (10, 20, 30, 128)
    expect(output.first).to_have_value("#0A141E", timeout=5_000)
    _wait_for_value(lambda: color.value == (10, 20, 30, 128))

    # Hue and canvas changes preserve the alpha channel.
    hue.focus()
    hue.press("Home")
    selection_bounds = selection.bounding_box()
    assert selection_bounds is not None
    selection.click(
        position={"x": selection_bounds["width"] - 8, "y": 8},
    )
    _wait_for_value(lambda: color.value[0] >= 225 and color.value[1] <= 25 and color.value[2] <= 25)
    selected_rgb = color.value[:3]
    assert color.value[3] == 128

    opacity.focus()
    opacity.press("Home")
    _wait_for_value(lambda: color.value == (*selected_rgb, 0))

    format_trigger.click()
    leika_page.get_by_role("option", name="HSL").click()
    expect(output).to_have_count(4)
    expect(output.first).to_have_value("0")
    expect(output.nth(3)).to_have_value("0")

    color.value = (3, 4, 5, 200)
    expect(output.nth(3)).to_have_value("78", timeout=5_000)
    format_trigger.click()
    leika_page.get_by_role("option", name="HEX").click()
    expect(output.first).to_have_value("#030405")
    expect(output.nth(1)).to_have_value("78")
    assert page_errors == []


def test_hue_survives_greyscale_and_the_far_right(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Hue is picker state, not something the color can carry back.

    A grey has no hue to recover and hue 360 is the same red as hue 0, so a
    slider reading its position off the RGB it produced was dead on greys and
    threw its thumb to the far left at the far right.
    """
    color = leika_server.gui.add_rgb("Accent", initial_value=(38, 38, 38))
    picker = _open_color_picker(leika_page, "Accent")
    hue = picker.get_by_role("slider", name="Hue")
    selection = picker.locator("[data-leika-color-selection]")

    # Grey: every hue is the same color, and the slider still has to move.
    expect(hue).to_have_attribute("aria-valuenow", "0")
    hue.focus()
    for _ in range(5):
        hue.press("ArrowRight")
    expect(hue).to_have_attribute("aria-valuenow", "5")
    assert color.value == (38, 38, 38)

    # Saturating from there keeps the hue that was chosen on the grey.
    selection_bounds = selection.bounding_box()
    assert selection_bounds is not None
    selection.click(position={"x": selection_bounds["width"] - 8, "y": 8})
    _wait_for_value(lambda: color.value[0] > color.value[2])
    expect(hue).to_have_attribute("aria-valuenow", "5")

    # The far right stays at the far right rather than wrapping to 0.
    hue.press("End")
    expect(hue).to_have_attribute("aria-valuenow", "360")
    thumb = picker.locator('[data-leika-color-slider="hue"] [data-slot="slider-thumb"]')
    track = picker.locator('[data-leika-color-slider="hue"] [data-slot="slider-track"]')
    thumb_box = thumb.bounding_box()
    track_box = track.bounding_box()
    assert thumb_box is not None and track_box is not None
    assert thumb_box["x"] > track_box["x"] + track_box["width"] / 2

    # And it is still the red that hue 0 would have given.
    _wait_for_value(lambda: color.value[0] > 200 and color.value[1] < 40)
    assert page_errors == []


def test_the_reset_button_appears_only_once_the_row_has_been_edited(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    color = leika_server.gui.add_rgb("Plot line", initial_value=(196, 196, 196))
    trigger = _color_trigger(leika_page, "Plot line")
    row = find_gui_row(leika_page, "Plot line")
    reset = row.locator("[data-leika-color-reset]")
    expect(trigger).to_be_visible()
    expect(reset).to_have_count(0)
    untouched_width = trigger.bounding_box()

    # Through the block rather than the hue slider: the initial value is a grey,
    # which every hue maps to alike.
    picker = _open_color_picker(leika_page, "Plot line")
    selection = picker.locator("[data-leika-color-selection]")
    bounds = selection.bounding_box()
    assert bounds is not None and untouched_width is not None
    selection.click(position={"x": bounds["width"] - 12, "y": 12})
    _wait_for_value(lambda: color.value != (196, 196, 196))
    selection.press("Escape")

    expect(reset).to_have_count(1)
    edited_width = trigger.bounding_box()
    assert edited_width is not None
    assert edited_width["width"] < untouched_width["width"]

    reset.click()
    _wait_for_value(lambda: color.value == (196, 196, 196))
    expect(reset).to_have_count(0)
    restored = trigger.bounding_box()
    assert restored is not None
    assert restored["width"] == untouched_width["width"]
    assert page_errors == []


def _settled_box(locator: Locator) -> dict[str, float]:
    """The element's box once it stops moving.

    The popover opens on a zoom-and-fade, so a box read the moment it becomes
    visible is a frame of that animation and lands a fraction of a pixel off.
    """
    previous: dict[str, float] | None = None
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        box = locator.bounding_box()
        assert box is not None
        if previous is not None and abs(box["x"] - previous["x"]) < 0.01:
            return box
        previous = box
        time.sleep(0.05)
    raise AssertionError("the popover never settled")


def test_the_popover_holds_its_place_when_the_reset_button_appears(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """It aligns to the row, not the trigger, which the button shortens."""
    color = leika_server.gui.add_rgb("Plot line", initial_value=(196, 196, 196))

    def popover_origin() -> tuple[float, float]:
        picker = _open_color_picker(leika_page, "Plot line")
        box = _settled_box(picker)
        picker.locator("[data-leika-color-selection]").press("Escape")
        expect(picker).to_be_hidden()
        return box["x"], box["y"]

    unedited = popover_origin()

    picker = _open_color_picker(leika_page, "Plot line")
    selection = picker.locator("[data-leika-color-selection]")
    bounds = selection.bounding_box()
    assert bounds is not None
    selection.click(position={"x": bounds["width"] - 12, "y": 12})
    _wait_for_value(lambda: color.value != (196, 196, 196))
    selection.press("Escape")
    expect(find_gui_row(leika_page, "Plot line").locator("[data-leika-color-reset]")).to_have_count(
        1
    )

    # Anchored to the trigger, this moved by the button's whole width plus the
    # gap, so a pixel of tolerance is nowhere near what the bug looked like.
    edited = popover_origin()
    assert abs(edited[0] - unedited[0]) < 1.0, (unedited, edited)
    assert abs(edited[1] - unedited[1]) < 1.0, (unedited, edited)
    assert page_errors == []


def _edge_scanlines(selection: Locator) -> dict[str, float]:
    """Mean brightness of each outermost edge of the block, read off the pixels.

    Sampled on the centre scanline of each edge, so the rounded corners are not
    what gets measured.
    """
    pixels = iio.imread(selection.screenshot(), extension=".png")[:, :, :3]
    height, width = pixels.shape[:2]
    return {
        "top": float(pixels[0, width // 4 : -width // 4].mean()),
        "bottom": float(pixels[-1, width // 4 : -width // 4].mean()),
        "left": float(pixels[height // 4 : -height // 4, 0].mean()),
        "right": float(pixels[height // 4 : -height // 4, -1].mean()),
    }


def test_the_selection_gradient_does_not_wrap_at_its_edges(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The block's gradients are sized to one box and painted into a larger one.

    Left at the CSS defaults that is a one-pixel shortfall filled by `repeat`
    with the START of the next tile, so every edge showed the color of the
    OPPOSITE edge: a white seam down the right, a pale one along the bottom.
    Only dark mode shows it, since a light theme's opaque border covers the
    overhang, so the assertion needs the translucent border to see through.
    """
    leika_server.gui.configure_theme(dark_mode=True)
    leika_server.gui.add_rgb("Accent", initial_value=(20, 90, 210))
    expect(leika_page.locator("html")).to_have_class(re.compile(r"\bdark\b"))
    picker = _open_color_picker(leika_page, "Accent")
    selection = picker.locator("[data-leika-color-selection]")
    expect(selection).to_be_visible()

    edges = _edge_scanlines(selection)
    # Brightness runs dark at the bottom to bright at the top, and saturation
    # white at the left to the full hue at the right. Both inverted under the
    # wrap, which is what makes this a fact about the gradient rather than a
    # reading of whichever pixels it happens to produce.
    assert edges["top"] > edges["bottom"] + 40, edges
    assert edges["left"] > edges["right"] + 40, edges
    assert page_errors == []
