"""Pointer-driven coverage of the docking surface.

The dock's layout MODEL is exhaustively unit-tested (layoutOps / hitTest /
widthReconciliation); what these tests cover is the layer above it -- the
gesture controller and the React views that read real DOM geometry. Docking to
an edge, splitting a region, snapping windows into a stack, tearing tabs out and
merging them back, resizing, minimizing, and cancelling a drag all depend on
measurements no unit test can produce, so they are exercised here against the
real app: the control panel is an ordinary (unmergeable) dock panel, and GUI tab
groups are ordinary dockable panels inside its nested area.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Locator, Page, expect

import leika

from .utils import Point, center, drag

# Mirrors the client's dock constants (src/dock/types.ts). A mismatch here means
# the rendered geometry drifted from the model the resize math is built on.
MIN_PANEL_WIDTH_PX = 220.0
MAX_PANEL_WIDTH_PX = 600.0
MINIMIZED_STRIP_PX = 36.0
# Deliberately the control panel's own width (CONTROL_WIDTH_PX below): every
# way of landing on an edge gives one width. A client test pins the equality.
DEFAULT_REGION_PX = 320.0
# Mirrors the collapsed floating-window hover grace. Assertions use a fraction
# of it before re-entry, then wait beyond it to prove the pending fade canceled.
PEEK_LEAVE_GRACE_MS = 1_000

# Conftest's viewport.
VIEWPORT_W = 960.0
VIEWPORT_H = 700.0
# A point over the canvas, clear of every edge/region drop zone. Used both as a
# waypoint (so a drag passes over neutral ground) and as a release point while
# the control panel is docked to the left.
CANVAS: Point = (620.0, 320.0)
# Release points for torn-out windows while the control panel still FLOATS in
# the top-right corner: left of it and vertically apart, so the windows never
# overlap each other or cover the tabs a later gesture needs to press.
PARK_LOWER: Point = (300.0, 470.0)
PARK_UPPER: Point = (300.0, 130.0)


@pytest.fixture()
def dock_page(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> Page:
    """The floating control panel plus a two-tab GUI group inside its area."""
    del page_errors  # Registers the pageerror listener; tests assert on it.
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    tabs = leika_server.gui.add_tab_group()
    with tabs.add_tab("Alpha"):
        leika_server.gui.add_text(None, "Alpha body", editable=False, markdown=True, multiline=True)
    with tabs.add_tab("Beta"):
        leika_server.gui.add_text(None, "Beta body", editable=False, markdown=True, multiline=True)

    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    expect(page.get_by_test_id("control-panel")).to_be_visible(timeout=5_000)
    expect(page.get_by_role("tab", name="Alpha", exact=True)).to_be_visible()
    return page


# --- locators ---------------------------------------------------------------


def control_panel(page: Page) -> Locator:
    """The control panel's outer element -- its floating window or docked leaf."""
    return page.get_by_test_id("control-panel")


def control_handle(page: Page) -> Locator:
    """The control panel's drag handle (its full-width header)."""
    return page.get_by_test_id("control-panel-handle")


def floating_windows(page: Page) -> Locator:
    return page.locator("[data-floating-window]")


def window_ids(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        "[data-floating-window]", "els => els.map(el => el.dataset.floatingWindow)"
    )


def gui_area(page: Page) -> Locator:
    """The nested dockable area that hosts the GUI tab group."""
    return page.locator("[data-dock-area]")


def canvas_inset(page: Page) -> float:
    """How far the canvas is pushed in from the left by the docked region."""
    bounds = page.locator("[data-viewport-workspace]").bounding_box()
    assert bounds is not None
    return bounds["x"]


def bounds(locator: Locator) -> dict[str, float]:
    value = locator.bounding_box()
    assert value is not None
    return value


# --- gesture helpers --------------------------------------------------------


def dock_control_panel_left(page: Page) -> None:
    """Drag the floating control panel into the empty left edge zone."""
    drag(page, center(control_handle(page)), CANVAS, (16.0, 300.0))
    expect(control_panel(page)).to_have_attribute("data-dock-side", "left", timeout=5_000)


def tear_out_tab(page: Page, name: str, park: Point = CANVAS) -> Locator:
    """Drag a GUI tab out of its strip into its own floating window at `park`.

    By the tab's GRIP -- the handle that appears on hover, as a list entry's
    does. The tab's face belongs to the strip's surface and drags the whole
    container instead."""
    before = set(window_ids(page))
    tab = page.get_by_role("tab", name=name, exact=True)
    tab.hover()
    grip = tab.locator("[data-leika-tab-drag-handle]")
    expect(grip).to_be_visible()
    start = center(grip)
    # Straight down, past the strip's tear threshold, then out to `park`.
    # Keep the two deliberate waypoints as individual pointer events: WebKit's
    # automation driver can discard the tail of one synthetic stepped move when
    # this gesture replaces the tab drag target with its new floating window.
    drag(page, start, (start[0], start[1] + 90.0), park, steps=1)
    expect(floating_windows(page)).to_have_count(len(before) + 1, timeout=5_000)
    new_ids = set(window_ids(page)) - before
    assert len(new_ids) == 1, new_ids
    return page.locator(f'[data-floating-window="{new_ids.pop()}"]')


def handle_of(window: Locator) -> Locator:
    """A floating window's title bar: its single group's tab strip."""
    return window.locator("[data-dock-strip]").first


# --- docking to an edge -----------------------------------------------------


def test_control_panel_docks_to_the_left_edge_and_insets_the_canvas(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    panel = control_panel(page)
    expect(panel).to_have_attribute("data-dock-side", "none")
    assert canvas_inset(page) == pytest.approx(0.0, abs=0.5)

    dock_control_panel_left(page)

    docked = bounds(panel)
    assert docked["x"] == pytest.approx(0.0, abs=0.5)
    assert docked["height"] == pytest.approx(VIEWPORT_H, abs=1.0)
    assert MIN_PANEL_WIDTH_PX <= docked["width"] <= MAX_PANEL_WIDTH_PX
    # The canvas is inset by exactly what the region reserves, so nothing is
    # hidden underneath the panel.
    assert canvas_inset(page) == pytest.approx(docked["width"], abs=1.0)
    expect(floating_windows(page)).to_have_count(0)
    expect(page.locator("[data-dock-region-resize='left']")).to_be_attached()
    assert page_errors == []


def test_desktop_dock_arrangement_survives_refresh(dock_page: Page, page_errors: list[str]) -> None:
    page = dock_page
    dock_control_panel_left(page)

    # Establish the structural placement before adjusting the region's
    # independent width; each synthetic WebKit gesture then keeps one DOM target.
    alpha_window = tear_out_tab(page, "Alpha", CANVAS)

    resizer = page.locator("[data-dock-region-resize='left']")
    grip = center(resizer)
    drag(page, grip, (grip[0] + 75.0, grip[1]))
    saved_width = bounds(control_panel(page))["width"]
    saved_alpha = bounds(alpha_window)
    page.mouse.click(*center(control_handle(page)))
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)

    page.reload()
    strip = page.get_by_test_id("control-panel-handle")
    expect(strip).to_have_attribute("data-dock-collapsed", "true", timeout=5_000)
    assert canvas_inset(page) == pytest.approx(MINIMIZED_STRIP_PX, abs=1.0)
    expect(page.get_by_text("Alpha body", exact=True)).to_be_visible(timeout=5_000)

    restored_alpha = bounds(
        page.get_by_text("Alpha body", exact=True).locator(
            "xpath=ancestor::*[@data-floating-window]"
        )
    )
    assert restored_alpha["x"] == pytest.approx(saved_alpha["x"], abs=2.0)
    assert restored_alpha["y"] == pytest.approx(saved_alpha["y"], abs=2.0)

    strip.locator("[data-dock-minimize]").click()
    expect(control_panel(page)).to_have_attribute("data-dock-side", "left")
    assert bounds(control_panel(page))["width"] == pytest.approx(saved_width, abs=2.0)
    expect(gui_area(page).get_by_role("tab", name="Alpha", exact=True)).to_have_count(0)
    expect(gui_area(page).get_by_role("tab", name="Beta", exact=True)).to_be_visible()
    assert page_errors == []


def test_edge_drop_hint_previews_the_dock_and_escape_abandons_it(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    panel = control_panel(page)
    before = bounds(panel)

    page.mouse.move(*center(control_handle(page)))
    page.mouse.down()
    try:
        page.mouse.move(*CANVAS, steps=6)
        page.mouse.move(16.0, 300.0, steps=6)
        # The edge zone previews the region the drop would create.
        hint = page.locator("[data-dock-hint]")
        expect(hint).to_have_attribute("data-dock-hint", "fill", timeout=2_000)
        hint_box = bounds(hint)
        assert hint_box["x"] == pytest.approx(0.0, abs=0.5)
        assert hint_box["width"] == pytest.approx(DEFAULT_REGION_PX, abs=0.5)
        assert hint_box["height"] == pytest.approx(VIEWPORT_H, abs=1.0)
        page.keyboard.press("Escape")
    finally:
        page.mouse.up()

    # Escape aborts: no dock, and the window snaps back to where it started.
    expect(panel).to_have_attribute("data-dock-side", "none")
    expect(page.locator("[data-dock-hint]")).to_have_count(0)
    after = bounds(panel)
    assert after["x"] == pytest.approx(before["x"], abs=0.5)
    assert after["y"] == pytest.approx(before["y"], abs=0.5)
    assert canvas_inset(page) == pytest.approx(0.0, abs=0.5)
    assert page_errors == []


def test_escape_while_undocking_restores_the_docked_layout(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    dock_control_panel_left(page)
    docked_width = bounds(control_panel(page))["width"]

    # Undocking floats the panel up front (so there is a window to drag), so
    # this is the cancel path that has to put a committed op back.
    drag(page, center(control_handle(page)), CANVAS, (700.0, 200.0), cancel=True)

    expect(control_panel(page)).to_have_attribute("data-dock-side", "left")
    expect(floating_windows(page)).to_have_count(0)
    assert bounds(control_panel(page))["width"] == pytest.approx(docked_width, abs=1.0)
    assert canvas_inset(page) == pytest.approx(docked_width, abs=1.0)
    assert page_errors == []


def test_dragging_a_docked_panel_out_floats_it_again(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    dock_control_panel_left(page)

    drag(page, center(control_handle(page)), (400.0, 250.0), (620.0, 260.0))

    panel = control_panel(page)
    expect(panel).to_have_attribute("data-dock-side", "none")
    expect(floating_windows(page)).to_have_count(1)
    assert canvas_inset(page) == pytest.approx(0.0, abs=0.5)
    # The window follows the cursor: it is grabbed by the header, so the
    # release point lands inside it.
    floated = bounds(panel)
    assert floated["x"] < 620.0 < floated["x"] + floated["width"]
    assert page_errors == []


# --- minimize / expand ------------------------------------------------------


def test_docked_panel_minimizes_to_a_strip_and_expands_again(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    dock_control_panel_left(page)
    expanded_width = bounds(control_panel(page))["width"]

    # A motionless press on the handle is a click, which toggles minimized.
    control_handle(page).click()

    strip = page.get_by_test_id("control-panel-handle")
    expect(strip).to_have_attribute("data-dock-collapsed", "true", timeout=5_000)
    # A minimized column is a fixed-width strip, not a canvas overlay: it still
    # reserves its own width.
    assert canvas_inset(page) == pytest.approx(MINIMIZED_STRIP_PX, abs=1.0)
    assert bounds(strip)["width"] <= MINIMIZED_STRIP_PX + 0.5
    expect(page.get_by_text("Main", exact=True)).to_be_visible()

    # The strip's expand (+) button restores the panel at its previous width.
    strip.locator("[data-dock-minimize]").click()
    expect(control_panel(page)).to_have_attribute("data-dock-side", "left")
    assert canvas_inset(page) == pytest.approx(expanded_width, abs=1.0)
    assert page_errors == []


# --- resizing ---------------------------------------------------------------


def test_region_resizer_widens_the_docked_region_and_clamps_at_the_minimum(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    dock_control_panel_left(page)
    start_width = bounds(control_panel(page))["width"]

    resizer = page.locator("[data-dock-region-resize='left']")
    grip = center(resizer)
    drag(page, grip, (grip[0] + 80.0, grip[1]))

    widened = bounds(control_panel(page))["width"]
    assert widened == pytest.approx(start_width + 80.0, abs=2.0)
    assert canvas_inset(page) == pytest.approx(widened, abs=1.0)

    # Dragging far past the minimum stops at it rather than collapsing. One
    # endpoint event is a valid fast pointer move and avoids WebKit's automation
    # driver truncating a stepped move after the resizer follows its first substep.
    grip = center(resizer)
    drag(page, grip, (grip[0] - 400.0, grip[1]), steps=1)
    assert bounds(control_panel(page))["width"] == pytest.approx(MIN_PANEL_WIDTH_PX, abs=2.0)
    assert page_errors == []


def test_floating_window_resizes_from_its_left_grip_keeping_the_right_edge(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    panel = control_panel(page)
    before = bounds(panel)

    grip = center(page.get_by_test_id("control-panel-resize-left"))
    drag(page, grip, (grip[0] - 60.0, grip[1]))

    after = bounds(panel)
    assert after["width"] == pytest.approx(before["width"] + 60.0, abs=2.0)
    # A left-edge resize moves x to hold the right edge still.
    assert after["x"] + after["width"] == pytest.approx(before["x"] + before["width"], abs=2.0)

    # Escape reverts every per-frame resize the gesture applied.
    grip = center(page.get_by_test_id("control-panel-resize-left"))
    drag(page, grip, (grip[0] - 120.0, grip[1]), cancel=True)
    reverted = bounds(panel)
    assert reverted["width"] == pytest.approx(after["width"], abs=2.0)
    assert reverted["x"] == pytest.approx(after["x"], abs=2.0)
    assert page_errors == []


# --- tabs: tear out, merge back, reorder ------------------------------------


def test_tab_tears_out_into_a_window_and_merges_back_into_the_area(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    torn = tear_out_tab(page, "Beta")

    # The panel left the area and now lives in its own window.
    expect(gui_area(page).locator("[data-dock-tab]")).to_have_count(1)
    expect(torn.get_by_role("tab", name="Beta", exact=True)).to_be_visible()
    expect(page.get_by_text("Beta body", exact=True)).to_be_visible()

    # Dropping it back over the area's tab strip re-inserts it as a tab.
    strip = gui_area(page).locator("[data-dock-strip]")
    drag(page, center(handle_of(torn)), CANVAS, center(strip))

    expect(floating_windows(page)).to_have_count(1)
    expect(gui_area(page).locator("[data-dock-tab]")).to_have_count(2)
    assert page_errors == []


def test_tabs_reorder_within_their_strip(dock_page: Page, page_errors: list[str]) -> None:
    page = dock_page
    tabs = gui_area(page).locator("[data-dock-tab]")
    expect(tabs).to_have_text(["Alpha", "Beta"])

    beta = bounds(page.get_by_role("tab", name="Beta", exact=True))
    alpha = page.get_by_role("tab", name="Alpha", exact=True)
    alpha.hover()
    # By the tab's grip: the face would drag the whole panel. Stay inside the
    # strip vertically -- leaving it would tear the tab out.
    start = center(alpha.locator("[data-leika-tab-drag-handle]"))
    drag(page, start, (beta["x"] + beta["width"] - 2.0, start[1]))

    expect(tabs).to_have_text(["Beta", "Alpha"])
    expect(floating_windows(page)).to_have_count(1)
    assert page_errors == []


# --- stacking and splitting -------------------------------------------------


def test_two_floating_windows_snap_into_one_stack(dock_page: Page, page_errors: list[str]) -> None:
    page = dock_page
    alpha = tear_out_tab(page, "Alpha", PARK_LOWER)
    beta = tear_out_tab(page, "Beta", PARK_UPPER)
    expect(floating_windows(page)).to_have_count(3)  # + the control panel

    # Dropping on the upper half of a window's BODY snaps in above that
    # group. (Dropping ON the tabs would merge in as a tab instead.)
    alpha_body = bounds(alpha)
    drag(
        page,
        center(handle_of(beta)),
        CANVAS,
        (alpha_body["x"] + alpha_body["width"] / 2, alpha_body["y"] + alpha_body["height"] * 0.55),
    )

    expect(floating_windows(page)).to_have_count(2)
    stacked = floating_windows(page).filter(has=page.get_by_role("tab", name="Alpha", exact=True))
    expect(stacked.locator("[data-dock-group]")).to_have_count(2)
    expect(stacked.get_by_role("tab", name="Beta", exact=True)).to_be_visible()
    assert page_errors == []


def test_dropping_below_a_docked_panel_splits_the_region(
    dock_page: Page, page_errors: list[str]
) -> None:
    """The drop previews as a line, splits into a column, and gains a divider."""
    page = dock_page
    dock_control_panel_left(page)
    torn = tear_out_tab(page, "Beta")

    leaf = bounds(page.locator("[data-dock-leaf]"))
    # The bottom band of a docked panel's content area splits it downward.
    target: Point = (
        leaf["x"] + leaf["width"] / 2,
        leaf["y"] + leaf["height"] - 25.0,
    )
    page.mouse.move(*center(handle_of(torn)))
    page.mouse.down()
    try:
        page.mouse.move(*CANVAS, steps=6)
        page.mouse.move(*target, steps=6)
        # A split previews as an insertion line, not a merge highlight.
        expect(page.locator("[data-dock-hint]")).to_have_attribute(
            "data-dock-hint", "line", timeout=2_000
        )
    finally:
        page.mouse.up()

    leaves = page.locator("[data-dock-leaf]")
    expect(leaves).to_have_count(2, timeout=5_000)
    expect(floating_windows(page)).to_have_count(0)
    # Stacked vertically, control panel on top, sharing the region's width.
    top, bottom = bounds(leaves.nth(0)), bounds(leaves.nth(1))
    assert top["y"] + top["height"] <= bottom["y"] + 0.5
    assert top["width"] == pytest.approx(bottom["width"], abs=1.0)
    assert canvas_inset(page) == pytest.approx(top["width"], abs=1.0)
    # Two stacked leaves make the region a pure column, which gains a handle,
    # and its divider redistributes the heights.
    expect(page.locator("[data-dock-column-handle]")).to_have_count(1)
    before = top["height"]
    divider = page.locator("[data-dock-divider='column']")
    expect(divider).to_have_count(1)
    grip = center(divider)
    drag(page, grip, (grip[0], grip[1] - 90.0))
    after = bounds(leaves.nth(0))["height"]
    assert after == pytest.approx(before - 90.0, abs=3.0)
    assert page_errors == []


def split_control_panel_below(page: Page) -> None:
    """Dock the control panel left, then split Beta into a band below it."""
    dock_control_panel_left(page)
    torn = tear_out_tab(page, "Beta")
    leaf = bounds(page.locator("[data-dock-leaf]"))
    drag(
        page,
        center(handle_of(torn)),
        CANVAS,
        (leaf["x"] + leaf["width"] / 2, leaf["y"] + leaf["height"] - 25.0),
    )
    expect(page.locator("[data-dock-leaf]")).to_have_count(2, timeout=5_000)


def test_column_handle_floats_the_whole_docked_column(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    split_control_panel_below(page)

    # The column handle drags the whole column out as one stacked window.
    drag(page, center(page.locator("[data-dock-column-handle]")), (500.0, 200.0))

    expect(floating_windows(page)).to_have_count(1)
    window = floating_windows(page)
    # Both panels came along; the floated stack carries no window-level bar.
    expect(window.locator("[data-floating-handle]")).to_have_count(0)
    expect(window.get_by_test_id("control-panel-handle")).to_be_visible()
    expect(window.get_by_role("tab", name="Beta", exact=True)).to_be_visible()
    expect(page.locator("[data-dock-leaf]")).to_have_count(0)
    assert canvas_inset(page) == pytest.approx(0.0, abs=0.5)
    assert page_errors == []


def test_dropping_a_window_on_anothers_body_stacks_them(
    dock_page: Page, page_errors: list[str]
) -> None:
    """A drop anywhere on another window's BODY stacks the two windows; only a
    drop on the tab strip merges them into one group. Dissolving a window into
    a tab was too much of a surprise for "I dropped it nearby"."""
    page = dock_page
    alpha = tear_out_tab(page, "Alpha", PARK_LOWER)
    beta = tear_out_tab(page, "Beta", PARK_UPPER)

    body = bounds(alpha)
    drag(
        page,
        center(handle_of(beta)),
        CANVAS,
        # Squarely mid-body: not the strip, not the thin snap bands.
        (body["x"] + body["width"] / 2, body["y"] + body["height"] * 0.6),
    )

    stacked = floating_windows(page).filter(has=page.get_by_role("tab", name="Alpha", exact=True))
    # Two GROUPS in one window -- a stack, not a two-tab group.
    expect(stacked.locator("[data-dock-group]")).to_have_count(2)
    assert page_errors == []


def test_a_stacked_window_has_no_header_and_moves_by_any_members_strip(
    dock_page: Page, page_errors: list[str]
) -> None:
    """A stack is its members and nothing else: no window-level bar above them.
    Any member's strip drags the whole window; a member's tab folds just that
    member; a member leaves by its tab's grip."""
    page = dock_page
    alpha = tear_out_tab(page, "Alpha", PARK_LOWER)
    beta = tear_out_tab(page, "Beta", PARK_UPPER)
    alpha_body = bounds(alpha)
    drag(
        page,
        center(handle_of(beta)),
        CANVAS,
        (alpha_body["x"] + alpha_body["width"] / 2, alpha_body["y"] + alpha_body["height"] * 0.55),
    )
    stacked = floating_windows(page).filter(has=page.get_by_role("tab", name="Alpha", exact=True))
    expect(stacked.locator("[data-dock-group]")).to_have_count(2)
    # No extra chrome: no stack header, no minimize buttons anywhere.
    expect(stacked.locator("[data-floating-handle]")).to_have_count(0)
    expect(stacked.locator("[data-dock-minimize-all]")).to_have_count(0)
    expect(stacked.locator("[data-dock-minimize]")).to_have_count(0)

    # Dragging the LOWER member's strip moves the window whole: still one
    # window, both groups aboard, at the new place.
    before = bounds(stacked)
    lower = stacked.locator("[data-dock-strip]").last
    start = center(lower)
    drag(page, start, (start[0] - 120.0, start[1] - 60.0))
    after = bounds(stacked)
    assert after["x"] == pytest.approx(before["x"] - 120.0, abs=2.0)
    expect(stacked.locator("[data-dock-group]")).to_have_count(2)
    expect(floating_windows(page)).to_have_count(2)  # + the control panel

    # A member's tab folds just that member.
    stacked.get_by_role("tab", name="Beta", exact=True).click()
    expect(stacked.locator("[data-dock-collapsed='true']")).to_have_count(1)
    expect(page.get_by_text("Alpha body", exact=True)).to_be_visible()
    assert page_errors == []


def test_double_clicking_a_torn_out_tab_sends_it_home(
    dock_page: Page, page_errors: list[str]
) -> None:
    """A torn-out tab's home is the tab group it came from: double-clicking its
    title re-inserts it at its declared place, the same gesture that sends the
    control panel home."""
    page = dock_page
    torn = tear_out_tab(page, "Alpha", PARK_LOWER)
    expect(gui_area(page).locator("[data-dock-tab]")).to_have_count(1)

    torn.get_by_role("tab", name="Alpha", exact=True).dblclick()

    # Back in the area, in declaration order -- Alpha was the FIRST tab, so
    # home is its old slot, not the end of the strip.
    tabs = gui_area(page).locator("[data-dock-tab]")
    expect(tabs).to_have_count(2, timeout=5_000)
    expect(tabs).to_have_text(["Alpha", "Beta"])
    # The emptied window went with it.
    expect(floating_windows(page)).to_have_count(1)  # the control panel
    assert page_errors == []


def test_double_clicking_the_handle_sends_the_panel_home(dock_page: Page) -> None:
    """Single-click collapses; twice in quick succession restores the panel's
    default size and position.

    Floating only, and not by choice: collapsing a DOCKED panel turns its
    header into a 36px vertical strip, so the second click of the pair has no
    header left under the cursor to land on. The gesture is wired for any panel
    that names a home -- it is the docked geometry that makes it unreachable.
    """
    page = dock_page
    home = bounds(control_panel(page))

    drag(page, center(control_handle(page)), CANVAS, (320.0, 400.0))
    moved = bounds(control_panel(page))
    assert (moved["x"], moved["y"]) != (home["x"], home["y"])

    handle = center(control_handle(page))
    page.mouse.click(*handle)
    page.mouse.click(*handle)

    restored = bounds(control_panel(page))
    assert abs(restored["x"] - home["x"]) < 1.0, (restored, home)
    assert abs(restored["y"] - home["y"]) < 1.0, (restored, home)
    assert abs(restored["width"] - home["width"]) < 1.0, (restored, home)
    # The pair is a toggle and its undo, so it lands expanded as it started.
    assert page.locator("[data-dock-collapsed]").count() == 0


def test_a_lone_click_on_the_handle_still_only_collapses(dock_page: Page) -> None:
    """The reset must not fire on a single click -- including the first click of
    a freshly loaded page, where a zero-initialized timestamp once read as the
    tail of a double-click."""
    page = dock_page
    home = bounds(control_panel(page))
    drag(page, center(control_handle(page)), CANVAS, (320.0, 400.0))
    moved = bounds(control_panel(page))

    page.mouse.click(*center(control_handle(page)))
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)
    still = bounds(control_panel(page))
    assert abs(still["x"] - moved["x"]) < 1.0, (still, moved, home)


def _sits_on(page: Page, point: Point, selector: str) -> bool:
    """Whether the topmost element at `point` belongs to `selector`."""
    return page.evaluate(
        "([x, y, sel]) => Boolean(document.elementFromPoint(x, y)?.closest(sel))",
        [point[0], point[1], selector],
    )


def test_the_handle_reaches_the_edges_of_its_card(dock_page: Page) -> None:
    """The band of card padding above a handle is part of the handle.

    Nothing else is drawn there, so it reads as title bar -- and has to drag and
    click like title bar rather than being the dead margin it started as. Same
    for the band below the title once the panel is collapsed and the header is
    the last thing left in the card.
    """
    page = dock_page
    card = bounds(control_panel(page))
    header = bounds(control_handle(page))
    assert header["y"] <= card["y"] + 0.5, (header, card)
    # Clear of the top resize grip, which owns the first few pixels of the card.
    band = (card["x"] + card["width"] / 2, card["y"] + 8.0)
    assert _sits_on(page, band, "[data-dock-header]")

    # It drags what the title bar drags.
    drag(page, band, CANVAS, (320.0, 400.0))
    moved = bounds(control_panel(page))
    assert (moved["x"], moved["y"]) != (card["x"], card["y"]), (moved, card)

    # And it collapses what the title bar collapses.
    page.mouse.click(moved["x"] + moved["width"] / 2, moved["y"] + 8.0)
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)

    # Folded, the header is the whole card -- including the band under the
    # title, which now has the card's bottom padding to itself.
    folded = bounds(control_panel(page))
    under_title = (folded["x"] + folded["width"] / 2, folded["y"] + folded["height"] - 6.0)
    assert _sits_on(page, under_title, "[data-dock-header]")
    page.mouse.click(*under_title)
    expect(page.locator("[data-dock-collapsed]")).to_have_count(0, timeout=5_000)


def test_the_tab_strip_is_the_torn_out_windows_title_bar(dock_page: Page) -> None:
    """A torn-out window has no separate grip bar: the strip is the title bar.

    It sits flush against the top of the card and takes the card's inset as its
    own padding, so the band above the tabs drags (and clicks) as part of it --
    the same treatment the unmergeable header gets. And there is no minimize
    button, because folding is what clicking the tab does.
    """
    page = dock_page
    window = tear_out_tab(page, "Alpha", PARK_UPPER)
    card = bounds(window)
    strip = bounds(handle_of(window))
    assert strip["y"] <= card["y"] + 0.5, (strip, card)
    assert _sits_on(page, (card["x"] + card["width"] / 2, card["y"] + 8.0), "[data-dock-strip]")
    expect(window.locator("[data-dock-griphandle]")).to_have_count(0)
    expect(window.locator("[data-dock-minimize]")).to_have_count(0)


def test_clicking_the_active_tab_folds_a_torn_out_window(
    dock_page: Page, page_errors: list[str]
) -> None:
    """The strip answers clicks the way the control panel's header does: the
    active tab is the group's name, so clicking it folds the body away and a
    second click brings it back."""
    page = dock_page
    window = tear_out_tab(page, "Alpha", PARK_LOWER)
    expanded_height = bounds(window)["height"]

    tab = window.get_by_role("tab", name="Alpha", exact=True)
    tab.click()
    expect(window.locator("[data-dock-collapsed='true']")).to_have_count(1, timeout=5_000)
    assert bounds(window)["height"] < expanded_height
    expect(page.get_by_text("Alpha body", exact=True)).not_to_be_visible()

    # Past the double-click window, so this second click is a plain unfold
    # rather than the fold-undo-and-go-home pair.
    page.wait_for_timeout(400)
    tab.click()
    expect(window.locator("[data-dock-collapsed='true']")).to_have_count(0, timeout=5_000)
    expect(page.get_by_text("Alpha body", exact=True)).to_be_visible()
    assert bounds(window)["height"] == pytest.approx(expanded_height, abs=2.0)
    assert page_errors == []


def _draws_a_shadow(box_shadow: str) -> bool:
    """Whether a computed `box-shadow` puts anything on screen.

    `shadow-none` computes to the layers the card's shadow and ring utilities
    declare, all of them at zero offset, spread, and blur -- so the string is
    never the literal "none" and has to be read for lengths instead.
    """
    return any(length != "0px" for length in re.findall(r"-?[\d.]+px", box_shadow))


def _peek_state(page: Page) -> dict[str, str]:
    """What the collapsed panel is currently painting, read off the live styles."""
    return page.evaluate(
        """() => {
            const card = document.querySelector('[data-testid="control-panel"]');
            const badge = card.querySelector('[data-dock-peek]');
            const gear = card.querySelector('[data-dock-peek-fade] [data-leika-settings-trigger]');
            const cardStyle = getComputedStyle(card);
            return {
                background: cardStyle.backgroundColor,
                shadow: cardStyle.boxShadow,
                pointerEvents: cardStyle.pointerEvents,
                badge: getComputedStyle(badge).opacity,
                gear: getComputedStyle(gear.closest('[data-dock-peek-fade]')).opacity,
            };
        }"""
    )


def test_a_collapsed_panel_fades_down_to_its_status_badge(dock_page: Page) -> None:
    """Folded away, the panel leaves the connection badge on the canvas and
    nothing else: no card behind it, and nothing of it in the way of a click.
    The badge is the one thing left to aim at, and hovering it brings the panel
    back."""
    page = dock_page
    card = bounds(control_panel(page))
    page.mouse.click(*center(control_handle(page)))
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)

    # The click that collapsed it does not also take the header away: the
    # pointer is still on it, and it fades only once the pointer leaves. (Under
    # a plain :hover the click-through card would stop counting as hovered the
    # moment it faded, so the second click of a double-click would land on the
    # canvas.)
    assert _draws_a_shadow(_peek_state(page)["shadow"]), _peek_state(page)

    page.mouse.move(*CANVAS)

    badge = control_panel(page).locator("[data-dock-peek]")
    expect(control_panel(page)).to_have_css("background-color", "rgba(0, 0, 0, 0)", timeout=5_000)
    faded = _peek_state(page)
    assert not _draws_a_shadow(faded["shadow"]), faded
    assert faded["gear"] == "0", faded
    # Still there to aim at, but dimmed: a marker of where the panel went.
    assert 0.0 < float(faded["badge"]) < 1.0, faded
    expect(badge).to_be_visible()

    # Click-through: a point on the card clear of the badge hits the canvas.
    over_card = (card["x"] + 24.0, card["y"] + card["height"] / 2)
    assert (
        page.evaluate(
            "([x, y]) => document.elementFromPoint(x, y).closest('[data-testid=\"control-panel\"]') !== null",
            list(over_card),
        )
        is False
    )

    # Hovering the badge -- and only the badge -- brings the whole header back.
    badge.hover()
    expect(control_panel(page)).not_to_have_css(
        "background-color", "rgba(0, 0, 0, 0)", timeout=5_000
    )
    restored = _peek_state(page)
    assert restored["gear"] == "1", restored
    assert restored["badge"] == "1", restored
    assert _draws_a_shadow(restored["shadow"]), restored

    # A brief slip off the header does not start the fade. Returning during the
    # grace period cancels it completely rather than merely postponing it.
    badge_point = center(badge)
    page.mouse.move(*CANVAS)
    page.wait_for_timeout(PEEK_LEAVE_GRACE_MS // 4)
    assert control_panel(page).get_attribute("data-dock-peeking") is None
    grace = _peek_state(page)
    assert _draws_a_shadow(grace["shadow"]), grace
    assert grace["gear"] == "1", grace
    page.mouse.move(*badge_point)
    page.wait_for_timeout(PEEK_LEAVE_GRACE_MS + 100)
    assert control_panel(page).get_attribute("data-dock-peeking") is None

    # A fresh uninterrupted leave consumes the grace and fades normally.
    page.mouse.move(*CANVAS)
    assert control_panel(page).get_attribute("data-dock-peeking") is None
    expect(control_panel(page)).to_have_css("background-color", "rgba(0, 0, 0, 0)", timeout=5_000)


def test_a_popout_holds_the_collapsed_panel_open(dock_page: Page) -> None:
    """Both popouts in the header are portaled to the body, so reading one means
    taking the pointer off the panel -- which is the gesture that folds a
    collapsed panel down to its badge. It has to stay up while either is open,
    or the reader is left with a badge and a popout hanging off nothing."""
    page = dock_page
    page.mouse.click(*center(control_handle(page)))
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)
    page.mouse.move(*CANVAS)
    expect(control_panel(page)).to_have_css("background-color", "rgba(0, 0, 0, 0)", timeout=5_000)

    for trigger, popover in (
        ("[data-leika-settings-trigger]", "[data-leika-settings-popover]"),
        ("[data-leika-connection-trigger]", "[data-leika-connection-popover]"),
    ):
        # The badge is the only thing left to aim at, so the panel comes back
        # first; opening from there is what the reader actually does.
        control_panel(page).locator("[data-dock-peek]").hover()
        page.locator(trigger).click()
        expect(page.locator(popover)).to_be_visible(timeout=5_000)

        # Pointer right away from both. Portal-bubbled events deliberately do
        # not masquerade as physical panel hover; the explicit popout hold is
        # what keeps the header visible wherever its reader's pointer goes.
        page.mouse.move(*CANVAS)
        page.wait_for_timeout(400)
        held = _peek_state(page)
        assert _draws_a_shadow(held["shadow"]), held
        assert held["gear"] == "1", held
        assert held["badge"] == "1", held

        # Dismissed with a click out on the canvas, it folds straight back
        # down. Closing hands focus to the control that opened it either way,
        # so this is the case that used to sit open behind a pointer that had
        # long since left.
        page.mouse.click(*CANVAS)
        expect(page.locator(popover)).to_have_count(0, timeout=5_000)
        expect(control_panel(page)).to_have_css(
            "background-color", "rgba(0, 0, 0, 0)", timeout=5_000
        )


def test_page_selector_uses_the_ordinary_header_leave_grace(
    leika_server: leika.Server,
    dock_page: Page,
    page_errors: list[str],
) -> None:
    """An open page menu does not exempt its header from the leave timer."""
    page = dock_page
    leika_server.pages.add("Analysis", page_id="analysis")
    selector = page.locator("[data-leika-page-selector]")

    page.mouse.click(*center(control_handle(page)))
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)
    selector.click()
    expect(selector).to_have_attribute("aria-expanded", "true")

    # The menu lives in a portal, so moving to it (or anywhere else off the
    # header) starts the same one-second grace as an ordinary header leave.
    page.mouse.move(*CANVAS)
    page.wait_for_timeout(PEEK_LEAVE_GRACE_MS // 4)
    expect(control_panel(page)).not_to_have_attribute("data-dock-peeking", "true")
    expect(control_panel(page)).to_have_attribute("data-dock-peeking", "true", timeout=5_000)
    assert page_errors == []


def test_a_keyboard_dismissal_leaves_the_panel_where_focus_is(dock_page: Page) -> None:
    """The other way out of a popout. Escape puts focus back on the control that
    opened it -- and a control being driven from the keyboard has to be visible,
    so this one case keeps the panel up with the pointer nowhere near it."""
    page = dock_page
    page.mouse.click(*center(control_handle(page)))
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)
    page.mouse.move(*CANVAS)
    expect(control_panel(page)).to_have_css("background-color", "rgba(0, 0, 0, 0)", timeout=5_000)

    trigger = page.locator("[data-leika-settings-trigger]")
    trigger.focus()
    page.keyboard.press("Enter")
    expect(page.locator("[data-leika-settings-popover]")).to_be_visible(timeout=5_000)
    page.mouse.move(*CANVAS)
    page.keyboard.press("Escape")
    expect(page.locator("[data-leika-settings-popover]")).to_have_count(0, timeout=5_000)

    page.wait_for_timeout(400)
    kept = _peek_state(page)
    assert _draws_a_shadow(kept["shadow"]), kept
    assert kept["gear"] == "1", kept

    # Once focus leaves too, there is nothing left holding it.
    page.evaluate("() => document.activeElement?.blur()")
    expect(control_panel(page)).to_have_css("background-color", "rgba(0, 0, 0, 0)", timeout=5_000)


def test_a_tab_strip_grows_to_hold_the_tabs_that_wrap(
    leika_server: leika.Server, page: Page, page_errors: list[str]
) -> None:
    """A strip of panel tabs wraps, and a wrapped strip is taller than one line.

    The stock tabs list sets a one-line height from the tabs root above it,
    which outranks a plain class on the strip -- so the strip stayed 32px tall
    while holding two lines of tabs. It does not clip, so the second line was
    painted over whatever the panel had below it, and the tab itself could not
    be read.
    """
    del page_errors  # Registers the pageerror listener; asserted on below.
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    tabs = leika_server.gui.add_tab_group()
    labels = ("Overview dashboard", "Experiment controls", "Detailed diagnostics")
    for label in labels:
        with tabs.add_tab(label):
            leika_server.gui.add_text(None, f"The {label} tab.", editable=False, markdown=True)

    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        '() => !document.body.innerText.includes("Connecting...")', timeout=15_000
    )
    strip = page.locator("[data-dock-strip]").filter(has_text=labels[0]).last
    expect(strip).to_be_visible(timeout=5_000)

    metrics = strip.evaluate(
        """(element) => {
          const tabs = [...element.querySelectorAll('[role=tab]')];
          const box = element.getBoundingClientRect();
          return {
            clientHeight: element.clientHeight,
            scrollHeight: element.scrollHeight,
            lines: new Set(tabs.map((tab) => Math.round(tab.getBoundingClientRect().top))).size,
            below: Math.max(
              0,
              ...tabs.map((tab) => tab.getBoundingClientRect().bottom - box.bottom),
            ),
          };
        }"""
    )

    # These labels are too wide for one line of a panel: the point of the test
    # is the strip that holds more than one.
    assert metrics["lines"] > 1, metrics
    # Nothing is left outside the strip, which would be painted over the panel.
    assert metrics["below"] <= 1.0, metrics
    assert metrics["scrollHeight"] - metrics["clientHeight"] <= 1, metrics


# --- server-chosen starting placement ---------------------------------------

# The panel's own width (src/ControlPanel/controlWidth.ts), which is also what
# DEFAULT_REGION_PX above mirrors: floating, dragged to an edge, or seeded
# there, the panel is one size.
CONTROL_WIDTH_PX = 320.0


def goto_docked(page: Page, leika_server: leika.Server, side: str, label: str = "Value") -> Page:
    """Load a workspace whose theme starts the control panel docked to `side`."""
    leika_server.gui.configure_theme(control_layout=side, dark_mode=True)  # type: ignore[arg-type]
    leika_server.gui.add_slider(label, min=0.0, max=1.0, step=0.01, initial_value=0.5)
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    expect(control_panel(page)).to_have_attribute("data-dock-side", side, timeout=5_000)
    return page


@pytest.mark.parametrize("side", ["left", "right"])
def test_theme_starts_the_panel_docked_and_insets_the_canvas(
    side: str,
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """`control_layout="left"/"right"` seeds the panel already docked, with no
    gesture -- at the panel's own width, so a configured dock and a floating
    panel are the same size."""
    goto_docked(page, leika_server, side)

    assert window_ids(page) == []
    # Docked cards tile flush against the viewport edge: square corners
    # (rounding is the floating window's lifted-off-the-surface affordance).
    expect(control_panel(page)).to_have_css("border-radius", "0px")
    docked = bounds(control_panel(page))
    assert docked["width"] == pytest.approx(CONTROL_WIDTH_PX, abs=1.0)
    workspace = bounds(page.locator("[data-viewport-workspace]"))
    if side == "left":
        # The canvas is pushed in from the left by the docked region.
        assert workspace["x"] == pytest.approx(CONTROL_WIDTH_PX, abs=2.0)
    else:
        # And gives up the same width on the right.
        assert workspace["x"] == pytest.approx(0.0, abs=1.0)
        assert workspace["width"] == pytest.approx(VIEWPORT_W - CONTROL_WIDTH_PX, abs=2.0)
    assert page_errors == []


def test_a_server_docked_panel_collapses_to_the_rail_and_floats_out(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """A seeded dock keeps every freedom a dragged-there dock has: the header
    click folds it to the vertical rail, the rail expands back, and the panel
    tears out into a floating window."""
    goto_docked(page, leika_server, "left")

    control_handle(page).click()
    strip = page.get_by_test_id("control-panel-handle")
    expect(strip).to_have_attribute("data-dock-collapsed", "true", timeout=5_000)
    assert canvas_inset(page) == pytest.approx(MINIMIZED_STRIP_PX, abs=1.0)
    expect(page.get_by_text("Main", exact=True)).to_be_visible()
    # The rail is flush with the edge like the expanded card: square too.
    expect(strip.locator("xpath=ancestor::*[@data-slot='card']")).to_have_css(
        "border-radius", "0px"
    )

    strip.locator("[data-dock-minimize]").click()
    expect(control_panel(page)).to_have_attribute("data-dock-side", "left")
    assert canvas_inset(page) == pytest.approx(CONTROL_WIDTH_PX, abs=1.0)

    drag(page, center(control_handle(page)), CANVAS)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none", timeout=5_000)
    assert len(window_ids(page)) == 1
    assert canvas_inset(page) == pytest.approx(0.0, abs=1.0)
    assert page_errors == []


def test_a_folded_rail_dragged_to_the_other_edge_lands_expanded(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """A drop that switches the panel's placement opens it: carrying the rail
    stub across the canvas and docking it on the other edge asks to USE the
    panel there, not to file the stub away."""
    goto_docked(page, leika_server, "left")

    control_handle(page).click()
    strip = page.get_by_test_id("control-panel-handle")
    expect(strip).to_have_attribute("data-dock-collapsed", "true", timeout=5_000)

    drag(page, center(strip), CANVAS, (VIEWPORT_W - 16.0, 300.0))
    expect(control_panel(page)).to_have_attribute("data-dock-side", "right", timeout=5_000)
    expect(page.locator("[data-dock-collapsed]")).to_have_count(0, timeout=5_000)
    # Expanded means the full region, not a 36px rail on the new edge.
    assert bounds(control_panel(page))["width"] == pytest.approx(DEFAULT_REGION_PX, abs=1.0)
    assert page_errors == []


def test_a_folded_rail_dragged_onto_the_canvas_lands_expanded(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """Dragging the rail stub out to float is the docked-to-floating half of
    the same rule: the window that lands is the open panel, not a folded bar."""
    goto_docked(page, leika_server, "left")

    control_handle(page).click()
    strip = page.get_by_test_id("control-panel-handle")
    expect(strip).to_have_attribute("data-dock-collapsed", "true", timeout=5_000)

    drag(page, center(strip), CANVAS)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none", timeout=5_000)
    assert len(window_ids(page)) == 1
    expect(page.locator("[data-dock-collapsed]")).to_have_count(0, timeout=5_000)
    # The body really arrived: the app's slider is on screen, not just a title.
    expect(page.get_by_text("Value", exact=True).first).to_be_visible()
    # And at the panel's width: the rail cell it was dragged as is 36px, but
    # what floats is the panel, not the strip.
    assert bounds(control_panel(page))["width"] == pytest.approx(CONTROL_WIDTH_PX, abs=1.0)
    assert page_errors == []


def test_a_viewers_region_resize_rides_through_fold_and_float(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """regionWidth survives full minimization so a restore can know the
    expanded width; the drag-to-float reads the same number, so a widened
    region floats out at the viewer's width, not the default."""
    goto_docked(page, leika_server, "left")

    resizer = page.locator("[data-dock-region-resize='left']")
    grip = center(resizer)
    drag(page, grip, (grip[0] + 80.0, grip[1]))
    assert bounds(control_panel(page))["width"] == pytest.approx(CONTROL_WIDTH_PX + 80.0, abs=2.0)

    control_handle(page).click()
    strip = page.get_by_test_id("control-panel-handle")
    expect(strip).to_have_attribute("data-dock-collapsed", "true", timeout=5_000)

    drag(page, center(strip), CANVAS)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none", timeout=5_000)
    expect(page.locator("[data-dock-collapsed]")).to_have_count(0, timeout=5_000)
    assert bounds(control_panel(page))["width"] == pytest.approx(CONTROL_WIDTH_PX + 80.0, abs=2.0)
    assert page_errors == []


def test_the_dragged_rail_stub_rides_under_the_cursor(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """The rail cell is a 36px-wide, region-tall box, but it floats as a
    full-width bar. Grab offsets measured against the cell would put that bar
    hundreds of px from the cursor -- and the drop zones read the cursor, so
    what docks would stop matching what the eye is dragging. The float must
    re-anchor the cursor onto the bar."""
    goto_docked(page, leika_server, "left")

    control_handle(page).click()
    strip = page.get_by_test_id("control-panel-handle")
    expect(strip).to_have_attribute("data-dock-collapsed", "true", timeout=5_000)

    page.mouse.move(*center(strip))
    page.mouse.down()
    try:
        page.mouse.move(*CANVAS, steps=8)
        window = bounds(floating_windows(page).first)
        assert window["x"] <= CANVAS[0] <= window["x"] + window["width"], (window, CANVAS)
        assert window["y"] <= CANVAS[1] <= window["y"] + window["height"], (window, CANVAS)
    finally:
        page.mouse.up()
    assert page_errors == []


def test_a_folded_floating_panel_docks_expanded(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """And the floating-to-docked half: folding the floating panel and dragging
    it onto an edge lands the full region there, not a rail. Nudging a folded
    window around the canvas, by contrast, keeps the fold -- that is a move
    within the same placement, not a switch."""
    goto_docked(page, leika_server, "left")
    drag(page, center(control_handle(page)), CANVAS, PARK_LOWER)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none", timeout=5_000)

    control_handle(page).click()
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1, timeout=5_000)

    # A folded window dropped on neutral canvas stays folded.
    drag(page, center(control_handle(page)), PARK_UPPER)
    expect(page.locator("[data-dock-collapsed]")).to_have_count(1)

    drag(page, center(control_handle(page)), CANVAS, (16.0, 300.0))
    expect(control_panel(page)).to_have_attribute("data-dock-side", "left", timeout=5_000)
    expect(page.locator("[data-dock-collapsed]")).to_have_count(0, timeout=5_000)
    assert canvas_inset(page) == pytest.approx(DEFAULT_REGION_PX, abs=1.0)
    assert page_errors == []


def test_double_click_sends_the_panel_home_to_its_configured_edge(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """Home is the CONFIGURED placement: for an app that starts docked right,
    the restore gesture re-docks rather than floating to a corner the app
    never used."""
    goto_docked(page, leika_server, "right")

    drag(page, center(control_handle(page)), CANVAS, PARK_LOWER)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none", timeout=5_000)

    handle = center(control_handle(page))
    page.mouse.click(*handle)
    page.mouse.click(*handle)

    expect(control_panel(page)).to_have_attribute("data-dock-side", "right", timeout=5_000)
    assert bounds(control_panel(page))["width"] == pytest.approx(CONTROL_WIDTH_PX, abs=1.0)
    # The pair is a toggle and its undo, so it lands expanded as it started.
    assert page.locator("[data-dock-collapsed]").count() == 0
    assert page_errors == []


def test_mid_session_theme_change_redocks_the_panel(
    leika_server: leika.Server,
    page: Page,
    page_errors: list[str],
) -> None:
    """A configure_theme call mid-session re-places the panel -- once. The
    server wins at the moment it asks; a viewer who then drags the panel away
    keeps their arrangement, since an unchanged value never re-asserts."""
    leika_server.gui.configure_theme(control_layout="floating", dark_mode=True)
    leika_server.gui.add_slider("Value", min=0.0, max=1.0, step=0.01, initial_value=0.5)
    page.goto(leika_server.url)
    page.wait_for_selector("[data-viewport-workspace]", timeout=15_000)
    page.wait_for_function(
        "() => !document.body.innerText.includes('Connecting...')", timeout=15_000
    )
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none", timeout=5_000)
    assert len(window_ids(page)) == 1

    leika_server.gui.configure_theme(control_layout="left", dark_mode=True)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "left", timeout=5_000)
    assert window_ids(page) == []

    # The viewer's next move is theirs to keep.
    drag(page, center(control_handle(page)), CANVAS)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none", timeout=5_000)
    page.wait_for_timeout(400)
    expect(control_panel(page)).to_have_attribute("data-dock-side", "none")
    assert page_errors == []
