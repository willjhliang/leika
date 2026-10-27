from __future__ import annotations

import pytest
from playwright.sync_api import Locator, Page, expect

import leika

from .utils import find_gui_row


@pytest.fixture(params=["same-origin", "cross-origin"])
def scene_click_target(
    request: pytest.FixtureRequest, leika_server: leika.Server, leika_page: Page
) -> tuple[tuple[float, float], Locator]:
    origin = leika_server.url if request.param == "same-origin" else "http://embedded-scene.test"
    url = origin + "/dismissal-scene"
    leika_page.route(
        url + "*",
        lambda route: route.fulfill(
            content_type="text/html",
            body="""<!doctype html><html><body data-clicks="0">
              <script>
                document.addEventListener('click', () => {
                  document.body.dataset.clicks = Number(document.body.dataset.clicks) + 1;
                });
              </script>
              Embedded scene
            </body></html>""",
        ),
    )
    leika_server.panes.add_viser(url, pane_id="dismissal-scene", title="Scene")
    iframe = leika_page.locator('iframe[title="Scene"]')
    scene = iframe.content_frame.locator("body")
    expect(scene).to_have_attribute("data-clicks", "0")
    bounds = iframe.bounding_box()
    assert bounds is not None
    # The left side of the scene is clear of the control panel and its popups.
    point = (bounds["x"] + bounds["width"] / 4, bounds["y"] + bounds["height"] / 2)
    return point, scene


@pytest.mark.parametrize(
    "kind", ["select", "searchable", "settings", "connection", "color", "folder", "form"]
)
def test_popups_dismiss_over_an_iframe_without_clicking_through(
    kind: str,
    leika_server: leika.Server,
    leika_page: Page,
    scene_click_target: tuple[tuple[float, float], Locator],
    page_errors: list[str],
) -> None:
    leika_server.gui.add_text("Persistent", "unchanged")
    persistent = find_gui_row(leika_page, "Persistent").get_by_role("textbox")
    expect(persistent).to_be_visible()
    if kind in ("select", "searchable"):
        leika_server.gui.add_dropdown(
            "Choice", ("First", "Second"), searchable=kind == "searchable"
        )
        trigger = find_gui_row(leika_page, "Choice").get_by_role("combobox")
        slot = "combobox-content" if kind == "searchable" else "select-content"
        popup = leika_page.locator(f'[data-slot="{slot}"]')
    elif kind in ("settings", "connection"):
        trigger = leika_page.locator(f"[data-leika-{kind}-trigger]")
        popup = leika_page.locator(f"[data-leika-{kind}-popover]")
    elif kind == "color":
        leika_server.gui.add_color("Color", initial_value=(10, 20, 30))
        trigger = leika_page.locator("[data-leika-color-trigger]")
        popup = leika_page.locator("[data-leika-color-popover]")
    else:
        if kind == "folder":
            with leika_server.gui.add_folder("Popup", popup=True):
                leika_server.gui.add_text("Field", "unchanged")
            prefix = "popup"
        else:
            with leika_server.gui.add_form(label="Form"):
                leika_server.gui.add_text("Field", "unchanged")
            prefix = "form"
        trigger = leika_page.locator(f"[data-leika-{prefix}-trigger]")
        popup = leika_page.locator(f"[data-leika-{prefix}-popover]")

    trigger.click()
    expect(popup).to_be_visible()
    point, scene = scene_click_target
    # Use coordinates: locator.click() would wait for a backdrop to disappear
    # and hide the exact failure this check is meant to catch.
    leika_page.mouse.click(*point)
    expect(popup).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(persistent).to_be_visible()
    expect(scene).to_have_attribute("data-clicks", "0")
    leika_page.mouse.click(*point)
    expect(scene).to_have_attribute("data-clicks", "1")
    assert page_errors == []


@pytest.mark.parametrize("searchable", [False, True])
def test_nested_dropdown_selection_and_dismissal(
    searchable: bool,
    leika_server: leika.Server,
    leika_page: Page,
    scene_click_target: tuple[tuple[float, float], Locator],
    page_errors: list[str],
) -> None:
    with leika_server.gui.add_folder("Popup", popup=True):
        dropdown = leika_server.gui.add_dropdown(
            "Choice", ("First", "Second"), searchable=searchable
        )
    outer_trigger = leika_page.locator("[data-leika-popup-trigger]")
    outer_trigger.click()
    parent = leika_page.locator("[data-leika-popup-popover]")
    trigger = parent.get_by_role("combobox")
    slot = "combobox-content" if searchable else "select-content"
    menu = leika_page.locator(f'[data-slot="{slot}"]')
    trigger.click()
    expect(menu).to_be_visible()
    if searchable:
        leika_page.get_by_role("combobox", name="Search options").fill("Second")
    leika_page.get_by_role("option", name="Second", exact=True).click()
    expect(menu).to_be_hidden()
    expect(trigger).to_contain_text("Second")
    expect(parent).to_be_visible()
    trigger.click()
    expect(menu).to_be_visible()
    if searchable:
        # The popup can paint before its automatic focus transfer finishes.
        # Send Escape only once the search input is the keyboard target.
        expect(leika_page.get_by_role("combobox", name="Search options")).to_be_focused()
    leika_page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(parent).to_be_visible()
    trigger.click()
    expect(menu).to_be_visible()
    point, scene = scene_click_target
    leika_page.mouse.click(*point)
    expect(parent).to_be_hidden()
    expect(outer_trigger).to_have_attribute("aria-expanded", "false")
    expect(scene).to_have_attribute("data-clicks", "0")
    leika_page.mouse.click(*point)
    expect(scene).to_have_attribute("data-clicks", "1")
    assert dropdown.value == "Second"
    assert page_errors == []
