from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np
import pytest
from playwright.sync_api import Locator, Page, expect

import leika

from .utils import find_gui_input, find_gui_row


def test_core_controls_render_and_update(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.add_markdown("## Controls")
    checkbox = leika_server.gui.add_checkbox("Enabled", initial_value=True)
    text = leika_server.gui.add_text("Name", initial_value="Leika")
    dropdown = leika_server.gui.add_dropdown("Mode", options=("Fast", "Accurate"))
    leika_server.gui.add_button("Run")

    enabled = find_gui_row(leika_page, "Enabled").get_by_role("checkbox")
    expect(enabled).to_be_checked(timeout=5_000)
    enabled.click()
    deadline = time.monotonic() + 2.0
    while checkbox.value and time.monotonic() < deadline:
        time.sleep(0.01)
    assert checkbox.value is False

    name = find_gui_input(leika_page, "Name")
    expect(name).to_have_value("Leika")
    text.value = "Updated"
    expect(name).to_have_value("Updated", timeout=5_000)
    expect(name.locator("xpath=parent::*")).to_have_attribute("data-slot", "field-content")

    mode_row = find_gui_row(leika_page, "Mode")
    mode = mode_row.locator('[data-slot="combobox-trigger"]')
    expect(mode).to_be_visible()
    expect(mode).to_have_attribute("data-slot", "combobox-trigger")
    expect(mode_row.locator('[data-slot="select-trigger"]')).to_have_count(0)
    mode.click()
    search = leika_page.get_by_role("combobox", name="Search options")
    expect(search).to_be_visible()
    search.fill("accu")
    accurate = leika_page.get_by_role("option", name="Accurate", exact=True)
    expect(accurate).to_be_visible()
    expect(leika_page.get_by_role("option", name="Fast", exact=True)).to_have_count(0)
    accurate.click()
    deadline = time.monotonic() + 2.0
    while dropdown.value != "Accurate" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert dropdown.value == "Accurate"
    expect(mode).to_contain_text("Accurate")

    run_button = leika_page.get_by_role("button", name="Run")
    expect(run_button).to_be_visible()
    expect(run_button.locator("xpath=ancestor::*[@data-leika-gui-container][1]")).to_be_visible()
    assert page_errors == []


def test_button_and_upload_hints_and_visibility(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.add_button("Hinted action", hint="Runs the action once.")
    leika_server.gui.add_button("Hidden action", visible=False)
    leika_server.gui.add_upload_button(
        "Import image", hint="Choose a PNG image.", mime_type="image/png"
    )
    leika_server.gui.add_upload_button("Hidden import", visible=False)

    action = leika_page.get_by_role("button", name="Hinted action", exact=True)
    upload = leika_page.get_by_role("button", name="Import image", exact=True)
    expect(action).to_have_attribute("data-slot", "button", timeout=5_000)
    expect(upload).to_have_attribute("data-slot", "button")
    expect(action.locator('xpath=ancestor::*[@data-slot="tooltip-trigger"][1]')).to_have_count(1)
    expect(upload.locator('xpath=ancestor::*[@data-slot="tooltip-trigger"][1]')).to_have_count(1)
    expect(leika_page.get_by_role("button", name="Hidden action")).to_have_count(0)
    expect(leika_page.get_by_role("button", name="Hidden import")).to_have_count(0)

    action.hover()
    action_hint = leika_page.locator(
        '[data-slot="tooltip-content"]', has_text="Runs the action once."
    )
    expect(action_hint).to_be_visible()
    upload.hover()
    upload_hint = leika_page.locator(
        '[data-slot="tooltip-content"]', has_text="Choose a PNG image."
    )
    expect(upload_hint).to_be_visible()
    file_input = leika_page.locator('input[type="file"][accept="image/png"]')
    expect(file_input).to_have_count(1)
    expect(file_input).to_be_hidden()
    assert page_errors == []


def test_button_group_updates_optimistically_and_repeats_selected_action(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    handle = leika_server.gui.add_button_group("Render mode", options=("One", "Two", "Three"))
    clicks: list[str] = []
    handle.on_click(lambda event: clicks.append(event.target.value))

    row = find_gui_row(leika_page, "Render mode")
    one = row.get_by_role("button", name="One", exact=True)
    two = row.get_by_role("button", name="Two", exact=True)
    expect(one).to_have_attribute("aria-pressed", "true", timeout=5_000)

    two.click()
    deadline = time.monotonic() + 2.0
    while (handle.value != "Two" or clicks != ["Two"]) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert handle.value == "Two"
    assert clicks == ["Two"]
    expect(two).to_have_attribute("aria-pressed", "true")
    expect(one).to_have_attribute("aria-pressed", "false")

    two.click()
    deadline = time.monotonic() + 2.0
    while len(clicks) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert clicks == ["Two", "Two"]
    expect(two).to_have_attribute("aria-pressed", "true")
    assert page_errors == []


def test_fast_slider_release_never_flickers_backward(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    slider = leika_server.gui.add_slider("Speed", min=0.0, max=10.0, step=0.1, initial_value=1.0)
    track = find_gui_row(leika_page, "Speed").locator("[data-leika-slider]")
    track.wait_for(state="visible", timeout=5_000)
    slider_role = track.get_by_role("slider")
    bounds = track.bounding_box()
    assert bounds is not None
    y = bounds["y"] + bounds["height"] / 2
    leika_page.mouse.move(bounds["x"] + bounds["width"] * 0.1, y)
    leika_page.mouse.down()
    leika_page.mouse.move(bounds["x"] + bounds["width"] * 0.92, y, steps=24)
    leika_page.mouse.up()

    released = float(slider_role.get_attribute("aria-valuenow") or "0")
    samples: list[float] = []
    for _ in range(15):
        samples.append(float(slider_role.get_attribute("aria-valuenow") or "0"))
        leika_page.wait_for_timeout(30)
    assert min(samples) >= released - 0.11, (released, samples)

    deadline = time.monotonic() + 2.0
    while abs(float(slider.value) - released) > 0.11 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert abs(float(slider.value) - released) <= 0.11
    assert page_errors == []


def test_marked_slider_drag_survives_unrelated_streaming_rerenders(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    slider = leika_server.gui.add_slider(
        "Streaming slider",
        min=0.0,
        max=10.0,
        step=0.1,
        initial_value=1.0,
        marks=((0.0, "low"), (5.0, "mid"), (10.0, "high")),
        hint="Tooltip stays structurally stable while dragging.",
    )
    stream = leika_server.gui.add_number(
        "Streaming counter",
        initial_value=0,
        disabled=True,
    )

    slider_root = find_gui_row(leika_page, "Streaming slider").locator("[data-leika-slider]")
    thumb = slider_root.locator('[data-slot="slider-thumb"]')
    track = slider_root.locator('[data-slot="slider-track"]')
    slider_role = slider_root.get_by_role("slider")
    thumb.wait_for(state="visible", timeout=5_000)
    thumb_bounds = thumb.bounding_box()
    track_bounds = track.bounding_box()
    assert thumb_bounds is not None
    assert track_bounds is not None

    annotations = find_gui_row(leika_page, "Streaming slider").locator(
        "[data-leika-slider-annotations]"
    )
    labels = annotations.locator("[data-leika-slider-mark-label]")
    expect(labels).to_have_count(3)
    annotation_bounds = annotations.bounding_box()
    assert annotation_bounds is not None
    for index in range(labels.count()):
        label_bounds = labels.nth(index).bounding_box()
        assert label_bounds is not None
        assert label_bounds["x"] >= annotation_bounds["x"] - 0.5
        assert (
            label_bounds["x"] + label_bounds["width"]
            <= annotation_bounds["x"] + annotation_bounds["width"] + 0.5
        )
    assert annotations.evaluate("element => element.scrollWidth <= element.clientWidth")

    stop_stream = threading.Event()
    stream_started = threading.Event()
    stream_errors: list[BaseException] = []

    def update_unrelated_handle() -> None:
        counter = 0
        try:
            while not stop_stream.wait(0.005):
                counter += 1
                stream.value = counter
                stream_started.set()
        except BaseException as error:
            stream_errors.append(error)
            stop_stream.set()

    producer = threading.Thread(target=update_unrelated_handle, daemon=True)
    producer.start()
    try:
        assert stream_started.wait(timeout=1.0)
        start_x = thumb_bounds["x"] + thumb_bounds["width"] / 2.0
        y = thumb_bounds["y"] + thumb_bounds["height"] / 2.0
        destination_x = track_bounds["x"] + track_bounds["width"] * 0.88
        leika_page.mouse.move(start_x, y)
        leika_page.mouse.down()
        for step_index in range(1, 25):
            fraction = step_index / 24.0
            leika_page.mouse.move(
                start_x + (destination_x - start_x) * fraction,
                y,
            )
            leika_page.wait_for_timeout(8)
        leika_page.mouse.up()

        released = float(slider_role.get_attribute("aria-valuenow") or "0")
        assert released >= 7.5
        samples: list[float] = []
        for _ in range(20):
            samples.append(float(slider_role.get_attribute("aria-valuenow") or "0"))
            leika_page.wait_for_timeout(20)
        assert min(samples) >= released - 0.11, (released, samples)

        deadline = time.monotonic() + 2.0
        while abs(float(slider.value) - released) > 0.11 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert abs(float(slider.value) - released) <= 0.11
        assert float(slider_role.get_attribute("aria-valuenow") or "0") >= released - 0.11
        assert stream_errors == []
        assert page_errors == []
    finally:
        stop_stream.set()
        producer.join(timeout=2.0)
        assert not producer.is_alive()


def test_multislider_stops_if_disabled_mid_drag(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    handle = leika_server.gui.add_multi_slider(
        "Range", min=0, max=10, step=1, initial_value=(0, 3, 10)
    )
    thumb = (
        find_gui_row(leika_page, "Range")
        .locator('[data-leika-slider="multi"] [data-slot="slider-thumb"]')
        .nth(1)
    )
    thumb.wait_for(state="visible", timeout=5_000)
    bounds = thumb.bounding_box()
    assert bounds is not None
    start_x = bounds["x"] + bounds["width"] / 2
    y = bounds["y"] + bounds["height"] / 2
    leika_page.mouse.move(start_x, y)
    leika_page.mouse.down()
    leika_page.mouse.move(start_x + 20, y)
    leika_page.wait_for_timeout(150)
    assert handle.value[1] != 3

    handle.disabled = True
    leika_page.wait_for_timeout(150)
    value_when_disabled = handle.value
    leika_page.mouse.move(start_x + 90, y)
    leika_page.wait_for_timeout(150)
    leika_page.mouse.up()
    assert handle.value == value_when_disabled
    assert page_errors == []


def test_multislider_track_click_and_keyboard_are_accessible(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    handle = leika_server.gui.add_multi_slider(
        "Accessible range",
        min=0.1,
        max=1.1,
        step=0.2,
        initial_value=(0.1, 0.5, 1.1),
    )
    slider = find_gui_row(leika_page, "Accessible range").locator('[data-leika-slider="multi"]')
    track = slider.locator('[data-slot="slider-track"]')
    thumbs = slider.locator('[data-slot="slider-thumb"]')
    slider_roles = slider.get_by_role("slider")
    expect(thumbs).to_have_count(3)
    expect(slider_roles).to_have_count(3)

    track_bounds = track.bounding_box()
    assert track_bounds is not None
    leika_page.mouse.click(
        track_bounds["x"] + track_bounds["width"] * 0.72,
        track_bounds["y"] + track_bounds["height"] / 2.0,
    )
    deadline = time.monotonic() + 2.0
    while handle.value != (0.1, 0.5, 0.9) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert handle.value == (0.1, 0.5, 0.9)
    expect(slider_roles.nth(2)).to_have_attribute("aria-valuenow", "0.9")

    middle = slider_roles.nth(1)
    expect(middle).to_have_attribute("type", "range")
    expect(middle).to_have_attribute("aria-orientation", "horizontal")
    expect(middle).to_have_attribute("min", "0.1")
    expect(middle).to_have_attribute("max", "1.1")
    expect(middle).to_have_attribute("aria-label", "Accessible range handle 2")
    middle.focus()
    middle.press("ArrowRight")
    deadline = time.monotonic() + 2.0
    while handle.value != (0.1, 0.7, 0.9) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert handle.value == (0.1, 0.7, 0.9)
    expect(middle).to_have_attribute("aria-valuenow", "0.7")
    assert page_errors == []


def test_controls_use_semantic_tokens_and_compact_density(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(dark_mode=True)
    leika_page.wait_for_function(
        '() => document.documentElement.classList.contains("dark")',
        timeout=5_000,
    )
    leika_server.gui.add_slider(
        "Styled slider",
        min=0.0,
        max=1.0,
        step=0.1,
        initial_value=0.5,
        marks=((0.0, "low"), (1.0, "high")),
    )
    leika_server.gui.add_multi_slider(
        "Styled range", min=0.0, max=1.0, step=0.1, initial_value=(0.2, 0.8)
    )
    leika_server.gui.add_button_group("Styled actions", options=("A", "B", "C"))
    leika_server.gui.add_checkbox("Styled checkbox", initial_value=True)
    leika_server.gui.add_text("Styled text", initial_value="compact")
    leika_server.gui.add_dropdown("Styled dropdown", options=("First", "Second"))
    leika_server.gui.add_rgb("Styled color", initial_value=(30, 90, 180))

    def style(locator: Locator) -> dict[str, Any]:
        locator.wait_for(state="visible", timeout=5_000)
        return locator.evaluate(
            """element => {
                const value = getComputedStyle(element);
                return {
                    background: value.backgroundColor,
                    color: value.color,
                    borderColor: value.borderColor,
                    borderRadius: parseFloat(value.borderRadius),
                    boxShadow: value.boxShadow,
                    width: parseFloat(value.width),
                    height: parseFloat(value.height),
                    fontSize: parseFloat(value.fontSize),
                    fontWeight: value.fontWeight,
                    lineHeight: parseFloat(value.lineHeight),
                };
            }"""
        )

    def resolved_background(variable: str) -> str:
        return leika_page.evaluate(
            """variable => {
                const probe = document.createElement("span");
                probe.style.position = "fixed";
                probe.style.visibility = "hidden";
                probe.style.backgroundColor = `var(${variable})`;
                document.body.append(probe);
                const value = getComputedStyle(probe).backgroundColor;
                probe.remove();
                return value;
            }""",
            variable,
        )

    primary = resolved_background("--primary")
    muted = resolved_background("--muted")
    muted_foreground = resolved_background("--muted-foreground")
    border = resolved_background("--border")
    card = resolved_background("--card")
    ring = resolved_background("--ring")

    slider_row = find_gui_row(leika_page, "Styled slider")
    field_label = style(slider_row.locator('[data-slot="field-label"]'))
    slider = slider_row.locator("[data-leika-slider]").first
    slider_role = slider.get_by_role("slider")
    slider_thumb_locator = slider.locator('[data-slot="slider-thumb"]')
    slider_track_locator = slider.locator('[data-slot="slider-track"]')
    slider_role.focus()
    slider_thumb = style(slider_thumb_locator)
    slider_track = style(slider_track_locator)
    slider_mark = style(slider_row.locator("[data-leika-slider-mark]").first)
    slider_bar = style(slider_row.locator('[data-slot="slider-range"]'))

    range_slider = find_gui_row(leika_page, "Styled range").locator('[data-leika-slider="multi"]')
    range_thumb_locator = range_slider.locator('[data-slot="slider-thumb"]').first
    range_slider.get_by_role("slider").first.focus()
    range_thumb = style(range_thumb_locator)
    range_fill = style(range_slider.locator('[data-slot="slider-range"]'))

    checkbox_locator = find_gui_row(leika_page, "Styled checkbox").get_by_role("checkbox")
    action_locator = find_gui_row(leika_page, "Styled actions").get_by_role("button", name="A")
    text_input_locator = find_gui_row(leika_page, "Styled text").get_by_role("textbox")
    dropdown_locator = find_gui_row(leika_page, "Styled dropdown").locator(
        '[data-slot="combobox-trigger"]'
    )
    color_locator = find_gui_row(leika_page, "Styled color").locator("[data-leika-color-trigger]")
    action_group = find_gui_row(leika_page, "Styled actions").locator('[data-slot="toggle-group"]')
    expect(action_group).to_have_attribute("aria-label", "Styled actions")
    expect(action_group).to_have_attribute("data-spacing", "0")
    action_items = action_group.locator('[data-slot="toggle-group-item"]')
    expect(action_items).to_have_count(3)
    group_metrics = action_group.evaluate(
        """element => ({
            display: getComputedStyle(element).display,
            clientWidth: element.clientWidth,
            scrollWidth: element.scrollWidth,
        })"""
    )
    assert group_metrics["display"] == "flex"
    assert group_metrics["scrollWidth"] <= group_metrics["clientWidth"]
    item_boxes = [action_items.nth(index).bounding_box() for index in range(3)]
    assert all(item is not None for item in item_boxes)
    typed_item_boxes = [item for item in item_boxes if item is not None]
    assert (
        max(item["y"] for item in typed_item_boxes) - min(item["y"] for item in typed_item_boxes)
        <= 0.5
    )
    assert (
        max(item["height"] for item in typed_item_boxes)
        - min(item["height"] for item in typed_item_boxes)
        <= 0.5
    )
    expect(checkbox_locator).to_be_visible()
    expect(checkbox_locator).to_have_attribute("data-slot", "checkbox")
    expect(action_locator).to_be_visible()
    expect(action_locator).to_have_attribute("data-slot", "toggle-group-item")
    expect(text_input_locator).to_be_visible()
    expect(text_input_locator).to_have_attribute("data-slot", "input")

    checkbox = style(checkbox_locator)
    action = style(action_locator)
    text_input = style(text_input_locator)
    dropdown_trigger = style(dropdown_locator)
    color_trigger = style(color_locator)
    floating_panel = style(leika_page.get_by_test_id("control-panel"))

    field_rows = [
        find_gui_row(leika_page, label)
        for label in (
            "Styled slider",
            "Styled range",
            "Styled actions",
            "Styled checkbox",
            "Styled text",
            "Styled dropdown",
            "Styled color",
        )
    ]
    row_heights: list[float] = []
    for row in field_rows:
        row_bounds = row.bounding_box()
        label_locator = row.locator('[data-slot="field-label"]')
        label_bounds = label_locator.bounding_box()
        expect(label_locator).to_have_attribute("title", label_locator.inner_text())
        assert row_bounds is not None and label_bounds is not None
        row_heights.append(row_bounds["height"])
        assert (
            abs(
                label_bounds["y"]
                + label_bounds["height"] / 2.0
                - row_bounds["y"]
                - row_bounds["height"] / 2.0
            )
            <= 0.5
        )
    assert max(row_heights) - min(row_heights) <= 0.5
    assert 23.5 <= row_heights[0] <= 24.5

    for field_text in (field_label, action, text_input, dropdown_trigger, color_trigger):
        assert field_text["fontWeight"] == "400"
        assert abs(field_text["lineHeight"] - field_text["fontSize"]) <= 0.25

    # Nova's controls stay dense and use modest, non-capsule rounding.
    # Slider thumbs use the stock compact circular pointer target.
    for thumb in (slider_thumb, range_thumb):
        assert abs(thumb["width"] - thumb["height"]) <= 0.25
        assert 10.0 <= thumb["width"] <= 16.0
        assert thumb["borderRadius"] > 0.0
    assert slider_track["height"] <= 6.0
    assert 14.0 <= checkbox["width"] <= 20.0
    assert abs(checkbox["width"] - checkbox["height"]) <= 0.25
    for control in (action, text_input, dropdown_trigger, color_trigger):
        assert 23.5 <= control["height"] <= 24.5
        assert 0.0 < control["borderRadius"] < control["height"] / 2.0
    assert 4.0 <= floating_panel["borderRadius"] <= 16.0

    # Resolve the live CSS variables instead of pinning the test to a palette.
    # This checks semantic wiring in both stock light and dark themes.
    assert field_label["color"] == muted_foreground
    assert slider_track["background"] == muted
    assert slider_bar["background"] == primary
    assert slider_mark["background"] == border
    assert checkbox["background"] == primary
    assert range_fill["background"] == primary
    assert action["background"] == muted
    assert floating_panel["background"] == card
    assert slider_thumb["borderColor"] == ring
    assert page_errors == []


def test_command_palette_keyboard_fuzzy_search_and_close(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    triggered: list[str] = []
    leika_server.gui.add_command(
        "Export workspace",
        lambda: triggered.append("export"),
        description="Save all visible panes",
    )
    leika_server.gui.add_command(
        "Reset layout",
        lambda: triggered.append("reset"),
        description="Restore the default pane arrangement",
    )

    palette = leika_page.locator("[data-leika-command-palette]")
    deadline = time.monotonic() + 5.0
    while palette.count() == 0 and time.monotonic() < deadline:
        leika_page.keyboard.press("Control+K")
        leika_page.wait_for_timeout(50)
    expect(palette).to_be_visible()

    search = palette.get_by_role("combobox", name="Search commands")
    expect(search).to_be_focused()
    search.fill("export workspce")
    command_list = palette.locator("[data-leika-command-list]")
    target = command_list.locator("[data-leika-command-action]", has_text="Export workspace")
    expect(target).to_be_visible()
    expect(target).to_have_attribute("aria-selected", "true")
    expect(
        command_list.locator("[data-leika-command-action]", has_text="Reset layout")
    ).to_have_count(0)

    search.press("Enter")
    expect(palette).to_have_count(0)
    deadline = time.monotonic() + 2.0
    while triggered != ["export"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert triggered == ["export"]

    leika_page.keyboard.press("Control+K")
    expect(palette).to_be_visible()
    search = palette.get_by_role("combobox", name="Search commands")
    expect(search).to_have_value("")
    search.press("Escape")
    expect(palette).to_have_count(0)
    assert page_errors == []


def test_visibility_toggles_uniformly_across_element_kinds(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """`visible` is honored the same way whatever the element is.

    Each component used to check the flag itself, so honoring it was a
    convention rather than a guarantee -- a new element that forgot the check
    would simply ignore `visible`. It is now applied once where elements are
    dispatched, which is what this exercises across a folder, a plain input, a
    display element, and an image.
    """
    folder = leika_server.gui.add_folder("Group")
    with folder:
        leika_server.gui.add_text("Nested", initial_value="inside")
    slider = leika_server.gui.add_slider("Gain", min=0.0, max=1.0, step=0.1, initial_value=0.5)
    markdown = leika_server.gui.add_markdown("## Heading")
    image = leika_server.gui.add_image(np.zeros((8, 12, 3), dtype=np.uint8), label="Preview")

    heading = leika_page.get_by_role("heading", name="Heading")
    preview = leika_page.locator('[data-slot="field-label"]', has_text="Preview")
    nested = find_gui_row(leika_page, "Nested")
    gain = find_gui_row(leika_page, "Gain")
    for locator in (heading, preview, nested, gain):
        expect(locator).to_be_visible(timeout=15_000)

    folder.visible = False
    slider.visible = False
    markdown.visible = False
    image.visible = False
    for locator in (heading, preview, nested, gain):
        expect(locator).to_have_count(0, timeout=5_000)

    folder.visible = True
    slider.visible = True
    markdown.visible = True
    image.visible = True
    for locator in (heading, preview, nested, gain):
        expect(locator).to_be_visible(timeout=5_000)
    assert page_errors == []


@pytest.mark.plotly
def test_charts_read_aspect_the_same_way(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """`aspect` is width over height for both chart kinds.

    They used to disagree -- Plotly multiplied the width by it while uPlot
    divided -- so the same number produced a landscape chart in one and a
    portrait one in the other, and no docstring could be right about both.
    """
    go = pytest.importorskip("plotly.graph_objects")
    figure = go.Figure(data=[go.Scatter(x=[0, 1, 2], y=[0, 1, 0])])
    figure.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})
    leika_server.gui.add_plotly(figure, aspect=2.0, config={"staticPlot": True})
    x_data = np.linspace(0.0, 1.0, 16)
    leika_server.gui.add_uplot((x_data, x_data), ({}, {"label": "y"}), aspect=2.0)

    plotly_plot = leika_page.locator(".js-plotly-plot")
    uplot_plot = leika_page.locator(".uplot-container .uplot")
    expect(plotly_plot).to_be_visible(timeout=15_000)
    expect(uplot_plot).to_be_visible(timeout=15_000)

    def ratio(locator: Locator) -> float:
        bounds = locator.bounding_box()
        assert bounds is not None
        assert bounds["height"] > 0
        return bounds["width"] / bounds["height"]

    # Both wider than tall, and close enough to each other that a flipped
    # reading (which would give 0.5 for one of them) cannot pass.
    assert ratio(plotly_plot) == pytest.approx(2.0, rel=0.15)
    assert ratio(uplot_plot) == pytest.approx(2.0, rel=0.35)
    assert page_errors == []
