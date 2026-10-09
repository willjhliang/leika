import React from "react";
import { Card, CardContent } from "../components/ui/card";
import { useViewer } from "../ViewerContext";
import { motionExceedsThreshold } from "../dragUtils";
import { prefersReducedMotion } from "../utils/motion";
import {
  VIEWPORT_ROOT_PANE_ID,
  type ViewportDropRegion,
  type ViewportLayout,
  dropViewportPane,
  sameViewportLayout,
} from "./layoutModel";
import {
  GRID_EPSILON,
  type DividerGeometry,
  type GridRect,
  type GridSpec,
  type LayoutGeometry,
  type WorkspaceSize,
  computeLayoutGeometry,
  directionalPaneTarget,
  dropRegionForPoint,
  gridSpecForLayout,
  pointInsidePane,
  resizeLayoutAtGridLine,
} from "./gridLayout";
import { initialViewportLayout, isViewportPageReady } from "./ViewportState";
import { panePositionStyle, paneTitle } from "./workspaceGeometry";
import { ViewportPaneHost } from "./ViewportPaneHost";
import { ViewportDivider } from "./ViewportDivider";
import { displayedViewportPage } from "./viewportSelectors";

const EMPTY_VIEWPORT_LAYOUT = initialViewportLayout();

const DRAG_INDICATOR_MAX_WIDTH_EM = 16;

interface DropHint {
  targetPaneId: string;
  region: ViewportDropRegion;
  rect: GridRect;
  cellSize: number;
}

interface GestureBase {
  pointerId: number;
  grip: HTMLElement;
  startLayout: ViewportLayout;
  startInteractionEpoch: number;
  grid: GridSpec;
  workspaceWidth: number;
  workspaceHeight: number;
}

interface PaneGesture extends GestureBase {
  kind: "pane";
  sourcePaneId: string;
  startGeometry: LayoutGeometry;
  startClientX: number;
  startClientY: number;
  dragStarted: boolean;
  indicatorShown: boolean;
  lastCandidate: ViewportLayout | null;
  lastHint: DropHint | null;
}

interface DividerGesture extends GestureBase {
  kind: "divider";
  divider: DividerGeometry;
  pointerOffset: number;
  lastValidLayout: ViewportLayout;
  lastGridLine: number;
}

type WorkspaceGesture = PaneGesture | DividerGesture;

interface PaneDragIndicator {
  paneId: string;
  title: string;
}

const paneMoveDirectionFromKey: Partial<
  Record<string, "left" | "right" | "top" | "bottom">
> = {
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "top",
  ArrowDown: "bottom",
};

/** The workspace root's content box, which the pane grid divides.
 *
 * Distinct from `useElementSize`: the grid needs integer `clientWidth` /
 * `clientHeight` (padding box, scrollbars excluded), not the fractional
 * border-box rect, so that cell arithmetic lands on whole pixels. */
function useWorkspaceSize(
  rootRef: React.RefObject<HTMLDivElement | null>,
): WorkspaceSize {
  const [size, setSize] = React.useState<WorkspaceSize>({
    width: 0,
    height: 0,
  });

  React.useLayoutEffect(() => {
    const root = rootRef.current;
    if (root === null) return;
    const update = () => {
      const next = { width: root.clientWidth, height: root.clientHeight };
      setSize((current) =>
        current.width === next.width && current.height === next.height
          ? current
          : next,
      );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(root);
    return () => observer.disconnect();
  }, [rootRef]);

  return size;
}

function geometryTransition(durationMs: number): string {
  return ["left", "top", "width", "height"]
    .map((property) => property + " " + durationMs + "ms ease")
    .join(", ");
}

function dragIndicatorLeft(clientX: number): string {
  return `clamp(8px, ${clientX + 12}px, calc(100vw - ${DRAG_INDICATOR_MAX_WIDTH_EM}em - 8px))`;
}

function dragIndicatorTop(clientY: number): string {
  return `clamp(8px, ${clientY + 12}px, calc(100vh - 2.4em - 8px))`;
}

/** Auto-filling split workspace for native image, matplotlib, Plotly, and
 * viser panes. */
export function ViewportWorkspace() {
  const viewer = useViewer();
  const displayPageId = viewer.useViewport((state) => state.displayPageId);
  const layout = viewer.useViewport(
    (state) => displayedViewportPage(state)?.layout ?? EMPTY_VIEWPORT_LAYOUT,
  );
  const interactive = viewer.useViewport(isViewportPageReady);
  const interactionEpoch = viewer.useViewport(
    (state) => state.interactionEpoch,
  );
  const rootRef = React.useRef<HTMLDivElement>(null);
  const canvasRef = React.useRef<HTMLDivElement>(null);
  const workspaceSize = useWorkspaceSize(rootRef);
  const gestureRef = React.useRef<WorkspaceGesture | null>(null);
  const dragIndicatorRef = React.useRef<HTMLDivElement>(null);
  const dragIndicatorPositionRef = React.useRef({ clientX: 0, clientY: 0 });
  const [draftLayout, setDraftLayout] = React.useState<ViewportLayout | null>(
    null,
  );
  const [dropHint, setDropHint] = React.useState<DropHint | null>(null);
  const [gestureView, setGestureView] = React.useState<{
    kind: WorkspaceGesture["kind"];
    grid: GridSpec;
    startLayout: ViewportLayout;
  } | null>(null);
  const [dragIndicator, setDragIndicator] =
    React.useState<PaneDragIndicator | null>(null);
  const [announcement, setAnnouncement] = React.useState("");
  const motionEnabled = !prefersReducedMotion();
  const paneGeometryTransition = motionEnabled
    ? geometryTransition(gestureView?.kind === "divider" ? 80 : 160)
    : undefined;
  const hintGeometryTransition = motionEnabled
    ? geometryTransition(120)
    : undefined;

  const displayLayout = draftLayout ?? layout;
  // The locked gesture grid is only valid for the layout the gesture started
  // from. A server-driven layout change can land one render before the
  // cancellation effect runs; falling back to a fresh grid keeps that render
  // from violating the new layout's subtree minima.
  const gestureGridIsCurrent =
    gestureView !== null &&
    (draftLayout !== null ||
      sameViewportLayout(gestureView.startLayout, layout));
  const grid = gestureGridIsCurrent
    ? gestureView.grid
    : gridSpecForLayout(displayLayout, workspaceSize);
  const geometry = React.useMemo(
    () => computeLayoutGeometry(displayLayout.root, grid.columns, grid.rows),
    [displayLayout.root, grid.columns, grid.rows],
  );
  const geometryRef = React.useRef(geometry);
  geometryRef.current = geometry;

  const getPaneTitle = React.useCallback(
    (paneId: string | null): string => {
      if (paneId === null) return "viewport pane";
      const pane = displayedViewportPage(viewer.useViewport.get())?.panes[
        paneId
      ];
      return pane === undefined ? "viewport pane" : paneTitle(pane);
    },
    [viewer.useViewport],
  );

  const isGestureStale = React.useCallback(
    (gesture: GestureBase): boolean => {
      const state = viewer.useViewport.get();
      const pageId = state.activePageId;
      const page = pageId === null ? undefined : state.pages[pageId];
      return (
        state.interactionEpoch !== gesture.startInteractionEpoch ||
        pageId === null ||
        !isViewportPageReady(state) ||
        page === undefined ||
        !sameViewportLayout(page.layout, gesture.startLayout)
      );
    },
    [viewer.useViewport],
  );

  const positionDragIndicator = React.useCallback(
    (clientX: number, clientY: number) => {
      dragIndicatorPositionRef.current = { clientX, clientY };
      const indicator = dragIndicatorRef.current;
      if (indicator === null) return;
      indicator.style.left = dragIndicatorLeft(clientX);
      indicator.style.top = dragIndicatorTop(clientY);
    },
    [],
  );

  const applyPaneDragPoint = React.useCallback(
    (gesture: PaneGesture, clientX: number, clientY: number) => {
      if (!interactive) return;
      if (!gesture.dragStarted) {
        if (
          !motionExceedsThreshold(
            [gesture.startClientX, gesture.startClientY],
            [clientX, clientY],
          )
        )
          return;
        gesture.dragStarted = true;
      }
      positionDragIndicator(clientX, clientY);
      if (!gesture.indicatorShown) {
        gesture.indicatorShown = true;
        setDragIndicator({
          paneId: gesture.sourcePaneId,
          title: getPaneTitle(gesture.sourcePaneId),
        });
      }
      const canvas = canvasRef.current;
      if (canvas === null || gesture.grid.cellSize <= 0) return;
      const bounds = canvas.getBoundingClientRect();
      const pointerX = (clientX - bounds.left) / gesture.grid.cellSize;
      const pointerY = (clientY - bounds.top) / gesture.grid.cellSize;
      const target = Object.entries(gesture.startGeometry.panes).find(
        ([paneId, rect]) =>
          paneId !== gesture.sourcePaneId &&
          pointInsidePane(rect, pointerX, pointerY),
      );
      if (target === undefined) {
        gesture.lastCandidate = null;
        gesture.lastHint = null;
        setDropHint(null);
        return;
      }

      const [targetPaneId, targetRect] = target;
      const region = dropRegionForPoint(targetRect, pointerX, pointerY);
      if (
        gesture.lastHint?.targetPaneId === targetPaneId &&
        gesture.lastHint.region === region
      ) {
        return;
      }
      const candidate = dropViewportPane(
        gesture.startLayout,
        gesture.sourcePaneId,
        targetPaneId,
        region,
      );
      const candidateGrid = gridSpecForLayout(candidate, {
        width: gesture.workspaceWidth,
        height: gesture.workspaceHeight,
      });
      const candidateGeometry = computeLayoutGeometry(
        candidate.root,
        candidateGrid.columns,
        candidateGrid.rows,
      );
      const candidateRect = candidateGeometry.panes[gesture.sourcePaneId];
      if (candidateRect === undefined) {
        gesture.lastCandidate = null;
        gesture.lastHint = null;
        setDropHint(null);
        return;
      }
      const hint = {
        targetPaneId,
        region,
        rect: candidateRect,
        cellSize: candidateGrid.cellSize,
      };
      gesture.lastCandidate = candidate;
      gesture.lastHint = hint;
      setDropHint(hint);
    },
    [getPaneTitle, interactive, positionDragIndicator],
  );

  const applyDividerPoint = React.useCallback(
    (gesture: DividerGesture, clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      if (!interactive) return;
      if (canvas === null || gesture.grid.cellSize <= 0) return;
      const bounds = canvas.getBoundingClientRect();
      const pointerCoordinate =
        gesture.divider.direction === "row"
          ? (clientX - bounds.left) / gesture.grid.cellSize
          : (clientY - bounds.top) / gesture.grid.cellSize;
      const requestedGridLine = Math.round(
        pointerCoordinate - gesture.pointerOffset,
      );
      const resized = resizeLayoutAtGridLine(
        gesture.startLayout,
        gesture.divider,
        requestedGridLine,
      );
      gesture.lastValidLayout = resized.layout;
      gesture.lastGridLine = resized.gridLine;
      setDraftLayout(resized.layout);
    },
    [interactive],
  );

  const clearGesture = React.useCallback(() => {
    const gesture = gestureRef.current;
    gestureRef.current = null;
    setDraftLayout(null);
    setDropHint(null);
    setGestureView(null);
    setDragIndicator(null);
    if (gesture !== null && gesture.grip.hasPointerCapture(gesture.pointerId)) {
      try {
        gesture.grip.releasePointerCapture(gesture.pointerId);
      } catch {
        // Pointer capture may already have been released by the browser.
      }
    }
  }, []);

  // A topology change or workspace resize invalidates in-flight paths and
  // geometry. Cancel instead of committing stale state.
  React.useEffect(() => {
    const gesture = gestureRef.current;
    if (
      gesture !== null &&
      (!interactive ||
        !sameViewportLayout(gesture.startLayout, layout) ||
        gesture.startInteractionEpoch !== interactionEpoch ||
        Math.abs(gesture.workspaceWidth - workspaceSize.width) > GRID_EPSILON ||
        Math.abs(gesture.workspaceHeight - workspaceSize.height) > GRID_EPSILON)
    ) {
      clearGesture();
    }
  }, [
    clearGesture,
    interactionEpoch,
    layout,
    interactive,
    workspaceSize.height,
    workspaceSize.width,
  ]);

  React.useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || gestureRef.current === null) return;
      event.preventDefault();
      clearGesture();
      setAnnouncement("Viewport gesture cancelled.");
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [clearGesture]);

  React.useEffect(() => clearGesture, [clearGesture]);

  const beginPaneDrag = React.useCallback(
    (event: React.PointerEvent<HTMLElement>, paneId: string) => {
      if (
        !interactive ||
        event.button !== 0 ||
        gestureRef.current !== null ||
        grid.cellSize <= 0
      ) {
        return;
      }
      // Lock the current grid for the gesture. Pane docking is preview-only,
      // so pointer-down must never rescale or rearrange the live workspace.
      const gestureGrid = grid;
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.setPointerCapture(event.pointerId);
      gestureRef.current = {
        kind: "pane",
        pointerId: event.pointerId,
        grip: event.currentTarget,
        startLayout: layout,
        startInteractionEpoch: interactionEpoch,
        grid: gestureGrid,
        workspaceWidth: workspaceSize.width,
        workspaceHeight: workspaceSize.height,
        sourcePaneId: paneId,
        startClientX: event.clientX,
        startClientY: event.clientY,
        dragStarted: false,
        indicatorShown: false,
        startGeometry: computeLayoutGeometry(
          layout.root,
          gestureGrid.columns,
          gestureGrid.rows,
        ),
        lastCandidate: null,
        lastHint: null,
      };
      setGestureView({ kind: "pane", grid: gestureGrid, startLayout: layout });
    },
    [grid, interactionEpoch, interactive, layout, workspaceSize],
  );

  const updatePaneDrag = React.useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const gesture = gestureRef.current;
      if (gesture?.kind !== "pane" || gesture.pointerId !== event.pointerId) {
        return;
      }
      applyPaneDragPoint(gesture, event.clientX, event.clientY);
    },
    [applyPaneDragPoint],
  );

  const finishPaneDrag = React.useCallback(
    (event: React.PointerEvent<HTMLElement>, cancelled: boolean) => {
      const gesture = gestureRef.current;
      if (gesture?.kind !== "pane" || gesture.pointerId !== event.pointerId) {
        return;
      }
      if (!cancelled) {
        applyPaneDragPoint(gesture, event.clientX, event.clientY);
      }
      if (!gesture.dragStarted) {
        const grip = gesture.grip;
        clearGesture();
        if (!cancelled) grip.focus();
        return;
      }
      const candidate = gesture.lastCandidate;
      const hint = gesture.lastHint;
      const stale = isGestureStale(gesture);
      const sourceTitle = getPaneTitle(gesture.sourcePaneId);
      const targetTitle = getPaneTitle(hint?.targetPaneId ?? null);
      clearGesture();
      if (
        cancelled ||
        stale ||
        candidate === null ||
        hint === null ||
        sameViewportLayout(candidate, gesture.startLayout)
      ) {
        return;
      }
      viewer.viewportActions.commitUserLayout(candidate);
      setAnnouncement(
        hint.region === "center"
          ? "Swapped " + sourceTitle + " with " + targetTitle + "."
          : "Moved " +
              sourceTitle +
              " " +
              hint.region +
              " of " +
              targetTitle +
              ".",
      );
    },
    [
      applyPaneDragPoint,
      clearGesture,
      getPaneTitle,
      isGestureStale,
      viewer.viewportActions,
    ],
  );

  const beginDividerResize = React.useCallback(
    (event: React.PointerEvent<HTMLElement>, divider: DividerGeometry) => {
      if (
        !interactive ||
        event.button !== 0 ||
        gestureRef.current !== null ||
        grid.cellSize <= 0
      ) {
        return;
      }
      const canvas = canvasRef.current;
      if (canvas === null) return;
      const bounds = canvas.getBoundingClientRect();
      const pointerCoordinate =
        divider.direction === "row"
          ? (event.clientX - bounds.left) / grid.cellSize
          : (event.clientY - bounds.top) / grid.cellSize;
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.setPointerCapture(event.pointerId);
      gestureRef.current = {
        kind: "divider",
        pointerId: event.pointerId,
        grip: event.currentTarget,
        startLayout: layout,
        startInteractionEpoch: interactionEpoch,
        grid,
        workspaceWidth: workspaceSize.width,
        workspaceHeight: workspaceSize.height,
        divider,
        pointerOffset: pointerCoordinate - divider.coordinate,
        lastValidLayout: layout,
        lastGridLine: divider.coordinate,
      };
      setGestureView({ kind: "divider", grid, startLayout: layout });
    },
    [grid, interactionEpoch, interactive, layout, workspaceSize],
  );

  const updateDividerResize = React.useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const gesture = gestureRef.current;
      if (
        gesture?.kind !== "divider" ||
        gesture.pointerId !== event.pointerId
      ) {
        return;
      }
      applyDividerPoint(gesture, event.clientX, event.clientY);
    },
    [applyDividerPoint],
  );

  const finishDividerResize = React.useCallback(
    (event: React.PointerEvent<HTMLElement>, cancelled: boolean) => {
      const gesture = gestureRef.current;
      if (
        gesture?.kind !== "divider" ||
        gesture.pointerId !== event.pointerId
      ) {
        return;
      }
      if (!cancelled) {
        applyDividerPoint(gesture, event.clientX, event.clientY);
      }
      const nextLayout = gesture.lastValidLayout;
      const gridLine = gesture.lastGridLine;
      const stale = isGestureStale(gesture);
      const axisName = gesture.divider.direction === "row" ? "column" : "row";
      clearGesture();
      if (
        cancelled ||
        stale ||
        sameViewportLayout(nextLayout, gesture.startLayout)
      ) {
        return;
      }
      viewer.viewportActions.commitUserLayout(nextLayout);
      setAnnouncement(
        "Moved viewport divider to " + axisName + " " + gridLine + ".",
      );
    },
    [applyDividerPoint, clearGesture, isGestureStale, viewer.viewportActions],
  );

  const resizeDividerWithKeyboard = React.useCallback(
    (event: React.KeyboardEvent<HTMLElement>, divider: DividerGeometry) => {
      if (!interactive || gestureRef.current !== null) return;
      const negativeKey = divider.direction === "row" ? "ArrowLeft" : "ArrowUp";
      const positiveKey =
        divider.direction === "row" ? "ArrowRight" : "ArrowDown";
      if (event.key !== negativeKey && event.key !== positiveKey) return;
      event.preventDefault();
      event.stopPropagation();
      const step = event.shiftKey ? 4 : 1;
      const requested =
        divider.coordinate + (event.key === negativeKey ? -step : step);
      const resized = resizeLayoutAtGridLine(layout, divider, requested);
      if (sameViewportLayout(resized.layout, layout)) return;
      viewer.viewportActions.commitUserLayout(resized.layout);
      setAnnouncement(
        "Resized " +
          getPaneTitle(divider.beforePaneId) +
          " and " +
          getPaneTitle(divider.afterPaneId) +
          " at " +
          (divider.direction === "row" ? "column " : "row ") +
          resized.gridLine +
          ".",
      );
    },
    [getPaneTitle, interactive, layout, viewer.viewportActions],
  );

  const swapPaneWithKeyboard = React.useCallback(
    (event: React.KeyboardEvent<HTMLElement>, paneId: string) => {
      const direction = paneMoveDirectionFromKey[event.key];
      if (
        !interactive ||
        !event.shiftKey ||
        direction === undefined ||
        gestureRef.current !== null
      ) {
        return;
      }
      const targetPaneId = directionalPaneTarget(
        geometryRef.current.panes,
        paneId,
        direction,
      );
      if (targetPaneId === null) return;
      event.preventDefault();
      event.stopPropagation();
      const nextLayout = dropViewportPane(
        layout,
        paneId,
        targetPaneId,
        "center",
      );
      if (sameViewportLayout(nextLayout, layout)) return;
      viewer.viewportActions.commitUserLayout(nextLayout);
      setAnnouncement(
        "Swapped " +
          getPaneTitle(paneId) +
          " with " +
          getPaneTitle(targetPaneId) +
          ".",
      );
    },
    [getPaneTitle, interactive, layout, viewer.viewportActions],
  );

  const pristineRootOnly =
    displayLayout.root.type === "pane" &&
    displayLayout.root.pane_id === VIEWPORT_ROOT_PANE_ID;
  const canvasWidth = grid.columns * grid.cellSize;
  const canvasHeight = grid.rows * grid.cellSize;
  // Visibility changes layout, not renderer ownership. In particular an iframe
  // must not reconnect, and a video must not lose its time or manual pause.
  const retainedPaneIds = viewer.useViewport(
    (state) => Object.keys(displayedViewportPage(state)?.panes ?? {}),
    (a, b) => a.length === b.length && a.every((id, index) => id === b[index]),
  );

  return (
    <div
      ref={rootRef}
      data-viewport-workspace
      aria-busy={!interactive}
      style={{
        position: "relative",
        isolation: "isolate",
        width: "100%",
        height: "100%",
        overflowX: "hidden",
        overflowY: "hidden",
        background: "var(--background)",
      }}
    >
      <div
        ref={canvasRef}
        data-viewport-grid-canvas
        inert={!interactive}
        style={{
          position: "relative",
          width: canvasWidth,
          height: canvasHeight,
          minWidth: "100%",
          minHeight: "100%",
          overflow: "hidden",
          background: "var(--border)",
        }}
      >
        {retainedPaneIds.map((paneId) => {
          const rect = geometry.panes[paneId] ?? null;
          return (
            <ViewportPaneHost
              key={`${displayPageId ?? "none"}:${paneId}`}
              pageId={displayPageId}
              paneId={paneId}
              rect={rect}
              cellSize={grid.cellSize}
              geometryTransition={paneGeometryTransition}
              isDragging={dragIndicator?.paneId === paneId}
              motionEnabled={motionEnabled}
              hideChrome={pristineRootOnly || paneId === VIEWPORT_ROOT_PANE_ID}
              onHeaderPointerDown={beginPaneDrag}
              onHeaderPointerMove={updatePaneDrag}
              onHeaderPointerUp={(event) => finishPaneDrag(event, false)}
              onHeaderPointerCancel={(event) => finishPaneDrag(event, true)}
              onHeaderLostPointerCapture={(event) =>
                finishPaneDrag(event, true)
              }
              onHeaderKeyDown={swapPaneWithKeyboard}
            />
          );
        })}

        {geometry.dividers.map((divider) => (
          <ViewportDivider
            key={divider.key}
            divider={divider}
            cellSize={grid.cellSize}
            geometryTransition={paneGeometryTransition}
            beforeTitle={getPaneTitle(divider.beforePaneId)}
            afterTitle={getPaneTitle(divider.afterPaneId)}
            onPointerDown={beginDividerResize}
            onPointerMove={updateDividerResize}
            onPointerUp={(event) => finishDividerResize(event, false)}
            onPointerCancel={(event) => finishDividerResize(event, true)}
            onLostPointerCapture={(event) => finishDividerResize(event, true)}
            onKeyDown={resizeDividerWithKeyboard}
          />
        ))}

        {dropHint !== null && (
          <Card
            data-viewport-drop-hint={
              dropHint.region === "center" ? "swap" : "split"
            }
            className="pointer-events-none z-50"
            style={{
              ...panePositionStyle(dropHint.rect, dropHint.cellSize),
              transition: hintGeometryTransition,
              opacity: 0.75,
            }}
          />
        )}
      </div>

      {dragIndicator !== null && (
        <Card
          size="sm"
          ref={dragIndicatorRef}
          data-viewport-drag-indicator
          data-viewport-pane-id={dragIndicator.paneId}
          aria-hidden="true"
          className="fixed z-1000 w-max max-w-64 pointer-events-none"
          style={{
            left: dragIndicatorLeft(dragIndicatorPositionRef.current.clientX),
            top: dragIndicatorTop(dragIndicatorPositionRef.current.clientY),
            cursor: "grabbing",
          }}
        >
          <CardContent className="truncate">{dragIndicator.title}</CardContent>
        </Card>
      )}

      <div
        aria-live="polite"
        aria-atomic="true"
        style={{
          position: "absolute",
          width: 1,
          height: 1,
          padding: 0,
          margin: -1,
          overflow: "hidden",
          clip: "rect(0, 0, 0, 0)",
          whiteSpace: "nowrap",
          border: 0,
        }}
      >
        {announcement}
      </div>
    </div>
  );
}
