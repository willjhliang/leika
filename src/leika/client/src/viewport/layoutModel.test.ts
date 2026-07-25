import { describe, expect, it } from "vitest";

import {
  VIEWPORT_ROOT_PANE_ID,
  ViewportLayout,
  ViewportLayoutNode,
  ViewportSplitDirection,
  collectViewportPaneIds,
  dropViewportPane,
  equalizeViewportPanes,
  insertViewportPane,
  normalizeViewportLayout,
  normalizeViewportWeights,
  reconcileViewportLayout,
  removeViewportPane,
  setViewportSplitWeights,
} from "./layoutModel";

const pane = (pane_id: string): ViewportLayoutNode => ({
  type: "pane",
  pane_id,
});
const split = (
  direction: ViewportSplitDirection,
  children: ViewportLayoutNode[],
  weights = children.map(() => 1 / children.length),
): ViewportLayoutNode => ({ type: "split", direction, children, weights });
const layout = (root: ViewportLayoutNode): ViewportLayout => ({
  version: 1,
  root,
});

function expectValidLayout(value: ViewportLayout): void {
  const seen = new Set<string>();
  const visit = (node: ViewportLayoutNode): void => {
    if (node.type === "pane") {
      expect(seen.has(node.pane_id)).toBe(false);
      seen.add(node.pane_id);
      return;
    }
    expect(node.children.length).toBeGreaterThanOrEqual(2);
    expect(node.weights).toHaveLength(node.children.length);
    expect(
      node.weights.every((weight) => Number.isFinite(weight) && weight > 0),
    ).toBe(true);
    expect(node.weights.reduce((sum, weight) => sum + weight, 0)).toBeCloseTo(
      1,
    );
    node.children.forEach(visit);
  };
  expect(value.version).toBe(1);
  visit(value.root);
  expect(seen.has(VIEWPORT_ROOT_PANE_ID)).toBe(true);
}

describe("normalizeViewportWeights", () => {
  it("repairs bad entries and handles huge finite weights", () => {
    expect(normalizeViewportWeights([2, -1, 2])).toEqual([0.4, 0.2, 0.4]);
    expect(normalizeViewportWeights([], 2)).toEqual([0.5, 0.5]);
    expect(normalizeViewportWeights([1e308, 1e308])).toEqual([0.5, 0.5]);
  });

  it("keeps extreme positive weights positive and renormalizable", () => {
    const normalized = normalizeViewportWeights([1e308, Number.MIN_VALUE]);

    expect(normalized).toHaveLength(2);
    expect(normalized.every((weight) => Number.isFinite(weight))).toBe(true);
    expect(normalized.every((weight) => weight > 0)).toBe(true);
    expect(normalized.reduce((sum, weight) => sum + weight, 0)).toBeCloseTo(1);
    expect(normalizeViewportWeights(normalized)).toEqual(normalized);
  });

  it("rejects invalid child counts", () => {
    expect(normalizeViewportWeights([1], -1)).toEqual([]);
    expect(normalizeViewportWeights([1], 1.5)).toEqual([]);
  });

  it("passes already-normalized weights through bit-identically", () => {
    const thirds = [1 / 3, 1 / 3, 1 - 2 / 3];
    expect(normalizeViewportWeights(thirds)).toEqual(thirds);
    const uneven = [0.7, 0.2, 0.1 - 1e-16];
    expect(normalizeViewportWeights(uneven)).toEqual(uneven);
  });
});

describe("normalizeViewportLayout", () => {
  it("wraps stored layouts that lack the root sentinel", () => {
    const normalized = normalizeViewportLayout({
      version: 1,
      root: { type: "pane", pane_id: "image" },
    });
    expect(normalized).toEqual({
      version: 1,
      root: {
        type: "split",
        direction: "row",
        children: [
          { type: "pane", pane_id: VIEWPORT_ROOT_PANE_ID },
          { type: "pane", pane_id: "image" },
        ],
        weights: [0.5, 0.5],
      },
    });
  });
});

describe("reconcileViewportLayout", () => {
  it("prunes unknown/duplicate panes, repairs weights, and appends missing panes", () => {
    const input = {
      version: 1,
      root: {
        type: "split",
        direction: "row",
        children: [
          { type: "pane", pane_id: "unknown" },
          { type: "pane", pane_id: "image" },
          { type: "pane", pane_id: "image" },
          {
            type: "split",
            direction: "column",
            children: [{ type: "invalid" }, { type: "pane", pane_id: VIEWPORT_ROOT_PANE_ID }],
            weights: [-1, 2],
          },
        ],
        weights: [9, 2, 3, 4],
      },
    };
    const before = JSON.stringify(input);
    const output = reconcileViewportLayout(input, ["image", "plot"]);

    expect(collectViewportPaneIds(output)).toEqual(["image", VIEWPORT_ROOT_PANE_ID, "plot"]);
    expect(output.root).toMatchObject({
      type: "split",
      direction: "row",
      weights: [1 / 3, 1 / 3, 1 / 3],
    });
    expect(JSON.stringify(input)).toBe(before);
    expectValidLayout(output);
  });

  it("retains root and produces deterministic defaults", () => {
    expect(
      collectViewportPaneIds(
        reconcileViewportLayout(
          { version: 1, root: { type: "pane", pane_id: "image" } },
          ["image"],
        ),
      ),
    ).toEqual([VIEWPORT_ROOT_PANE_ID, "image"]);
    expect(
      collectViewportPaneIds(reconcileViewportLayout(null, ["b", "a", "b"])),
    ).toEqual([VIEWPORT_ROOT_PANE_ID, "b", "a"]);
    expect(
      collectViewportPaneIds(
        reconcileViewportLayout(
          { version: 2, root: { type: "pane", pane_id: "a" } },
          ["a"],
        ),
      ),
    ).toEqual([VIEWPORT_ROOT_PANE_ID, "a"]);
  });

  it("omits a hidden root but retains it as the empty fallback", () => {
    const rootAndImage = layout(split("row", [pane(VIEWPORT_ROOT_PANE_ID), pane("image")]));
    expect(
      collectViewportPaneIds(
        reconcileViewportLayout(
          rootAndImage,
          ["image"],
          VIEWPORT_ROOT_PANE_ID,
          false,
        ),
      ),
    ).toEqual(["image"]);
    expect(
      collectViewportPaneIds(
        reconcileViewportLayout(
          layout(pane(VIEWPORT_ROOT_PANE_ID)),
          [],
          VIEWPORT_ROOT_PANE_ID,
          false,
        ),
      ),
    ).toEqual([VIEWPORT_ROOT_PANE_ID]);
  });

  it("preserves nested same-axis splits from serialized layouts", () => {
    const output = reconcileViewportLayout(
      {
        version: 1,
        root: {
          type: "split",
          direction: "row",
          children: [
            { type: "pane", pane_id: VIEWPORT_ROOT_PANE_ID },
            {
              type: "split",
              direction: "row",
              children: [
                { type: "pane", pane_id: "a" },
                { type: "pane", pane_id: "b" },
              ],
              weights: [3, 1],
            },
          ],
          weights: [1, 1],
        },
      },
      ["a", "b"],
    );
    expect(output.root).toEqual(
      split(
        "row",
        [pane(VIEWPORT_ROOT_PANE_ID), split("row", [pane("a"), pane("b")], [0.75, 0.25])],
        [0.5, 0.5],
      ),
    );
    expectValidLayout(output);
  });

  it("safely discards cyclic object graphs", () => {
    const cyclic: {
      type: "split";
      direction: "column";
      children: unknown[];
      weights: number[];
    } = { type: "split", direction: "column", children: [], weights: [1, 1] };
    cyclic.children.push(cyclic, { type: "pane", pane_id: VIEWPORT_ROOT_PANE_ID });
    const output = reconcileViewportLayout({ version: 1, root: cyclic }, [
      "image",
    ]);
    expect(collectViewportPaneIds(output)).toEqual([VIEWPORT_ROOT_PANE_ID, "image"]);
    expectValidLayout(output);
  });
});

describe("removeViewportPane", () => {
  const nested = (): ViewportLayout =>
    layout(
      split(
        "row",
        [
          pane(VIEWPORT_ROOT_PANE_ID),
          split("column", [pane("a"), pane("b")], [0.7, 0.3]),
          pane("c"),
        ],
        [0.2, 0.5, 0.3],
      ),
    );

  it("removes panes and collapses one-child splits", () => {
    const output = removeViewportPane(nested(), "b");
    expect(collectViewportPaneIds(output)).toEqual([VIEWPORT_ROOT_PANE_ID, "a", "c"]);
    expect(output.root).toMatchObject({ weights: [0.2, 0.5, 0.3] });
    expectValidLayout(output);
  });

  it("protects root and no-ops for unknown panes", () => {
    const input = nested();
    expect(removeViewportPane(input, "missing")).toBe(input);
    expect(removeViewportPane(input, VIEWPORT_ROOT_PANE_ID)).toBe(input);
  });

  it("collapses the root after removing the final image", () => {
    const input = layout(split("row", [pane(VIEWPORT_ROOT_PANE_ID), pane("image")]));
    expect(removeViewportPane(input, "image")).toEqual(layout(pane(VIEWPORT_ROOT_PANE_ID)));
  });
});

describe("insertViewportPane and edge drops", () => {
  it("creates row and column splits around targets", () => {
    const withImage = insertViewportPane(
      layout(pane(VIEWPORT_ROOT_PANE_ID)),
      "image",
      VIEWPORT_ROOT_PANE_ID,
      "right",
    );
    const output = insertViewportPane(withImage, "plot", "image", "bottom");
    expect(output.root).toEqual(
      split(
        "row",
        [pane(VIEWPORT_ROOT_PANE_ID), split("column", [pane("image"), pane("plot")])],
        [0.5, 0.5],
      ),
    );
    expectValidLayout(output);
  });

  it("splits a target allocation when adding a same-axis sibling", () => {
    const input = layout(
      split("row", [pane(VIEWPORT_ROOT_PANE_ID), pane("image")], [0.8, 0.2]),
    );
    const output = insertViewportPane(input, "plot", "image", "right");
    expect(output.root).toMatchObject({ weights: [0.8, 0.1, 0.1] });
    expect(collectViewportPaneIds(output)).toEqual([VIEWPORT_ROOT_PANE_ID, "image", "plot"]);
  });

  it("reorders siblings while preserving pane allocations", () => {
    const input = layout(
      split("row", [pane(VIEWPORT_ROOT_PANE_ID), pane("a"), pane("b")], [0.6, 0.3, 0.1]),
    );
    const output = insertViewportPane(input, "b", "a", "left");
    expect(collectViewportPaneIds(output)).toEqual([VIEWPORT_ROOT_PANE_ID, "b", "a"]);
    expect(output.root).toMatchObject({ weights: [0.6, 0.1, 0.3] });
  });

  it("detaches, collapses, and reinserts panes moved across axes", () => {
    const input = layout(
      split(
        "row",
        [pane(VIEWPORT_ROOT_PANE_ID), split("column", [pane("a"), pane("b")], [0.7, 0.3])],
        [0.6, 0.4],
      ),
    );
    const output = insertViewportPane(input, "a", VIEWPORT_ROOT_PANE_ID, "right");
    expect(collectViewportPaneIds(output)).toEqual([VIEWPORT_ROOT_PANE_ID, "a", "b"]);
    expect(output.root.type).toBe("split");
    if (output.root.type === "split") {
      output.root.weights.forEach((weight, index) =>
        expect(weight).toBeCloseTo([0.3, 0.3, 0.4][index]),
      );
    }
    expectValidLayout(output);
  });

  it("safely no-ops for missing and self targets", () => {
    const input = layout(split("row", [pane(VIEWPORT_ROOT_PANE_ID), pane("a")]));
    expect(insertViewportPane(input, "a", "missing", "right")).toBe(input);
    expect(insertViewportPane(input, "a", "a", "right")).toBe(input);
  });
});

describe("dropViewportPane", () => {
  it("center swaps positions without changing geometry", () => {
    const input = layout(
      split(
        "row",
        [pane(VIEWPORT_ROOT_PANE_ID), split("column", [pane("a"), pane("b")], [0.7, 0.3])],
        [0.6, 0.4],
      ),
    );
    const output = dropViewportPane(input, VIEWPORT_ROOT_PANE_ID, "b", "center");
    expect(collectViewportPaneIds(output)).toEqual(["b", "a", VIEWPORT_ROOT_PANE_ID]);
    expect(output.root).toMatchObject({
      weights: [0.6, 0.4],
      children: [{ pane_id: "b" }, { weights: [0.7, 0.3] }],
    });
    expectValidLayout(output);
  });

  it("no-ops for self and missing center drops and delegates edge drops", () => {
    const input = layout(split("row", [pane(VIEWPORT_ROOT_PANE_ID), pane("a")]));
    expect(dropViewportPane(input, "a", "a", "center")).toBe(input);
    expect(dropViewportPane(input, "missing", "a", "center")).toBe(input);
    expect(
      collectViewportPaneIds(dropViewportPane(input, "a", VIEWPORT_ROOT_PANE_ID, "left")),
    ).toEqual(["a", VIEWPORT_ROOT_PANE_ID]);
  });
});

describe("split weights", () => {
  it("updates nested split weights by child-index path", () => {
    const input = layout(
      split(
        "row",
        [pane(VIEWPORT_ROOT_PANE_ID), split("column", [pane("a"), pane("b")])],
        [0.6, 0.4],
      ),
    );

    const set = setViewportSplitWeights(input, [1], [3, 1]);
    expect(set.root).toMatchObject({
      children: [{}, { weights: [0.75, 0.25] }],
    });
    expect(setViewportSplitWeights(input, [9], [3, 1])).toBe(input);
    expect(setViewportSplitWeights(input, [1], [1])).toBe(input);
  });
});

describe("equalizeViewportPanes", () => {
  it("levels group members without disturbing outside panes", () => {
    // root keeps 1/2; the group's combined 1/2 splits into thirds.
    const input = layout(
      split(
        "row",
        [pane(VIEWPORT_ROOT_PANE_ID), pane("a"), pane("b"), pane("c")],
        [0.5, 0.25, 0.125, 0.125],
      ),
    );
    const result = equalizeViewportPanes(input, ["a", "b", "c"]);
    expectValidLayout(result);
    expect(result.root).toMatchObject({
      weights: [0.5, 0.5 / 3, 0.5 / 3, 0.5 / 3],
    });
  });

  it("only equalizes members that are siblings of one split", () => {
    const input = layout(
      split(
        "row",
        [
          split("column", [pane(VIEWPORT_ROOT_PANE_ID), pane("a")], [0.5, 0.5]),
          pane("b"),
          pane("c"),
        ],
        [0.5, 0.375, 0.125],
      ),
    );
    // "a" lives in a different split; only b and c level with each other.
    const result = equalizeViewportPanes(input, ["a", "b", "c"]);
    expectValidLayout(result);
    expect(result.root).toMatchObject({ weights: [0.5, 0.25, 0.25] });
    expect(result.root).toMatchObject({
      children: [{ weights: [0.5, 0.5] }, {}, {}],
    });
  });

  it("returns the same layout when fewer than two members match", () => {
    const input = layout(
      split("row", [pane(VIEWPORT_ROOT_PANE_ID), pane("a")], [0.75, 0.25]),
    );
    expect(equalizeViewportPanes(input, ["a"])).toBe(input);
    expect(equalizeViewportPanes(input, ["a", "missing"])).toBe(input);
    expect(equalizeViewportPanes(input, [])).toBe(input);
  });
});
