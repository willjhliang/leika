from __future__ import annotations

import re
import threading
import time
from typing import Any

import numpy as np
import pytest
from playwright.sync_api import Locator, Page, expect

import leika
from leika import _messages

from .utils import assert_stable_viewer, find_gui_input, find_gui_row, wait_until


def test_core_controls_render_and_update(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.add_text(None, "## Controls", editable=False, markdown=True, multiline=True)
    checkbox = leika_server.gui.add_checkbox("Enabled", initial_value=True)
    text = leika_server.gui.add_text("Name", initial_value="Leika")
    # Searchable, so this covers the filtering path; the plain default has its
    # own test below.
    dropdown = leika_server.gui.add_dropdown("Mode", options=("Fast", "Accurate"), searchable=True)
    leika_server.gui.add_button("Run")

    enabled = find_gui_row(leika_page, "Enabled").get_by_role("checkbox")
    expect(enabled).to_be_checked(timeout=5_000)
    enabled.click()
    wait_until(lambda: checkbox.value is False)

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
    wait_until(lambda: dropdown.value == "Accurate")
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
    leika_server.gui.add_button("Hinted action", hint="Runs the action once.", color="inverse")
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


def test_a_multi_part_upload_completes_through_the_acknowledged_wire_path(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    upload = leika_server.gui.add_upload_button(
        "Import recording", mime_type="application/octet-stream"
    )
    # One byte into a second client chunk exercises ACK0 authorization, the
    # first cumulative ACK, and the final ACK over the real worker/socket.
    contents = bytes(range(256)) * 2048 + b"!"
    file_input = leika_page.locator('input[type="file"][accept="application/octet-stream"]')
    expect(file_input).to_have_count(1, timeout=5_000)
    file_input.set_input_files(
        {
            "name": "recording.bin",
            "mimeType": "application/octet-stream",
            "buffer": contents,
        }
    )

    wait_until(lambda: upload.value.name == "recording.bin" and upload.value.content == contents)
    expect(leika_page.get_by_role("button", name="Import recording")).to_be_enabled()
    expect(leika_page.locator("[data-leika-upload-error]")).to_have_count(0)
    expect(leika_page.locator('[data-slot="progress"]')).to_have_count(0)
    assert page_errors == []


def open_form(page: Page) -> Locator:
    """Open the panel's form popout, and return it."""
    popover = page.locator("[data-leika-form-popover]")
    if popover.count() == 0:
        page.locator("[data-leika-form-trigger]").click()
        expect(popover).to_be_visible(timeout=5_000)
    return popover


def test_a_form_opens_from_one_row_into_a_popout(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A form is one row -- its label and a way in -- not a section sitting
    open among the live controls. The fields are in the popout, and submitting
    from there reaches Python, by the button and by Enter alike."""
    submits: list[int] = []
    with leika_server.gui.add_form(label="Profile") as form:
        name = leika_server.gui.add_text("Name", initial_value="Ada")
    form.on_submit(lambda _: submits.append(len(submits) + 1))

    row = find_gui_row(leika_page, "Profile")
    expect(row).to_be_visible(timeout=5_000)
    trigger = row.locator("[data-leika-form-trigger]")
    expect(trigger).to_have_text("Open form")
    # Secondary: the way into a form does not carry the panel's accent.
    expect(trigger).to_have_attribute("data-leika-button-color", "default")
    # Closed, the form is a row and nothing else -- no fields on the panel.
    expect(leika_page.get_by_label("Name")).to_have_count(0)

    popout = open_form(leika_page)
    field = popout.get_by_label("Name")
    expect(field).to_be_visible()
    submit = popout.get_by_role("button", name="Submit", exact=True)
    reset = popout.get_by_role("button", name="Reset", exact=True)
    expect(submit).to_be_visible()
    expect(reset).to_be_visible()

    # Reset is the other way out of a half-written answer: it puts the fields
    # back to what Python declared, and leaves the popout open to start again.
    field.fill("Edited")
    wait_until(lambda: name.value == "Edited")
    reset.click()
    wait_until(lambda: name.value == "Ada")
    expect(field).to_have_value("Ada")
    expect(popout).to_be_visible()
    assert submits == []

    # Submitting is the way out proper: the popout closes on its own button.
    submit.click()
    wait_until(lambda: submits == [1])
    expect(popout).to_have_count(0, timeout=5_000)

    # Enter in a single-line text input is the same commit, and closes it the
    # same way. The edit is not waited on before the press, so a submit can
    # ride in the same throttle window as the edit it commits -- which used to
    # replace that edit outright, leaving `on_submit` reading the old value.
    # Whether the two land in one window here is up to Playwright's own
    # timings; what pins that case down is WebsocketUtils.test.ts.
    popout = open_form(leika_page)
    field = popout.get_by_label("Name")
    field.fill("Grace")
    field.press("Enter")
    wait_until(lambda: submits == [1, 2])
    assert name.value == "Grace"
    expect(popout).to_have_count(0, timeout=5_000)

    # And a submit from Python closes it too, having reached the client by the
    # one path every submit takes.
    popout = open_form(leika_page)
    form.submit_form()
    wait_until(lambda: submits == [1, 2, 3])
    expect(popout).to_have_count(0, timeout=5_000)

    # A form with no label: its trigger takes the whole row, the way a
    # labelless button does, rather than leaving an empty label column.
    plain = leika_server.gui.add_form()
    plain.add_text("Comment", initial_value="")
    triggers = leika_page.locator("[data-leika-form-trigger]")
    expect(triggers).to_have_count(2, timeout=5_000)
    labelled = trigger.bounding_box()
    unlabelled = triggers.nth(1).bounding_box()
    assert labelled is not None and unlabelled is not None
    assert unlabelled["width"] > labelled["width"], (unlabelled, labelled)
    assert triggers.nth(1).locator("xpath=ancestor::*[@data-leika-gui-row]").count() == 0
    assert page_errors == []


def test_a_popup_opens_folder_like_contents_from_a_labelled_row(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    with leika_server.gui.add_popup("Render options") as popup:
        axes = leika_server.gui.add_checkbox("Show axes", initial_value=True)
        with leika_server.gui.add_folder("Advanced"):
            leika_server.gui.add_number("Line width", initial_value=2.0)

    row = find_gui_row(leika_page, "Render options")
    expect(row).to_be_visible(timeout=5_000)
    trigger = row.locator("[data-leika-popup-trigger]")
    expect(trigger).to_have_text("Open popup")
    expect(trigger.locator("svg")).to_have_class(re.compile("lucide-panel-top-open"))
    expect(leika_page.get_by_role("checkbox", name="Show axes")).to_have_count(0)

    trigger.click()
    popout = leika_page.locator("[data-leika-popup-popover]")
    expect(popout).to_be_visible(timeout=5_000)
    checkbox = popout.get_by_role("checkbox", name="Show axes")
    expect(checkbox).to_be_checked()
    expect(popout.get_by_text("Advanced", exact=True)).to_be_visible()
    checkbox.click()
    wait_until(lambda: axes.value is False)

    popup.label = "Updated options"
    expect(find_gui_row(leika_page, "Updated options")).to_be_visible(timeout=5_000)
    expect(popout).to_be_visible()
    leika_page.keyboard.press("Escape")
    expect(popout).to_have_count(0)

    empty = leika_server.gui.add_popup("Empty popup")
    empty_trigger = find_gui_row(leika_page, "Empty popup").locator("[data-leika-popup-trigger]")
    expect(empty_trigger).to_be_disabled(timeout=5_000)
    late = empty.add_text("Late field", initial_value="")
    expect(empty_trigger).to_be_enabled(timeout=5_000)
    empty_trigger.click()
    late_field = leika_page.get_by_role("textbox", name="Late field")
    expect(late_field).to_be_visible(timeout=5_000)
    late.remove()
    expect(late_field).to_have_count(0)
    expect(empty_trigger).to_have_attribute("aria-expanded", "false")

    popup.visible = False
    expect(leika_page.locator("[data-leika-popup-popover]")).to_have_count(0)
    expect(leika_page.get_by_role("button", name="Open popup")).to_have_count(1)
    assert page_errors == []


def test_a_mini_form_sends_from_the_end_of_its_field_row(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """One field, no popout: the field keeps its row and the commit joins it as
    a square button on the end, sized like the undo a color row carries."""
    submits: list[str] = []
    with leika_server.gui.add_mini_form() as mini:
        query = leika_server.gui.add_text("Search", initial_value="")
    mini.on_submit(lambda _: submits.append(query.value))

    field = find_gui_input(leika_page, "Search")
    expect(field).to_be_visible(timeout=5_000)
    send = leika_page.locator("[data-leika-form-send]")
    # No door and no row of its own: the field's row is the whole of it.
    expect(leika_page.locator("[data-leika-form-trigger]")).to_have_count(0)
    expect(send).to_be_visible()
    box = send.bounding_box()
    assert box is not None
    assert box["width"] == box["height"], box

    field.fill("comets")
    wait_until(lambda: query.value == "comets")
    send.click()
    wait_until(lambda: submits == ["comets"])

    # Enter in the field is the same send, since the button is the form's own
    # submit rather than a click handler beside it.
    field.fill("again")
    wait_until(lambda: query.value == "again")
    field.press("Enter")
    wait_until(lambda: submits == ["comets", "again"])
    assert page_errors == []


def test_a_forms_action_buttons_render_below_its_fields(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A form's actions belong at the bottom, and they are created at the top.

    They have to exist before the `with` body that fills the form runs, so they
    hold the form's smallest order number and the server moves them after the
    fact. That has to land on the client that watched the form being built as
    well as on one that arrives to find it finished -- two different paths, an
    update and a replay.
    """
    with leika_server.gui.add_form(label="Profile") as form:
        leika_server.gui.add_text("Name", initial_value="Ada")
        leika_server.gui.add_checkbox("Subscribe", initial_value=False)

    def assert_submit_is_last(page: Page) -> None:
        """Every row of the form sits above the action buttons."""
        open_form(page)
        save = page.get_by_role("button", name="Submit", exact=True)
        expect(save).to_be_visible(timeout=5_000)
        button = save.bounding_box()
        assert button is not None
        rows = page.locator("form", has=save).locator("[data-leika-gui-row]")
        for index in range(rows.count()):
            row = rows.nth(index)
            # The actions' own row is the one they are allowed to be level with.
            if row.get_by_role("button", name="Submit", exact=True).count():
                continue
            box = row.bounding_box()
            assert box is not None
            assert box["y"] + box["height"] <= button["y"] + 0.5, (index, box, button)

    # The client that was already connected, and saw the move as an update.
    assert_submit_is_last(leika_page)

    # A client that arrives afterwards, and is replayed the finished form.
    leika_page.reload()
    leika_page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    assert_submit_is_last(leika_page)

    # And a field added to a form the client has already drawn, which is the
    # case that has nothing to do with what order the messages went out in: the
    # button is on screen, in a place the client has to be told to move it from.
    form.add_text("Nickname", initial_value="")
    expect(find_gui_row(leika_page, "Nickname")).to_be_visible(timeout=5_000)
    assert_submit_is_last(leika_page)
    assert page_errors == []


def test_a_button_group_reports_every_press_and_marks_none_of_them(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A row of buttons, not a choice between them. Each press is reported --
    including a repeat of the one just pressed, which a selection control would
    swallow as a no-op -- and nothing in the row is left looking pressed."""
    handle = leika_server.gui.add_button(("One", "Two", "Three"), label="Render mode")
    clicks: list[str] = []
    handle.on_click(lambda event: clicks.append(event.target.value))

    row = find_gui_row(leika_page, "Render mode")
    one = row.get_by_role("button", name="One", exact=True)
    two = row.get_by_role("button", name="Two", exact=True)
    expect(one).to_be_visible(timeout=5_000)

    two.click()
    wait_until(lambda: handle.value == "Two" and clicks == ["Two"])

    # The same option again: two presses, not one press and a no-op.
    two.click()
    wait_until(lambda: len(clicks) >= 2)
    assert clicks == ["Two", "Two"]

    # And none of it shows on screen: no option is on.
    for option in (one, two):
        assert option.get_attribute("aria-pressed") is None
        assert option.get_attribute("data-state") is None
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
    wait_until(lambda: handle.value == (0.1, 0.5, 0.9))
    expect(slider_roles.nth(2)).to_have_attribute("aria-valuenow", "0.9")

    middle = slider_roles.nth(1)
    expect(middle).to_have_attribute("type", "range")
    expect(middle).to_have_attribute("aria-orientation", "horizontal")
    expect(middle).to_have_attribute("min", "0.1")
    expect(middle).to_have_attribute("max", "1.1")
    expect(middle).to_have_attribute("aria-label", "Accessible range handle 2")
    middle.focus()
    middle.press("ArrowRight")
    wait_until(lambda: handle.value == (0.1, 0.7, 0.9))
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
    leika_server.gui.add_button(("A", "B", "C"), label="Styled actions", color="inverse")
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

    # The UI runs Geist a step lighter than the Tailwind defaults, so resolve
    # the body weight rather than pinning the test to a number.
    body_font_weight = leika_page.evaluate("() => getComputedStyle(document.body).fontWeight")

    primary = resolved_background("--primary")
    muted = resolved_background("--muted")
    muted_foreground = resolved_background("--muted-foreground")
    border = resolved_background("--border")
    card = resolved_background("--card")
    ring = resolved_background("--ring")
    input_border = resolved_background("--input")

    slider_row = find_gui_row(leika_page, "Styled slider")
    field_label = style(slider_row.locator('[data-slot="field-label"]'))
    slider = slider_row.locator("[data-leika-slider]").first
    slider_role = slider.get_by_role("slider")
    slider_thumb_locator = slider.locator('[data-slot="slider-thumb"]')
    slider_track_locator = slider.locator('[data-slot="slider-track"]')
    slider_thumb = style(slider_thumb_locator)
    slider_track = style(slider_track_locator)
    slider_mark = style(slider_row.locator("[data-leika-slider-mark]").first)
    slider_bar = style(slider_row.locator('[data-slot="slider-range"]'))

    range_slider = find_gui_row(leika_page, "Styled range").locator('[data-leika-slider="multi"]')
    range_fill = style(range_slider.locator('[data-slot="slider-range"]'))

    checkbox_locator = find_gui_row(leika_page, "Styled checkbox").get_by_role("checkbox")
    action_locator = find_gui_row(leika_page, "Styled actions").get_by_role("button", name="A")
    text_input_locator = find_gui_row(leika_page, "Styled text").get_by_role("textbox")
    dropdown_locator = find_gui_row(leika_page, "Styled dropdown").locator(
        '[data-slot="select-trigger"]'
    )
    color_locator = find_gui_row(leika_page, "Styled color").locator("[data-leika-color-trigger]")
    action_group = find_gui_row(leika_page, "Styled actions").locator("[data-leika-button-group]")
    expect(action_group).to_have_attribute("aria-label", "Styled actions")
    expect(action_group.locator('[data-slot="button"]')).to_have_count(3)
    expect(checkbox_locator).to_be_visible()
    expect(checkbox_locator).to_have_attribute("data-slot", "checkbox")
    expect(action_locator).to_be_visible()
    expect(action_locator).to_have_attribute("data-slot", "button")
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
    # Every kind of row runs at the same height; the number itself is design.
    assert max(row_heights) - min(row_heights) <= 0.5

    for field_text in (field_label, action, text_input, dropdown_trigger, color_trigger):
        assert field_text["fontWeight"] == body_font_weight
    for field_text in (field_label, action, dropdown_trigger, color_trigger):
        assert abs(field_text["lineHeight"] - field_text["fontSize"]) <= 0.25
    # Firefox deliberately uses the native input control's internal leading,
    # which CSS cannot override. Its compact contract is the same font size and
    # the uniform row height asserted above.
    assert text_input["fontSize"] == field_label["fontSize"]

    # Resolve the live CSS variables instead of pinning the test to a palette.
    # This checks semantic wiring in both stock light and dark themes.
    assert field_label["color"] == muted_foreground
    assert slider_track["background"] == muted
    assert slider_bar["background"] == primary
    assert slider_mark["background"] == border
    assert checkbox["background"] == primary
    assert range_fill["background"] == primary
    # A group's selected option carries the accent, the way a filled button
    # does: `color` is one setting across both, and "inverse" means the same
    # thing to each.
    assert action["background"] == primary
    assert floating_panel["background"] == card
    # The thumb carries the app-wide focus treatment: a resting outline in
    # --input that switches to --ring when the range input inside it takes
    # focus. `to_have_css` polls, which settles the color transition.
    assert slider_thumb["borderColor"] == input_border
    slider_role.focus()
    expect(slider_thumb_locator).to_have_css("border-color", ring)
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
    wait_until(lambda: triggered == ["export"])

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
    markdown = leika_server.gui.add_text(
        None, "## Heading", editable=False, markdown=True, multiline=True
    )
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


def test_live_image_keeps_last_frame_mounted_during_replacements(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A live image keeps showing its last good frame while preparing the next one."""
    image = leika_server.gui.add_image(
        np.zeros((18, 24, 3), dtype=np.uint8),
        label="Live preview",
        format="png",
    )
    inline_image = leika_page.locator('[data-leika-gui-container] img[alt="Live preview"]')
    expect(inline_image).to_be_visible(timeout=15_000)
    leika_page.get_by_role("button", name="Expand image").click()
    viewer = leika_page.get_by_role("dialog", name="Live preview", exact=True)
    expanded_image = viewer.get_by_role("img", name="Live preview", exact=True)
    expect(expanded_image).to_be_visible(timeout=5_000)

    inline_image.evaluate("element => { element.dataset.leikaImageIdentity = 'inline'; }")
    expanded_image.evaluate("element => { element.dataset.leikaImageIdentity = 'expanded'; }")

    update_errors: list[BaseException] = []

    def publish_frames() -> None:
        try:
            time.sleep(0.15)
            for index in range(24):
                image.image = np.full(
                    (18, 24, 3),
                    (index * 11) % 256,
                    dtype=np.uint8,
                )
                time.sleep(0.025)
        except BaseException as error:
            update_errors.append(error)

    producer = threading.Thread(target=publish_frames, daemon=True)
    producer.start()
    continuity = leika_page.evaluate(
        """label => new Promise(resolve => {
            const findCopies = () => {
                const images = Array.from(document.querySelectorAll("img"))
                    .filter(image => image.getAttribute("alt") === label);
                return {
                    inline: images.find(image => image.closest('[role="dialog"]') === null),
                    expanded: images.find(image => image.closest('[role="dialog"]') !== null),
                };
            };
            const initial = findCopies();
            const copies = {
                inline: {
                    node: initial.inline,
                    missingSamples: 0,
                    replacements: 0,
                    previousSource: initial.inline?.getAttribute("src") ?? null,
                },
                expanded: {
                    node: initial.expanded,
                    missingSamples: 0,
                    replacements: 0,
                    previousSource: initial.expanded?.getAttribute("src") ?? null,
                },
            };
            const inspect = () => {
                const current = findCopies();
                for (const kind of ["inline", "expanded"]) {
                    const copy = copies[kind];
                    const node = current[kind];
                    if (node === undefined || node !== copy.node) {
                        copy.missingSamples += 1;
                        continue;
                    }
                    const source = node.getAttribute("src");
                    if (copy.previousSource !== null && source !== copy.previousSource) {
                        copy.replacements += 1;
                    }
                    copy.previousSource = source;
                }
            };
            const observer = new MutationObserver(inspect);
            observer.observe(document.body, {
                attributes: true,
                attributeFilter: ["src"],
                childList: true,
                subtree: true,
            });
            const sampler = window.setInterval(inspect, 4);
            window.setTimeout(() => {
                window.clearInterval(sampler);
                observer.disconnect();
                inspect();
                resolve({
                    inline: {
                        missingSamples: copies.inline.missingSamples,
                        replacements: copies.inline.replacements,
                    },
                    expanded: {
                        missingSamples: copies.expanded.missingSamples,
                        replacements: copies.expanded.replacements,
                    },
                });
            }, 1200);
        })""",
        "Live preview",
    )
    producer.join(timeout=2.0)

    assert not producer.is_alive()
    assert update_errors == []
    for kind in ("inline", "expanded"):
        assert continuity[kind]["replacements"] > 0, continuity
        assert continuity[kind]["missingSamples"] == 0, continuity
    expect(inline_image).to_have_attribute("data-leika-image-identity", "inline")
    expect(expanded_image).to_have_attribute("data-leika-image-identity", "expanded")
    assert page_errors == []


@pytest.mark.plotly
def test_charts_read_aspect_as_width_over_height(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """`aspect` is width over height: 2.0 must yield a landscape chart, so a
    flipped reading (which would measure 0.5) cannot pass."""
    go = pytest.importorskip("plotly.graph_objects")
    figure = go.Figure(data=[go.Scatter(x=[0, 1, 2], y=[0, 1, 0])])
    figure.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})
    leika_server.gui.add_plotly(figure, aspect=2.0, config={"staticPlot": True})

    plotly_plot = leika_page.locator(".js-plotly-plot")
    expect(plotly_plot).to_be_visible(timeout=15_000)

    def ratio(locator: Locator) -> float:
        bounds = locator.bounding_box()
        assert bounds is not None
        assert bounds["height"] > 0
        return bounds["width"] / bounds["height"]

    assert ratio(plotly_plot) == pytest.approx(2.0, rel=0.15)
    assert page_errors == []


@pytest.mark.plotly
def test_plotly_invalid_payload_is_visible_and_recovers(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """One malformed figure must not unmount the whole generated panel."""
    go = pytest.importorskip("plotly.graph_objects")
    handle = leika_server.gui.add_plotly(
        go.Figure(go.Scatter(y=[1, 2, 1])), config={"staticPlot": True}
    )
    plot = leika_page.locator(".js-plotly-plot")
    expect(plot).to_be_visible(timeout=15_000)

    # Exercise explicit test-only wire injection: public/private property
    # assignment cannot bypass the figure serializer, while the browser still
    # has to contain a stale or corrupted payload rather than throwing from
    # React render.
    leika_server.gui._websock_interface.queue_message_or_raise(
        _messages.GuiUpdateMessage(handle.id, {"_plotly_json_str": "{"})
    )
    error = leika_page.get_by_role("status")
    expect(error).to_have_text("Plotly data contains invalid JSON.", timeout=5_000)
    expect(error).to_be_visible()
    expect(plot).to_have_count(0)

    handle.figure = go.Figure(go.Bar(y=[3, 1, 2]))
    expect(error).to_have_count(0, timeout=5_000)
    expect(plot).to_be_visible(timeout=10_000)
    assert page_errors == []


@pytest.mark.plotly
def test_plotly_rejection_recovers_and_does_not_outlive_unmount(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    go = pytest.importorskip("plotly.graph_objects")
    handle = leika_server.gui.add_plotly(
        go.Figure(go.Scatter(y=[1, 2, 1])), config={"staticPlot": True}
    )
    plot = leika_page.locator(".js-plotly-plot")
    expect(plot).to_be_visible(timeout=15_000)

    leika_page.evaluate(
        """() => {
          window.__leikaPlotlyOriginalReact = window.Plotly.react;
          window.Plotly.react = () => Promise.reject(
            new Error("expected Plotly test rejection")
          );
        }"""
    )
    handle.figure = go.Figure(go.Bar(y=[2, 3, 1]))
    render_error = leika_page.get_by_role("status")
    expect(render_error).to_have_text("Plotly failed to render.", timeout=5_000)
    expect(render_error).to_be_visible()

    leika_page.evaluate(
        """() => {
          window.Plotly.react = window.__leikaPlotlyOriginalReact;
        }"""
    )
    handle.figure = go.Figure(go.Scatter(y=[3, 1, 2]))
    expect(render_error).to_have_count(0, timeout=5_000)
    expect(plot).to_be_visible(timeout=10_000)

    # Superseding a still-pending render revokes its ownership of status. Its
    # eventual rejection is handled, but cannot cover the newer valid figure.
    leika_page.evaluate(
        """() => {
          const plotly = window.Plotly;
          window.__leikaPlotlyOriginalReact = plotly.react;
          plotly.react = () => new Promise((_resolve, reject) => {
            window.__leikaPlotlyStaleReject = reject;
          });
        }"""
    )
    handle.figure = go.Figure(go.Bar(y=[2, 1, 3]))
    leika_page.wait_for_function(
        "() => typeof window.__leikaPlotlyStaleReject === 'function'",
        timeout=5_000,
    )
    leika_page.evaluate(
        """() => {
          const plotly = window.Plotly;
          const original = window.__leikaPlotlyOriginalReact;
          window.__leikaPlotlyNewerCalls = 0;
          plotly.react = (...args) => {
            window.__leikaPlotlyNewerCalls += 1;
            return original.apply(plotly, args);
          };
        }"""
    )
    handle.figure = go.Figure(go.Scatter(y=[1, 3, 2]))
    leika_page.wait_for_function("() => window.__leikaPlotlyNewerCalls > 0", timeout=5_000)
    leika_page.evaluate(
        """() => {
          window.__leikaPlotlyStaleReject(
            new Error("superseded Plotly test rejection")
          );
        }"""
    )
    leika_page.wait_for_timeout(50)
    expect(render_error).to_have_count(0)
    expect(plot).to_be_visible()
    leika_page.evaluate("() => { window.Plotly.react = window.__leikaPlotlyOriginalReact; }")

    # Leave a render promise pending, then remove the component before it
    # rejects. The rejection remains handled, cannot set state after unmount,
    # and the imperative Plotly host is purged exactly through cleanup.
    leika_page.evaluate(
        """() => {
          const plotly = window.Plotly;
          window.__leikaPlotlyOriginalReact = plotly.react;
          window.__leikaPlotlyOriginalPurge = plotly.purge;
          window.__leikaPlotlyPurgeCount = 0;
          plotly.react = () => new Promise((_resolve, reject) => {
            window.__leikaPlotlyReject = reject;
          });
          plotly.purge = (node) => {
            window.__leikaPlotlyPurgeCount += 1;
            return window.__leikaPlotlyOriginalPurge.call(plotly, node);
          };
        }"""
    )
    handle.figure = go.Figure(go.Bar(y=[1, 3, 2]))
    leika_page.wait_for_function(
        "() => typeof window.__leikaPlotlyReject === 'function'", timeout=5_000
    )
    handle.remove()
    expect(leika_page.get_by_role("button", name="Expand plot")).to_have_count(0, timeout=5_000)
    leika_page.wait_for_function("() => window.__leikaPlotlyPurgeCount > 0", timeout=5_000)
    leika_page.evaluate(
        """() => {
          window.Plotly.react = window.__leikaPlotlyOriginalReact;
          window.Plotly.purge = window.__leikaPlotlyOriginalPurge;
          window.__leikaPlotlyReject(new Error("late Plotly test rejection"));
        }"""
    )
    leika_page.wait_for_timeout(50)
    assert page_errors == []


def test_dropdown_defaults_to_a_plain_select_with_no_search_box(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Without `searchable`, the dropdown is a Select rather than a Combobox.

    The two differ in more than a filter box: the Select opens with the current
    option under the cursor, so part of the list can sit above the trigger,
    while the Combobox anchors its whole list below.
    """
    dropdown = leika_server.gui.add_dropdown("Mode", options=("Fast", "Accurate", "Exact"))

    row = find_gui_row(leika_page, "Mode")
    trigger = row.locator('[data-slot="select-trigger"]')
    expect(trigger).to_be_visible(timeout=5_000)
    expect(trigger).to_contain_text("Fast")
    expect(row.locator('[data-slot="combobox-trigger"]')).to_have_count(0)

    trigger.click()
    expect(leika_page.locator('[data-slot="select-content"]')).to_be_visible(timeout=5_000)
    # The filter box is the whole point of `searchable`; it must be absent here.
    expect(leika_page.get_by_role("combobox", name="Search options")).to_have_count(0)

    leika_page.get_by_role("option", name="Exact", exact=True).click()
    wait_until(lambda: dropdown.value == "Exact")
    expect(trigger).to_contain_text("Exact")

    # Server-side assignment drives the trigger too, not just user clicks.
    dropdown.value = "Accurate"
    expect(trigger).to_contain_text("Accurate", timeout=5_000)
    assert page_errors == []


def test_plain_dropdown_list_can_open_above_the_trigger(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The Select aligns the active option with the trigger.

    That is what distinguishes it from the Combobox: with a later option
    selected, the earlier ones have to render above the trigger rather than the
    whole list hanging below it.
    """
    options = tuple(f"Option {index}" for index in range(1, 9))
    leika_server.gui.add_dropdown("Many", options=options, initial_value="Option 6")

    trigger = find_gui_row(leika_page, "Many").locator('[data-slot="select-trigger"]')
    expect(trigger).to_be_visible(timeout=5_000)
    trigger.click()
    popup = leika_page.locator('[data-slot="select-content"]')
    expect(popup).to_be_visible(timeout=5_000)

    geometry = popup.evaluate(
        """el => {
            const trigger = document.querySelector('[data-slot="select-trigger"]');
            const first = el.querySelector('[data-slot="select-item"]');
            return {
                alignsItemWithTrigger: el.dataset.alignTrigger,
                firstItemAboveTriggerTop:
                    first.getBoundingClientRect().top
                    < trigger.getBoundingClientRect().top,
            };
        }"""
    )
    assert geometry == {"alignsItemWithTrigger": "true", "firstItemAboveTriggerTop": True}
    assert page_errors == []


@pytest.mark.plotly
def test_media_chrome_is_shared_and_labelled_like_the_panel(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Images and charts expand through the same control, drawn the same way,
    and an image's stacked label is typographically a row label.

    The media elements each carried their own copy of the expand button, which
    is how they came to disagree about its size. The label above an image is a
    layout difference, not a typographic one, so it is compared against a row
    label rather than pinned to literal values.
    """
    go = pytest.importorskip("plotly.graph_objects")
    leika_server.gui.add_slider("Threshold", min=0.0, max=1.0, step=0.1, initial_value=0.5)
    leika_server.gui.add_image(np.zeros((20, 30, 3), dtype=np.uint8), label="Preview")
    figure = go.Figure(data=[go.Scatter(x=[0, 1, 2], y=[0, 1, 0])])
    leika_server.gui.add_plotly(figure, aspect=2.0, config={"staticPlot": True})

    image_button = leika_page.get_by_role("button", name="Expand image")
    plot_button = leika_page.get_by_role("button", name="Expand plot")
    expect(image_button).to_be_attached(timeout=15_000)
    expect(plot_button).to_be_attached(timeout=15_000)

    probe = """el => {
        const style = getComputedStyle(el);
        const glyph = getComputedStyle(el.querySelector('svg'));
        return {
            width: style.width,
            height: style.height,
            position: style.position,
            glyphWidth: glyph.width,
            glyphHeight: glyph.height,
        };
    }"""
    assert image_button.evaluate(probe) == plot_button.evaluate(probe)

    label_probe = """el => {
        const style = getComputedStyle(el);
        return {
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            color: style.color,
            lineHeight: style.lineHeight,
        };
    }"""
    row_label = find_gui_row(leika_page, "Threshold").locator('[data-slot="field-label"]')
    expect(row_label).to_be_visible(timeout=5_000)
    image_label = leika_page.locator('[data-slot="field-label"]', has_text="Preview")
    expect(image_label).to_be_visible(timeout=5_000)
    assert image_label.evaluate(label_probe) == row_label.evaluate(label_probe)

    # Chrome, not content: hidden until the pointer (or focus) arrives.
    assert image_button.evaluate("el => getComputedStyle(el).opacity") == "0"
    leika_page.get_by_role("img").first.hover()
    expect(image_button).to_be_visible()
    image_button.click()
    expect(leika_page.get_by_role("dialog")).to_be_visible(timeout=5_000)
    assert page_errors == []


@pytest.mark.plotly
def test_a_plots_preview_is_titled_like_an_images(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Expanding a plot draws a title, the way expanding an image does.

    Drawing it was once optional and a plot took the default, so a plot's
    preview opened with a name only a screen reader could reach. The title is
    the one line of chrome a preview has, and what it says is which of the
    things on the page you are now looking at -- a question the media itself
    cannot answer, since it looks the same here as it did in the panel.
    """
    go = pytest.importorskip("plotly.graph_objects")
    leika_server.gui.add_image(np.zeros((20, 30, 3), dtype=np.uint8), label="Preview")
    figure = go.Figure(data=[go.Scatter(x=[0, 1, 2], y=[0, 1, 0])])
    leika_server.gui.add_plotly(figure, aspect=2.0, config={"staticPlot": True})

    title = leika_page.locator('[data-slot="dialog-title"]')
    # Typography and flow only. The two popups are different widths -- each is
    # the size of its own media -- and so their title boxes are too.
    probe = """el => {
        const style = getComputedStyle(el);
        return {
            fontSize: style.fontSize,
            fontWeight: style.fontWeight,
            lineHeight: style.lineHeight,
            color: style.color,
            position: style.position,
        };
    }"""

    seen = {}
    for control, expected in (("Expand image", "Preview"), ("Expand plot", "Plot")):
        button = leika_page.get_by_role("button", name=control)
        expect(button).to_be_attached(timeout=15_000)
        button.click()
        viewer = leika_page.locator(
            '[data-slot="dialog-content"][data-dialog-presentation="viewer"]'
        )
        expect(viewer).to_be_visible(timeout=5_000)
        assert_stable_viewer(viewer)
        # Visible, not merely present: `sr-only` would still satisfy a text
        # assertion, and being reachable by sight is the whole point.
        expect(title).to_be_visible(timeout=5_000)
        expect(title).to_have_text(expected)
        seen[control] = title.evaluate(probe)
        leika_page.keyboard.press("Escape")
        expect(title).to_have_count(0)

    # Same line of chrome, not two that happen to both be drawn.
    assert seen["Expand image"] == seen["Expand plot"], seen
    assert page_errors == []


def test_the_slider_number_box_is_opt_in(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """`show_value` is off by default, which leaves the track the whole row."""
    plain = leika_server.gui.add_slider("Trail", min=0.0, max=1.0, step=0.01, initial_value=0.5)
    leika_server.gui.add_slider(
        "Speed", min=0.0, max=1.0, step=0.01, initial_value=0.5, show_value=True
    )

    plain_row = find_gui_row(leika_page, "Trail")
    shown_row = find_gui_row(leika_page, "Speed")
    expect(plain_row.locator("[data-leika-slider]")).to_be_visible(timeout=5_000)
    expect(plain_row.get_by_label("Trail value")).to_have_count(0)
    expect(shown_row.get_by_label("Speed value")).to_have_value("0.5")

    # The box costs the track its width, so the plain one is the wider of the two.
    plain_track = plain_row.locator("[data-leika-slider]").bounding_box()
    shown_track = shown_row.locator("[data-leika-slider]").bounding_box()
    assert plain_track is not None and shown_track is not None
    assert plain_track["width"] > shown_track["width"] + 40

    # And it is a live prop, not only a constructor argument.
    plain.show_value = True
    expect(plain_row.get_by_label("Trail value")).to_have_value("0.5", timeout=5_000)
    assert page_errors == []


def test_button_and_toggle_colorways_are_roles(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Two roles, not two palettes: one carries the accent, one does not --
    across a single button, a whole group, and one option at a time (a Submit
    with a Reset beside it). All of them live props."""
    inverse = leika_server.gui.add_button("Run", color="inverse")
    plain = leika_server.gui.add_button("Cancel")
    group = leika_server.gui.add_button(("A", "B"), label="Filled", color="inverse")
    leika_server.gui.add_button(("C", "D"), label="Marked")
    leika_server.gui.add_button(
        ("Reset", "Submit"), label="Actions", color=("default", "inverse"), merge=True
    )
    leika_server.gui.add_toggle(
        ("Draft", "Live"), label="Stage", color=("default", "inverse"), multiple=True
    )

    run = leika_page.get_by_role("button", name="Run", exact=True)
    cancel = leika_page.get_by_role("button", name="Cancel", exact=True)
    expect(run).to_be_visible(timeout=5_000)

    # The filled one paints its background; the outlined one draws a border and
    # leaves the surface behind it alone.
    run_fill = run.evaluate("e => getComputedStyle(e).backgroundColor")
    cancel_fill = cancel.evaluate("e => getComputedStyle(e).backgroundColor")
    assert run_fill != cancel_fill, (run_fill, cancel_fill)
    assert cancel.evaluate("e => parseFloat(getComputedStyle(e).borderTopWidth)") >= 1

    # The outlined one is what a button is unless asked otherwise, and the
    # role is a live prop.
    assert plain.color == "default"
    assert inverse.color == "inverse"
    inverse.color = "default"
    expect(run).to_have_attribute("data-leika-button-color", "default", timeout=5_000)

    # A group is a row of buttons, so the colorway is what a button's is: it
    # applies to every option alike.
    filled = find_gui_row(leika_page, "Filled").locator('[data-slot="button"]')
    marked = find_gui_row(leika_page, "Marked").locator('[data-slot="button"]')

    def fill(option: Locator) -> str:
        return option.evaluate("e => getComputedStyle(e).backgroundColor")

    assert fill(filled.nth(0)) == fill(filled.nth(1))
    assert fill(marked.nth(0)) == fill(marked.nth(1))
    assert fill(filled.nth(0)) != fill(marked.nth(0))

    assert group.color == ("inverse", "inverse")
    group.color = "default"
    expect(
        find_gui_row(leika_page, "Filled").locator('[data-leika-button-color="default"]')
    ).to_have_count(2, timeout=5_000)
    # The fill is a transition, so this polls rather than reading one frame of
    # it: settled, the two groups are the same control in the same role.
    expect(filled.nth(0)).to_have_css("background-color", fill(marked.nth(0)), timeout=5_000)

    # And a sequence answers one option at a time, buttons and toggles alike.
    for row, kind in (("Actions", "button"), ("Stage", "toggle")):
        options = find_gui_row(leika_page, row).locator(f"[data-leika-{kind}]")
        expect(options.first).to_be_visible(timeout=5_000)
        assert options.count() == 2, row
        quiet, loud = options.nth(0), options.nth(1)
        assert quiet.get_attribute("data-leika-button-color") == "default", row
        assert loud.get_attribute("data-leika-button-color") == "inverse", row
        fills = [
            option.evaluate("e => getComputedStyle(e).backgroundColor") for option in (quiet, loud)
        ]
        assert fills[0] != fills[1], (row, fills)
        assert quiet.evaluate("e => parseFloat(getComputedStyle(e).borderLeftWidth)") >= 1
    assert page_errors == []


def test_a_label_sets_a_buttons_row_and_its_height(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Unlabelled -- the default -- a button or a group is the row, at its
    standalone 32px. Given a label it becomes a control in one: the label
    takes the left column, and the button drops to the 24px every other row
    control runs at."""
    leika_server.gui.add_text("Text", initial_value="x")
    leika_server.gui.add_button("Run")
    leika_server.gui.add_button("Stop", label="Playback")
    leika_server.gui.add_button(("A", "B", "C"))
    leika_server.gui.add_button(("X", "Y", "Z"), label="Channel")

    plain_button = leika_page.get_by_role("button", name="Run", exact=True)
    labelled_button = leika_page.get_by_role("button", name="Stop", exact=True)
    plain_group = leika_page.get_by_role("button", name="A", exact=True)
    labelled_option = leika_page.get_by_role("button", name="X", exact=True)
    expect(plain_button).to_be_visible(timeout=5_000)

    # The label is what puts a row around it, so an unlabelled control has none.
    assert plain_button.locator("xpath=ancestor::*[@data-leika-gui-row]").count() == 0
    assert plain_group.locator("xpath=ancestor::*[@data-leika-gui-row]").count() == 0
    assert labelled_button.locator("xpath=ancestor::*[@data-leika-gui-row]").count() == 1

    # And the width says the same thing: the labelled one gives up the label
    # column, which is a fixed 6rem.
    full = plain_button.bounding_box()
    beside_a_label = labelled_button.bounding_box()
    assert full is not None and beside_a_label is not None
    assert beside_a_label["width"] < full["width"] - 90
    assert beside_a_label["x"] > full["x"] + 90

    # The group divides whatever width it is given, so its options are wider
    # across the row than they are in the column.
    wide_option = plain_group.bounding_box()
    narrow_option = labelled_option.bounding_box()
    assert wide_option is not None and narrow_option is not None
    assert wide_option["width"] > narrow_option["width"]

    def height(locator: Locator) -> float:
        box = locator.bounding_box()
        assert box is not None
        return box["height"]

    row_input = find_gui_row(leika_page, "Text").get_by_role("textbox")
    for control in (labelled_button, labelled_option):
        assert height(control) == pytest.approx(height(row_input), abs=0.5)
        assert height(control) == pytest.approx(24.0, abs=0.5)
    for control in (plain_button, plain_group):
        assert height(control) == pytest.approx(32.0, abs=0.5)
    assert page_errors == []


def test_merging_joins_neighbouring_buttons_and_splitting_parts_them(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """`merge` is about the gaps between buttons: joined, neighbours share an
    edge and read as one block; parted, each stands on its own. A sequence
    answers one gap at a time, so a row can do both."""
    leika_server.gui.add_button(("A", "B", "C"), label="Joined")
    leika_server.gui.add_button(("A", "B", "C"), label="Parted", merge=False)
    leika_server.gui.add_button(("A", "B", "C"), label="Mixed", merge=(True, False))
    # A toggle row is the same control with a state that sticks, so its gaps
    # have to be the same too -- the buttons once lost a pixel of theirs to the
    # stock group's border overlap, which has no edge to overlap between runs.
    leika_server.gui.add_toggle(("A", "B", "C"), label="Toggles", merge=(True, False))
    leika_server.gui.add_button(
        ("Reset", "Submit"), label="Half", color=("default", "inverse"), merge=True
    )

    def gaps(row_label: str, kind: str = "button") -> list[float]:
        """Horizontal space between each pair of neighbouring controls."""
        items = find_gui_row(leika_page, row_label).locator(f"[data-leika-{kind}]")
        expect(items).to_have_count(3, timeout=5_000)
        boxes = [items.nth(index).bounding_box() for index in range(3)]
        assert all(box is not None for box in boxes)
        return [
            boxes[index + 1]["x"] - (boxes[index]["x"] + boxes[index]["width"])  # type: ignore[index]
            for index in range(2)
        ]

    # Joined neighbours share an edge -- they overlap by the one pixel of
    # border between them -- and parted ones stand the panel's own 4px apart.
    joined, parted, mixed = gaps("Joined"), gaps("Parted"), gaps("Mixed")
    assert joined == pytest.approx([-1.0, -1.0], abs=0.01), joined
    assert parted == pytest.approx([4.0, 4.0], abs=0.01), parted
    assert mixed == pytest.approx([-1.0, 4.0], abs=0.01), mixed
    toggle_gaps = gaps("Toggles", "toggle")
    assert toggle_gaps == pytest.approx(mixed, abs=0.01), (toggle_gaps, mixed)

    # Joined, and one half outlined: the hairline that divides two filled
    # neighbours would be drawn over that half's own border, so it is not.
    expect(
        find_gui_row(leika_page, "Half").locator('[data-slot="button-group-separator"]')
    ).to_have_count(0)
    assert page_errors == []


def test_a_toggle_wears_the_button_pressed_look_in_both_themes(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Off, a toggle is its button at rest; on, it is that button under the
    pointer. Asserted as an EQUALITY against the live button rather than as a
    difference: the dark outlined colorway once had no pressed value of its own
    and rendered ON exactly like OFF, which "they differ" would not have caught.

    Both roles, both themes, and no 1px nudge -- an on toggle must sit level
    with its neighbours.
    """
    # No label may be a substring of another: rows are found by label text.
    toggle = leika_server.gui.add_toggle("Face", label="Filled toggle", color="inverse")
    leika_server.gui.add_button("Face", label="Filled button", color="inverse")
    outlined = leika_server.gui.add_toggle("Face", label="Thin toggle", color="default")
    leika_server.gui.add_button("Face", label="Thin button", color="default")

    def control(row: str, kind: str) -> Locator:
        return find_gui_row(leika_page, row).locator(f"[data-leika-{kind}]")

    def settled_background(locator: Locator, *, hover: bool) -> str:
        """The element's background once it stops moving.

        These transition their colour, so the frame right after a hover is
        still the old one. Normalized across `oklab`/`oklch` notation, which
        the browser picks per state and which coincide for the greys this
        theme is built from.
        """
        leika_page.mouse.move(0, 0)
        if hover:
            locator.hover()
        previous = None
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            current = locator.evaluate("e => getComputedStyle(e).backgroundColor")
            if current == previous:
                return re.sub(r"^okl(ab|ch)", "okl", current)
            previous = current
            time.sleep(0.05)
        raise AssertionError("the colour never settled")

    expect(control("Filled toggle", "toggle")).to_be_visible(timeout=5_000)
    for dark in (False, True):
        leika_server.gui.configure_theme(dark_mode=dark)
        expect(leika_page.locator("html")).to_have_class(
            re.compile(r"\bdark\b") if dark else re.compile(r"^(?!.*\bdark\b).*$")
        )
        for toggle_row, button_row, handle in (
            ("Filled toggle", "Filled button", toggle),
            ("Thin toggle", "Thin button", outlined),
        ):
            toggle_control = control(toggle_row, "toggle")
            button = control(button_row, "button")
            where = (toggle_row, "dark" if dark else "light")

            handle.value = False
            expect(toggle_control).to_have_attribute("aria-pressed", "false", timeout=5_000)
            assert settled_background(toggle_control, hover=False) == settled_background(
                button, hover=False
            ), where

            handle.value = True
            expect(toggle_control).to_have_attribute("aria-pressed", "true", timeout=5_000)
            assert settled_background(toggle_control, hover=False) == settled_background(
                button, hover=True
            ), where
            assert toggle_control.evaluate("e => getComputedStyle(e).transform") in (
                "none",
                "matrix(1, 0, 0, 1, 0, 0)",
            ), where

    # And the browser drives it, not only Python.
    control("Filled toggle", "toggle").click()
    wait_until(lambda: toggle.value is False)
    assert page_errors == []


def test_a_toggle_row_holds_one_or_many(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The default row is a choice between its options; `multiple` lets them
    all be on at once. Either way the value is the tuple of what is on."""
    one = leika_server.gui.add_toggle(("Bold", "Italic"), label="One", initial_value="Bold")
    many = leika_server.gui.add_toggle(("Grid", "Axes"), label="Many", multiple=True)
    clearable = leika_server.gui.add_toggle(
        ("Bold", "Italic"), label="Clearable", initial_value="Bold", required=False
    )

    one_row = find_gui_row(leika_page, "One").locator("[data-leika-toggle]")
    many_row = find_gui_row(leika_page, "Many").locator("[data-leika-toggle]")
    expect(one_row.first).to_have_attribute("aria-pressed", "true", timeout=5_000)

    # Turning one on turns the other off.
    one_row.nth(1).click()
    wait_until(lambda: one.value == ("Italic",))
    expect(one_row.first).to_have_attribute("aria-pressed", "false")

    # Where several may be on, they accumulate -- and stay in declaration order
    # however they were clicked.
    many_row.nth(1).click()
    wait_until(lambda: many.value == ("Axes",))
    many_row.nth(0).click()
    wait_until(lambda: many.value == ("Grid", "Axes"))

    # A one-at-a-time row is required by default, so pressing the toggle that is
    # on is refused rather than emptying the row -- nothing to undo, and no
    # round trip. Made optional, the same press clears it.
    one_row.nth(1).click()
    wait_until(lambda: one.value == ("Italic",))
    leika_page.wait_for_timeout(300)
    assert one.value == ("Italic",)
    expect(one_row.nth(1)).to_have_attribute("aria-pressed", "true")

    clearable_row = find_gui_row(leika_page, "Clearable").locator("[data-leika-toggle]")
    clearable_row.nth(0).click()
    wait_until(lambda: clearable.value == ())
    expect(clearable_row.nth(0)).to_have_attribute("aria-pressed", "false")
    assert page_errors == []


def test_text_can_be_read_only_and_rendered_as_markdown(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """One element for text the viewer writes and text it only reads. Read-only
    it is not an input at all: no box to type in, a tint to say so, and markdown
    drawn as markdown."""
    prose = leika_server.gui.add_text(
        None, "## Heading\n\nWith **bold** in it.", editable=False, markdown=True, multiline=True
    )
    leika_server.gui.add_text("Status", "**ready**", editable=False)
    field = leika_server.gui.add_text("Name", "Ada")

    expect(leika_page.get_by_role("heading", name="Heading")).to_be_visible(timeout=15_000)
    expect(leika_page.locator("strong", has_text="bold")).to_be_visible()

    # Read-only means read-only: nowhere to type, and no input to find.
    reading = leika_page.locator("[data-leika-text-reading]")
    expect(reading).to_have_count(2)
    assert reading.first.locator("input, textarea").count() == 0

    # The characters themselves when markdown was not asked for, so a value
    # with markup in it is shown rather than interpreted.
    literal = find_gui_row(leika_page, "Status").locator("[data-leika-text-reading]")
    expect(literal).to_have_text("**ready**")

    # Tinted, and unmistakably not the same surface as the box beside it.
    tint, plain = (
        locator.evaluate("el => getComputedStyle(el).backgroundColor")
        for locator in (literal, find_gui_input(leika_page, "Name"))
    )
    assert tint != plain, (tint, plain)
    assert tint != "rgba(0, 0, 0, 0)", tint

    # Python still owns the value, and the rendering follows it.
    prose.value = "### Later"
    expect(leika_page.get_by_role("heading", name="Later")).to_be_visible(timeout=5_000)

    # And the editable one is still an input, which is the point of one element
    # doing both.
    name = find_gui_input(leika_page, "Name")
    name.fill("Grace")
    wait_until(lambda: field.value == "Grace")
    assert page_errors == []


def test_a_multiline_text_input_keeps_its_height_and_scrolls_its_own_text(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """The height a field asks for is the height it keeps. Sizing itself to its
    content instead, it grew without end: a pasted page of text made a 2618px
    box and pushed the control below it off the bottom of the screen."""
    leika_server.gui.add_text("Note", "", multiline=True, rows=3)
    leika_server.gui.add_text("Body", "", multiline=True, rows=8)
    leika_server.gui.add_button("Run")

    note = find_gui_row(leika_page, "Note").locator("textarea")
    body = find_gui_row(leika_page, "Body").locator("textarea")
    expect(note).to_be_visible(timeout=5_000)

    # More lines is a taller box, by something worth calling a line.
    short = note.bounding_box()
    tall = body.bounding_box()
    assert short is not None and tall is not None
    assert (tall["height"] - short["height"]) / 5 > 4, (tall, short)

    run = leika_page.get_by_role("button", name="Run")
    was = run.bounding_box()
    assert was is not None

    # Filled well past its height, the box is unmoved and scrolls its own text
    # instead -- and so is everything under it in the panel.
    note.fill("\n".join(f"line {n}" for n in range(200)))
    expect(note).to_have_value(re.compile("line 199"))
    now = note.bounding_box()
    after = run.bounding_box()
    assert now is not None and after is not None
    assert abs(now["height"] - short["height"]) < 1.0, (now, short)
    assert abs(after["y"] - was["y"]) < 1.0, (after, was)
    assert note.evaluate("el => el.scrollHeight > el.clientHeight + 1") is True
    assert page_errors == []


def _showing_controls(page: Page) -> list[str]:
    """The entries whose row is showing its grip and remove.

    A list keeps both in the tree at every row so they can be tabbed to and
    focused, and brings out only the ones on the row being worked on -- so what
    is on show is read off the paint rather than off the markup."""
    return page.locator("[data-leika-list-item]").evaluate_all(
        """rows => rows
            .filter((row) => getComputedStyle(
                row.querySelector("[data-leika-list-controls]")).opacity === "1")
            .map((row) => row.querySelector("[data-leika-list-entry]").value)"""
    )


def test_a_list_is_edited_added_to_removed_from_and_reordered(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Every one of the four reports the whole list, in the order it now reads."""
    entries = leika_server.gui.add_list("Tags", ("alpha", "beta", "gamma"))

    boxes = leika_page.locator("[data-leika-list-entry]")
    rows = leika_page.locator("[data-leika-list-item]")
    expect(boxes).to_have_count(3, timeout=5_000)

    # At rest a list is its entries; the controls come out inside the box,
    # which keeps the width they take.
    idle = boxes.first.bounding_box()
    rows.first.hover()
    hovered = boxes.first.bounding_box()
    assert idle is not None and hovered is not None
    # The box keeps its width: the controls are inside it, not beside it.
    assert hovered["width"] == idle["width"], (hovered, idle)
    for control in ("[data-leika-list-grip]", "[data-leika-list-remove]"):
        box = leika_page.locator(control).first.bounding_box()
        assert box is not None, control
        assert idle["x"] <= box["x"], (control, box, idle)
        assert box["x"] + box["width"] <= idle["x"] + idle["width"] + 0.5
        assert idle["y"] <= box["y"] + 0.5
        assert box["y"] + box["height"] <= idle["y"] + idle["height"] + 0.5

    # Typing in one.
    boxes.nth(0).fill("ALPHA")
    wait_until(lambda: entries.value == ("ALPHA", "beta", "gamma"))

    # Adding one: a new entry starts empty, at the end.
    leika_page.locator("[data-leika-list-add]").click()
    wait_until(lambda: entries.value == ("ALPHA", "beta", "gamma", ""))

    # Removing one, by its own button rather than the row's position.
    rows.nth(1).hover()
    leika_page.get_by_label("Remove entry 2").click()
    wait_until(lambda: entries.value == ("ALPHA", "gamma", ""))

    # Reordering by dragging a grip: the entry follows the pointer, and the
    # list is left alone until it lands -- so the move is reported once, as the
    # viewer meant it, rather than once for every row it crossed on the way.
    #
    # One row down means ONE row: an entry belongs to the row whose middle the
    # pointer is nearest. Measured from the top of the first row instead, it
    # changed rows half a row early and a drag onto the next one landed two
    # down.
    rows.first.hover()
    grip = leika_page.get_by_label("Reorder entry 1").bounding_box()
    second = rows.nth(1).bounding_box()
    last = rows.nth(2).bounding_box()
    assert grip is not None and second is not None and last is not None

    # Watch the carried box on every frame of what follows. Its surface is only
    # ever wrong for an instant -- a fade, restarted at each row it crosses --
    # so reading it once afterwards says nothing.
    leika_page.evaluate(
        """() => {
            window.__leikaSeeThrough = 0;
            const tick = () => {
                const box = document.querySelector(
                    "[data-leika-list-carried] [data-leika-list-entry]",
                );
                if (box !== null) {
                    const paint = getComputedStyle(box).backgroundColor;
                    if (paint.includes("/") || paint === "rgba(0, 0, 0, 0)") {
                        window.__leikaSeeThrough += 1;
                    }
                }
                if (window.__leikaWatching) requestAnimationFrame(tick);
            };
            window.__leikaWatching = true;
            requestAnimationFrame(tick);
        }"""
    )
    leika_page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    leika_page.mouse.down()
    leika_page.mouse.move(
        grip["x"] + grip["width"] / 2, second["y"] + second["height"] / 2, steps=6
    )
    leika_page.wait_for_timeout(250)
    # In hand is not moved: nothing has been reported, and the list still reads
    # as it did when the grip went down.
    assert entries.value == ("ALPHA", "gamma", ""), entries.value

    # The row is carried: it rides with the cursor rather than snapping between
    # slots, so it is offset from where its row rests and lifted over the ones
    # it passes.
    carried = leika_page.locator("[data-leika-list-carried]")
    expect(carried).to_have_count(1)
    expect(carried.locator("[data-leika-list-entry]")).to_have_value("ALPHA")
    assert carried.evaluate("row => getComputedStyle(row).transform") != "none"
    assert carried.evaluate("row => Number(getComputedStyle(row).zIndex)") > 0

    # And SOLID, not merely coloured, from the first frame it is held. A box
    # fades its colours by default, so the surface used to arrive over a sixth
    # of a second and start again from nothing at every row the entry crossed
    # -- see-through for most of a drag, with the entries behind showing
    # through the one in hand.
    surface = carried.locator("[data-leika-list-entry]").evaluate(
        "box => getComputedStyle(box).backgroundColor"
    )
    assert "/" not in surface and surface != "rgba(0, 0, 0, 0)", surface

    # The row it would fall into has stepped aside to open the space, so the
    # list reads as it will once the entry lands.
    assert rows.nth(1).evaluate("row => getComputedStyle(row).transform") != "none"

    # Only the entry in hand shows its controls. The rows are moving under a
    # cursor that is holding one of them, so whichever row happens to be
    # beneath it is not the row being worked on -- and each one it passed used
    # to light up as it went.
    assert _showing_controls(leika_page) == ["ALPHA"]

    leika_page.mouse.move(grip["x"] + grip["width"] / 2, last["y"] + last["height"] / 2, steps=6)

    # Dragged well past the end, it sits on the last row's place rather than
    # sailing on over whatever the panel has below the list.
    leika_page.mouse.move(grip["x"] + grip["width"] / 2, last["y"] + 400, steps=4)
    floating = carried.bounding_box()
    assert floating is not None
    assert abs(floating["y"] - last["y"]) < 1.5, (floating, last)

    leika_page.mouse.up()
    wait_until(lambda: entries.value == ("gamma", "", "ALPHA"))

    see_through = leika_page.evaluate(
        "() => { window.__leikaWatching = false; return window.__leikaSeeThrough; }"
    )
    assert see_through == 0, f"{see_through} frames of a see-through carried row"

    # Dropped, it is given back to the list: no row is carried, lifted, or left
    # holding the offset it travelled by.
    expect(leika_page.locator("[data-leika-list-carried]")).to_have_count(0)
    assert (
        leika_page.locator("[data-leika-list-item]").evaluate_all(
            "rows => rows.every(row => getComputedStyle(row).transform === 'none')"
        )
        is True
    )

    # And by the keyboard, which a drag cannot be asked to do. Rows are keyed
    # by place, so a reorder rewrites their contents rather than moving them:
    # the keys follow the entry to the row it moved into, which keeps its
    # controls out because that is the row the keys are working.
    rows.nth(2).hover()
    leika_page.get_by_label("Reorder entry 3").click()
    leika_page.keyboard.press("ArrowUp")
    leika_page.mouse.move(0, 0)
    wait_until(lambda: entries.value == ("gamma", "ALPHA", ""))
    expect(leika_page.get_by_label("Reorder entry 2")).to_be_focused()

    # A move slides the rows it touches from where their new contents came
    # from -- except here, where the browser is asked for reduced motion and
    # the rows are simply redrawn. Either way none of them is left holding a
    # transform once it is over.
    assert (
        leika_page.locator("[data-leika-list-item]").evaluate_all(
            "rows => rows.every(row => getComputedStyle(row).transform === 'none')"
        )
        is True
    )
    assert page_errors == []


def test_a_list_shows_its_controls_to_the_row_being_worked_on(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """An entry's controls are the pointer's or the keyboard's: they come out
    on the row one of them is on, on no other, and not at all once both have
    gone elsewhere."""
    entries = leika_server.gui.add_list("Items", ("alpha", "beta", "gamma"))
    rows = leika_page.locator("[data-leika-list-item]")
    expect(rows).to_have_count(3, timeout=5_000)

    def look_away() -> None:
        leika_page.mouse.move(2.0, 2.0)
        leika_page.wait_for_timeout(150)

    # The pointer: whichever row it is over, and none once it has left.
    rows.nth(1).hover()
    assert _showing_controls(leika_page) == ["beta"]
    look_away()
    assert _showing_controls(leika_page) == []

    # A drag leaves the keys on the grip so they can carry on from where the
    # pointer left off -- on the entry it moved rather than the row the drag
    # started in -- but leaving them there is not the same as working the row,
    # so the controls go with the cursor.
    rows.first.hover()
    grip = leika_page.get_by_label("Reorder entry 1").bounding_box()
    second = rows.nth(1).bounding_box()
    assert grip is not None and second is not None
    leika_page.mouse.move(grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    leika_page.mouse.down()
    leika_page.mouse.move(
        grip["x"] + grip["width"] / 2, second["y"] + second["height"] / 2, steps=6
    )
    leika_page.mouse.up()
    wait_until(lambda: entries.value == ("beta", "alpha", "gamma"))
    look_away()
    expect(leika_page.get_by_label("Reorder entry 2")).to_be_focused()
    assert _showing_controls(leika_page) == []

    # An arrow key IS the keys working the row, so from there on the row shows
    # what they are working with, cursor or no cursor.
    leika_page.keyboard.press("ArrowUp")
    look_away()
    wait_until(lambda: entries.value == ("alpha", "beta", "gamma"))
    assert _showing_controls(leika_page) == ["alpha"]

    # The keyboard can reach them at all, which is why they are kept in the
    # tree rather than drawn only for the pointer: Tab out of a box lands on
    # that row's grip, and a grip the keys have found shows itself.
    leika_page.get_by_label("Items entry 3").click()
    look_away()
    assert _showing_controls(leika_page) == []
    leika_page.keyboard.press("Tab")
    expect(leika_page.get_by_label("Reorder entry 3")).to_be_focused()
    assert _showing_controls(leika_page) == ["gamma"]

    # And they go when the keys leave the controls, the pointer being nowhere
    # near them.
    leika_page.locator("[data-leika-list-add]").click()
    wait_until(lambda: entries.value == ("alpha", "beta", "gamma", ""))
    look_away()
    assert _showing_controls(leika_page) == []

    # A focused box does not take its own controls with it: the box lifts
    # itself over the neighbours it hugs when focused, which once put it over
    # the controls as well -- visible, and swallowing every click meant for
    # them.
    leika_page.get_by_label("Items entry 2").click()
    leika_page.keyboard.type("!")
    wait_until(lambda: entries.value == ("alpha", "beta!", "gamma", ""))
    rows.nth(1).hover()
    leika_page.get_by_label("Remove entry 2").click()
    wait_until(lambda: entries.value == ("alpha", "gamma", ""))
    assert page_errors == []


def test_a_frozen_list_keeps_its_length_and_order(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Frozen is about the LIST, not its entries: nothing can be added,
    removed, or moved, and the controls that would do so are not drawn -- but
    the text is still the viewer's to edit."""
    entries = leika_server.gui.add_list("Fixed", ("read", "only"), frozen=True)

    boxes = leika_page.locator("[data-leika-list-entry]")
    expect(boxes).to_have_count(2, timeout=5_000)
    # That nothing frozen draws a grip, remove, or add is pinned by
    # ListInput.test.ts; the add's absence here is the baseline for the thaw.
    expect(leika_page.locator("[data-leika-list-add]")).to_have_count(0)

    boxes.nth(1).fill("edited")
    wait_until(lambda: entries.value == ("read", "edited"))

    # Thawing it from Python brings the controls back without a reload.
    entries.frozen = False
    expect(leika_page.locator("[data-leika-list-add]")).to_have_count(1, timeout=5_000)
    expect(leika_page.locator("[data-leika-list-grip]")).to_have_count(2)
    assert page_errors == []


def test_a_wrapped_row_of_options_rounds_its_own_controls(
    leika_server: leika.Server, leika_page: Page, page_errors: list[str]
) -> None:
    """A run too wide for the row wraps, and the block it makes keeps four
    rounded corners -- drawn by the controls themselves.

    The run's box cannot carry them: clipping a rounded box cuts the control's
    OUTLINE off at the corner, and that outline is the part that answers the
    pointer, so the corner would sit out its own hover. Which control holds
    which corner is a question about lines, so it is measured.
    """
    leika_server.gui.add_button(("Start the capture", "Stop the capture"), label="Capture")
    # A toggle row too. The stock toggle pulls every item but the first of its
    # box left for itself, so a wrapped toggle needs that pull actively undone
    # where a button merely needs it left off -- and a test that only drove the
    # buttons passed either way.
    leika_server.gui.add_toggle(("Start the capture", "Stop the capture"), label="Palette")
    runs = leika_page.locator("[data-leika-group-run]")
    expect(runs).to_have_count(2, timeout=5_000)

    # A corner is measured, so it arrives a render after the run is laid out --
    # and the controls transition, so it eases in rather than snapping. Poll for
    # the settled shape rather than catching the radius mid-flight.
    leika_page.wait_for_function(
        """() => {
          const runs = [...document.querySelectorAll("[data-leika-group-run]")];
          if (runs.length !== 2) return false;
          return runs.every((run) => {
            const items = [...run.querySelectorAll("[data-leika-run-item]")];
            if (items.length !== 2) return false;
            const radii = items.map((el) => {
              const style = getComputedStyle(el);
              return [
                style.borderTopLeftRadius,
                style.borderTopRightRadius,
                style.borderBottomRightRadius,
                style.borderBottomLeftRadius,
              ].join(",");
            });
            return (
              radii[0] === "4px,4px,0px,0px" && radii[1] === "0px,0px,4px,4px"
            );
          });
        }""",
        timeout=5_000,
    )

    def measure(run: Locator) -> dict:
        return run.evaluate(
            """(run) => {
          const box = run.getBoundingClientRect();
          const items = [...run.querySelectorAll("[data-leika-run-item]")];
          return {
            clips: getComputedStyle(run).overflowX,
            runRadius: getComputedStyle(run).borderTopLeftRadius,
            tops: items.map((el) =>
              Math.round(el.getBoundingClientRect().top - box.top),
            ),
            lefts: items.map((el) =>
              +(el.getBoundingClientRect().left - box.left).toFixed(2),
            ),
            rights: items.map((el) =>
              +(el.getBoundingClientRect().right - box.left).toFixed(2),
            ),
            borders: items.map((el) => getComputedStyle(el).borderTopWidth),
          };
        }"""
        )

    for index in range(runs.count()):
        measured = measure(runs.nth(index))
        # Both controls are too wide to share a line, so the run is two deep --
        # which is what makes the corners a statement about lines rather than
        # about the first and last control.
        assert len(set(measured["tops"])) == 2, measured
        # Nothing is clipped, and the box draws no corner of its own: every
        # control keeps its own outline the whole way round, hover and all.
        assert measured["clips"] == "visible", measured
        assert measured["runRadius"] == "0px", measured
        assert measured["borders"] == ["1px", "1px"], measured

        # Each line opens on the run's own left edge. A control shares an edge
        # with the one BESIDE it by pulling a border's width left, and a control
        # that opens a line has nothing beside it -- pulled anyway, it hung a
        # pixel out past the line above, which is the sort of thing a reader
        # sees before they can say what it is.
        assert measured["lefts"] == [0.0, 0.0], measured
        # And every line fills the run, which is what makes the block a
        # rectangle and its four corners the run's own.
        assert len(set(measured["rights"])) == 1, measured

    assert page_errors == []
