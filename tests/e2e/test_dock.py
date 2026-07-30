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
DEFAULT_REGION_PX = 300.0

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
    """Drag a GUI tab out of its strip into its own floating window at `park`."""
    before = set(window_ids(page))
    tab = page.get_by_role("tab", name=name, exact=True)
    tab_box = bounds(tab)
    start = center(tab)
    # Straight down, past the strip's tear threshold, then out to `park`.
    drag(page, start, (start[0], tab_box["y"] + tab_box["height"] + 60.0), park)
    expect(floating_windows(page)).to_have_count(len(before) + 1, timeout=5_000)
    new_ids = set(window_ids(page)) - before
    assert len(new_ids) == 1, new_ids
    return page.locator(f'[data-floating-window="{new_ids.pop()}"]')


def grip_of(window: Locator) -> Locator:
    """A floating window's own grip bar (the drag handle of its single group)."""
    return window.locator("[data-dock-griphandle]").first


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
    expect(page.get_by_text("Control panel", exact=True)).to_be_visible()

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

    # Dragging far past the minimum stops at it rather than collapsing.
    grip = center(resizer)
    drag(page, grip, (grip[0] - 400.0, grip[1]))
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
    drag(page, center(grip_of(torn)), CANVAS, center(strip))

    expect(floating_windows(page)).to_have_count(1)
    expect(gui_area(page).locator("[data-dock-tab]")).to_have_count(2)
    assert page_errors == []


def test_tabs_reorder_within_their_strip(dock_page: Page, page_errors: list[str]) -> None:
    page = dock_page
    tabs = gui_area(page).locator("[data-dock-tab]")
    expect(tabs).to_have_text(["Alpha", "Beta"])

    beta = bounds(page.get_by_role("tab", name="Beta", exact=True))
    start = center(page.get_by_role("tab", name="Alpha", exact=True))
    # Stay inside the strip vertically -- leaving it would tear the tab out.
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

    # Dropping over a window's grip bar snaps in above that group.
    drag(page, center(grip_of(beta)), CANVAS, center(grip_of(alpha)))

    expect(floating_windows(page)).to_have_count(2)
    stacked = floating_windows(page).filter(has=page.get_by_role("tab", name="Alpha", exact=True))
    expect(stacked.locator("[data-dock-group]")).to_have_count(2)
    # A multi-group window grows a header that drags the whole stack.
    expect(stacked.locator("[data-floating-handle]")).to_have_count(1)
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
    page.mouse.move(*center(grip_of(torn)))
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
        center(grip_of(torn)),
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
    # Both panels came along, under one stack header.
    expect(window.locator("[data-floating-handle]")).to_have_count(1)
    expect(window.get_by_test_id("control-panel-handle")).to_be_visible()
    expect(window.get_by_role("tab", name="Beta", exact=True)).to_be_visible()
    expect(page.locator("[data-dock-leaf]")).to_have_count(0)
    assert canvas_inset(page) == pytest.approx(0.0, abs=0.5)
    assert page_errors == []


def test_minimize_all_collapses_a_floating_stack_and_restores_it(
    dock_page: Page, page_errors: list[str]
) -> None:
    page = dock_page
    alpha = tear_out_tab(page, "Alpha", PARK_LOWER)
    beta = tear_out_tab(page, "Beta", PARK_UPPER)
    drag(page, center(grip_of(beta)), CANVAS, center(grip_of(alpha)))
    stacked = floating_windows(page).filter(has=page.get_by_role("tab", name="Alpha", exact=True))
    expect(stacked.locator("[data-dock-group]")).to_have_count(2)
    expanded_height = bounds(stacked)["height"]

    minimize_all = stacked.locator("[data-dock-minimize-all]")
    expect(minimize_all).to_have_attribute("aria-label", "Minimize all panels")
    minimize_all.click()

    expect(stacked.locator("[data-dock-collapsed='true']")).to_have_count(2)
    assert bounds(stacked)["height"] < expanded_height
    expect(minimize_all).to_have_attribute("aria-label", "Expand all panels")

    minimize_all.click()
    expect(stacked.locator("[data-dock-collapsed='true']")).to_have_count(0)
    assert bounds(stacked)["height"] == pytest.approx(expanded_height, abs=2.0)
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


def test_a_grip_bar_reaches_the_top_of_its_window(dock_page: Page) -> None:
    """The same band above a tabbed group's grip bar, which drags in place of a
    header. Its own height is unchanged by taking the band on: the pill stays
    centred in the bar rather than in the bar plus the padding above it."""
    page = dock_page
    window = tear_out_tab(page, "Alpha", PARK_UPPER)
    card = bounds(window)
    grip = bounds(grip_of(window))
    assert grip["y"] <= card["y"] + 0.5, (grip, card)
    assert grip["height"] == pytest.approx(32.0 + 16.0, abs=0.5), grip
    assert _sits_on(
        page, (card["x"] + card["width"] / 2, card["y"] + 8.0), "[data-dock-griphandle]"
    )

    pill = bounds(grip_of(window).locator('[data-slot="separator"]'))
    assert pill["y"] + pill["height"] / 2 == pytest.approx(card["y"] + 16.0 + 16.0, abs=0.5)


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

    # And leaving it fades the panel back down.
    page.mouse.move(*CANVAS)
    expect(control_panel(page)).to_have_css("background-color", "rgba(0, 0, 0, 0)", timeout=5_000)
