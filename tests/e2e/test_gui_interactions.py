from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
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
    # Searchable, so this covers the filtering path; the plain default has its
    # own test below.
    dropdown = leika_server.gui.add_dropdown("Mode", options=("Fast", "Accurate"), searchable=True)
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


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


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
    expect(trigger).to_have_attribute("data-leika-button-color", "secondary")
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
    _wait_until(lambda: name.value == "Edited")
    reset.click()
    _wait_until(lambda: name.value == "Ada")
    expect(field).to_have_value("Ada")
    expect(popout).to_be_visible()
    assert submits == []

    # Submitting is the way out proper: the popout closes on its own button.
    submit.click()
    _wait_until(lambda: submits == [1])
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
    _wait_until(lambda: submits == [1, 2])
    assert name.value == "Grace"
    expect(popout).to_have_count(0, timeout=5_000)

    # And a submit from Python closes it too, having reached the client by the
    # one path every submit takes.
    popout = open_form(leika_page)
    form.submit_form()
    _wait_until(lambda: submits == [1, 2, 3])
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
    _wait_until(lambda: query.value == "comets")
    send.click()
    _wait_until(lambda: submits == ["comets"])

    # Enter in the field is the same send, since the button is the form's own
    # submit rather than a click handler beside it.
    field.fill("again")
    _wait_until(lambda: query.value == "again")
    field.press("Enter")
    _wait_until(lambda: submits == ["comets", "again"])
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
    deadline = time.monotonic() + 2.0
    while (handle.value != "Two" or clicks != ["Two"]) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert handle.value == "Two"
    assert clicks == ["Two"]

    # The same option again: two presses, not one press and a no-op.
    two.click()
    deadline = time.monotonic() + 2.0
    while len(clicks) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert clicks == ["Two", "Two"]

    # And none of it shows on screen: no option is on.
    for option in (one, two):
        assert option.get_attribute("aria-pressed") is None
        assert option.get_attribute("data-state") is None
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
    leika_server.gui.add_button(("A", "B", "C"), label="Styled actions")
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
    range_thumb_locator = range_slider.locator('[data-slot="slider-thumb"]').first
    range_thumb = style(range_thumb_locator)
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
    action_items = action_group.locator('[data-slot="button"]')
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
    assert max(row_heights) - min(row_heights) <= 0.5
    assert 23.5 <= row_heights[0] <= 24.5

    for field_text in (field_label, action, text_input, dropdown_trigger, color_trigger):
        assert field_text["fontWeight"] == body_font_weight
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
    # A group's selected option carries the accent, the way a filled button
    # does: `color` is one setting across both, and it defaults to primary.
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
    deadline = time.monotonic() + 2.0
    while dropdown.value != "Exact" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert dropdown.value == "Exact"
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


def test_media_elements_share_one_expand_affordance(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Images and charts expand through the same control, drawn the same way.

    The three media elements each carried their own copy of this button, which
    is how they came to disagree about its size. Only the corner is allowed to
    differ, and only because uPlot puts its legend where the others do not.
    """
    leika_server.gui.add_image(np.zeros((20, 30, 3), dtype=np.uint8), label="Preview")
    x_data = np.linspace(0.0, 1.0, 16)
    leika_server.gui.add_uplot((x_data, x_data), ({}, {"label": "y"}), aspect=2.0)

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

    # Chrome, not content: hidden until the pointer (or focus) arrives.
    assert image_button.evaluate("el => getComputedStyle(el).opacity") == "0"
    leika_page.get_by_role("img").first.hover()
    expect(image_button).to_be_visible()
    image_button.click()
    expect(leika_page.get_by_role("dialog")).to_be_visible(timeout=5_000)
    assert page_errors == []


def test_gui_image_label_is_styled_like_every_other_label(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """An image's label stacks above it instead of sitting in the label column.

    That is a layout difference, not a typographic one: it still names a
    control, so it has to read as a label rather than as a heading. Stock
    `Label` is medium-weight foreground, so the styling has to be applied
    deliberately -- this compares it against a row label rather than pinning
    literal values, which would just restate the CSS.
    """
    leika_server.gui.add_slider("Threshold", min=0.0, max=1.0, step=0.1, initial_value=0.5)
    leika_server.gui.add_image(np.zeros((20, 30, 3), dtype=np.uint8), label="Preview")

    probe = """el => {
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

    assert image_label.evaluate(probe) == row_label.evaluate(probe)
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


def test_button_colorways_are_a_filled_and_an_outlined_role(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Two roles, not two palettes: one carries the accent, one does not."""
    primary = leika_server.gui.add_button("Run")
    leika_server.gui.add_button("Cancel", color="secondary")

    run = leika_page.locator('[data-leika-button][data-leika-button-color="primary"]')
    cancel = leika_page.locator('[data-leika-button][data-leika-button-color="secondary"]')
    expect(run).to_be_visible(timeout=5_000)
    expect(cancel).to_be_visible(timeout=5_000)

    # The filled one paints its background; the outlined one draws a border and
    # leaves the surface behind it alone.
    run_fill = run.evaluate("e => getComputedStyle(e).backgroundColor")
    cancel_fill = cancel.evaluate("e => getComputedStyle(e).backgroundColor")
    assert run_fill != cancel_fill, (run_fill, cancel_fill)
    assert cancel.evaluate("e => parseFloat(getComputedStyle(e).borderTopWidth)") >= 1

    # The default is the filled one, and the role is a live prop.
    assert primary.color == "primary"
    primary.color = "secondary"
    expect(
        leika_page.locator('[data-leika-button][data-leika-button-color="secondary"]')
    ).to_have_count(2, timeout=5_000)
    assert page_errors == []


def test_a_label_is_what_takes_a_button_out_of_the_full_row(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """Unlabelled -- the default -- a button or a group is the row. Given a
    label, it becomes a control in one: the label takes the left column and the
    control sits beside it, like every other row in the panel."""
    leika_server.gui.add_button("Run")
    leika_server.gui.add_button("Stop", label="Playback")
    leika_server.gui.add_button(("A", "B", "C"))
    leika_server.gui.add_button(("X", "Y", "Z"), label="Channel")

    plain_button = leika_page.get_by_role("button", name="Run", exact=True)
    labelled_button = leika_page.get_by_role("button", name="Stop", exact=True)
    plain_group = leika_page.get_by_role("button", name="A", exact=True)
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
    narrow_option = leika_page.get_by_role("button", name="X", exact=True).bounding_box()
    assert wide_option is not None and narrow_option is not None
    assert wide_option["width"] > narrow_option["width"]
    assert page_errors == []


def test_a_group_takes_the_same_colorways_as_a_single_button(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """One `color` setting across both faces of `add_button`. A group is a row
    of buttons, so the colorway is what a button's is: it applies to every
    option alike, exactly as if each were its own `add_button`."""
    group = leika_server.gui.add_button(("A", "B"), label="Filled")
    leika_server.gui.add_button(("C", "D"), label="Marked", color="secondary")

    filled = find_gui_row(leika_page, "Filled").locator('[data-slot="button"]')
    marked = find_gui_row(leika_page, "Marked").locator('[data-slot="button"]')
    expect(filled.first).to_be_visible(timeout=5_000)

    def fill(option: Locator) -> str:
        return option.evaluate("e => getComputedStyle(e).backgroundColor")

    # Every option in a group shares its colorway -- none of them is picked out
    # -- and the two colorways differ.
    assert fill(filled.nth(0)) == fill(filled.nth(1))
    assert fill(marked.nth(0)) == fill(marked.nth(1))
    assert fill(filled.nth(0)) != fill(marked.nth(0))

    # And it is a live prop, as it is on a single button -- read back per
    # option, since a row may wear a different role on each.
    assert group.color == ("primary", "primary")
    group.color = "secondary"
    expect(
        find_gui_row(leika_page, "Filled").locator('[data-leika-button-color="secondary"]')
    ).to_have_count(2, timeout=5_000)
    # The fill is a transition, so this polls rather than reading one frame of
    # it: settled, the two groups are the same control in the same role.
    expect(filled.nth(0)).to_have_css("background-color", fill(marked.nth(0)), timeout=5_000)
    assert page_errors == []


def test_a_row_can_wear_one_role_per_option(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """A row usually wants one weight throughout, and sometimes wants its
    accent behind one option only -- a Submit with a Reset beside it."""
    leika_server.gui.add_button(
        ("Reset", "Submit"), label="Actions", color=("secondary", "primary"), merge=True
    )
    leika_server.gui.add_toggle(
        ("Draft", "Live"), label="Stage", color=("secondary", "primary"), multiple=True
    )

    for row, kind in (("Actions", "button"), ("Stage", "toggle")):
        options = find_gui_row(leika_page, row).locator(f"[data-leika-{kind}]")
        expect(options.first).to_be_visible(timeout=5_000)
        assert options.count() == 2, row
        quiet, loud = options.nth(0), options.nth(1)
        assert quiet.get_attribute("data-leika-button-color") == "secondary", row
        assert loud.get_attribute("data-leika-button-color") == "primary", row
        # The accent is a fill: the quiet one leaves the surface behind it and
        # draws a border instead.
        fills = [
            option.evaluate("e => getComputedStyle(e).backgroundColor") for option in (quiet, loud)
        ]
        assert fills[0] != fills[1], (row, fills)
        assert quiet.evaluate("e => parseFloat(getComputedStyle(e).borderLeftWidth)") >= 1

    # Joined, and one half outlined: the hairline that divides two filled
    # neighbours would be drawn over that half's own border, so it is not.
    expect(
        find_gui_row(leika_page, "Actions").locator('[data-slot="button-group-separator"]')
    ).to_have_count(0)
    assert page_errors == []


def test_a_labelled_button_is_the_height_of_every_other_row_control(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    """24px beside a label, 32px filling the row. A button used to stay at its
    standalone height in both, which made its row taller than the panel's."""
    leika_server.gui.add_text("Text", initial_value="x")
    leika_server.gui.add_button("Face", label="Row")
    leika_server.gui.add_button(("A", "B"), label="Group")
    leika_server.gui.add_button("Solo")
    leika_server.gui.add_button(("C", "D"))

    def height(locator: Locator) -> float:
        box = locator.bounding_box()
        assert box is not None
        return box["height"]

    solo = leika_page.get_by_role("button", name="Solo", exact=True)
    expect(solo).to_be_visible(timeout=5_000)

    row_input = find_gui_row(leika_page, "Text").get_by_role("textbox")
    labelled_button = find_gui_row(leika_page, "Row").get_by_role("button", name="Face")
    labelled_option = find_gui_row(leika_page, "Group").locator('[data-slot="button"]').first
    for control in (labelled_button, labelled_option):
        assert height(control) == pytest.approx(height(row_input), abs=0.5)
        assert height(control) == pytest.approx(24.0, abs=0.5)

    lone_option = leika_page.get_by_role("button", name="C", exact=True)
    for control in (solo, lone_option):
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
    assert joined == [-1.0, -1.0], joined
    assert parted == [4.0, 4.0], parted
    assert mixed == [-1.0, 4.0], mixed
    assert gaps("Toggles", "toggle") == mixed, (gaps("Toggles", "toggle"), mixed)
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
    toggle = leika_server.gui.add_toggle("Face", label="Filled toggle")
    leika_server.gui.add_button("Face", label="Filled button")
    outlined = leika_server.gui.add_toggle("Face", label="Thin toggle", color="secondary")
    leika_server.gui.add_button("Face", label="Thin button", color="secondary")

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
    deadline = time.monotonic() + 2.0
    while toggle.value is not False and time.monotonic() < deadline:
        time.sleep(0.01)
    assert toggle.value is False
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

    def wait_for(read: Callable[[], tuple[str, ...]], expected: tuple[str, ...]) -> None:
        deadline = time.monotonic() + 2.0
        while read() != expected and time.monotonic() < deadline:
            time.sleep(0.01)
        assert read() == expected

    # Turning one on turns the other off.
    one_row.nth(1).click()
    wait_for(lambda: one.value, ("Italic",))
    expect(one_row.first).to_have_attribute("aria-pressed", "false")

    # Where several may be on, they accumulate -- and stay in declaration order
    # however they were clicked.
    many_row.nth(1).click()
    wait_for(lambda: many.value, ("Axes",))
    many_row.nth(0).click()
    wait_for(lambda: many.value, ("Grid", "Axes"))

    # A one-at-a-time row is required by default, so pressing the toggle that is
    # on is refused rather than emptying the row -- nothing to undo, and no
    # round trip. Made optional, the same press clears it.
    one_row.nth(1).click()
    wait_for(lambda: one.value, ("Italic",))
    leika_page.wait_for_timeout(300)
    assert one.value == ("Italic",)
    expect(one_row.nth(1)).to_have_attribute("aria-pressed", "true")

    clearable_row = find_gui_row(leika_page, "Clearable").locator("[data-leika-toggle]")
    clearable_row.nth(0).click()
    wait_for(lambda: clearable.value, ())
    expect(clearable_row.nth(0)).to_have_attribute("aria-pressed", "false")
    assert page_errors == []
