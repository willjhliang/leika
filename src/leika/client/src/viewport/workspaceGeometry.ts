import type { CSSProperties } from "react";
import type { GridRect, GridSpec } from "./gridLayout";
import type { ViewportPane } from "./ViewportState";

/** Where a grid line falls on screen, snapped to a whole pixel.
 *
 * Each axis's cell size is rarely integral, so raw `line * cellSize` puts
 * pane edges and divider lines on fractions of a pixel, which renders as a
 * blurred pair of columns. Every edge goes through here, so two panes that
 * share a grid line still land on the exact same pixel -- no seam, no
 * overlap. */
export function gridLinePx(line: number, cellSize: number): number {
  return Math.round(line * cellSize);
}

export function panePositionStyle(
  rect: GridRect,
  { cellWidth, cellHeight }: GridSpec,
): CSSProperties {
  const left = gridLinePx(rect.x, cellWidth);
  const top = gridLinePx(rect.y, cellHeight);
  return {
    position: "absolute",
    left,
    top,
    // Sized from the far edge rather than the span, so rounding cannot open a
    // gap between neighbours.
    width: gridLinePx(rect.x + rect.width, cellWidth) - left,
    height: gridLinePx(rect.y + rect.height, cellHeight) - top,
    visibility: cellWidth > 0 && cellHeight > 0 ? "visible" : "hidden",
  };
}

export function paneTitle(pane: ViewportPane): string {
  return pane.kind === "root" ? "" : pane.props.title;
}
