// Top-level docking surface. Owns the layout, renders the left/right docked
// regions and floating windows over a center area, and runs the drag-and-drop
// controller that powers moving, docking, tab tear-out, merging, and snapping.
//
// Drag model: every drag is normalized to "dragging a floating window". A drag
// that starts on a docked group or a tab first floats/tears that group into a
// new window (via flushSync, so the window DOM exists immediately), then drags
// it. Movement is applied as a CSS transform on the window element so the
// per-move setState (for the drop hint) doesn't clobber it. On release we
// either apply a docking op for the hovered drop target, or commit the final
// floating position.

import { Card } from "../components/ui/card";
import React from "react";
import { emptyRecord } from "../recordUtils";
import { createDragController } from "./dragController";
import { createGestureCoordinator } from "./gestures";
import {
  DockContext,
  DockContextValue,
  DockMetrics,
  DockMetricsContext,
} from "./DockContext";
import { FloatingWindowView } from "./FloatingWindowView";
import { SplitView } from "./SplitView";
import * as ops from "./layoutOps";
import { RegionResizer } from "./RegionResizer";
import { plannedReservedWidth, planRegion } from "./regionPlan";
import { reconcileRegionWidths } from "./widthReconciliation";
import { anchorFloatingWindow } from "./windowAnchor";
import { DropHint } from "./hitTest";
import {
  DockEdge,
  DockLayout,
  GroupId,
  PanelId,
  PanelRegistry,
  regionWidthsOf,
  WindowId,
} from "./types";

export function DockManager({
  initialLayout,
  panels,
  children,
  onLayoutChange,
}: {
  initialLayout: DockLayout;
  panels: PanelRegistry;
  /** Center content (e.g. the 3D canvas), inset by the docked regions. */
  children?: React.ReactNode;
  /** Observe every committed layout (e.g. for persistence or test probes). */
  onLayoutChange?: (layout: DockLayout) => void;
}) {
  const [layout, setLayout] = React.useState(initialLayout);
  const layoutRef = React.useRef(layout);
  layoutRef.current = layout;
  const onLayoutChangeRef = React.useRef(onLayoutChange);
  onLayoutChangeRef.current = onLayoutChange;
  React.useEffect(() => {
    onLayoutChangeRef.current?.(layout);
  }, [layout]);

  // Region widths are part of the layout MODEL (DockLayout.regionWidth, the
  // single source of truth -- see widthReconciliation.ts); this is just the
  // defaults-filled view of it. Gesture closures read the synchronous truth
  // via regionWidthsOf(layoutRef.current).
  const regionWidth = React.useMemo(() => regionWidthsOf(layout), [layout]);
  // Rendered region widths per edge (assigned after the region plans below).
  const reservedWidthRef = React.useRef({ left: 0, right: 0 });
  const [draggingGroupId, setDraggingGroupId] = React.useState<GroupId | null>(
    null,
  );
  const [draggingTabId, setDraggingTabId] = React.useState<PanelId | null>(
    null,
  );
  const [resizing, setResizing] = React.useState(false);

  // Drop hint, driven IMPERATIVELY (style mutations on a persistent element)
  // rather than via state: the hint updates on every pointer move during a
  // drag, and routing that through setState would re-render the entire dock
  // subtree -- all panels and their contents -- once per frame. With the hint
  // (and the window transform, tab glue, and leaf preview, which were already
  // imperative) off the React path, a drag does no React work per move at all.
  const hintRef = React.useRef<HTMLDivElement>(null);
  const showHint = React.useCallback((hint: DropHint | null) => {
    const el = hintRef.current;
    if (el === null) return;
    if (hint === null) {
      el.style.display = "none";
      el.removeAttribute("data-dock-hint");
      return;
    }
    const variant = HINT_VARIANT_STYLES[hint.variant];
    el.style.display = "block";
    el.style.left = `${hint.left}px`;
    el.style.top = `${hint.top}px`;
    el.style.width = `${hint.width}px`;
    el.style.height = `${hint.height}px`;
    el.style.backgroundColor = variant.backgroundColor;
    el.style.borderRadius = variant.borderRadius;
    el.style.opacity = variant.opacity;
    el.setAttribute("data-dock-hint", hint.variant);
  }, []);

  const containerRef = React.useRef<HTMLDivElement>(null);
  // The window currently being dragged, if any. The container ResizeObserver
  // skips it: during a drag the CURSOR is the source of truth for that
  // window's position, and an anchor/pull write mid-drag would detach the
  // window from the cursor (the drop commits the final position anyway).
  const draggingWindowIdRef = React.useRef<WindowId | null>(null);
  // One active pointer gesture per manager. The tokenized coordinator covers
  // drag presses, moves, split/region dividers, and floating-window resizes.
  const [gestureCoordinator] = React.useState(createGestureCoordinator);
  // Pending tab-reorder "settle" timer, so it can be cancelled on unmount.
  const settleTimer = React.useRef<number | undefined>(undefined);
  React.useEffect(
    () => () => {
      gestureCoordinator.cancel();
      if (settleTimer.current !== undefined) clearTimeout(settleTimer.current);
    },
    [gestureCoordinator],
  );

  // ONE region plan per edge per layout, shared by every consumer below:
  // planning is several tree walks, and a region resize commits once a frame.
  const plans = React.useMemo(
    () => ({
      left:
        layout.docked.left !== null
          ? planRegion(layout.docked.left, layout.groups)
          : null,
      right:
        layout.docked.right !== null
          ? planRegion(layout.docked.right, layout.groups)
          : null,
    }),
    [layout],
  );

  // Apply a layout op, reconciling docked region widths (written into
  // next.regionWidth) so panels keep their pixel widths across structural
  // changes (see widthReconciliation.ts). The reconciler enforces the
  // min-width floor on every commit, so a too-narrow region is
  // unrepresentable in committed state.
  const applyOp = React.useCallback((next: DockLayout) => {
    if (next === layoutRef.current) return; // no-op op: nothing to commit.
    reconcileRegionWidths(layoutRef.current, next);
    layoutRef.current = next;
    setLayout(next);
  }, []);

  // Restore a previously COMMITTED layout exactly (Escape after a drag that
  // committed an op up front). No reconciliation: the snapshot already
  // carries valid widths -- regionWidth lives in the layout, so "put the
  // pre-drag layout back" restores geometry by construction, where the
  // reconciler's content-matching would treat restored columns as new and
  // reset them to defaults.
  const restoreLayout = React.useCallback((snapshot: DockLayout) => {
    layoutRef.current = snapshot;
    setLayout(snapshot);
  }, []);

  // Imperative panel lifecycle API (exposed via context). Stable identity so
  // sync layers can list it in effect deps without re-running.
  const api = React.useMemo(
    () => ({
      apply: (fn: (l: DockLayout) => DockLayout) =>
        applyOp(fn(layoutRef.current)),
      addPanelToArea: (areaId: string, panelId: PanelId, index?: number) =>
        applyOp(ops.addPanelToArea(layoutRef.current, areaId, panelId, index)),
    }),
    [applyOp],
  );

  // Registry reconciliation: a panel whose spec disappears from `panels` (e.g.
  // removed server-side after the user dragged it out of its area) is removed
  // from wherever it lives in the layout, collapsing emptied windows/cells.
  React.useEffect(() => {
    const current = layoutRef.current;
    let next = current;
    for (const group of Object.values(current.groups)) {
      for (const p of group.panelIds) {
        if (panels[p] === undefined) next = ops.removePanel(next, p);
      }
    }
    if (next !== current) applyOp(next);
  }, [panels, layout, applyOp]);

  // Live container dimensions. Height caps floating panels' scrolling bodies.
  // Width also lets right-anchored windows render from a CSS `right` inset:
  // browser layout can then preserve that inset synchronously when the viewport
  // changes, before ResizeObserver delivers the corresponding model
  // reconciliation.
  const [containerSize, setContainerSize] = React.useState({
    width: 0,
    height: 0,
  });

  // Keep floating windows sensibly placed when the container resizes: measure
  // the rendered heights (what anchoring operates on) and hand each window to
  // anchorFloatingWindow, which owns the nearer-edge / shrink-pull / clamp
  // rules.
  const prevContainerSize = React.useRef<{
    width: number;
    height: number;
  } | null>(null);
  React.useLayoutEffect(() => {
    const el = containerRef.current;
    if (el === null) return;
    const reconcileContainer = () => {
      const rect = el.getBoundingClientRect();
      setContainerSize((current) =>
        current.width === rect.width && current.height === rect.height
          ? current
          : { width: rect.width, height: rect.height },
      );
      const prevSize = prevContainerSize.current;
      prevContainerSize.current = { width: rect.width, height: rect.height };
      // Rendered heights, for vertical anchoring of auto-height windows.
      const heights = new Map<string, number>();
      el.querySelectorAll<HTMLElement>("[data-floating-window]").forEach(
        (winEl) => {
          const id = winEl.getAttribute("data-floating-window");
          if (id !== null) heights.set(id, winEl.offsetHeight);
        },
      );
      setLayout((prev) => {
        let changed = false;
        const floating = prev.floating.map((w) => {
          if (w.id === draggingWindowIdRef.current) return w;
          // Anchoring and pulling operate on what the user SEES: the RENDERED
          // height, which the map above just measured. The model height is
          // only a fallback for a window with no DOM yet. (Using the model
          // height first yanked collapsed pinned-height windows around by the
          // height of their hidden content.)
          const [x, y] = anchorFloatingWindow(
            { ...w, height: heights.get(w.id) ?? w.height ?? 0 },
            prevSize,
            rect,
          );
          if (x === w.x && y === w.y) return w;
          changed = true;
          return { ...w, x, y };
        });
        if (!changed) return prev;
        const next = { ...prev, floating };
        layoutRef.current = next;
        return next;
      });
    };
    // Seed dimensions and the resize baseline before the first panel can be
    // painted. ResizeObserver delivery is deferred, so observing alone leaves
    // one frame with no right-anchor information.
    reconcileContainer();
    const observer = new ResizeObserver(reconcileContainer);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // --- Gestures ----------------------------------------------------------
  // The five pointer state machines (window drag, group float, column float,
  // tab reorder/tear, press arbitration) live in dragController.ts. Every
  // dependency is a stable ref or callback, so ONE controller is created and
  // its starters keep a stable identity for the memoized context below.
  const panelsRef = React.useRef(panels);
  panelsRef.current = panels;
  const gestures = React.useMemo(
    () =>
      createDragController({
        containerRef,
        layoutRef,
        reservedWidthRef,
        draggingWindowIdRef,
        gestureCoordinator,
        settleTimer,
        panelsRef,
        applyOp,
        restoreLayout,
        showHint,
        setDraggingGroupId,
        setDraggingTabId,
      }),
    [applyOp, gestureCoordinator, restoreLayout, showHint],
  );

  const activateTab = React.useCallback(
    (groupId: GroupId, panelId: PanelId) =>
      applyOp(ops.setActiveTab(layoutRef.current, groupId, panelId)),
    [applyOp],
  );
  const toggleCollapsed = React.useCallback(
    (groupId: GroupId) =>
      applyOp(ops.toggleCollapsed(layoutRef.current, groupId)),
    [applyOp],
  );
  // Memoized so renders driven by HIGH-CHURN state (region widths during a
  // resize drag, container height during a browser resize -- which live in
  // DockMetricsContext instead) don't invalidate every context consumer: with
  // a stable context, memoized children skip re-rendering entirely.
  const contextValue: DockContextValue = React.useMemo(
    () => ({
      panels,
      api,
      layout,
      groups: layout.groups,
      areas: layout.areas ?? {},
      resizing,
      setResizing,
      gestureCoordinator,
      ...gestures,
      activateTab,
      toggleCollapsed,
      draggingGroupId,
      draggingTabId,
    }),
    [
      panels,
      api,
      layout,
      resizing,
      gestureCoordinator,
      gestures,
      activateTab,
      toggleCollapsed,
      draggingGroupId,
      draggingTabId,
    ],
  );
  const metrics: DockMetrics = React.useMemo(
    () => ({
      reservedWidth: {
        left:
          plans.left !== null
            ? plannedReservedWidth(plans.left, regionWidth.left)
            : 0,
        right:
          plans.right !== null
            ? plannedReservedWidth(plans.right, regionWidth.right)
            : 0,
      },
    }),
    [regionWidth, plans],
  );

  // Stable per-window handlers (windowId-first) so FloatingWindowView can be
  // memoized -- inline per-window closures would break the memo every render.
  const onWindowResize = React.useCallback(
    (windowId: WindowId, width: number, x?: number) =>
      applyOp(ops.resizeWindow(layoutRef.current, windowId, width, x)),
    [applyOp],
  );
  const onWindowResizeHeight = React.useCallback(
    (windowId: WindowId, height: number | undefined, y?: number) =>
      applyOp(ops.resizeWindowHeight(layoutRef.current, windowId, height, y)),
    [applyOp],
  );
  const onWindowSetStackWeights = React.useCallback(
    (windowId: WindowId, weights: Record<GroupId, number>) =>
      applyOp(ops.setStackWeights(layoutRef.current, windowId, weights)),
    [applyOp],
  );
  const onWindowRestoreStackWeights = React.useCallback(
    (
      windowId: WindowId,
      groupIds: readonly GroupId[],
      weights: Readonly<Record<GroupId, number>> | undefined,
    ) =>
      applyOp(
        ops.restoreStackWeights(layoutRef.current, windowId, groupIds, weights),
      ),
    [applyOp],
  );
  const onWindowFront = React.useCallback(
    (windowId: WindowId) =>
      applyOp(ops.bringToFront(layoutRef.current, windowId)),
    [applyOp],
  );

  // Each docked region renders its FULL tree: fully-minimized columns are
  // fixed-width vertical strips that inset the canvas like any other column.
  // All width accounting (which columns are strips, how much fixed chrome
  // sits on top of regionWidth) comes from ONE classification: planRegion.
  const regions = (["left", "right"] as DockEdge[]).map((edge) => {
    const tree = layout.docked[edge];
    const plan = plans[edge];
    if (tree === null || plan === null)
      return { edge, tree, reservedWidth: 0, hasExpanded: false };
    return {
      edge,
      tree,
      hasExpanded: plan.hasExpanded,
      reservedWidth: plannedReservedWidth(plan, regionWidth[edge]),
    };
  });
  const leftInset = regions[0].reservedWidth;
  const rightInset = regions[1].reservedWidth;
  // Rendered region widths, for hit-testing during drags: drop zones and
  // their hints must align to what's on screen, not to the MODEL regionWidth
  // (which excludes the strips and preserves widths through minimization).
  reservedWidthRef.current = { left: leftInset, right: rightInset };

  return (
    <DockContext.Provider value={contextValue}>
      <DockMetricsContext.Provider value={metrics}>
        <div
          ref={containerRef}
          data-dock-root
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            overflow: "hidden",
          }}
        >
          {/* Center content, inset by docked regions. */}
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: leftInset,
              right: rightInset,
            }}
          >
            {children}
          </div>

          {/* Docked regions: every column insets the canvas, with fully-minimized
        columns rendering as fixed-width vertical strips. */}
          {regions.map(({ edge, tree, hasExpanded, reservedWidth }) => (
            <React.Fragment key={edge}>
              {tree !== null && (
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    bottom: 0,
                    [edge]: 0,
                    width: reservedWidth,
                    display: "flex",
                    zIndex: 5,
                  }}
                >
                  <SplitView node={tree} edge={edge} topLevel />
                  {hasExpanded && (
                    <RegionResizer
                      edge={edge}
                      getStart={() => reservedWidth}
                      // Called once per drag: snapshots the columns' start widths
                      // and limits, and returns the per-frame handler. Widths are
                      // redistributed across ALL columns from their drag-start
                      // proportions, clamping each to its own min/max and handing
                      // the difference to columns that still have room -- so the
                      // region keeps resizing while any column can give or take.
                      makeOnResize={() => {
                        const layout0 = layoutRef.current;
                        const tree0 = layout0.docked[edge];
                        if (tree0 === null) return () => {};
                        // Only EXPANDED columns participate: minimized strips are
                        // fixed-width chrome that the drag passes through, so the
                        // cursor moves 1:1 with the expanded panels. The plan is
                        // the same classification the render uses.
                        const plan = planRegion(tree0, layout0.groups);
                        const cols = plan.expandedColumns;
                        if (cols.length === 0) return () => {};
                        const startRegion = regionWidthsOf(layoutRef.current)[
                          edge
                        ];
                        // Weights are pixels for side-by-side columns (the
                        // reconciler wrote them); a single surfaced column's px
                        // is the regionWidth itself (its weight may be a height).
                        const init = plan.singleColumn
                          ? [startRegion]
                          : cols.map((c) => c.weight);
                        const mins = cols.map((c) => ops.minRegionWidth(c));
                        const maxs = cols.map((c) => ops.maxRegionWidth(c));
                        const ids = cols.map((c) => c.id);
                        return (reservedPx: number) => {
                          // The grip reports the desired RESERVED width, which
                          // includes the fixed chrome; subtract it to get the
                          // expanded columns' share.
                          const widths = ops.resizeRegionColumns(
                            init,
                            mins,
                            maxs,
                            reservedPx - plan.chromePx,
                          );
                          const total = widths.reduce((a, b) => a + b, 0);
                          // Only rewrite weights for genuinely side-by-side
                          // columns; a single surfaced column may be a vertical
                          // child whose weight is a HEIGHT (see applyOp). The
                          // total goes through the setRegionWidth op so the model
                          // stays the single source of truth for the width.
                          let next = layoutRef.current;
                          if (!plan.singleColumn) {
                            const byId = emptyRecord<number>();
                            ids.forEach((id, i) => {
                              byId[id] = widths[i];
                            });
                            next = ops.setNodeWeights(next, edge, byId);
                          }
                          applyOp(ops.setRegionWidth(next, edge, total));
                        };
                      }}
                    />
                  )}
                </div>
              )}
            </React.Fragment>
          ))}

          {/* Floating windows. The `floating` array order is the front-order
        (last = topmost), but we render in a STABLE order (by id) and drive
        stacking with z-index. That way raising a window (bringToFront reorders
        the array) only changes z-index -- it never moves the DOM node, which
        would otherwise eat an in-flight click on e.g. the minimize button. */}
          {layout.floating
            .map((win, frontOrder) => ({ win, frontOrder }))
            .sort((a, b) =>
              a.win.id < b.win.id ? -1 : a.win.id > b.win.id ? 1 : 0,
            )
            .map(({ win, frontOrder }) => (
              <FloatingWindowView
                key={win.id}
                win={win}
                zIndex={10 + frontOrder}
                containerWidth={containerSize.width}
                containerHeight={containerSize.height}
                onResize={onWindowResize}
                onResizeHeight={onWindowResizeHeight}
                onSetStackWeights={onWindowSetStackWeights}
                onRestoreStackWeights={onWindowRestoreStackWeights}
                onFront={onWindowFront}
              />
            ))}

          {/* Drop hint: a persistent element positioned imperatively by
        showHint. Its style prop is a module constant, so React's style diff
        never touches the imperative mutations across re-renders. */}
          <Card ref={hintRef} style={HINT_BASE_STYLE} />
        </div>
      </DockMetricsContext.Provider>
    </DockContext.Provider>
  );
}

// Base style for the imperative drop-hint element (see showHint). The hint per
// variant: a tinted highlight (tab merge), a solid zone (edge dock), or a thin
// insertion bar (split / tab-position / stack drops).
const HINT_BASE_STYLE: React.CSSProperties = {
  position: "absolute",
  display: "none",
  pointerEvents: "none",
  zIndex: 1000,
  boxSizing: "border-box",
};
const HINT_VARIANT_STYLES: Record<
  DropHint["variant"],
  { backgroundColor: string; borderRadius: string; opacity: string }
> = {
  merge: {
    backgroundColor: "var(--accent)",
    borderRadius: "6px",
    opacity: "0.75",
  },
  fill: {
    backgroundColor: "var(--accent)",
    borderRadius: "0",
    opacity: "0.8",
  },
  line: {
    backgroundColor: "var(--foreground)",
    borderRadius: "0",
    opacity: "1",
  },
};
