from __future__ import annotations

import pytest
from playwright.sync_api import Locator, Page, expect

import leika


def _assert_inside_viewport(page: Page) -> None:
    panel = page.get_by_test_id("control-panel")
    expect(panel).to_be_visible(timeout=5_000)
    bounds = panel.bounding_box()
    viewport = page.viewport_size
    assert bounds is not None and viewport is not None
    assert bounds["x"] >= -0.5
    assert bounds["y"] >= -0.5
    assert bounds["x"] + bounds["width"] <= viewport["width"] + 0.5
    assert bounds["y"] + bounds["height"] <= viewport["height"] + 0.5


def test_initial_hover_panel_preserves_right_inset(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    # The panel width is a constant, so the width the client mounts with is the
    # width it keeps once the theme message arrives -- no resize on connect.
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    leika_server.gui.add_text("Ready", initial_value="yes")
    leika_server.gui.add_command("Open command palette", lambda: None)

    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )

    panel = page.get_by_test_id("control-panel")
    expect(panel).to_be_visible(timeout=5_000)
    expect(panel).to_have_css("width", "320px")
    bounds = panel.bounding_box()
    viewport = page.viewport_size
    assert bounds is not None and viewport is not None
    assert abs(viewport["width"] - bounds["x"] - bounds["width"] - 15.0) <= 0.5

    # The handle carries the connection status alone: no action buttons, and
    # no connection settings view behind them.
    expect(page.get_by_role("button", name="Commands")).to_have_count(0)
    expect(page.get_by_role("button", name="Connection settings")).to_have_count(0)
    expect(page.get_by_text("Server URL", exact=True)).to_have_count(0)
    assert page_errors == []


def test_nested_gui_tabs_do_not_create_nested_card_surfaces(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    tabs = leika_server.gui.add_tab_group()
    with tabs.add_tab("Nested tab"):
        leika_server.gui.add_text("Nested content", initial_value="ready")

    page.goto(leika_server.url)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    nested_content = page.get_by_text("Nested content", exact=True)
    expect(nested_content).to_be_visible(timeout=5_000)
    card_content_ancestors = nested_content.locator("xpath=ancestor::*[@data-slot='card-content']")
    expect(card_content_ancestors).to_have_count(1)

    panel = page.get_by_test_id("control-panel")
    expect(panel).to_have_attribute("data-slot", "card")
    expect(page.locator('[data-slot="card"] [data-slot="card"]')).to_have_count(0)
    control_group = panel.locator("[data-dock-group]").first
    expect(control_group).to_be_visible()
    expect(control_group.locator(':scope > [data-slot="tabs"]')).to_have_count(0)

    nested_tab = page.get_by_role("tab", name="Nested tab")
    tab_bounds = nested_tab.bounding_box()
    assert tab_bounds is not None
    tab_x = tab_bounds["x"] + tab_bounds["width"] / 2
    tab_y = tab_bounds["y"] + tab_bounds["height"] / 2
    page.mouse.move(tab_x, tab_y)
    page.mouse.down()
    page.mouse.move(tab_x, tab_bounds["y"] + tab_bounds["height"] + 48, steps=8)
    page.mouse.up()

    expect(page.locator("[data-floating-window]")).to_have_count(2)
    torn_window = nested_content.locator("xpath=ancestor::*[@data-floating-window][1]")
    expect(torn_window).to_be_visible()
    expect(card_content_ancestors).to_have_count(1)
    assert page_errors == []


def test_dockable_tabs_keep_inactive_panel_dom_mounted(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    tabs = leika_server.gui.add_tab_group()
    with tabs.add_tab("First mount"):
        leika_server.gui.add_html("<span data-tab-mount-sentinel>original</span>")
    with tabs.add_tab("Second mount"):
        leika_server.gui.add_markdown("Second panel")

    page.goto(leika_server.url)
    page.wait_for_function(
        '() => !document.body.innerText.includes("Connecting...")', timeout=15_000
    )
    first_tab = page.get_by_role("tab", name="First mount", exact=True)
    second_tab = page.get_by_role("tab", name="Second mount", exact=True)
    sentinel = page.locator("[data-tab-mount-sentinel]")
    expect(first_tab).to_have_attribute("aria-selected", "true", timeout=5_000)
    expect(sentinel).to_be_visible()
    sentinel.evaluate('element => { element.textContent = "preserved"; }')

    second_tab.click()
    expect(second_tab).to_have_attribute("aria-selected", "true")
    expect(sentinel).to_be_attached()
    expect(sentinel).to_have_text("preserved")
    first_tab.click()
    expect(sentinel).to_be_visible()
    expect(sentinel).to_have_text("preserved")
    assert page_errors == []


def test_narrow_plain_tabs_and_button_groups_scroll_without_page_overflow(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(control_layout="fixed", dark_mode=True)
    tabs = leika_server.gui.add_tab_group()
    tab_labels = (
        "Overview dashboard",
        "Experiment controls",
        "Detailed diagnostics",
        "Export configuration",
    )
    for index, label in enumerate(tab_labels):
        with tabs.add_tab(label):
            leika_server.gui.add_markdown(f"Panel content {index + 1}")
    leika_server.gui.add_button(
        (
            "Interactive preview",
            "Publication quality",
            "Diagnostic overlay",
            "Presentation mode",
        ),
        label="Many modes",
    )

    page.set_viewport_size({"width": 320, "height": 700})
    page.goto(leika_server.url)
    page.wait_for_function(
        '() => !document.body.innerText.includes("Connecting...")', timeout=15_000
    )
    tabs_list = page.locator("[data-leika-tabs-list]")
    expect(tabs_list).to_be_visible(timeout=5_000)
    tab_metrics = tabs_list.evaluate(
        "element => ({clientWidth: element.clientWidth, scrollWidth: element.scrollWidth})"
    )
    assert tab_metrics["scrollWidth"] > tab_metrics["clientWidth"]
    last_tab = page.get_by_role("tab", name=tab_labels[-1], exact=True)
    last_tab.scroll_into_view_if_needed()
    last_tab.click()
    expect(page.get_by_text("Panel content 4", exact=True)).to_be_visible()

    group = page.locator(
        "[data-leika-button-group]", has=page.get_by_role("button", name="Interactive preview")
    )
    expect(group).to_be_visible()
    group_metrics = group.evaluate(
        "element => ({clientWidth: element.clientWidth, scrollWidth: element.scrollWidth})"
    )
    assert group_metrics["scrollWidth"] > group_metrics["clientWidth"]
    last_option = group.get_by_role("button", name="Presentation mode", exact=True)
    last_option.scroll_into_view_if_needed()
    last_option.click()

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page_errors == []


def test_hover_panel_is_clamped_on_desktop_tablet_and_mobile(
    leika_server: leika.Server,
    leika_page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    with leika_server.gui.add_folder("First folder"):
        leika_server.gui.add_slider(
            "Spacing slider", min=0.0, max=1.0, step=0.01, initial_value=0.5
        )
    with leika_server.gui.add_folder("Second folder"):
        leika_server.gui.add_vector3("Vector", initial_value=(1.0, 2.0, 3.0))
    with leika_server.gui.add_folder("Tall section"):
        for index in range(36):
            leika_server.gui.add_checkbox(f"Tall control {index + 1}", initial_value=index % 2 == 0)

    leika_page.set_viewport_size({"width": 1440, "height": 900})
    last_control = leika_page.get_by_text("Tall control 36", exact=True)
    expect(last_control).to_be_attached(timeout=5_000)
    _assert_inside_viewport(leika_page)
    panel = leika_page.get_by_test_id("control-panel")
    bounds = panel.bounding_box()
    assert bounds is not None
    assert abs(bounds["y"] - 15.0) <= 0.5
    assert bounds["height"] <= 870.5
    scroll_viewport = panel.locator(
        '[data-dock-panel-scroll-body] > [data-slot="scroll-area-viewport"]'
    ).first
    assert scroll_viewport.evaluate("element => element.scrollHeight > element.clientHeight")
    last_control.scroll_into_view_if_needed()
    expect(last_control).to_be_visible()
    leika_page.set_viewport_size({"width": 800, "height": 700})
    _assert_inside_viewport(leika_page)
    leika_page.set_viewport_size({"width": 420, "height": 700})
    expect(leika_page.get_by_test_id("control-panel")).to_have_count(0)
    first_folder = leika_page.get_by_text("First folder", exact=True)
    expect(first_folder).to_be_visible()
    bottom_panel = leika_page.locator('[data-slot="card"]').filter(
        has=leika_page.locator("[data-leika-bottom-panel-handle]")
    )
    expect(bottom_panel).to_have_count(1)
    bounds = bottom_panel.bounding_box()
    viewport = leika_page.viewport_size
    assert bounds is not None and viewport is not None
    assert bounds["x"] >= -0.5
    assert bounds["x"] + bounds["width"] <= viewport["width"] + 0.5
    assert abs(bounds["y"] + bounds["height"] - viewport["height"]) <= 1.0

    handle = bottom_panel.locator("[data-leika-bottom-panel-handle]")
    expect(handle.locator("button")).to_have_count(0)
    scroll_root = bottom_panel.locator(
        ':scope > [data-slot="collapsible"] [data-slot="scroll-area"]'
    )
    scroll_viewport = scroll_root.locator(':scope > [data-slot="scroll-area-viewport"]')
    expect(handle).to_be_visible()
    expect(handle).to_have_attribute("data-slot", "collapsible-trigger")
    collapsible_content = bottom_panel.locator(
        ':scope > [data-slot="collapsible"] > [data-slot="collapsible-content"]'
    )
    controls_id = handle.get_attribute("aria-controls")
    assert controls_id is not None
    expect(collapsible_content).to_have_attribute("id", controls_id)
    header_bounds = handle.bounding_box()
    content_inset_x = bottom_panel.locator('[data-slot="card-content"]').evaluate(
        "element => element.getBoundingClientRect().left + parseFloat(getComputedStyle(element).paddingLeft)"
    )
    assert header_bounds is not None
    assert abs(header_bounds["x"] - content_inset_x) <= 0.5

    handle.click()
    expect(handle).to_have_attribute("aria-expanded", "false")
    expect(collapsible_content).to_be_hidden()
    handle.click()
    expect(handle).to_have_attribute("aria-expanded", "true")
    expect(collapsible_content).to_be_visible()
    expect(scroll_root).to_be_visible()
    expect(scroll_root.locator("[data-leika-bottom-panel-handle]")).to_have_count(0)
    scroll_metrics = scroll_viewport.evaluate(
        "element => ({clientHeight: element.clientHeight, scrollHeight: element.scrollHeight})"
    )
    assert 0 < scroll_metrics["clientHeight"] < scroll_metrics["scrollHeight"]
    handle_y = handle.bounding_box()
    expect(last_control).not_to_be_in_viewport()
    last_control.scroll_into_view_if_needed()
    expect(last_control).to_be_in_viewport()
    assert scroll_viewport.evaluate("element => element.scrollTop > 0")
    scrolled_handle_y = handle.bounding_box()
    assert handle_y is not None and scrolled_handle_y is not None
    assert abs(handle_y["y"] - scrolled_handle_y["y"]) <= 0.5

    expect(first_folder).to_be_visible()
    expect(leika_page.get_by_text("Second folder", exact=True)).to_be_visible()

    leika_page.set_viewport_size({"width": 240, "height": 700})
    bounds = bottom_panel.bounding_box()
    viewport = leika_page.viewport_size
    assert bounds is not None and viewport is not None
    assert bounds["x"] >= -0.5
    assert bounds["width"] <= viewport["width"] + 0.5
    assert bounds["x"] + bounds["width"] <= viewport["width"] + 0.5
    assert page_errors == []


@pytest.mark.parametrize("control_layout", ["fixed", "collapsible"])
def test_tall_sidebar_scrolls_internally_and_stays_inside_viewport(
    control_layout: str,
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(
        control_layout=control_layout,
        dark_mode=True,
    )
    for index in range(60):
        leika_server.gui.add_checkbox(f"Sidebar control {index + 1}", initial_value=index % 2 == 0)

    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )

    last_control = page.get_by_text("Sidebar control 60", exact=True)
    expect(last_control).to_be_attached(timeout=5_000)
    scroll_viewport = last_control.locator("xpath=ancestor::*[@data-slot='sidebar-content'][1]")
    sidebar = scroll_viewport.locator("xpath=ancestor::*[@data-slot='sidebar'][1]")
    scroll_root = scroll_viewport
    expect(scroll_root).to_be_visible()
    expect(sidebar).to_be_visible()
    expect(scroll_viewport).to_be_visible()
    sidebar_group = scroll_root.locator(':scope > [data-slot="sidebar-group"]')
    expect(sidebar_group).to_have_count(1)
    expect(sidebar_group.locator(':scope > [data-slot="sidebar-group-content"]')).to_have_count(1)

    viewport = page.viewport_size
    sidebar_bounds = sidebar.bounding_box()
    scroll_bounds = scroll_root.bounding_box()
    group_bounds = sidebar_group.bounding_box()
    group_content_bounds = sidebar_group.locator(
        ':scope > [data-slot="sidebar-group-content"]'
    ).bounding_box()
    assert (
        viewport is not None
        and sidebar_bounds is not None
        and scroll_bounds is not None
        and group_bounds is not None
        and group_content_bounds is not None
    )
    assert sidebar_bounds["x"] >= -0.5
    assert sidebar_bounds["y"] >= -0.5
    assert sidebar_bounds["x"] + sidebar_bounds["width"] <= viewport["width"] + 0.5
    assert sidebar_bounds["y"] + sidebar_bounds["height"] <= viewport["height"] + 0.5
    assert scroll_bounds["y"] + scroll_bounds["height"] <= viewport["height"] + 0.5
    assert group_content_bounds["x"] > sidebar_bounds["x"]
    assert (
        group_content_bounds["x"] + group_content_bounds["width"]
        < sidebar_bounds["x"] + sidebar_bounds["width"]
    )

    scroll_metrics = scroll_viewport.evaluate(
        "element => ({clientHeight: element.clientHeight, scrollHeight: element.scrollHeight})"
    )
    assert 0 < scroll_metrics["clientHeight"] <= viewport["height"]
    assert scroll_metrics["scrollHeight"] > scroll_metrics["clientHeight"]
    expect(last_control).not_to_be_in_viewport()
    last_control.scroll_into_view_if_needed()
    expect(last_control).to_be_in_viewport()
    assert scroll_viewport.evaluate("element => element.scrollTop > 0")
    assert page_errors == []


def test_nested_sections_expand_and_collapse(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    with leika_server.gui.add_folder("Outer section"):
        leika_server.gui.add_text("Outer input", initial_value="outer")
        with leika_server.gui.add_folder("Inner section"):
            leika_server.gui.add_slider(
                "Inner input", min=0.0, max=1.0, step=0.1, initial_value=0.5
            )
            with leika_server.gui.add_folder("Deep section"):
                leika_server.gui.add_checkbox("Deep input", initial_value=True)
    with leika_server.gui.add_folder("Sibling section"):
        leika_server.gui.add_text("Sibling input", initial_value="sibling")
    with leika_server.gui.add_form(label="Form section"):
        leika_server.gui.add_text("Form input", initial_value="form")
    with leika_server.gui.add_form():
        leika_server.gui.add_text("Unlabeled first", initial_value="one")
        leika_server.gui.add_text("Unlabeled second", initial_value="two")

    page.goto(leika_server.url)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )

    def section_named(name: str) -> Locator:
        return page.get_by_text(name, exact=True).locator(
            "xpath=ancestor::*[@data-leika-section][1]"
        )

    outer = section_named("Outer section")
    inner = section_named("Inner section")
    deep = section_named("Deep section")
    sibling = section_named("Sibling section")
    form = section_named("Form section")

    for section in (outer, inner, deep, sibling):
        expect(section).to_have_attribute("data-slot", "accordion")
    # Nesting is structural: each section contains the next one down.
    expect(outer.locator("[data-leika-section]")).to_have_count(2)
    expect(inner.locator("[data-leika-section]")).to_have_count(1)
    expect(deep.locator("[data-leika-section]")).to_have_count(0)
    expect(form.locator(':scope > [data-slot="accordion"]')).to_have_count(1)

    unlabeled_form = page.get_by_text("Unlabeled first", exact=True).locator(
        "xpath=ancestor::form[1]"
    )
    unlabeled_metrics = unlabeled_form.evaluate(
        "element => ({display: getComputedStyle(element).display, rowGap: getComputedStyle(element).rowGap})"
    )
    assert unlabeled_metrics == {"display": "flex", "rowGap": "12px"}

    for section in (outer, inner, deep, sibling, form):
        trigger = section.locator("[data-leika-section-trigger]").first
        contents = section.locator("[data-leika-section-contents]").first
        expect(trigger).to_have_attribute("data-slot", "accordion-trigger")
        expect(contents).to_have_attribute("data-slot", "accordion-content")
        expect(trigger).to_have_attribute("type", "button")
        expect(trigger).to_have_attribute("aria-expanded", "true")
        controls_id = trigger.get_attribute("aria-controls")
        trigger_id = trigger.get_attribute("id")
        assert controls_id is not None and trigger_id is not None
        expect(contents).to_have_attribute("id", controls_id)
        expect(contents).to_have_attribute("role", "region")
        expect(contents).to_have_attribute("aria-labelledby", trigger_id)
        expect(trigger.locator('[data-slot="accordion-trigger-icon"]:visible')).to_have_count(1)
        assert contents.evaluate("el => getComputedStyle(el).borderLeftWidth") == "0px"

    inner_trigger = inner.locator("[data-leika-section-trigger]").first
    inner_contents = inner.locator("[data-leika-section-contents]").first
    inner_trigger.focus()
    page.keyboard.press("Enter")
    expect(inner_trigger).to_have_attribute("aria-expanded", "false")
    expect(inner_trigger.locator('[data-slot="accordion-trigger-icon"]:visible')).to_have_count(1)
    expect(inner_contents).to_be_hidden()
    page.keyboard.press("Space")
    expect(inner_trigger).to_have_attribute("aria-expanded", "true")
    expect(inner_contents).to_be_visible()

    form_trigger = form.locator("[data-leika-section-trigger]").first
    form_contents = form.locator("[data-leika-section-contents]").first
    form_trigger.focus()
    page.keyboard.press("Space")
    expect(form_trigger).to_have_attribute("aria-expanded", "false")
    expect(form_contents).to_be_hidden()
    page.keyboard.press("Enter")
    expect(form_trigger).to_have_attribute("aria-expanded", "true")
    expect(form_contents).to_be_visible()
    assert page_errors == []


def test_empty_panel_body_leaves_no_gap_under_the_header(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """A panel with nothing to show is just its header inside the card.

    The body stays mounted at zero height so its intrinsic-size transition can
    be measured, which leaves it a flex item -- and the header/body gap hanging
    below a lone "Connecting..." or "Inactive" header, unbalanced by the card's
    padding. The gap belongs to the body, so it goes when the body has nothing
    in it, and the header runs on to the bottom of the card instead.

    The gap is the header's own bottom padding rather than a gap between flex
    items, so that pressing it lands on the header: it is title bar to look at
    and has to be title bar to the pointer too.
    """
    leika_server.gui.configure_theme(control_layout="floating")
    page.goto(leika_server.url)
    page.wait_for_selector('[data-testid="control-panel"]', timeout=15_000)

    frame = page.locator("[data-dock-group]").filter(
        has=page.get_by_test_id("control-panel-handle")
    )
    measure = """el => {
        const header = el.querySelector('[data-dock-header]');
        return {
            // Below the title: the gap, or the card's own inset once the header
            // is the last thing in the card and has taken that inset over.
            underTitle: getComputedStyle(header).paddingBottom,
            // The frame is exactly its header when nothing follows it.
            trailingSpace: Math.round(
                el.getBoundingClientRect().bottom
                - header.getBoundingClientRect().bottom
            ),
        };
    }"""
    expect(frame).to_be_visible(timeout=5_000)
    assert frame.evaluate(measure) == {"underTitle": "16px", "trailingSpace": 0}

    # A populated body earns the gap back: it now has something to separate.
    leika_server.gui.add_text("Ready", initial_value="yes")
    expect(page.get_by_text("Ready")).to_be_visible(timeout=5_000)
    assert frame.evaluate(measure)["underTitle"] == "8px"
    assert page_errors == []
