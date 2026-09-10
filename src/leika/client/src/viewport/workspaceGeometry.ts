import type { CSSProperties } from "react";
import type { GridRect } from "./gridLayout";
import type { ViewportPane } from "./ViewportState";

/** Where a grid line falls on screen, snapped to a whole pixel.
 *
 * `cellSize` is rarely integral, so raw `line * cellSize` puts pane edges and
 * divider lines on fractions of a pixel, which the compositor renders as a
 * blurred pair of columns. Every edge goes through here, so two panes that
 * share a grid line still land on the exact same pixel -- no seam, no
 * overlap. */
export function gridLinePx(line: number, cellSize: number): number {
  return Math.round(line * cellSize);
}

export function panePositionStyle(
  rect: GridRect,
  cellSize: number,
): CSSProperties {
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

export function paneTitle(pane: ViewportPane): string {
  return pane.kind === "root" ? "" : pane.props.title;
}
