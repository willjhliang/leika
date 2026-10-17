import { describe, expect, it } from "vitest";

import { ViewportLayout } from "./layoutModel";
import { panePositionStyle } from "./workspaceGeometry";
import {
  computeLayoutGeometry,
  directionalPaneTarget,
  dropRegionForPoint,
  gridSpecForLayout,
  resizeLayoutAtGridLine,
} from "./gridLayout";

const nestedLayout: ViewportLayout = {
  version: 1,
  root: {
    type: "split",
    direction: "row",
    children: [
      { type: "pane", pane_id: "primary" },
      {
        type: "split",
        direction: "column",
        children: [
          { type: "pane", pane_id: "video" },
          { type: "pane", pane_id: "plot" },
        ],
        weights: [0.5, 0.5],
      },
    ],
    weights: [0.5, 0.5],
  },
};

describe("viewport 60 x 60 grid geometry", () => {
  it.each([
    { width: 960, height: 700 },
    { width: 1920, height: 10 },
  ])("keeps exact halves in a $width x $height workspace", (workspace) => {
    const grid = gridSpecForLayout(nestedLayout, workspace);
    expect(grid).toEqual({
      columns: 60,
      rows: 60,
      cellWidth: workspace.width / 60,
      cellHeight: workspace.height / 60,
    });

    const geometry = computeLayoutGeometry(
      nestedLayout.root,
      grid.columns,
      grid.rows,
    );
    expect(geometry.panes.video).toEqual({
      x: 30,
      y: 0,
      width: 30,
      height: 30,
    });
    expect(
      geometry.dividers.every((divider) =>
        Number.isInteger(divider.coordinate),
      ),
    ).toBe(true);
    expect(panePositionStyle(geometry.panes.video, grid)).toMatchObject({
      left: workspace.width / 2,
      top: 0,
      width: workspace.width / 2,
      height: workspace.height / 2,
    });
    expect(panePositionStyle(geometry.panes.plot, grid)).toMatchObject({
      left: workspace.width / 2,
      top: workspace.height / 2,
      width: workspace.width / 2,
      height: workspace.height / 2,
    });
  });

  describe.each(["row", "column"] as const)("%s splits", (direction) => {
    it("splits the full axis into three equal panes", () => {
      const paneCount = 3;
      const layout: ViewportLayout = {
        version: 1,
        root: {
          type: "split",
          direction,
          children: Array.from({ length: paneCount }, (_, index) => ({
            type: "pane" as const,
            pane_id: `pane-${index}`,
          })),
          weights: Array.from({ length: paneCount }, () => 1 / paneCount),
        },
      };
      const grid = gridSpecForLayout(layout, { width: 1920, height: 1080 });
      expect(grid.columns).toBe(60);
      expect(grid.rows).toBe(60);
      const geometry = computeLayoutGeometry(
        layout.root,
        grid.columns,
        grid.rows,
      );
      const spans = Object.values(geometry.panes).map((rect) =>
        direction === "row" ? rect.width : rect.height,
      );
      expect(spans).toEqual(
        Array.from({ length: paneCount }, () => 60 / paneCount),
      );
      expect(
        geometry.dividers.every((divider) =>
          Number.isInteger(divider.coordinate),
        ),
      ).toBe(true);
    });

    it("preserves minimum pane sizes in dense layouts", () => {
      const layout: ViewportLayout = {
        version: 1,
        root: {
          type: "split",
          direction,
          children: Array.from({ length: 21 }, (_, index) => ({
            type: "pane",
            pane_id: `pane-${index}`,
          })),
          weights: Array.from({ length: 21 }, () => 1 / 21),
        },
      };
      const grid = gridSpecForLayout(layout, { width: 960, height: 700 });
      expect(grid.columns).toBe(direction === "row" ? 120 : 60);
      expect(grid.rows).toBe(direction === "column" ? 120 : 60);
      const geometry = computeLayoutGeometry(
        layout.root,
        grid.columns,
        grid.rows,
      );
      for (const rect of Object.values(geometry.panes)) {
        expect(rect.width).toBeGreaterThanOrEqual(4);
        expect(rect.height).toBeGreaterThanOrEqual(3);
      }
      const lastPane = panePositionStyle(geometry.panes["pane-20"], grid);
      expect(Number(lastPane.left) + Number(lastPane.width)).toBe(960);
      expect(Number(lastPane.top) + Number(lastPane.height)).toBe(700);
    });
  });

  it.each([
    { width: 0, height: 700 },
    { width: 960, height: 0 },
  ])("hides unmeasured workspaces ($width x $height)", (workspace) => {
    const grid = gridSpecForLayout(nestedLayout, workspace);
    expect(grid).toEqual({
      columns: 60,
      rows: 60,
      cellWidth: 0,
      cellHeight: 0,
    });
    expect(
      panePositionStyle({ x: 0, y: 0, width: 60, height: 60 }, grid).visibility,
    ).toBe("hidden");
  });

  it("rounds shared pane edges to the same pixel on both axes", () => {
    const grid = gridSpecForLayout(nestedLayout, { width: 961, height: 701 });
    const { panes } = computeLayoutGeometry(
      nestedLayout.root,
      grid.columns,
      grid.rows,
    );
    const primary = panePositionStyle(panes.primary, grid);
    const video = panePositionStyle(panes.video, grid);
    const plot = panePositionStyle(panes.plot, grid);
    expect(primary.width).toBe(video.left);
    expect(video.left).toBe(plot.left);
    expect(video.height).toBe(plot.top);
    expect(Number(plot.left) + Number(plot.width)).toBe(961);
    expect(Number(plot.top) + Number(plot.height)).toBe(701);
    for (const rect of [primary, video, plot]) {
      for (const value of [rect.left, rect.top, rect.width, rect.height]) {
        expect(Number.isInteger(value)).toBe(true);
      }
    }
  });

  it("snaps divider updates to grid lines and clamps subtree minima", () => {
    const grid = gridSpecForLayout(nestedLayout, {
      width: 960,
      height: 576,
    });
    const geometry = computeLayoutGeometry(
      nestedLayout.root,
      grid.columns,
      grid.rows,
    );
    const rootDivider = geometry.dividers.find(
      (divider) => divider.direction === "row",
    )!;

    const moved = resizeLayoutAtGridLine(nestedLayout, rootDivider, 20);
    expect(moved.gridLine).toBe(20);
    expect(moved.layout.root).toMatchObject({ weights: [20 / 60, 40 / 60] });

    const clamped = resizeLayoutAtGridLine(nestedLayout, rootDivider, -100);
    expect(clamped.gridLine).toBe(4);
  });

  it("classifies edge and center pane drops", () => {
    const rect = { x: 10, y: 20, width: 40, height: 20 };
    expect(dropRegionForPoint(rect, 11, 30)).toBe("left");
    expect(dropRegionForPoint(rect, 49, 30)).toBe("right");
    expect(dropRegionForPoint(rect, 30, 21)).toBe("top");
    expect(dropRegionForPoint(rect, 30, 39)).toBe("bottom");
    expect(dropRegionForPoint(rect, 30, 30)).toBe("center");
  });

  it("chooses deterministic directional keyboard targets", () => {
    const panes = {
      primary: { x: 0, y: 0, width: 20, height: 20 },
      upper: { x: 20, y: 0, width: 20, height: 10 },
      lower: { x: 20, y: 10, width: 20, height: 10 },
    };
    expect(directionalPaneTarget(panes, "primary", "right")).toBe("lower");
    expect(directionalPaneTarget(panes, "upper", "bottom")).toBe("lower");
    expect(directionalPaneTarget(panes, "primary", "left")).toBeNull();
  });
});
