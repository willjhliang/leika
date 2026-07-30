// The dock's drag-and-drop controller: the pointer state machines behind
// moving, docking, tab tear-out, merging, and snapping. Pure gesture logic
// over a fixed set of refs and stable callbacks -- no rendering. DockManager
// creates one controller and hands its starters to the dock context.
//
// Drag model: every drag is normalized to "dragging a floating window". A drag
// that starts on a docked group or a tab first floats/tears that group into a
// new window (via flushSync, so the window DOM exists immediately), then drags
// it. Movement is applied as a CSS transform on the window element so the
// per-move setState (for the drop hint) doesn't clobber it. On release we
// either apply a docking op for the hovered drop target, or commit the final
// floating position.

import { flushSync } from "react-dom";

import {
  bindPointerGesture,
  grabbingCursor,
  motionExceedsThreshold,
  suppressTextSelection,
  tryCapture,
  tryRelease,
} from "./gestures";
import { prefersReducedMotion } from "../utils/motion";
import * as ops from "./layoutOps";
import { clampCorner, translationOf } from "./windowAnchor";
import {
  DropHint,
  DropResult,
  DropTargets,
  GroupContext,
  GroupTarget,
  hitTest,
  tabInsertion,
} from "./hitTest";
import { DockContextValue } from "./DockContext";
import {
  clamp,
  DEFAULT_REGION_PX,
  TAB_GLIDE_MS,
  DockEdge,
  DockLayout,
  GroupId,
  MAX_PANEL_WIDTH_PX,
  MIN_PANEL_WIDTH_PX,
  NodeId,
  PanelId,
  PanelRegistry,
  WindowId,
} from "./types";

// How far past a tab strip's edge the pointer must travel before a tab reorder
// becomes a tear-out into a floating window.
const TAB_TEAR_PX = 30;
// A nested area's HIT rect is inset by up to this much on its left/right/bottom
// so a frame around a full-bleed area falls through to the HOST panel's zones.
const AREA_HIT_INSET_PX = 40;
// Areas with a smaller rendered rect than this are skipped as drop targets:
// a MINIMIZED host collapses its area to ~0px, and offering that would put a
// phantom target over the host's own handle. Kept well below the smallest
// legitimate area (an empty "drop a panel here" placeholder is ~40px tall --
// it must stay droppable), and well above the collapsed case (~0px).
const AREA_MIN_TARGET_PX = 24;

export type DragControllerDeps = {
  containerRef: React.RefObject<HTMLDivElement | null>;
  /** The committed layout, synchronously current (see DockManager). */
  layoutRef: React.RefObject<DockLayout>;
  /** Rendered reserved widths per edge -- what's on screen, NOT the model
   * regionWidth -- so drop zones align with the pixels. */
  reservedWidthRef: React.RefObject<{ left: number; right: number }>;
  /** The window being dragged, for the container observer to leave alone. */
  draggingWindowIdRef: React.RefObject<WindowId | null>;
  /** Cleanup for an in-flight gesture, run if the manager unmounts mid-drag. */
  activeCleanup: React.RefObject<(() => void) | null>;
  /** Pending tab-reorder "settle" timer, cancellable on unmount. */
  settleTimer: React.RefObject<number | undefined>;
  panelsRef: React.RefObject<PanelRegistry>;
  applyOp: (next: DockLayout) => void;
  restoreLayout: (snapshot: DockLayout) => void;
  showHint: (hint: DropHint | null) => void;
  setDraggingGroupId: (id: GroupId | null) => void;
  setDraggingTabId: (id: PanelId | null) => void;
};

export type DragController = Pick<
  DockContextValue,
  "startGroupDrag" | "startTabDrag" | "startWindowDrag" | "startColumnDrag"
>;

export function createDragController(deps: DragControllerDeps): DragController {
  const {
    containerRef,
    layoutRef,
    reservedWidthRef,
    draggingWindowIdRef,
    activeCleanup,
    settleTimer,
    panelsRef,
    applyOp,
    restoreLayout,
    showHint,
    setDraggingGroupId,
    setDraggingTabId,
  } = deps;

  const containerRect = () =>
    containerRef.current?.getBoundingClientRect() ?? new DOMRect();

  // --- Drop-target hit testing -------------------------------------------

  const collectTargets = (draggedWindowId: WindowId): DropTargets => {
    const container = containerRef.current;
    const targets: DropTargets = { groups: [] };
    if (container === null) return targets;

    // Tabs animate to new slots with a transient FLIP `transform: translate(...)`
    // (see TabGroupFrame). Collecting targets right after a tear-out's flushSync
    // would otherwise capture those mid-animation positions -- making the strip
    // look like it still has the just-removed tab's geometry. Measure each tab at
    // its RESTING layout box by subtracting its own transform translation.
    const restingRect = (el: Element): DOMRect => {
      const rect = el.getBoundingClientRect();
      const [tx, ty] = translationOf(getComputedStyle(el).transform);
      if (tx === 0 && ty === 0) return rect;
      return new DOMRect(
        rect.left - tx,
        rect.top - ty,
        rect.width,
        rect.height,
      );
    };

    // Collect the strip + tabs that belong to ONE group, scoped so a nested
    // group (e.g. a DockArea inside this panel's body) doesn't leak its strip or
    // tabs into this target. `rectEl` is the element whose box defines the
    // target's hit rect (the group element itself, or an area's wrapper).
    const buildTarget = (
      rectEl: Element,
      scopeEl: Element,
      groupId: GroupId,
      ctx: GroupContext,
    ): GroupTarget => {
      const stripEl = scopeEl.querySelector(`[data-dock-strip="${groupId}"]`);
      const tabs: { panelId: PanelId; rect: DOMRect }[] = [];
      scopeEl.querySelectorAll("[data-dock-tab]").forEach((t) => {
        // Skip tabs that belong to a nested group (their nearest group ancestor
        // isn't ours).
        if (t.closest("[data-dock-group]") !== scopeEl) return;
        const panelId = t.getAttribute("data-dock-tab");
        if (panelId !== null) tabs.push({ panelId, rect: restingRect(t) });
      });
      return {
        groupId,
        rect: rectEl.getBoundingClientRect(),
        stripRect: stripEl?.getBoundingClientRect() ?? null,
        tabs,
        ctx,
        collapsed: layoutRef.current.groups[groupId]?.collapsed === true,
        unmergeable: ops.isGroupUnmergeable(
          layoutRef.current,
          panelsRef.current,
          groupId,
        ),
      };
    };
    const readGroup = (el: Element, ctx: GroupContext): GroupTarget | null => {
      const groupId = el.getAttribute("data-dock-group");
      if (groupId === null) return null;
      return buildTarget(el, el, groupId, ctx);
    };

    container.querySelectorAll("[data-dock-leaf]").forEach((leaf) => {
      const nodeId = leaf.getAttribute("data-dock-leaf");
      const edge = leaf.getAttribute("data-dock-edge") as DockEdge | null;
      const groupEl = leaf.querySelector("[data-dock-group]");
      if (nodeId === null || edge === null || groupEl === null) return;
      const g = readGroup(groupEl, { kind: "docked", nodeId, edge });
      if (g !== null) targets.groups.push(g);
    });
    // Iterate floating windows in front-order (array order = z), not DOM order
    // (which is stable/by-id), so targets are ordered back-to-front and hitTest
    // can pick the topmost (last) match over overlapping windows.
    layoutRef.current.floating.forEach((win) => {
      if (win.id === draggedWindowId) return;
      const winEl = container.querySelector(
        `[data-floating-window="${win.id}"]`,
      );
      if (winEl === null) return;
      winEl.querySelectorAll("[data-dock-group]").forEach((groupEl, index) => {
        const g = readGroup(groupEl, {
          kind: "floating",
          windowId: win.id,
          index,
        });
        if (g !== null) targets.groups.push(g);
      });
    });
    // Nested dockable areas. Pushed LAST so that when an area sits inside a
    // docked/floating panel's body, hovering it makes the area (the topmost
    // match) win over its host. The area's group id comes from the layout (not
    // the DOM), so an EMPTY area -- which renders no inner group/strip -- is
    // still a valid drop target sized to its wrapper.
    const areas = layoutRef.current.areas ?? {};
    container.querySelectorAll("[data-dock-area]").forEach((areaEl) => {
      const areaId = areaEl.getAttribute("data-dock-area");
      if (areaId === null) return;
      const area = areas[areaId];
      if (area === undefined) return;
      if (layoutRef.current.groups[area.group] === undefined) return;
      // Never offer an area that lives INSIDE the dragged window: dropping the
      // window into its own nested area would make the host a child of itself
      // (a containment cycle). Floating windows already skip the dragged one
      // above; areas are found by a container-wide scan, so filter here too.
      if (
        areaEl.closest(`[data-floating-window="${draggedWindowId}"]`) !== null
      )
        return;
      // Skip an area whose host panel is minimized: its wrapper collapses to
      // (near) zero height, and flooring that into a hit band would put a
      // phantom "drop into area" target on top of the host's own handle/zones.
      const areaRect = areaEl.getBoundingClientRect();
      if (
        areaRect.height < AREA_MIN_TARGET_PX ||
        areaRect.width < AREA_MIN_TARGET_PX
      )
        return;
      const innerGroupEl = areaEl.querySelector(
        `[data-dock-group="${area.group}"]`,
      );
      const t = buildTarget(areaEl, innerGroupEl ?? areaEl, area.group, {
        kind: "area",
        areaId,
      });
      // Inset the area's HIT rect on the left/right/bottom (not the top, which
      // holds its tab strip) so a frame around it falls through to the HOST
      // panel's own edge zones -- otherwise a full-bleed area (one that fills its
      // whole panel) would shadow the host everywhere, leaving no way to dock
      // beside/below it. `rect` stays full so the merge HINT is still full-width;
      // only `hitRect` (used for hit detection) is inset.
      const r = t.rect;
      const mx = Math.min(AREA_HIT_INSET_PX, r.width * 0.28);
      const mb = Math.min(AREA_HIT_INSET_PX, r.height * 0.28);
      t.hitRect = new DOMRect(
        r.left + mx,
        r.top,
        Math.max(AREA_HIT_INSET_PX, r.width - 2 * mx),
        Math.max(AREA_HIT_INSET_PX, r.height - mb),
      );
      targets.groups.push(t);
    });
    return targets;
  };

  // --- Split preview -----------------------------------------------------
  // Top/bottom splits make vertical room by actually shrinking the target
  // leaf's height (its contents just scroll -- no distortion). Left/right
  // splits don't change widths at all (the region grows on drop and the new
  // panel brings its own width), so the leaf is left untouched -- only the
  // ghost is shown. Hit-testing uses rects cached at drag start, so the live
  // height change here doesn't move the drop zones.
  let previewLeaf: HTMLElement | null = null;
  // The wrapper's inline background BEFORE the preview tinted it. The wrapper
  // can be a React-managed element with its own inline backgroundColor (when
  // the region is a single leaf, the leaf's parent IS the reserved region
  // container) -- clearing to "" on reset would wipe that style, and React's
  // style diff never re-writes an unchanged value, leaving the region
  // permanently transparent. Restore the saved value instead.
  let previewWrapperBg = "";
  const resetLeafPreview = () => {
    const el = previewLeaf;
    if (el === null) return;
    el.style.height = "";
    el.style.alignSelf = "";
    el.style.transition = "";
    // Restore the wrapper's pre-tint background (see applyLeafPreview).
    const wrapper = el.parentElement;
    if (wrapper !== null) wrapper.style.backgroundColor = previewWrapperBg;
    previewLeaf = null;
  };
  const applyLeafPreview = (
    nodeId: NodeId,
    region: "top" | "bottom" | "left" | "right",
  ) => {
    // Left/right: no leaf change (ghost only).
    if (region === "left" || region === "right") {
      resetLeafPreview();
      return;
    }
    const el = containerRef.current?.querySelector<HTMLElement>(
      `[data-dock-leaf="${nodeId}"]`,
    );
    if (el == null) {
      resetLeafPreview();
      return;
    }
    if (previewLeaf !== null && previewLeaf !== el) {
      resetLeafPreview();
    }
    el.style.transition = prefersReducedMotion() ? "none" : "height 120ms ease";
    el.style.height = "50%";
    // Keep the leaf in the half the new panel won't take.
    el.style.alignSelf = region === "top" ? "flex-end" : "flex-start";
    // Tint the vacated half so the gap reads as a drop hint (the opaque leaf
    // Paper covers its own half; the wrapper's tint shows through the other).
    const wrapper = el.parentElement;
    if (wrapper !== null) {
      if (previewLeaf !== el) {
        // First application to this leaf: remember the wrapper's own value.
        previewWrapperBg = wrapper.style.backgroundColor;
      }
      wrapper.style.backgroundColor = "var(--accent)";
    }
    previewLeaf = el;
  };

  // --- Window drag (shared by every drag path) ---------------------------

  const beginWindowDrag = (
    windowId: WindowId,
    groupIdForDim: GroupId | null,
    pointerId: number,
    grabX: number,
    grabY: number,
    /** Pre-drag layout for drags that COMMIT an op up front (float a group/
     * column, tear out a tab): a cancel (Escape) restores it, so the panel
     * docks back where it came from instead of stranding as a floater.
     * Deliberately a whole-layout snapshot, not an inverse op: cancelling
     * also discards any external layout changes that landed mid-drag, which
     * is acceptable for a sub-second gesture and far simpler than rebasing. */
    restoreOnCancel?: DockLayout,
  ) => {
    const container = containerRef.current;
    const el0 = container?.querySelector<HTMLElement>(
      `[data-floating-window="${windowId}"]`,
    );
    if (container == null || el0 == null) return;
    let el: HTMLElement = el0;

    setDraggingGroupId(groupIdForDim);
    draggingWindowIdRef.current = windowId;
    const restoreCursor = grabbingCursor();
    let crect = container.getBoundingClientRect();
    let targets = collectTargets(windowId);
    // The layout the targets were collected against. A mid-drag layout change
    // (e.g. a server update adding/removing panels) invalidates the cached
    // rects AND may recreate the dragged window's DOM node; both are
    // re-resolved lazily in apply() so drops land on what's actually on screen.
    let targetsLayout = layoutRef.current;
    // The dragged stack is fixed for the whole drag; if it holds an unmergeable
    // panel, hitTest suppresses merge/insertTab results (and their hints).
    const draggingUnmergeable = (
      layoutRef.current.floating.find((w) => w.id === windowId)?.stack ?? []
    ).some((gid) =>
      ops.isGroupUnmergeable(layoutRef.current, panelsRef.current, gid),
    );
    let restingLeft = el.offsetLeft;
    let restingTop = el.offsetTop;

    let latest: PointerEvent | null = null;
    let raf: number | null = null;
    let lastResult: DropResult | null = null;
    let finalX = restingLeft;
    let finalY = restingTop;

    const apply = () => {
      raf = null;
      const e = latest;
      if (e === null) return;
      if (layoutRef.current !== targetsLayout) {
        targetsLayout = layoutRef.current;
        targets = collectTargets(windowId);
        crect = container.getBoundingClientRect();
        if (!el.isConnected) {
          // Reconciliation recreated the window's DOM node mid-drag; without
          // re-resolving, the per-frame transform would land on the detached
          // node and the window would snap back to rest until release.
          el =
            container.querySelector<HTMLElement>(
              `[data-floating-window="${windowId}"]`,
            ) ?? el;
        }
        // A mid-drag layout change may have moved the dragged window's
        // RESTING position (e.g. a server update). The transform is relative
        // to rest, so re-baseline against the freshly rendered offsets --
        // otherwise the window rides at a stale offset from the cursor for
        // the remainder of the drag. (offsetLeft/Top ignore the transform.)
        restingLeft = el.offsetLeft;
        restingTop = el.offsetTop;
      }
      // Off-screen panels are allowed (the body may overflow the right/bottom),
      // but we keep the top-left corner within the container so the handle is
      // always reachable.
      const desiredLeft = e.clientX - crect.left - grabX;
      const desiredTop = e.clientY - crect.top - grabY;
      [finalX, finalY] = clampCorner(
        desiredLeft,
        desiredTop,
        crect.width,
        crect.height,
      );
      el.style.transform = `translate(${finalX - restingLeft}px, ${finalY - restingTop}px)`;
      const hit = hitTest(
        layoutRef.current,
        // Rendered reserved widths (NOT the model regionWidth): drop zones
        // must align to what's on screen when columns are overlaid as a rail.
        reservedWidthRef.current,
        crect,
        targets,
        e.clientX,
        e.clientY,
        { draggingUnmergeable },
      );
      lastResult = hit?.result ?? null;
      showHint(hit?.hint ?? null);
      // Preview a split by shrinking the target leaf (top/bottom only); clear
      // otherwise.
      if (hit?.result.kind === "split") {
        applyLeafPreview(hit.result.nodeId, hit.result.region);
      } else {
        resetLeafPreview();
      }
    };

    const detach = bindPointerGesture(
      (e) => {
        latest = e;
        if (raf === null) raf = requestAnimationFrame(apply);
      },
      (_endEvent, cancelled) => {
        // A cancelled pointer (Escape, browser-stolen touch) ABORTS: no dock,
        // no move -- clearing the transform snaps the window back to where the
        // drag started. Only a real pointerup commits.
        detach();
        activeCleanup.current = null;
        if (raf !== null) {
          cancelAnimationFrame(raf);
          if (!cancelled) apply();
        }
        tryRelease(el, pointerId);
        el.style.transform = "";
        el.style.willChange = "";
        el.style.opacity = "";
        restoreSelect();
        restoreCursor();
        showHint(null);
        setDraggingGroupId(null);
        draggingWindowIdRef.current = null;
        resetLeafPreview();
        if (cancelled) {
          // A deferred-float drag already committed its float op; put the
          // pre-drag layout back so Escape really means "never mind" --
          // including region widths, which the snapshot carries.
          if (restoreOnCancel !== undefined) restoreLayout(restoreOnCancel);
          return;
        }

        const result = lastResult;
        const base = layoutRef.current;
        // The whole dragged stack docks together (a snapped multi-group window
        // keeps all its panels, not just the top one). Unmergeable policy is
        // hitTest's: it never returns merge/insertTab for an unmergeable drag.
        const stack = base.floating.find((w) => w.id === windowId)?.stack ?? [];
        if (result === null || stack.length === 0) {
          applyOp(ops.moveWindow(base, windowId, finalX, finalY));
          return;
        }
        // Widths are reconciled centrally in applyOp, so these just apply the
        // structural op (no per-path region-width juggling).
        if (result.kind === "edge") {
          applyOp(ops.dockToEdge(base, stack, result.edge));
        } else if (result.kind === "regionEdge") {
          applyOp(ops.dockToRegionEdge(base, stack, result.edge, result.side));
        } else if (result.kind === "split") {
          applyOp(
            ops.dropOnDockedLeaf(
              base,
              stack,
              result.edge,
              result.nodeId,
              result.region,
            ),
          );
        } else if (result.kind === "merge") {
          // Expanding a collapsed target makes the drop visible -- merging
          // into a minimized handle would silently hide the dropped panel.
          applyOp(
            ops.expandGroup(
              ops.mergeGroupsInto(base, result.targetGroupId, stack),
              result.targetGroupId,
            ),
          );
        } else if (result.kind === "insertTab") {
          applyOp(
            ops.expandGroup(
              ops.insertTabsInto(
                base,
                result.targetGroupId,
                stack,
                result.index,
              ),
              result.targetGroupId,
            ),
          );
        } else {
          applyOp(
            ops.snapToWindowStack(base, stack, result.windowId, result.index),
          );
        }
      },
      // Ignore other pointers so a second finger can't drive/commit this drag.
      pointerId,
    );
    el.style.willChange = "transform";
    // Dim the dragged window so the drop target underneath stays visible.
    el.style.opacity = "0.6";
    // Suppress text selection anywhere while dragging over content.
    const restoreSelect = suppressTextSelection();
    tryCapture(el, pointerId);
    activeCleanup.current = () => {
      detach();
      el.style.opacity = "";
      restoreSelect();
      restoreCursor();
      draggingWindowIdRef.current = null;
      if (raf !== null) cancelAnimationFrame(raf);
    };
  };

  /** Run a drag whose gesture COMMITS layout ops up front (float a group or
   * column, tear out a tab, expand-then-drag). Pairs the commit with its
   * Escape-restore snapshot BY CONSTRUCTION: the snapshot is taken here,
   * before `commit` runs, so no call site can commit without one. `commit`
   * applies its ops (flushed where the new window's DOM must exist) and
   * returns the drag parameters, or null to abort (nothing committed). */
  const dragAfterCommit = (
    e: PointerEvent,
    commit: () => {
      windowId: WindowId;
      groupIdForDim: GroupId | null;
      grabX: number;
      grabY: number;
    } | null,
  ) => {
    const before = layoutRef.current;
    const params = commit();
    if (params === null) return;
    beginWindowDrag(
      params.windowId,
      params.groupIdForDim,
      e.pointerId,
      params.grabX,
      params.grabY,
      before,
    );
  };

  // --- Deferred drags (float/tear, then drag the new window) -------------

  /** Arm a press: wait for motion past threshold (-> onDrag) or a release with
   * no motion (-> onClick). */
  const armPress = (
    event: React.PointerEvent<HTMLElement>,
    onDrag: (e: PointerEvent) => void,
    onClick?: () => void,
  ) => {
    // Only the primary button starts a gesture. A right/middle press would
    // otherwise arm a drag whose pointerup is swallowed by the context menu,
    // leaving the panel stuck "dragging" until the next move.
    if (event.button !== 0) return;
    // Ignore presses that bubble in from PORTALED children (a share modal's
    // overlay, a tooltip label): React portals bubble through the REACT tree,
    // so without this DOM-containment check a click inside an open modal
    // would arm a drag / click-toggle on the handle underneath.
    if (!event.currentTarget.contains(event.target as Node)) return;
    // Finalize any pending tab-reorder settle so its delayed setDraggingTabId
    // doesn't fire in the middle of this new gesture (which would un-mark a tab
    // mid-drag and let FLIP fight the manager's imperative transform).
    if (settleTimer.current !== undefined) {
      clearTimeout(settleTimer.current);
      settleTimer.current = undefined;
      setDraggingTabId(null);
    }
    // Suppress text selection from the PRESS, not from the drag threshold: the
    // browser anchors a selection on the initial mousedown, so suppressing only
    // once motion exceeds 3px would still let a drag highlight page text.
    const restoreSelect = suppressTextSelection();
    const startX = event.clientX;
    const startY = event.clientY;
    let triggered = false;
    const detach = bindPointerGesture(
      (e) => {
        if (triggered) return;
        if (!motionExceedsThreshold([startX, startY], [e.clientX, e.clientY]))
          return;
        triggered = true;
        detach();
        activeCleanup.current = null;
        // The drag handler re-suppresses for its own (longer) lifetime.
        restoreSelect();
        onDrag(e);
      },
      (_e, cancelled) => {
        detach();
        activeCleanup.current = null;
        restoreSelect();
        // Only a real release is a click -- a CANCELLED pointer (touch grabbed
        // by the browser for scrolling, palm rejection, etc.) must not activate.
        if (!triggered && !cancelled) onClick?.();
      },
      // Ignore other pointers so a second finger can't trigger/cancel this press.
      event.pointerId,
    );
    activeCleanup.current = () => {
      detach();
      restoreSelect();
    };
  };

  const floatRectFor = (selector: string) => {
    const container = containerRef.current;
    const el = container?.querySelector<HTMLElement>(selector);
    const crect = containerRect();
    if (el == null) {
      return { x: 40, y: 40, width: DEFAULT_REGION_PX, height: undefined };
    }
    const r = el.getBoundingClientRect();
    return {
      x: r.left - crect.left,
      y: r.top - crect.top,
      width: clamp(r.width, MIN_PANEL_WIDTH_PX, MAX_PANEL_WIDTH_PX),
      // Rendered height -- used to give an undocked panel a definite height when
      // it needs one (e.g. a full-bleed nested area, which collapses to 0 in an
      // auto-height window). Clamped so a region-tall panel doesn't float huge.
      height: clamp(r.height, 120, 560),
    };
  };

  // --- Gesture starters --------------------------------------------------

  const startWindowDrag: DragController["startWindowDrag"] = (
    event,
    windowId,
  ) => {
    if (layoutRef.current.floating.every((w) => w.id !== windowId)) return;
    // Press-time POINTER coordinates, but the window's CURRENT model position
    // at drag start: the window may move between press and the drag threshold
    // (container-resize anchoring), and offsets frozen against the press-time
    // position would teleport it back on the first drag frame.
    const pressX = event.clientX;
    const pressY = event.clientY;
    armPress(event, (e) => {
      const win = layoutRef.current.floating.find((w) => w.id === windowId);
      if (win === undefined) return;
      const crect = containerRect();
      beginWindowDrag(
        windowId,
        null,
        e.pointerId,
        pressX - crect.left - win.x,
        pressY - crect.top - win.y,
      );
    });
  };

  const startGroupDrag: DragController["startGroupDrag"] = (
    event,
    groupId,
    opts,
  ) => {
    // A no-motion press drags nothing but fires opts.onClick (the unmergeable
    // header uses this to toggle minimize on click).
    const onClick = opts?.onClick;
    const expandOnDrag = opts?.expandOnDrag === true;
    const loc = ops.findGroupLocation(layoutRef.current, groupId);
    // A group alone in its floating window just moves that window on drag.
    if (loc?.kind === "floating") {
      const win0 = layoutRef.current.floating.find(
        (w) => w.id === loc.windowId,
      );
      if (win0 !== undefined && win0.stack.length === 1) {
        const windowId = win0.id;
        // Press-time pointer, drag-start model position (see startWindowDrag).
        const pressX = event.clientX;
        const pressY = event.clientY;
        armPress(
          event,
          (e) => {
            const win = layoutRef.current.floating.find(
              (w) => w.id === windowId,
            );
            if (win === undefined) return;
            const crect = containerRect();
            const grabX = pressX - crect.left - win.x;
            const grabY = pressY - crect.top - win.y;
            if (expandOnDrag) {
              // A drag from the expand (+) button tears out the FULL panel:
              // expand first (flushed so the window height renders), then
              // drag. The expand is an up-front COMMIT, so it goes through
              // dragAfterCommit and Escape restores the minimized state.
              dragAfterCommit(e, () => {
                flushSync(() =>
                  applyOp(ops.expandGroup(layoutRef.current, groupId)),
                );
                return { windowId, groupIdForDim: null, grabX, grabY };
              });
            } else {
              beginWindowDrag(windowId, null, e.pointerId, grabX, grabY);
            }
          },
          onClick,
        );
        return;
      }
    }
    armPress(
      event,
      (e) => {
        dragAfterCommit(e, () => {
          const rect = floatRectFor(`[data-dock-group="${groupId}"]`);
          // A panel whose body is a full-bleed nested area needs a definite
          // height to fill (it collapses to 0 in an auto-height window). Give
          // the undocked window the panel's current rendered height in that
          // case; ordinary panels keep auto-height (content-sized) as before.
          const needsHeight = (
            layoutRef.current.groups[groupId]?.panelIds ?? []
          ).some((p) => panelsRef.current[p]?.fullBleed === true);
          const res = ops.floatGroup(
            layoutRef.current,
            groupId,
            rect.x,
            rect.y,
            rect.width,
            needsHeight ? rect.height : undefined,
          );
          // Null only for an area's backing group, which no UI surface offers a
          // group-drag for; bail rather than drag a window that doesn't exist.
          if (res.windowId === null) return null;
          // applyOp reconciles region widths: undocking this column removes it
          // from the region's column set, so siblings keep their widths and the
          // region shrinks by the removed column's width. A drag from the
          // expand (+) button floats the panel EXPANDED -- dragging it should
          // produce a full panel, not a minimized stub.
          flushSync(() =>
            applyOp(
              expandOnDrag ? ops.expandGroup(res.layout, groupId) : res.layout,
            ),
          );
          const crect = containerRect();
          return {
            windowId: res.windowId,
            groupIdForDim: groupId,
            grabX: e.clientX - crect.left - rect.x,
            grabY: e.clientY - crect.top - rect.y,
          };
        });
      },
      onClick,
    );
  };

  const startColumnDrag: DragController["startColumnDrag"] = (
    event,
    edge,
    columnNodeId,
  ) => {
    armPress(event, (e) => {
      dragAfterCommit(e, () => {
        // Measure the COLUMN wrapper (not the 1em handle): floatRectFor clamps
        // width/height into sane floating ranges, same as a group undock.
        const rect = floatRectFor(`[data-dock-column="${columnNodeId}"]`);
        const res = ops.floatColumn(
          layoutRef.current,
          edge,
          columnNodeId,
          rect.x,
          rect.y,
          rect.width,
          rect.height,
        );
        // Null when the column was restructured under us or isn't a pure
        // column anymore; just don't drag.
        if (res.windowId === null) return null;
        // applyOp reconciles region widths: removing this column from the
        // edge's column set lets survivors keep their px and shrinks the
        // region.
        flushSync(() => applyOp(res.layout));
        const crect = containerRect();
        return {
          // No single origin group to dim; the whole column left the tree.
          windowId: res.windowId,
          groupIdForDim: null,
          grabX: e.clientX - crect.left - rect.x,
          grabY: e.clientY - crect.top - rect.y,
        };
      });
    });
  };

  const startTabDrag: DragController["startTabDrag"] = (
    event,
    groupId,
    panelId,
  ) => {
    const stripEl = (event.target as HTMLElement).closest<HTMLElement>(
      "[data-dock-strip]",
    );
    const stripRect = stripEl?.getBoundingClientRect() ?? null;

    let raf: number | null = null;
    let latest: PointerEvent | null = null;
    let detach: (() => void) | null = null;
    let reordering = false;
    // Insertion index shown by the line and committed on drop.
    let lastInsert: number | null = null;
    // Accumulated translateX on the dragged tab (so it follows the cursor).
    let tabTx = 0;
    const draggedTabEl = () =>
      stripEl?.querySelector<HTMLElement>(`[data-dock-tab="${panelId}"]`) ??
      null;

    // Set when the reorder phase arms; restores page-wide text selection and
    // the grabbing cursor.
    let restoreSelect: (() => void) | null = null;
    let restoreCursor: (() => void) | null = null;
    const teardown = () => {
      detach?.();
      detach = null;
      if (raf !== null) cancelAnimationFrame(raf);
      raf = null;
      activeCleanup.current = null;
      restoreSelect?.();
      restoreSelect = null;
      restoreCursor?.();
      restoreCursor = null;
      showHint(null);
    };
    // Used when the gesture is abandoned without committing (tear-out, unmount):
    // snap the dragged tab back and clear drag state immediately.
    const cleanup = () => {
      teardown();
      const tabEl = draggedTabEl();
      if (tabEl !== null) {
        tabEl.style.transition = "";
        tabEl.style.transform = "";
      }
      if (reordering) setDraggingTabId(null);
    };
    // Pointer-up while reordering: commit the reorder to the line's index, then
    // glide the dragged tab from the cursor into its new slot.
    const commitReorder = () => {
      teardown();
      if (!reordering) return;
      if (lastInsert === null) {
        setDraggingTabId(null);
        return;
      }
      const cursorX = latest?.clientX ?? 0;
      const index = lastInsert;
      flushSync(() =>
        applyOp(ops.reorderTab(layoutRef.current, groupId, panelId, index)),
      );
      const tabEl = draggedTabEl();
      if (tabEl !== null && prefersReducedMotion()) {
        tabEl.style.transition = "";
        tabEl.style.transform = "";
      } else if (tabEl !== null) {
        // Re-anchor at the cursor (no jump when the slot moves), then ease in.
        const rect = tabEl.getBoundingClientRect();
        const restCenter = rect.left + rect.width / 2 - tabTx;
        tabEl.style.transition = "none";
        tabEl.style.transform = `translateX(${cursorX - restCenter}px)`;
        requestAnimationFrame(() => {
          tabEl.style.transition = `transform ${TAB_GLIDE_MS}ms ease`;
          tabEl.style.transform = "";
        });
      }
      // Keep draggingTabId set through the settle so FLIP leaves this tab to
      // us -- except under reduced motion, where there's no glide to protect.
      if (prefersReducedMotion()) {
        setDraggingTabId(null);
      } else {
        settleTimer.current = window.setTimeout(
          () => setDraggingTabId(null),
          TAB_GLIDE_MS + 20,
        );
      }
    };

    const tearOut = (e: PointerEvent) => {
      cleanup();
      dragAfterCommit(e, () => {
        const src = floatRectFor(`[data-dock-group="${groupId}"]`);
        const res = ops.tearOutPanel(
          layoutRef.current,
          groupId,
          panelId,
          src.x,
          src.y,
          src.width,
        );
        flushSync(() => applyOp(res.layout));

        // Anchor the new window so the cursor lands on its tab strip. Unlike
        // a group drag (which floats on the first 3px of motion), a tear-out
        // only triggers after the pointer has left the strip, so we can't
        // reuse the accumulated offset -- re-measure the new window's strip
        // and reposition.
        const crect = containerRect();
        const winEl = containerRef.current?.querySelector<HTMLElement>(
          `[data-floating-window="${res.windowId}"]`,
        );
        let grabX = 40;
        let grabY = 18;
        if (winEl != null) {
          const winRect = winEl.getBoundingClientRect();
          grabX = Math.min(40, winRect.width / 2);
          const stripEl2 =
            winEl.querySelector<HTMLElement>("[data-dock-strip]");
          if (stripEl2 != null) {
            const sRect = stripEl2.getBoundingClientRect();
            grabY = sRect.top - winRect.top + sRect.height / 2;
          } else {
            // Strip not found (defensive): anchor within the window's actual
            // height rather than a fixed 18px that may overshoot a short
            // window.
            grabY = Math.min(18, winRect.height / 2);
          }
        }
        const newX = e.clientX - crect.left - grabX;
        const newY = e.clientY - crect.top - grabY;
        flushSync(() =>
          applyOp(ops.moveWindow(layoutRef.current, res.windowId, newX, newY)),
        );
        return {
          windowId: res.windowId,
          groupIdForDim: res.floatingGroupId,
          grabX,
          grabY,
        };
      });
    };

    const apply = () => {
      raf = null;
      const e = latest;
      if (e === null) return;
      // Leaving the strip vertically tears the tab out into a floating window.
      if (
        stripEl === null ||
        stripRect === null ||
        e.clientY > stripRect.bottom + TAB_TEAR_PX ||
        e.clientY < stripRect.top - TAB_TEAR_PX
      ) {
        tearOut(e);
        return;
      }
      // Reorder within the strip. The dragged tab follows the cursor
      // immediately (imperative transform); the other tabs stay put and an
      // insertion line shows where it will land (same affordance as a tab
      // merge). The reorder is committed on drop.
      if (!reordering) {
        reordering = true;
        setDraggingTabId(panelId);
      }
      // Nearest-tab insertion among the other tabs (2D, so it's correct when
      // the strip wraps onto multiple rows). The line is anchored to the matched
      // tab's own row.
      const others: { rect: DOMRect }[] = [];
      stripEl.querySelectorAll<HTMLElement>("[data-dock-tab]").forEach((t) => {
        if (t.getAttribute("data-dock-tab") !== panelId)
          others.push({ rect: t.getBoundingClientRect() });
      });
      const ins = tabInsertion(others, e.clientX, e.clientY);
      const crect = containerRect();
      if (ins !== null) {
        lastInsert = ins.index;
        showHint({
          left: ins.lineLeft - crect.left - 1,
          top: ins.lineTop - crect.top,
          width: 2,
          height: ins.lineHeight,
          variant: "line",
        });
      } else {
        lastInsert = 0;
        showHint(null);
      }

      // Glue the dragged tab to the cursor. Self-correcting: strip the current
      // transform from the measured center to recover the resting center, then
      // re-solve for the translate that centers it on the pointer.
      const tabEl = draggedTabEl();
      if (tabEl !== null) {
        const r = tabEl.getBoundingClientRect();
        const restCenter = r.left + r.width / 2 - tabTx;
        tabTx = e.clientX - restCenter;
        tabEl.style.transition = "none";
        tabEl.style.transform = `translateX(${tabTx}px)`;
      }
    };

    armPress(
      event,
      (e0) => {
        // A single-tab strip has nothing to reorder: grabbing the tab should
        // immediately move the panel itself. A group alone in its floating
        // window just drags that window (like its grip would); anything else
        // tears out right away instead of arming the reorder state machine.
        const group = layoutRef.current.groups[groupId];
        if ((group?.panelIds.length ?? 0) <= 1) {
          const loc = ops.findGroupLocation(layoutRef.current, groupId);
          if (loc?.kind === "floating") {
            const win = layoutRef.current.floating.find(
              (w) => w.id === loc.windowId,
            );
            if (win !== undefined && win.stack.length === 1) {
              const crect = containerRect();
              beginWindowDrag(
                win.id,
                groupId,
                e0.pointerId,
                e0.clientX - crect.left - win.x,
                e0.clientY - crect.top - win.y,
              );
              return;
            }
          }
          tearOut(e0);
          return;
        }
        // Keep selection suppressed through the reorder phase (armPress's
        // suppression ends when it hands off to this drag handler).
        restoreSelect = suppressTextSelection();
        restoreCursor = grabbingCursor();
        latest = e0;
        detach = bindPointerGesture(
          (e) => {
            latest = e;
            if (raf === null) raf = requestAnimationFrame(apply);
          },
          // Pointer-up commits the reorder to the line's index; a CANCELLED
          // pointer (Escape, browser-stolen touch) abandons it and snaps the
          // dragged tab back to its original slot.
          (_endEvent, cancelled) => (cancelled ? cleanup() : commitReorder()),
          e0.pointerId, // ignore other fingers during the reorder/tear.
        );
        activeCleanup.current = cleanup;
        raf = requestAnimationFrame(apply);
      },
      () => applyOp(ops.setActiveTab(layoutRef.current, groupId, panelId)),
    );
  };

  return { startWindowDrag, startGroupDrag, startColumnDrag, startTabDrag };
}
