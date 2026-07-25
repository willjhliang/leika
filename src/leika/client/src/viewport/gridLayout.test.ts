import { describe, expect, it } from "vitest";

import { ViewportLayout } from "./layoutModel";
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

describe("viewport square-grid geometry", () => {
  it("represents common aspect ratios with integer grid corners", () => {
    const grid = gridSpecForLayout(nestedLayout, {
      width: 960,
      height: 576,
    });
    expect(grid).toEqual({ columns: 60, rows: 36, cellSize: 16 });

    const geometry = computeLayoutGeometry(
      nestedLayout.root,
      grid.columns,
      grid.rows,
    );
    expect(geometry.panes.video).toEqual({
      x: 30,
      y: 0,
      width: 30,
      height: 18,
    });
    expect(
      geometry.dividers.every((divider) =>
        Number.isInteger(divider.coordinate),
      ),
    ).toBe(true);
  });

  it.each([2, 3, 4, 5, 6])(
    "splits the full width into %i exactly equal panes",
    (paneCount) => {
      const layout: ViewportLayout = {
        version: 1,
        root: {
          type: "split",
          direction: "row",
          children: Array.from({ length: paneCount }, (_, index) => ({
            type: "pane" as const,
            pane_id: `pane-${index}`,
          })),
          weights: Array.from({ length: paneCount }, () => 1 / paneCount),
        },
      };
      const grid = gridSpecForLayout(layout, { width: 1920, height: 1080 });
      expect(grid.columns).toBe(60);
      const geometry = computeLayoutGeometry(
        layout.root,
        grid.columns,
        grid.rows,
      );
      const widths = Object.values(geometry.panes).map((rect) => rect.width);
      expect(widths).toEqual(
        Array.from({ length: paneCount }, () => 60 / paneCount),
      );
      expect(
        geometry.dividers.every((divider) =>
          Number.isInteger(divider.coordinate),
        ),
      ).toBe(true);
    },
  );

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
