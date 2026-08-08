// Data model for the docking library.
//
// The layout is intentionally serializable: it holds only ids, geometry, and
// structure -- never React nodes. Panel *content* lives in a separate registry
// (see PanelRegistry) keyed by panel id, so the same layout can be saved,
// restored, or driven from the server later without touching the render tree.
//
// Vocabulary:
// - Panel: a single titled pane of content. The atomic unit.
// - TabGroup: one or more panels shown as tabs in a shared frame. A group with
//   a single panel is just a plain panel (we hide the tab strip in that case).
// - DockNode: a binary/n-ary split tree describing the docked region on one
//   screen edge. Leaves point at a TabGroup; splits arrange children in a row
//   (side by side) or column (stacked) with per-child flex weights.
// - FloatingWindow: a free-positioned container holding a vertical stack of
//   TabGroups (a "snap group"). A stack of one is a normal floating panel.

import React from "react";

export type PanelId = string;
export type GroupId = string;
export type WindowId = string;
export type NodeId = string;
export type AreaId = string;

/** Minimum width of a panel, enforced everywhere a panel's width is set or
 * previewed: floating windows, docked regions, and drop-zone hints. */
export const MIN_PANEL_WIDTH_PX = 220;

/** Maximum width of a *single* panel. Region/window caps are derived per-panel
 * from this (e.g. a two-column region can be up to 2x this), never applied to
 * the summed width of several panels. */
export const MAX_PANEL_WIDTH_PX = 600;

/** Width (px) of the narrow vertical strip used for every fully-minimized
 * docked column. In px (not em) because minimized strips participate in the
 * region-width MODEL: totals and resize math add this constant directly, so
 * the rendered width must match it exactly. */
export const MINIMIZED_STRIP_PX = 36;

/** Rendered width (px) of the divider between a region's side-by-side
 * columns. Participates in the region-width model the same way strips do:
 * the rendered region is the expanded columns' regionWidth plus these fixed
 * chrome widths, so resize math stays 1:1 with the cursor. */
export const SPLIT_DIVIDER_PX = 7;

/** Width (px) a docked region starts at (and that a newly docked column gets)
 * before the user resizes it.
 *
 * The same 320px as the control panel's own CONTROL_WIDTH_PX, so every way of
 * landing on an edge -- a drag, a server-configured start, the reset gesture
 * -- gives one width, and docking a floating panel does not change its size.
 * Restated rather than imported (the dock does not reach into the panel's
 * code); a test pins the two together. */
export const DEFAULT_REGION_PX = 320;

/** Breathing room (px) an auto-height window keeps above and below itself: its
 * height budget is the container's height less twice this. Shared with the
 * anchoring rules, which have to recognise a window sitting at that budget. */
export const AUTO_HEIGHT_BOUNDARY_PAD_PX = 15;

/** How long a reordered tab glides to its slot. The reorder settle in
 * DockManager is derived from this: it must outlast the glide, or FLIP takes
 * the tab back mid-flight. */
export const TAB_GLIDE_MS = 160;

/** How close two handle clicks must fall to count as a double-click. Matches
 * the interval desktop environments use, which is what a viewer's hands are
 * already tuned to. */
export const DOUBLE_CLICK_MS = 400;

/** Clamp `v` into [lo, hi]. Shared by every place a size/position is bounded
 * (resize gestures, width reconciliation, hint geometry). */
export const clamp = (v: number, lo: number, hi: number): number =>
  Math.max(lo, Math.min(hi, v));

/** Which screen edge a docked region is pinned to. Top/bottom are intentionally
 * unsupported: Leika GUI panels are vertical layouts, so only left/right make
 * sense for docking. */
export type DockEdge = "left" | "right";

/** The four relative positions for docking against an existing docked panel,
 * plus "center" for merging into its tab group. */
export type DropRegion = "center" | "top" | "bottom" | "left" | "right";

/** Content + metadata for a single panel. Kept out of the serializable layout;
 * supplied by the consumer via the panel registry. */
export interface PanelSpec {
  id: PanelId;
  title: string;
  /** Optional small icon shown before the title in tab strips. */
  icon?: React.ReactNode;
  /** Optional custom header content, used in place of the plain `title` text
   * when this panel renders as a full-width header (i.e. when `unmergeable`).
   * Lets a panel show a richer title bar -- e.g. a connection-status label with
   * action icons -- matching the live control panel's handle. The header is
   * still a drag handle, so interactive children should stopPropagation on
   * pointerdown. */
  titleNode?: React.ReactNode;
  /** When true, the panel body is rendered with NO padding so its content sits
   * flush to the panel edges (e.g. a panel whose entire body is a nested
   * dockable area). Default false (the usual comfortable body padding). */
  fullBleed?: boolean;
  /** Renders the panel body. A function (not a node) so each group can keep
   * inactive tabs mounted without storing React nodes in the layout model. */
  render: () => React.ReactNode;
  /** When true, `render` currently produces nothing with height, so the frame
   * drops the gap between header and body. A body that stays mounted at zero
   * height -- to keep an intrinsic-size transition measurable, say -- is still
   * a flex item, and the gap would hang below the header as bare whitespace.
   * The panel has to say so: the frame cannot tell a zero-height body from one
   * that has simply not laid out yet. */
  bodyIsEmpty?: boolean;
  /** When true, this panel may be minimized but never merged into another
   * group's tab strip (and nothing can be merged into it). Its label is shown
   * as a full-width header rather than a tab. An unmergeable panel always lives
   * alone in its group. */
  unmergeable?: boolean;
  /** Put this panel back at the size and position its owner calls home.
   *
   * Fired by a DOUBLE-click on the panel's drag handle, the gesture a titlebar
   * usually carries. The panel supplies it because only its owner knows what
   * "default" means -- the dock remembers geometry, never the intent behind it,
   * and a window's creation rect is not a default for one the user tore out.
   * Omitted, a double-click is just the two collapse toggles it is made of.
   */
  onResetLayout?: () => void;
  /** Take a single click on the handle before the default collapse toggle.
   *
   * Return true to say the click has been dealt with and the group must NOT
   * toggle. For a panel showing only part of itself, the first click is how the
   * rest arrives -- collapsing instead would throw away what the click was
   * asking for. Anything else falls through to the toggle. */
  onHandleClick?: () => boolean;
  /** Take an "expand this panel" request before the default collapsed-flag
   * clear. Fired when a gesture wants the panel OPEN wherever it lands -- a
   * drop that gives it a new placement, a drag from a rail's + button.
   *
   * Return true to say the request has been dealt with. A panel whose fold
   * mirrors state it owns (the control panel folds because its controls
   * section is closed) must be expanded by opening that state: clearing the
   * group's flag directly would only get re-folded by the panel's sync. */
  onExpand?: () => boolean;
  /** Collapsed, fade this window away once the pointer leaves it.
   *
   * A panel that is nothing but a header when collapsed still paints a card
   * the full width of its window across the canvas -- a lot of opaque surface
   * for a bar with nothing in it. Opted in, the card and its header fade out
   * behind the pointer, leaving whatever the panel marked `data-dock-peek`
   * sitting on the canvas alone: hovering that one thing brings the rest back.
   *
   * Faded, the window is also CLICK-THROUGH, so the canvas underneath stays
   * reachable and the peek element is the only target the window still offers
   * -- which is what makes "hover to bring it back" mean the peek element
   * rather than the invisible rectangle around it. It fades on LEAVING rather
   * than on losing hover, so the click that collapsed the panel does not pull
   * the header out from under the pointer that is still on it.
   *
   * Floating windows only; a docked panel collapses to a strip in the region's
   * own column, which is already the small thing this would make it. */
  peekWhenCollapsed?: boolean;
  /** Optional stable `data-testid` for the element this panel renders into.
   *
   * The library's own attributes (`data-dock-leaf`, `data-floating-window`,
   * ...) are generic -- every panel gets them -- so a consumer that needs to
   * address ONE specific panel from outside (an end-to-end test, say) supplies
   * a name here. The chrome around the panel derives suffixed ids from it:
   * `-handle` for its drag handle, `-resize-left` / `-resize-right` for a
   * floating window's resize edges. */
  testId?: string;
}

export type PanelRegistry = Record<PanelId, PanelSpec>;

/** The `testId` of whichever panel a group is currently showing, if any. */
export function testIdForGroup(
  panels: PanelRegistry,
  group: TabGroup | undefined,
): string | undefined {
  return group === undefined ? undefined : panels[group.activeId]?.testId;
}

/** A stack of panels shown as tabs. `activeId` must always be a member of
 * `panelIds`. */
export interface TabGroup {
  id: GroupId;
  panelIds: PanelId[];
  activeId: PanelId;
  /** When true, the group is minimized: only its handle + tab strip show, with
   * the contents hidden. */
  collapsed?: boolean;
  /** Set by minimizeStack on groups that were EXPANDED when the user clicked
   * the stack handle's minimize-all button. expandStack expands exactly the
   * tagged groups, so a mixed min/max arrangement round-trips through a
   * parent minimize/expand. Cleared whenever the user takes individual
   * control of the group (toggleCollapsed / expandGroup). */
  collapsedByParent?: boolean;
}

interface DockNodeBase {
  id: NodeId;
  /** Flex weight relative to siblings within the same split. Ignored for the
   * root node. */
  weight: number;
}

/** A leaf in the docked split tree: a single tab group. */
export interface DockLeaf extends DockNodeBase {
  type: "leaf";
  group: GroupId;
}

/** An internal split: children laid out along one axis.
 * - "row": children side by side (a vertical divider between them).
 * - "column": children stacked top to bottom (a horizontal divider). */
export interface DockSplit extends DockNodeBase {
  type: "split";
  dir: "row" | "column";
  children: DockNode[];
}

export type DockNode = DockLeaf | DockSplit;

/** A free-floating container. Holds a vertical stack of tab groups that move
 * together (the "snap group" from the spec). A single-group stack is an
 * ordinary floating panel. Position/size are parent-relative pixels. */
export interface FloatingWindow {
  id: WindowId;
  x: number;
  y: number;
  width: number;
  /** Explicit height in px once the user vertically resizes; otherwise the
   * window auto-sizes to its content (capped per group). */
  height?: number;
  /** Tab groups stacked top to bottom. */
  stack: GroupId[];
  /** Per-group height weights for a multi-group stack (groupId -> flex weight),
   * used when the window has an explicit `height` so a draggable divider can
   * redistribute height between stacked groups. Missing/absent groups default to
   * weight 1 (equal). Keyed by group id (not index) so it survives stack
   * insert/remove without re-alignment. Layout operations prune stale keys. */
  stackWeights?: Record<GroupId, number>;
}

/** The complete, serializable layout. */
export interface DockLayout {
  /** All tab groups, keyed by id. Referenced from docked trees and floating
   * stacks. A group is "owned" by exactly one location at a time. */
  groups: Record<GroupId, TabGroup>;
  /** Docked region pinned to each edge, or null when that edge is empty. */
  docked: Record<DockEdge, DockNode | null>;
  /** Docked region widths in px per edge: the EXPANDED width-columns' summed
   * pixels (minimized strips and dividers render on top -- see regionPlan).
   * THE single source of truth for region width. It travels with the layout
   * through every op (clones carry it) and is rewritten only by width
   * reconciliation in applyOp -- so snapshot/restore, persistence, and undo
   * preserve widths by construction. Kept while an edge is empty or fully
   * minimized so the width survives for restore.
   *
   * Optional so layout literals (e.g. in tests) stay terse; a missing value
   * reads as DEFAULT_REGION_PX per edge (see regionWidthsOf). */
  regionWidth?: Record<DockEdge, number>;
  /** Floating windows, painted in array order (last = topmost). */
  floating: FloatingWindow[];
  /** Nested dockable areas, keyed by id. Each is a flat tab group embedded in a
   * panel's body (rendered there by `DockArea`); the area's `group` is a normal
   * TabGroup in `groups`. Areas are first-class drop targets and tab sources --
   * they reuse the same drop/reorder/tear ops as everything else. An area's
   * group is a fixed fixture: panels move in/out of it, but the group itself is
   * never floated or removed (it persists empty as a drop affordance).
   *
   * Optional so existing layout literals (e.g. in tests) stay valid; treat a
   * missing value as no areas. */
  areas?: Record<AreaId, { id: AreaId; group: GroupId }>;
}

/** A reference to where a tab group currently lives. Used by drag/drop and
 * layout ops to locate and detach groups. */
export type GroupLocation =
  | { kind: "docked"; edge: DockEdge; nodeId: NodeId }
  | { kind: "floating"; windowId: WindowId }
  | { kind: "area"; areaId: AreaId };

export const emptyLayout = (): DockLayout => ({
  groups: {},
  docked: { left: null, right: null },
  floating: [],
  areas: {},
});

/** The layout's region widths with defaults filled in (the one place the
 * missing-field fallback lives). */
export const regionWidthsOf = (
  layout: DockLayout,
): Record<DockEdge, number> => ({
  left: layout.regionWidth?.left ?? DEFAULT_REGION_PX,
  right: layout.regionWidth?.right ?? DEFAULT_REGION_PX,
});
