from __future__ import annotations

import re
import time
from collections.abc import Callable

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
