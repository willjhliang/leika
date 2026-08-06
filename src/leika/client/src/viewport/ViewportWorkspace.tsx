import React from "react";

import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Separator } from "../components/ui/separator";
import { cn } from "../lib/utils";

import { IMAGE_FIT_OBJECT_FIT } from "../ClientSettings";
import { guiLabelClassName } from "../components/guiLabelStyles";
import { getPlotly, plotlyReady, PlotlyGlobal } from "../plotlyReady";
import { ViewerContext } from "../ViewerContext";
import { motionExceedsThreshold } from "../dragUtils";
import { prefersReducedMotion } from "../utils/motion";
import { useColorScheme } from "../hooks/useColorScheme";
import { useElementSize } from "../hooks/useElementSize";
import {
  VIEWPORT_ROOT_PANE_ID,
  ViewportDropRegion,
  ViewportLayout,
  collectViewportPaneIds,
  dropViewportPane,
  sameViewportLayout,
} from "./layoutModel";
import {
  GRID_EPSILON,
  DividerGeometry,
  GridRect,
  GridSpec,
  LayoutGeometry,
  WorkspaceSize,
  computeLayoutGeometry,
  directionalPaneTarget,
  dropRegionForPoint,
  gridSpecForLayout,
  pointInsidePane,
  resizeLayoutAtGridLine,
} from "./gridLayout";

import { Spinner } from "../components/ui/spinner";
import {
  ViewportImagePane,
  ViewportMatplotlibPane,
  ViewportPane,
  ViewportPlotlyPane,
  ViewportViserPane,
} from "./ViewportState";

/** The pane title bar matches the dock's 24px label rows. A constant rather
 * than a class so the content offset below an in-flow bar cannot drift from
 * the bar's own height. */
const PANE_TITLE_BAR_PX = 24;
const DIVIDER_HIT_SIZE_PX = 24;
/** One pixel, which cannot straddle a grid line: it comes out of the pane
 * after the line rather than being split across both. Centring it instead
 * would put it on a half pixel, which renders as a blurred pair of columns --
 * worse than the slight asymmetry. */
const DIVIDER_LINE_SIZE_PX = 1;
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

/** Where a grid line falls on screen, snapped to a whole pixel.
 *
 * `cellSize` is rarely integral, so raw `line * cellSize` puts pane edges and
 * divider lines on fractions of a pixel, which the compositor renders as a
 * blurred pair of columns. Every edge goes through here, so two panes that
 * share a grid line still land on the exact same pixel -- no seam, no
 * overlap. */
function gridLinePx(line: number, cellSize: number): number {
  return Math.round(line * cellSize);
}

function panePositionStyle(
  rect: GridRect,
  cellSize: number,
): React.CSSProperties {
  const left = gridLinePx(rect.x, cellSize);
  const top = gridLinePx(rect.y, cellSize);
  return {
    position: "absolute",
    left,
    top,
    // Sized from the far edge rather than the span, so rounding cannot open a
    // gap between neighbours.
    width: gridLinePx(rect.x + rect.width, cellSize) - left,
    height: gridLinePx(rect.y + rect.height, cellSize) - top,
    visibility: cellSize > 0 ? "visible" : "hidden",
  };
}

function paneTitle(pane: ViewportPane): string {
  return pane.kind === "root" ? "" : pane.props.title;
}

/** Auto-filling split workspace for native image, matplotlib, Plotly, and
 * viser panes. */
export function ViewportWorkspace() {
  const viewer = React.useContext(ViewerContext)!;
  const layout = viewer.useViewport((state) => state.layout);
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
      const pane = viewer.useViewport.get().panes[paneId];
      return pane === undefined ? "viewport pane" : paneTitle(pane);
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
    [getPaneTitle, positionDragIndicator],
  );

  const applyDividerPoint = React.useCallback(
    (gesture: DividerGesture, clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
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
    [],
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
      (!sameViewportLayout(gesture.startLayout, layout) ||
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
    [grid, interactionEpoch, layout, workspaceSize],
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
      const currentViewport = viewer.useViewport.get();
      const stale =
        currentViewport.interactionEpoch !== gesture.startInteractionEpoch ||
        !sameViewportLayout(currentViewport.layout, gesture.startLayout);
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
      viewer.viewportActions,
      viewer.useViewport,
    ],
  );

  const beginDividerResize = React.useCallback(
    (event: React.PointerEvent<HTMLElement>, divider: DividerGeometry) => {
      if (
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
    [grid, interactionEpoch, layout, workspaceSize],
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
      const currentViewport = viewer.useViewport.get();
      const stale =
        currentViewport.interactionEpoch !== gesture.startInteractionEpoch ||
        !sameViewportLayout(currentViewport.layout, gesture.startLayout);
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
    [
      applyDividerPoint,
      clearGesture,
      viewer.viewportActions,
      viewer.useViewport,
    ],
  );

  const resizeDividerWithKeyboard = React.useCallback(
    (event: React.KeyboardEvent<HTMLElement>, divider: DividerGeometry) => {
      if (gestureRef.current !== null) return;
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
    [getPaneTitle, layout, viewer.viewportActions],
  );

  const swapPaneWithKeyboard = React.useCallback(
    (event: React.KeyboardEvent<HTMLElement>, paneId: string) => {
      const direction = paneMoveDirectionFromKey[event.key];
      if (
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
    [getPaneTitle, layout, viewer.viewportActions],
  );

  const pristineRootOnly =
    displayLayout.root.type === "pane" &&
    displayLayout.root.pane_id === VIEWPORT_ROOT_PANE_ID;
  const canvasWidth = grid.columns * grid.cellSize;
  const canvasHeight = grid.rows * grid.cellSize;
  const visiblePaneIds = collectViewportPaneIds(displayLayout);

  return (
    <div
      ref={rootRef}
      data-viewport-workspace
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
        {visiblePaneIds.map((paneId) => {
          const rect = geometry.panes[paneId] ?? null;
          if (rect === null && paneId !== VIEWPORT_ROOT_PANE_ID) {
            return null;
          }
          return (
            <ViewportPaneHost
              key={paneId}
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

function ViewportPaneHost({
  paneId,
  rect,
  cellSize,
  geometryTransition,
  isDragging,
  motionEnabled,
  hideChrome,
  onHeaderPointerDown,
  onHeaderPointerMove,
  onHeaderPointerUp,
  onHeaderPointerCancel,
  onHeaderLostPointerCapture,
  onHeaderKeyDown,
}: {
  paneId: string;
  rect: GridRect | null;
  cellSize: number;
  geometryTransition: string | undefined;
  isDragging: boolean;
  motionEnabled: boolean;
  hideChrome: boolean;
  onHeaderPointerDown: (
    event: React.PointerEvent<HTMLElement>,
    paneId: string,
  ) => void;
  onHeaderPointerMove: (event: React.PointerEvent<HTMLElement>) => void;
  onHeaderPointerUp: (event: React.PointerEvent<HTMLElement>) => void;
  onHeaderPointerCancel: (event: React.PointerEvent<HTMLElement>) => void;
  onHeaderLostPointerCapture: (event: React.PointerEvent<HTMLElement>) => void;
  onHeaderKeyDown: (
    event: React.KeyboardEvent<HTMLElement>,
    paneId: string,
  ) => void;
}) {
  const viewer = React.useContext(ViewerContext)!;
  const pane = viewer.useViewport((state) => state.panes[paneId]);
  const showPaneTitles = viewer.useSettings((state) => state.showPaneTitles);
  const [isHovered, setIsHovered] = React.useState(false);
  // Keyboard users can focus the header without hovering; keep it visible.
  const [isFocused, setIsFocused] = React.useState(false);
  if (pane === undefined) return null;

  const isHiddenRootHost = rect === null;
  const title = paneTitle(pane);
  const hasTitleBar = !hideChrome && !isHiddenRootHost;
  return (
    <Card
      data-viewport-pane={isHiddenRootHost ? undefined : paneId}
      role="region"
      aria-hidden={isHiddenRootHost || undefined}
      className={cn(
        // Panes tile the canvas edge to edge, so they get neither rounding nor
        // a ring: Card's ring is drawn OUTSIDE its box, which put every pane's
        // outline a pixel into its neighbour instead of on its own edge, and
        // rounded corners let the canvas show through at each junction. The
        // divider owns the seam line; the canvas owns the colour behind it.
        "isolate min-h-0 min-w-0 overflow-hidden rounded-none ring-0",
        (hideChrome || isHiddenRootHost) && "gap-0 bg-background py-0",
      )}
      style={{
        ...(isHiddenRootHost
          ? {
              position: "absolute" as const,
              left: 0,
              top: 0,
              width: 1,
              height: 1,
              visibility: "hidden" as const,
              pointerEvents: "none" as const,
            }
          : panePositionStyle(rect, cellSize)),
        minWidth: 0,
        minHeight: 0,
        transition: isHiddenRootHost ? undefined : geometryTransition,
      }}
    >
      <div
        data-viewport-pane-content={paneId}
        style={{
          position: "absolute",
          inset: 0,
          // With titles on, the bar is a real top bar and the content starts
          // beneath it; off, the bar overlays the content instead.
          top: hasTitleBar && showPaneTitles ? PANE_TITLE_BAR_PX : 0,
          minWidth: 0,
          minHeight: 0,
          overflow: "hidden",
        }}
      >
        <ViewportPaneRenderer pane={pane} />
      </div>

      {hasTitleBar && (
        <button
          type="button"
          data-viewport-pane-header={paneId}
          data-viewport-pane-title={paneId}
          title={title}
          aria-label={
            "Drag " +
            title +
            " onto another pane: its center swaps, and an edge splits. Shift plus arrow keys swap directionally."
          }
          onPointerDown={(event) => onHeaderPointerDown(event, paneId)}
          tabIndex={0}
          aria-keyshortcuts="Shift+ArrowLeft Shift+ArrowRight Shift+ArrowUp Shift+ArrowDown"
          aria-roledescription="movable split pane"
          onKeyDown={(event) => onHeaderKeyDown(event, paneId)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          // Hover tracks the bar itself, not the whole pane: when titles are
          // hidden, only a pointer over the strip the bar occupies reveals it.
          onPointerEnter={() => setIsHovered(true)}
          onPointerLeave={() => setIsHovered(false)}
          onPointerMove={onHeaderPointerMove}
          onPointerUp={onHeaderPointerUp}
          onPointerCancel={onHeaderPointerCancel}
          onLostPointerCapture={onHeaderLostPointerCapture}
          // Dock chrome on a pane: the dock's card surface, square corners
          // (every corner of the bar sits on a pane seam), and the muted
          // field-label type the dock's rows use. Focus is border-only, like
          // every other control.
          className={cn(
            "absolute inset-x-0 top-0 z-20 flex items-center rounded-none border border-transparent bg-card px-2 text-sm outline-none select-none focus-visible:border-ring",
            guiLabelClassName,
          )}
          style={{
            height: PANE_TITLE_BAR_PX,
            // A drag still hides it whatever the setting says: the header is
            // the thing being dragged, and the drag preview stands in for it.
            opacity:
              (showPaneTitles || isHovered || isFocused) && !isDragging ? 1 : 0,
            transition: motionEnabled ? "opacity 250ms ease-in-out" : undefined,
            cursor: isDragging ? "grabbing" : "grab",
            touchAction: "none",
          }}
        >
          <span className="truncate">{title}</span>
        </button>
      )}
    </Card>
  );
}

function ViewportDivider({
  divider,
  cellSize,
  geometryTransition,
  beforeTitle,
  afterTitle,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onLostPointerCapture,
  onKeyDown,
}: {
  divider: DividerGeometry;
  cellSize: number;
  geometryTransition: string | undefined;
  beforeTitle: string;
  afterTitle: string;
  onPointerDown: (
    event: React.PointerEvent<HTMLElement>,
    divider: DividerGeometry,
  ) => void;
  onPointerMove: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: React.PointerEvent<HTMLElement>) => void;
  onPointerCancel: (event: React.PointerEvent<HTMLElement>) => void;
  onLostPointerCapture: (event: React.PointerEvent<HTMLElement>) => void;
  onKeyDown: (
    event: React.KeyboardEvent<HTMLElement>,
    divider: DividerGeometry,
  ) => void;
}) {
  const vertical = divider.direction === "row";
  const index = divider.dividerIndex;
  const minimum = Math.ceil(
    divider.coordinate -
      divider.childSpans[index] +
      divider.childMinimums[index] -
      GRID_EPSILON,
  );
  const maximum = Math.floor(
    divider.coordinate +
      divider.childSpans[index + 1] -
      divider.childMinimums[index + 1] +
      GRID_EPSILON,
  );
  const lineStyle: React.CSSProperties = {
    position: "absolute",
    // On the grid line, not centred in the hit area: the hit area is an even
    // 24px, so centring a 1px line inside it lands on a half pixel.
    left: vertical ? DIVIDER_HIT_SIZE_PX / 2 : 0,
    top: vertical ? 0 : DIVIDER_HIT_SIZE_PX / 2,
    width: vertical ? DIVIDER_LINE_SIZE_PX : "100%",
    height: vertical ? "100%" : DIVIDER_LINE_SIZE_PX,
    pointerEvents: "none",
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      role="separator"
      data-viewport-divider={divider.key}
      data-viewport-divider-direction={divider.direction}
      aria-label={"Resize " + beforeTitle + " and " + afterTitle + " panes"}
      aria-orientation={vertical ? "vertical" : "horizontal"}
      aria-valuemin={minimum}
      aria-valuemax={maximum}
      aria-valuenow={divider.coordinate}
      aria-valuetext={(vertical ? "column " : "row ") + divider.coordinate}
      aria-keyshortcuts={
        vertical
          ? "ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight"
          : "ArrowUp ArrowDown Shift+ArrowUp Shift+ArrowDown"
      }
      onPointerDown={(event) => onPointerDown(event, divider)}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onLostPointerCapture={onLostPointerCapture}
      onKeyDown={(event) => onKeyDown(event, divider)}
      // An invisible 24px grab strip. It drops Button's transparent border,
      // because the line inside is positioned against the PADDING box and that
      // 1px border offset it from the grid line and trimmed both ends. The
      // ghost variant's hover fill is dropped too: hovering recolours the
      // divider itself rather than painting a band the width of the strip.
      //
      // Crossing dividers overlap by a pixel, and the one painted last wins.
      // Raising the active one keeps its highlight unbroken along its whole
      // length instead of notched wherever another divider crosses it. The
      // z-index lives here rather than in `style` so the hover variant can
      // reach it; inline styles would outrank it.
      className="group/divider z-30 border-0 hover:z-40 hover:bg-transparent focus-visible:z-40 dark:hover:bg-transparent"
      style={{
        position: "absolute",
        left: vertical
          ? gridLinePx(divider.coordinate, cellSize) - DIVIDER_HIT_SIZE_PX / 2
          : gridLinePx(divider.nodeRect.x, cellSize),
        top: vertical
          ? gridLinePx(divider.nodeRect.y, cellSize)
          : gridLinePx(divider.coordinate, cellSize) - DIVIDER_HIT_SIZE_PX / 2,
        width: vertical
          ? DIVIDER_HIT_SIZE_PX
          : gridLinePx(divider.nodeRect.x + divider.nodeRect.width, cellSize) -
            gridLinePx(divider.nodeRect.x, cellSize),
        height: vertical
          ? gridLinePx(divider.nodeRect.y + divider.nodeRect.height, cellSize) -
            gridLinePx(divider.nodeRect.y, cellSize)
          : DIVIDER_HIT_SIZE_PX,
        cursor: vertical ? "col-resize" : "row-resize",
        touchAction: "none",
        transition: geometryTransition,
      }}
    >
      {/* Backdrop and line share one rect: the line's tokens are translucent
          in dark mode, so without an opaque layer beneath it the divider would
          tint whatever pane content sits behind it and read as a different
          colour over every pane. Two elements rather than stacking the token
          as a background image over a background colour, because only
          background-COLOR can transition. */}
      <span aria-hidden="true" className="bg-background" style={lineStyle} />
      <Separator
        aria-hidden="true"
        orientation={vertical ? "vertical" : "horizontal"}
        // The same two tokens an input's border uses: `--input` at rest,
        // `--ring` once the divider is hovered or focused. Keyboard resizing
        // needs the focus half, since the strip itself draws nothing.
        className="bg-input transition-colors group-hover/divider:bg-ring group-focus-visible/divider:bg-ring"
        style={lineStyle}
      />
    </Button>
  );
}

function ViewportPaneRenderer({ pane }: { pane: ViewportPane }) {
  switch (pane.kind) {
    case "root":
      return null;
    case "image":
      return <ViewportImageRenderer pane={pane} />;
    case "matplotlib":
      return <ViewportMatplotlibRenderer pane={pane} />;
    case "plotly":
      return <ViewportPlotlyRenderer pane={pane} />;
    case "viser":
      return <ViewportViserRenderer pane={pane} />;
  }
}

/** Static matplotlib figure, relayed as SVG.
 *
 * Rendered through an `img` rather than inlined into the document: SVG can
 * carry script, and an image context cannot run it. Vector scales for free,
 * so a pane resize needs no redraw in Python. */
function ViewportMatplotlibRenderer({
  pane,
}: {
  pane: ViewportMatplotlibPane;
}) {
  const [objectUrl, setObjectUrl] = React.useState<string | null>(null);
  React.useEffect(() => {
    const url = URL.createObjectURL(
      new Blob([pane.props._svg], { type: "image/svg+xml" }),
    );
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [pane.props._svg]);

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "var(--background)",
      }}
    >
      {objectUrl === null ? null : (
        <img
          src={objectUrl}
          alt={pane.props.title}
          draggable={false}
          style={{
            display: "block",
            width: "100%",
            height: "100%",
            // The figure keeps the proportions it was composed with.
            objectFit: "contain",
          }}
        />
      )}
    </div>
  );
}

/** Interactive Plotly renderer that always fills its pane, tracking pane
 * resizes via ResizeObserver. */
function ViewportPlotlyRenderer({ pane }: { pane: ViewportPlotlyPane }) {
  const { ref, width, height } = useElementSize();
  // Figures without an explicit template follow Leika theme, which can
  // change at runtime (server-configured, URL-forced, or auto-detected).
  const colorScheme = useColorScheme();
  // Used to imperatively call ``Plotly.react``, matching the control-panel
  // Plotly component (see components/PlotlyComponent.tsx).
  const plotRef = React.useRef<HTMLDivElement>(null);

  const themeTemplates = React.useMemo(
    () =>
      pane.props._theme_templates === ""
        ? null
        : JSON.parse(pane.props._theme_templates),
    [pane.props._theme_templates],
  );

  // Parse JSON only when the figure changes; resizes reuse the parsed value.
  const plotJson = React.useMemo(() => {
    if (pane.props._plotly_json_str === "") return null;
    const parsed = JSON.parse(pane.props._plotly_json_str);
    // Keep zoom/selection state across figure updates, see
    // https://plotly.com/javascript/uirevision/.
    parsed.layout = { ...parsed.layout, uirevision: "true" };
    return parsed;
  }, [pane.props._plotly_json_str]);

  const layoutTemplate =
    plotJson?.layout?.template ??
    (themeTemplates === null
      ? undefined
      : (themeTemplates[colorScheme] ?? themeTemplates.light));

  const [plotlyMissing, setPlotlyMissing] = React.useState(false);
  React.useEffect(() => {
    if (plotJson === null || width === 0 || height === 0) return;
    // Plotly is loaded globally by a RunJavascriptMessage that the server
    // queues before any Plotly pane; a render that races it waits on the
    // ready promise. If it never arrives (blocked or failed eval), show a
    // fallback rather than a blank pane.
    let cancelled = false;
    const render = (plotly: PlotlyGlobal) => {
      if (cancelled || plotRef.current === null) return;
      setPlotlyMissing(false);
      // A malformed figure must not take down the workspace; Plotly.react
      // reports errors both synchronously and as a rejected promise.
      try {
        Promise.resolve(
          plotly.react(
            plotRef.current,
            plotJson.data,
            {
              ...plotJson.layout,
              template: layoutTemplate,
              width,
              height,
              autosize: false,
            },
            plotJson.config,
          ),
        ).catch((error) => console.error("Plotly render failed:", error));
      } catch (error) {
        console.error("Plotly render failed:", error);
      }
    };
    plotlyReady.then((plotly) => {
      if (!cancelled) render(plotly);
    });
    const fallback = window.setTimeout(() => {
      if (!cancelled && getPlotly() === undefined) setPlotlyMissing(true);
    }, 10_000);
    return () => {
      cancelled = true;
      clearTimeout(fallback);
    };
  }, [plotJson, layoutTemplate, width, height]);

  // Purge the Plotly instance on unmount so event listeners and (for gl
  // traces) WebGL contexts don't leak each time a pane is removed.
  React.useEffect(() => {
    const node = plotRef.current;
    return () => {
      const plotly = getPlotly();
      if (node !== null && plotly !== undefined) {
        plotly.purge(node);
      }
    };
  }, []);

  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "var(--background)",
      }}
    >
      <div ref={plotRef} />
      {plotlyMissing ? (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--muted-foreground)",
            fontSize: "var(--text-sm)",
          }}
        >
          Plotly failed to load.
        </div>
      ) : null}
    </div>
  );
}

/** Live viser scene embed: viser's own client in an iframe. The iframe is
 * keyed by its resolved URL, so re-pointing the pane — and flipping Leika's
 * theme, which changes the darkMode parameter — remounts it, resetting the
 * scene connection and camera state rather than navigating in place. */
function ViewportViserRenderer({ pane }: { pane: ViewportViserPane }) {
  // Viser renders the darkMode URL flag, so the embed follows Leika's theme.
  const colorScheme = useColorScheme();
  const src = React.useMemo(() => {
    // Port-based targets connect to the viser server on whatever hostname
    // this page was loaded from; the Python-side host is unusable because
    // viser binds 0.0.0.0. URL targets are used near-verbatim (new URL()
    // normalizes, e.g. adding a trailing slash).
    const base =
      pane.props._url !== null
        ? pane.props._url
        : `${window.location.protocol}//${window.location.hostname}:${pane.props._port}/`;
    try {
      // Viser's darkMode flag is presence-based, so following Leika's theme
      // means removing it as well as adding it.
      const url = new URL(base);
      if (colorScheme === "dark") url.searchParams.set("darkMode", "");
      else url.searchParams.delete("darkMode");
      return url.toString();
    } catch {
      // Python's URL validation is looser than the browser's; a string the
      // browser cannot parse must not take down the workspace. As a plain
      // iframe src it just fails to load, minus theme forwarding.
      return base;
    }
  }, [pane.props._url, pane.props._port, colorScheme]);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "var(--background)",
      }}
    >
      <ViewportViserFrame key={src} src={src} title={pane.props.title} />
    </div>
  );
}

function ViewportViserFrame({ src, title }: { src: string; title: string }) {
  const [loaded, setLoaded] = React.useState(false);
  return (
    <>
      {/* No sandbox: viser's client needs scripts, web workers, and
       * same-origin storage. Cross-origin frames emit load for error pages
       * too and no signal at all for network failures, so the overlay below
       * is best-effort: it clears on load and otherwise stays. */}
      <iframe
        src={src}
        title={title}
        referrerPolicy="strict-origin-when-cross-origin"
        allow="fullscreen; clipboard-write"
        onLoad={() => setLoaded(true)}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          border: 0,
          display: "block",
          background: "var(--background)",
        }}
      />
      {loaded ? null : (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "0.5rem",
            color: "var(--muted-foreground)",
            fontSize: "var(--text-sm)",
            background: "var(--background)",
          }}
        >
          <Spinner />
          Loading viser…
        </div>
      )}
    </>
  );
}

function ViewportImageRenderer({ pane }: { pane: ViewportImagePane }) {
  const viewer = React.useContext(ViewerContext)!;
  // An app that named a fit meant it; one that did not leaves the choice to
  // whoever is looking at the image.
  const preferredFit = viewer.useSettings((state) => state.imageFit);
  const fit = IMAGE_FIT_OBJECT_FIT[pane.props.fit ?? preferredFit];
  const [objectUrl, setObjectUrl] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (pane.props._data === null) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(
      new Blob([pane.props._data], { type: "image/" + pane.props._format }),
    );
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [pane.props._data, pane.props._format]);

  if (objectUrl === null) {
    return (
      <span
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          alignItems: "center",
          justifyContent: "center",
          background: "#000",
          color: "#888",
          fontSize: "var(--text-sm)",
        }}
      >
        No image
      </span>
    );
  }

  return (
    <img
      src={objectUrl}
      alt={pane.props.title}
      draggable={false}
      style={{
        display: "block",
        width: "100%",
        height: "100%",
        objectFit: fit,
        userSelect: "none",
        background: "#000",
      }}
    />
  );
}
