import { describe, expect, it } from "vitest";

import {
  ViewportLayout,
  ViewportLayoutNode,
  ViewportSplitDirection,
  collectViewportPaneIds,
  dropViewportPane,
  equalizeViewportPanes,
  insertViewportPane,
  normalizeViewportLayout,
  normalizeViewportWeights,
  placeViewportPane,
  reconcileViewportLayout,
  removeViewportPane,
  setViewportSplitWeights,
} from "./layoutModel";
import {
  MAX_LAYOUT_CHILDREN,
  MAX_LAYOUT_DEPTH,
  MAX_LAYOUT_ID_CODE_UNITS,
  MAX_LAYOUT_ITEMS,
} from "../persistenceLimits";

const pane = (pane_id: string): ViewportLayoutNode => ({
  type: "pane",
  pane_id,
});
const split = (
  direction: ViewportSplitDirection,
  children: ViewportLayoutNode[],
  weights = children.map(() => 1 / children.length),
): ViewportLayoutNode => ({ type: "split", direction, children, weights });
const layout = (root: ViewportLayoutNode | null): ViewportLayout => ({
  version: 1,
  root,
});
/** An ordinary pane the structural tests arrange others around. */
const BASE = "base";

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
  if (value.root !== null) visit(value.root);
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
});

describe("normalizeViewportLayout", () => {
  it("keeps a stored layout and reads anything else as empty", () => {
    expect(
      normalizeViewportLayout({ version: 1, root: pane("image") }),
    ).toEqual(layout(pane("image")));
    expect(normalizeViewportLayout({ version: 1, root: null })).toEqual(
      layout(null),
    );
    expect(normalizeViewportLayout("invalid")).toEqual(layout(null));
  });

  it("falls back safely for deep, broad, cyclic, and oversized input", () => {
    let deep: unknown = { type: "pane", pane_id: "last" };
    for (let depth = 0; depth <= MAX_LAYOUT_DEPTH; depth += 1) {
      deep = {
        type: "split",
        direction: "row",
        children: [deep],
        weights: [1],
      };
    }
    const broad = {
      type: "split",
      direction: "row",
      children: Array.from({ length: MAX_LAYOUT_CHILDREN + 1 }, (_, index) => ({
        type: "pane",
        pane_id: `pane-${index}`,
      })),
      weights: [],
    };
    const cyclic: { type: string; direction: string; children: unknown[] } = {
      type: "split",
      direction: "row",
      children: [],
    };
    cyclic.children.push(cyclic);
    for (const root of [
      deep,
      broad,
      cyclic,
      { type: "pane", pane_id: "x".repeat(MAX_LAYOUT_ID_CODE_UNITS + 1) },
    ]) {
      expect(
        collectViewportPaneIds(normalizeViewportLayout({ version: 1, root })),
      ).toEqual([]);
    }
  });

  it("bounds and deduplicates a hostile public pane list", () => {
    const paneIds = Array.from(
      { length: MAX_LAYOUT_ITEMS + 100 },
      (_, index) => `pane-${index}`,
    );
    const output = reconcileViewportLayout(null, [
      ...paneIds,
      ...paneIds,
      "x".repeat(MAX_LAYOUT_ID_CODE_UNITS + 1),
    ]);
    expect(collectViewportPaneIds(output)).toHaveLength(MAX_LAYOUT_ITEMS);
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
            children: [{ type: "invalid" }, { type: "pane", pane_id: BASE }],
            weights: [-1, 2],
          },
        ],
        weights: [9, 2, 3, 4],
      },
    };
    const before = JSON.stringify(input);
    const output = reconcileViewportLayout(input, [BASE, "image", "plot"]);

    expect(collectViewportPaneIds(output)).toEqual(["image", BASE, "plot"]);
    expect(output.root).toMatchObject({
      type: "split",
      direction: "row",
      weights: [1 / 3, 1 / 3, 1 / 3],
    });
    expect(JSON.stringify(input)).toBe(before);
    expectValidLayout(output);
  });

  it("produces deterministic defaults", () => {
    expect(
      collectViewportPaneIds(
        reconcileViewportLayout(layout(pane("image")), ["image"]),
      ),
    ).toEqual(["image"]);
    expect(
      collectViewportPaneIds(reconcileViewportLayout(null, ["b", "a", "b"])),
    ).toEqual(["b", "a"]);
    expect(
      collectViewportPaneIds(
        reconcileViewportLayout({ version: 2, root: pane("a") }, ["a"]),
      ),
    ).toEqual(["a"]);
  });

  it("drops hidden panes and empties the layout when none is visible", () => {
    const pair = layout(split("row", [pane("a"), pane("image")]));
    expect(
      collectViewportPaneIds(reconcileViewportLayout(pair, ["image"])),
    ).toEqual(["image"]);
    expect(reconcileViewportLayout(pair, [])).toEqual(layout(null));
  });

  it("preserves nested same-axis splits from serialized layouts", () => {
    const output = reconcileViewportLayout(
      {
        version: 1,
        root: {
          type: "split",
          direction: "row",
          children: [
            { type: "pane", pane_id: BASE },
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
      [BASE, "a", "b"],
    );
    expect(output.root).toEqual(
      split(
        "row",
        [pane(BASE), split("row", [pane("a"), pane("b")], [0.75, 0.25])],
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
    cyclic.children.push(cyclic, { type: "pane", pane_id: BASE });
    const output = reconcileViewportLayout({ version: 1, root: cyclic }, [
      BASE,
      "image",
    ]);
    expect(collectViewportPaneIds(output)).toEqual([BASE, "image"]);
    expectValidLayout(output);
  });
});

describe("removeViewportPane", () => {
  const nested = (): ViewportLayout =>
    layout(
      split(
        "row",
        [
          pane(BASE),
          split("column", [pane("a"), pane("b")], [0.7, 0.3]),
          pane("c"),
        ],
        [0.2, 0.5, 0.3],
      ),
    );

  it("removes panes and collapses one-child splits", () => {
    const output = removeViewportPane(nested(), "b");
    expect(collectViewportPaneIds(output)).toEqual([BASE, "a", "c"]);
    expect(output.root).toMatchObject({ weights: [0.2, 0.5, 0.3] });
    expectValidLayout(output);
  });

  it("no-ops for unknown panes and empty layouts", () => {
    const input = nested();
    expect(removeViewportPane(input, "missing")).toBe(input);
    const empty = layout(null);
    expect(removeViewportPane(empty, "missing")).toBe(empty);
  });

  it("empties the layout after removing the final pane", () => {
    const input = layout(split("row", [pane(BASE), pane("image")]));
    const withoutImage = removeViewportPane(input, "image");
    expect(withoutImage).toEqual(layout(pane(BASE)));
    expect(removeViewportPane(withoutImage, BASE)).toEqual(layout(null));
  });
});

describe("insertViewportPane and edge drops", () => {
  it("creates row and column splits around targets", () => {
    const withImage = insertViewportPane(
      layout(pane(BASE)),
      "image",
      BASE,
      "right",
    );
    const output = insertViewportPane(withImage, "plot", "image", "bottom");
    expect(output.root).toEqual(
      split(
        "row",
        [pane(BASE), split("column", [pane("image"), pane("plot")])],
        [0.5, 0.5],
      ),
    );
    expectValidLayout(output);
  });

  it("splits a target allocation when adding a same-axis sibling", () => {
    const input = layout(split("row", [pane(BASE), pane("image")], [0.8, 0.2]));
    const output = insertViewportPane(input, "plot", "image", "right");
    expect(output.root).toMatchObject({ weights: [0.8, 0.1, 0.1] });
    expect(collectViewportPaneIds(output)).toEqual([BASE, "image", "plot"]);
  });

  it("reorders siblings while preserving pane allocations", () => {
    const input = layout(
      split("row", [pane(BASE), pane("a"), pane("b")], [0.6, 0.3, 0.1]),
    );
    const output = insertViewportPane(input, "b", "a", "left");
    expect(collectViewportPaneIds(output)).toEqual([BASE, "b", "a"]);
    expect(output.root).toMatchObject({ weights: [0.6, 0.1, 0.3] });
  });

  it("detaches, collapses, and reinserts panes moved across axes", () => {
    const input = layout(
      split(
        "row",
        [pane(BASE), split("column", [pane("a"), pane("b")], [0.7, 0.3])],
        [0.6, 0.4],
      ),
    );
    const output = insertViewportPane(input, "a", BASE, "right");
    expect(collectViewportPaneIds(output)).toEqual([BASE, "a", "b"]);
    expect(output.root?.type).toBe("split");
    if (output.root?.type === "split") {
      output.root.weights.forEach((weight, index) =>
        expect(weight).toBeCloseTo([0.3, 0.3, 0.4][index]),
      );
    }
    expectValidLayout(output);
  });

  it("places a new pane beside its anchor, the last pane, or alone", () => {
    const first = placeViewportPane(layout(null), "a", "missing", "right");
    expect(first).toEqual(layout(pane("a")));
    const second = placeViewportPane(first, "b", null, "bottom");
    expect(second.root).toEqual(split("column", [pane("a"), pane("b")]));
    const third = placeViewportPane(second, "c", "a", "left");
    expect(collectViewportPaneIds(third)).toEqual(["c", "a", "b"]);
  });

  it("safely no-ops for missing and self targets", () => {
    const input = layout(split("row", [pane(BASE), pane("a")]));
    expect(insertViewportPane(input, "a", "missing", "right")).toBe(input);
    expect(insertViewportPane(input, "a", "a", "right")).toBe(input);
  });
});

describe("dropViewportPane", () => {
  it("center swaps positions without changing geometry", () => {
    const input = layout(
      split(
        "row",
        [pane(BASE), split("column", [pane("a"), pane("b")], [0.7, 0.3])],
        [0.6, 0.4],
      ),
    );
    const output = dropViewportPane(input, BASE, "b", "center");
    expect(collectViewportPaneIds(output)).toEqual(["b", "a", BASE]);
    expect(output.root).toMatchObject({
      weights: [0.6, 0.4],
      children: [{ pane_id: "b" }, { weights: [0.7, 0.3] }],
    });
    expectValidLayout(output);
  });

  it("no-ops for self and missing center drops and delegates edge drops", () => {
    const input = layout(split("row", [pane(BASE), pane("a")]));
    expect(dropViewportPane(input, "a", "a", "center")).toBe(input);
    expect(dropViewportPane(input, "missing", "a", "center")).toBe(input);
    expect(
      collectViewportPaneIds(dropViewportPane(input, "a", BASE, "left")),
    ).toEqual(["a", BASE]);
  });
});

describe("split weights", () => {
  it("updates nested split weights by child-index path", () => {
    const input = layout(
      split(
        "row",
        [pane(BASE), split("column", [pane("a"), pane("b")])],
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
    // base keeps 1/2; the group's combined 1/2 splits into thirds.
    const input = layout(
      split(
        "row",
        [pane(BASE), pane("a"), pane("b"), pane("c")],
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
          split("column", [pane(BASE), pane("a")], [0.5, 0.5]),
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
    const input = layout(split("row", [pane(BASE), pane("a")], [0.75, 0.25]));
    expect(equalizeViewportPanes(input, ["a"])).toBe(input);
    expect(equalizeViewportPanes(input, ["a", "missing"])).toBe(input);
    expect(equalizeViewportPanes(input, [])).toBe(input);
  });
});
