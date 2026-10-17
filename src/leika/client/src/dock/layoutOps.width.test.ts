// Width-column discovery, subtree bounds, node-weight updates, and the split
// shapes produced by top/bottom docking.

import { describe, it, expect } from "vitest";
import { DockLayout, DockNode, GroupId } from "./types";
import {
  widthColumns,
  setNodeWeights,
  dockToRegionEdge,
  dropOnDockedLeaf,
  collectLeafGroups,
} from "./layoutOps";
import {
  leaf,
  row as rowSplit,
  col as colSplit,
  dockedLeft,
  group,
  groupsRecord as groups,
} from "./testUtils";

function layoutWith(tree: DockNode, ...gids: GroupId[]): DockLayout {
  return {
    groups: groups(...gids),
    docked: { left: tree, right: null },
    floating: [],
  };
}
/** The single split node in a tree shaped as one split (for weight checks). */
function asSplit(n: DockNode | null): Extract<DockNode, { type: "split" }> {
  if (n === null || n.type !== "split") throw new Error("expected split");
  return n;
}

describe("setNodeWeights", () => {
  it("sets a nested node's weight by id (works on partial/synthetic subtrees)", () => {
    // The M1 case: a divider in a reserved subtree references children by their
    // own ids, so even when only some children are present the right ones update.
    const b = leaf("b", 1);
    const c = leaf("c", 1);
    const inner = rowSplit([b, c]);
    const tree = rowSplit([leaf("a", 1), inner]);
    const layout = dockedLeft(tree);
    const out = setNodeWeights(layout, "left", { [b.id]: 7, [c.id]: 2 });
    const root = out.docked.left as Extract<DockNode, { type: "split" }>;
    const nested = root.children[1] as Extract<DockNode, { type: "split" }>;
    expect(nested.children.map((x) => x.weight)).toEqual([7, 2]);
  });

  it("rejects non-finite and non-positive weights (keeps the old weight)", () => {
    const a = leaf("a", 2);
    const b = leaf("b", 2);
    const c = leaf("c", 2);
    const layout = dockedLeft(rowSplit([a, b, c]));
    const out = setNodeWeights(layout, "left", {
      [a.id]: 0,
      [b.id]: -3,
      [c.id]: Number.NaN,
    });
    const root = out.docked.left as Extract<DockNode, { type: "split" }>;
    expect(root.children.map((x) => x.weight)).toEqual([2, 2, 2]); // all kept
  });

  it("returns the input when the edge is empty", () => {
    const layout = dockedLeft(null);
    expect(setNodeWeights(layout, "left", { x: 1 })).toBe(layout);
  });
});

// Top/bottom region docks use equal vertical weights, independent of the
// existing subtree's horizontal weight.
describe("dockToRegionEdge top/bottom: equal vertical split (no weight leak)", () => {
  it("wrapping a heavy-weighted row puts BOTH children at equal weight", () => {
    // A horizontal pixel weight must not leak into the new vertical split.
    const a = leaf("a", 297);
    const b = leaf("b", 297);
    const existing = rowSplit([a, b], 300); // leftover px root weight
    const l = layoutWith(existing, "a", "b");
    l.groups["c"] = group("c");

    const out = dockToRegionEdge(l, ["c"], "left", "top");
    const root = asSplit(out.docked.left);
    expect(root.dir).toBe("column");
    // Two children: [C, row[A,B]] (C first, dragged-first for "top").
    expect(root.children).toHaveLength(2);
    expect(root.children.map((c) => c.weight)).toEqual([1, 1]); // 50/50
    // C is on top; the row is preserved underneath.
    expect(collectLeafGroups(root.children[0])).toEqual(["c"]);
    expect(collectLeafGroups(root.children[1]).sort()).toEqual(["a", "b"]);
  });

  it("bottom side puts the dragged panel last, still 50/50", () => {
    const existing = rowSplit([leaf("a", 250), leaf("b", 250)], 250);
    const l = layoutWith(existing, "a", "b");
    l.groups["c"] = group("c");
    const out = dockToRegionEdge(l, ["c"], "left", "bottom");
    const root = asSplit(out.docked.left);
    expect(root.dir).toBe("column");
    expect(root.children.map((c) => c.weight)).toEqual([1, 1]);
    expect(collectLeafGroups(root.children[1])).toEqual(["c"]); // dragged last
  });
});

// Per-panel top/bottom drops split height equally and preserve the wrapper's
// horizontal weight.
describe("dropOnDockedLeaf top/bottom: 50/50 split, width preserved", () => {
  function regionLayout(): { l: DockLayout; targetId: string } {
    // Right region [A(297) | B(297)] -- drop C above A.
    const a: DockNode = { type: "leaf", id: "La", group: "a", weight: 297 };
    const b: DockNode = { type: "leaf", id: "Lb", group: "b", weight: 297 };
    const tree: DockNode = {
      type: "split",
      id: "S",
      dir: "row",
      weight: 1,
      children: [a, b],
    };
    const l: DockLayout = {
      groups: groups("a", "b", "c"),
      docked: { left: null, right: tree },
      floating: [{ id: "w", x: 0, y: 0, width: 280, stack: ["c"] }],
    };
    return { l, targetId: "La" };
  }

  it("above A: column[C, A] is 50/50 and keeps A's width on the wrapper", () => {
    const { l, targetId } = regionLayout();
    const out = dropOnDockedLeaf(l, ["c"], "right", targetId, "top");
    const root = asSplit(out.docked.right);
    // The first column (where A was) is now a column split [C, A].
    const aCol = root.children[0];
    const wrap = asSplit(aCol);
    expect(wrap.dir).toBe("column");
    expect(wrap.children.map((x) => x.weight)).toEqual([1, 1]); // 50/50 height
    expect(collectLeafGroups(wrap.children[0])).toEqual(["c"]); // C on top
    expect(collectLeafGroups(wrap.children[1])).toEqual(["a"]);
    // The wrapper preserves A's horizontal weight (297) so the column keeps width.
    expect(wrap.weight).toBe(297);
    // B is untouched.
    expect(root.children[1].weight).toBe(297);
  });

  it("below A: column[A, C] is 50/50 (dragged last)", () => {
    const { l, targetId } = regionLayout();
    const out = dropOnDockedLeaf(l, ["c"], "right", targetId, "bottom");
    const wrap = asSplit(asSplit(out.docked.right).children[0]);
    expect(wrap.dir).toBe("column");
    expect(wrap.children.map((x) => x.weight)).toEqual([1, 1]);
    expect(collectLeafGroups(wrap.children[1])).toEqual(["c"]); // dragged last
  });
});

// Column-rooted width comes from its widest inner row.
describe("column-rooted region width bounds reflect the inner row", () => {
  it("widthColumns of the column root preserves the inner side-by-side widths", () => {
    const a = leaf("a", 300);
    const b = leaf("b", 300);
    const tree = colSplit([leaf("c", 1), rowSplit([a, b], 1)]);
    const cols = widthColumns(tree);
    const sum = cols.reduce((s, c) => s + c.weight, 0);
    expect(cols.map((c) => collectLeafGroups(c)[0])).toEqual(["a", "b"]);
    expect(sum).toBe(600);
  });
});
