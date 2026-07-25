import {
  ViewportDropRegion,
  ViewportLayout,
  ViewportLayoutNode,
  ViewportLayoutPath,
  ViewportSplitDirection,
  normalizeViewportWeights,
  setViewportSplitWeights,
} from "./layoutModel";

// LCM(2..6): splitting the full width into 2-6 equal panes lands exactly on
// integer grid lines. This exactness assumes the nominal grid; when minimum
// pane sizes force a smaller cell (e.g. very short workspaces), the column
// count stops being a multiple of 60 and equal splits round to the nearest
// grid line instead.
const NOMINAL_GRID_COLUMNS = 60;
const MIN_PANE_COLUMNS = 4;
const MIN_PANE_ROWS = 3;
const DROP_EDGE_FRACTION = 0.25;
export const GRID_EPSILON = 1e-9;

export interface WorkspaceSize {
  width: number;
  height: number;
}

export interface GridRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface GridSpec {
  columns: number;
  rows: number;
  cellSize: number;
}

export interface DividerGeometry {
  key: string;
  path: ViewportLayoutPath;
  dividerIndex: number;
  direction: ViewportSplitDirection;
  nodeRect: GridRect;
  coordinate: number;
  childSpans: number[];
  childMinimums: number[];
  beforePaneId: string;
  afterPaneId: string;
}

export interface LayoutGeometry {
  panes: Record<string, GridRect>;
  dividers: DividerGeometry[];
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function minimumSubtreeSpan(
  node: ViewportLayoutNode,
  axis: ViewportSplitDirection,
): number {
  if (node.type === "pane") {
    return axis === "row" ? MIN_PANE_COLUMNS : MIN_PANE_ROWS;
  }
  const childSpans = node.children.map((child) =>
    minimumSubtreeSpan(child, axis),
  );
  return node.direction === axis
    ? childSpans.reduce((sum, span) => sum + span, 0)
    : Math.max(...childSpans);
}

/** Create a square-cell grid large enough for every layout subtree. */
export function gridSpecForLayout(
  layout: ViewportLayout,
  workspace: WorkspaceSize,
  minimums?: { columns: number; rows: number },
): GridSpec {
  const minimumColumns =
    minimums?.columns ?? minimumSubtreeSpan(layout.root, "row");
  const minimumRows =
    minimums?.rows ?? minimumSubtreeSpan(layout.root, "column");
  if (workspace.width <= 0 || workspace.height <= 0) {
    return {
      columns: Math.max(NOMINAL_GRID_COLUMNS, minimumColumns),
      rows: minimumRows,
      cellSize: 0,
    };
  }
  const cellSize = Math.min(
    workspace.width / NOMINAL_GRID_COLUMNS,
    workspace.width / minimumColumns,
    workspace.height / minimumRows,
  );
  return {
    columns: workspace.width / cellSize,
    rows: workspace.height / cellSize,
    cellSize,
  };
}

function allocateGridSpans(
  total: number,
  weights: readonly unknown[],
  minimums: readonly number[],
): number[] {
  if (minimums.length === 0) return [];
  const minimumTotal = minimums.reduce((sum, span) => sum + span, 0);
  if (total + GRID_EPSILON < minimumTotal) {
    throw new Error("Viewport grid is smaller than its subtree minimum.");
  }

  const normalized = normalizeViewportWeights(weights, minimums.length);
  const spans: number[] = [];
  let consumed = 0;
  let remainingMinimum = minimumTotal;
  let cumulativeWeight = 0;
  for (let index = 0; index < minimums.length - 1; index++) {
    remainingMinimum -= minimums[index];
    cumulativeWeight += normalized[index];
    const idealEnd = Math.round(total * cumulativeWeight);
    const maximumEnd = Math.floor(total - remainingMinimum + GRID_EPSILON);
    const end = clamp(
      idealEnd,
      Math.ceil(consumed + minimums[index]),
      maximumEnd,
    );
    spans.push(end - consumed);
    consumed = end;
  }
  spans.push(total - consumed);
  return spans;
}

function firstPaneId(node: ViewportLayoutNode): string {
  return node.type === "pane" ? node.pane_id : firstPaneId(node.children[0]);
}

function dividerKey(path: ViewportLayoutPath, dividerIndex: number): string {
  return path.join(".") + ":" + dividerIndex;
}

/** Resolve layout weights to integer internal grid lines and pane rectangles. */
export function computeLayoutGeometry(
  root: ViewportLayoutNode,
  columns: number,
  rows: number,
): LayoutGeometry {
  const panes = Object.create(null) as Record<string, GridRect>;
  const dividers: DividerGeometry[] = [];

  const visit = (
    node: ViewportLayoutNode,
    rect: GridRect,
    path: number[],
  ): void => {
    if (node.type === "pane") {
      panes[node.pane_id] = rect;
      return;
    }

    const total = node.direction === "row" ? rect.width : rect.height;
    const minimums = node.children.map((child) =>
      minimumSubtreeSpan(child, node.direction),
    );
    const spans = allocateGridSpans(total, node.weights, minimums);
    let offset = node.direction === "row" ? rect.x : rect.y;
    node.children.forEach((child, index) => {
      const childRect =
        node.direction === "row"
          ? {
              x: offset,
              y: rect.y,
              width: spans[index],
              height: rect.height,
            }
          : {
              x: rect.x,
              y: offset,
              width: rect.width,
              height: spans[index],
            };
      visit(child, childRect, [...path, index]);
      offset += spans[index];
      if (index < node.children.length - 1) {
        dividers.push({
          key: dividerKey(path, index),
          path,
          dividerIndex: index,
          direction: node.direction,
          nodeRect: rect,
          coordinate: offset,
          childSpans: spans,
          childMinimums: minimums,
          beforePaneId: firstPaneId(node.children[index]),
          afterPaneId: firstPaneId(node.children[index + 1]),
        });
      }
    });
  };

  visit(root, { x: 0, y: 0, width: columns, height: rows }, []);
  return { panes, dividers };
}

export function pointInsidePane(rect: GridRect, x: number, y: number): boolean {
  return (
    x >= rect.x &&
    x < rect.x + rect.width &&
    y >= rect.y &&
    y < rect.y + rect.height
  );
}

export function dropRegionForPoint(
  rect: GridRect,
  x: number,
  y: number,
): ViewportDropRegion {
  const relativeX = (x - rect.x) / rect.width;
  const relativeY = (y - rect.y) / rect.height;
  const candidates: {
    region: Exclude<ViewportDropRegion, "center">;
    score: number;
  }[] = [];
  if (relativeX < DROP_EDGE_FRACTION) {
    candidates.push({ region: "left", score: relativeX });
  }
  if (relativeX > 1 - DROP_EDGE_FRACTION) {
    candidates.push({ region: "right", score: 1 - relativeX });
  }
  if (relativeY < DROP_EDGE_FRACTION) {
    candidates.push({ region: "top", score: relativeY });
  }
  if (relativeY > 1 - DROP_EDGE_FRACTION) {
    candidates.push({ region: "bottom", score: 1 - relativeY });
  }
  candidates.sort((left, right) => left.score - right.score);
  return candidates[0]?.region ?? "center";
}

export function directionalPaneTarget(
  panes: Record<string, GridRect>,
  sourcePaneId: string,
  direction: "left" | "right" | "top" | "bottom",
): string | null {
  const source = panes[sourcePaneId];
  if (source === undefined) return null;
  const sourceX = source.x + source.width / 2;
  const sourceY = source.y + source.height / 2;
  const horizontal = direction === "left" || direction === "right";
  const sign = direction === "left" || direction === "top" ? -1 : 1;
  const candidates = Object.entries(panes).flatMap(([paneId, rect]) => {
    if (paneId === sourcePaneId) return [];
    const deltaX = rect.x + rect.width / 2 - sourceX;
    const deltaY = rect.y + rect.height / 2 - sourceY;
    const primary = (horizontal ? deltaX : deltaY) * sign;
    if (primary <= 0) return [];
    const cross = horizontal ? deltaY : deltaX;
    return [{ paneId, distance: primary * primary + cross * cross }];
  });
  candidates.sort(
    (left, right) =>
      left.distance - right.distance || left.paneId.localeCompare(right.paneId),
  );
  return candidates[0]?.paneId ?? null;
}

/** Move a divider to an integer grid line while respecting subtree minima. */
export function resizeLayoutAtGridLine(
  layout: ViewportLayout,
  divider: DividerGeometry,
  requestedGridLine: number,
): { layout: ViewportLayout; gridLine: number } {
  const index = divider.dividerIndex;
  const childStart = divider.coordinate - divider.childSpans[index];
  const childEnd = divider.coordinate + divider.childSpans[index + 1];
  const minimum = Math.ceil(
    childStart + divider.childMinimums[index] - GRID_EPSILON,
  );
  const maximum = Math.floor(
    childEnd - divider.childMinimums[index + 1] + GRID_EPSILON,
  );
  const gridLine = clamp(requestedGridLine, minimum, maximum);
  if (gridLine === divider.coordinate) return { layout, gridLine };
  const spans = [...divider.childSpans];
  const delta = gridLine - divider.coordinate;
  spans[index] += delta;
  spans[index + 1] -= delta;
  return {
    layout: setViewportSplitWeights(layout, divider.path, spans),
    gridLine,
  };
}
