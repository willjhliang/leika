// Docking, tab movement, and resizing behavior. General layout invariants
// are exercised by layoutOps.fuzz.test.ts.

import { describe, it, expect } from "vitest";
import { DockLayout, GroupId, MIN_PANEL_WIDTH_PX, emptyLayout } from "./types";
import {
  leaf,
  row,
  col,
  makeLayout,
  shapeOf,
  groupsInTree,
  group,
  refCount,
} from "./testUtils";
import {
  findGroupLocation,
  dockToEdge,
  dockToRegionEdge,
  dropOnDockedLeaf,
  insertTabsInto,
  floatGroup,
  tearOutPanel,
  moveWindow,
  resizeWindow,
  resizeWindowHeight,
  snapToWindowStack,
  bringToFront,
  reorderTab,
  toggleCollapsed,
  minimizeStack,
  expandStack,
  setActiveTab,
  cascadeResize,
  resizeRegionColumns,
  setStackWeights,
  restoreStackWeights,
} from "./layoutOps";

// ---------------------------------------------------------------------------
// Shared fixtures.
// ---------------------------------------------------------------------------

/** Left edge holds row [a | b] with fixed node ids S / La / Lb. */
function twoLeafRow(): DockLayout {
  const l = emptyLayout();
  l.groups = { a: group("a"), b: group("b") };
  l.docked.left = {
    type: "split",
    id: "S",
    dir: "row",
    weight: 1,
    children: [
      { type: "leaf", id: "La", group: "a", weight: 1 },
      { type: "leaf", id: "Lb", group: "b", weight: 1 },
    ],
  };
  return l;
}

/** Floating-only layout with explicit per-window stacks and stack weights. */
function floatingLayout(
  windows: {
    id: string;
    stack: GroupId[];
    stackWeights?: Record<GroupId, number>;
  }[],
): DockLayout {
  const l = emptyLayout();
  l.floating = windows.map((w) => ({
    id: w.id,
    x: 0,
    y: 0,
    width: 300,
    stack: [...w.stack],
    ...(w.stackWeights !== undefined
      ? { stackWeights: { ...w.stackWeights } }
      : {}),
  }));
  for (const w of windows)
    for (const g of w.stack)
      if (l.groups[g] === undefined)
        l.groups[g] = { id: g, panelIds: [g], activeId: g };
  return l;
}

/** One area (backed by "area-grp" with two panels) plus plain target/source
 * groups, for the area-as-fixture guards. */
function areaSourceLayout(): DockLayout {
  const l = emptyLayout();
  // Backing group for an area, holding two panels.
  l.groups["area-grp"] = {
    id: "area-grp",
    panelIds: ["props", "history"],
    activeId: "props",
  };
  // A plain target group to merge into.
  l.groups["target"] = { id: "target", panelIds: ["scene"], activeId: "scene" };
  // A plain source we DO expect to be consumed.
  l.groups["plain-src"] = {
    id: "plain-src",
    panelIds: ["controls"],
    activeId: "controls",
  };
  l.areas = { "area-1": { id: "area-1", group: "area-grp" } };
  return l;
}

describe("dockToEdge", () => {
  it("docks a single floating group to an empty left edge as a leaf", () => {
    const layout = makeLayout({ floating: [{ id: "w1", stack: ["a"] }] });
    const out = dockToEdge(layout, ["a"], "left");
    expect(shapeOf(out.docked.left)).toEqual({ leaf: "a" });
    expect(out.floating).toHaveLength(0); // empty window cleaned up
    expect(out).not.toBe(layout); // new object
  });

  it("docks a multi-group snapped stack as a column subtree, preserving order", () => {
    const layout = makeLayout({
      floating: [{ id: "w1", stack: ["a", "b", "c"] }],
    });
    const out = dockToEdge(layout, ["a", "b", "c"], "left");
    expect(shapeOf(out.docked.left)).toEqual({
      dir: "column",
      children: [{ leaf: "a" }, { leaf: "b" }, { leaf: "c" }],
    });
    expect(out.floating).toHaveLength(0);
  });

  it("detaches from the source edge when re-docking within docked regions", () => {
    const layout = makeLayout({ left: leaf("a"), right: leaf("b") });
    const out = dockToEdge(layout, ["b"], "left");
    expect(out.docked.right).toBeNull(); // source edge emptied
    expect(groupsInTree(out.docked.left).sort()).toEqual(["a", "b"]);
  });
});

describe("dockToRegionEdge", () => {
  // Wraps the region in a column (top/bottom) or row (left/right), with the
  // dragged band first for top/left and last for bottom/right.
  it.each([
    ["top", "column", ["b", "a"]],
    ["bottom", "column", ["a", "b"]],
    ["left", "row", ["b", "a"]],
    ["right", "row", ["a", "b"]],
  ] as const)("%s: wraps in a %s with order %j", (side, dir, order) => {
    const layout = makeLayout({
      left: leaf("a"),
      floating: [{ id: "w1", stack: ["b"] }],
    });
    const out = dockToRegionEdge(layout, ["b"], "left", side);
    expect(shapeOf(out.docked.left)).toEqual({
      dir,
      children: order.map((g) => ({ leaf: g })),
    });
  });

  it("docks a multi-group stack as a column band, preserving order", () => {
    const layout = makeLayout({
      left: leaf("x"),
      floating: [{ id: "w1", stack: ["a", "b"] }],
    });
    // The dragged column band [a/b] is wrapped in a column with the existing
    // leaf; same-axis flattening then merges them into one flat column.
    const out = dockToRegionEdge(layout, ["a", "b"], "left", "top");
    expect(shapeOf(out.docked.left)).toEqual({
      dir: "column",
      children: [{ leaf: "a" }, { leaf: "b" }, { leaf: "x" }],
    });
  });

  it("keeps the dragged band nested when its axis differs from the wrap (left side)", () => {
    // Dragged stack [a/b] is a column; docking to the *left* wraps in a row, so
    // the column survives as a nested child (no same-axis flattening).
    const layout = makeLayout({
      left: leaf("x"),
      floating: [{ id: "w1", stack: ["a", "b"] }],
    });
    const out = dockToRegionEdge(layout, ["a", "b"], "left", "left");
    expect(shapeOf(out.docked.left)).toEqual({
      dir: "row",
      children: [
        { dir: "column", children: [{ leaf: "a" }, { leaf: "b" }] },
        { leaf: "x" },
      ],
    });
  });
});

describe("dropOnDockedLeaf", () => {
  /** Helper: find the node id of the docked leaf holding `group`. */
  function leafIdOf(layout: DockLayout, group: GroupId): string {
    const loc = findGroupLocation(layout, group);
    if (loc === null || loc.kind !== "docked") throw new Error("not docked");
    return loc.nodeId;
  }

  it("center: merges every dragged panel into the target group's tabs", () => {
    const layout = makeLayout({
      left: leaf("a"),
      floating: [{ id: "w1", stack: ["b"] }],
      groups: { a: 1, b: 2 },
    });
    const id = leafIdOf(layout, "a");
    const out = dropOnDockedLeaf(layout, ["b"], "left", id, "center");
    expect(shapeOf(out.docked.left)).toEqual({ leaf: "a" });
    expect(out.groups["a"].panelIds).toEqual(["a:0", "b:0", "b:1"]);
    expect(out.groups["b"]).toBeUndefined(); // source group dropped
    expect(out.floating).toHaveLength(0);
  });

  // Side splits: dragged goes before the target for left/top, after for
  // right/bottom; left/right split as a row, top/bottom as a column.
  it.each([
    ["left", "row", ["b", "a"]],
    ["right", "row", ["a", "b"]],
    ["top", "column", ["b", "a"]],
    ["bottom", "column", ["a", "b"]],
  ] as const)("%s split: %s with order %j", (region, dir, order) => {
    const layout = makeLayout({
      left: leaf("a"),
      floating: [{ id: "w1", stack: ["b"] }],
    });
    const id = leafIdOf(layout, "a");
    const out = dropOnDockedLeaf(layout, ["b"], "left", id, region);
    expect(shapeOf(out.docked.left)).toEqual({
      dir,
      children: order.map((g) => ({ leaf: g })),
    });
  });

  it("a same-edge dragged group is detached before the split (no duplication)", () => {
    // Both a and b live on the left; drop b to the right of a.
    const layout = makeLayout({ left: row([leaf("a"), leaf("b")]) });
    const id = leafIdOf(layout, "a");
    const out = dropOnDockedLeaf(layout, ["b"], "left", id, "right");
    // b removed from its old spot, then re-inserted next to a; flattened to a row.
    expect(groupsInTree(out.docked.left).sort()).toEqual(["a", "b"]);
    expect(shapeOf(out.docked.left)).toEqual({
      dir: "row",
      children: [{ leaf: "a" }, { leaf: "b" }],
    });
  });

  it("drops a multi-group stack kept together as a column subtree on a side", () => {
    const layout = makeLayout({
      left: leaf("a"),
      floating: [{ id: "w1", stack: ["b", "c"] }],
    });
    const id = leafIdOf(layout, "a");
    const out = dropOnDockedLeaf(layout, ["b", "c"], "left", id, "right");
    expect(shapeOf(out.docked.left)).toEqual({
      dir: "row",
      children: [
        { leaf: "a" },
        { dir: "column", children: [{ leaf: "b" }, { leaf: "c" }] },
      ],
    });
  });
});

// regression: dropOnDockedLeaf with a non-center region, where the dragged set
// includes the target leaf's own group, used to orphan/lose the dragged group
// (was HIGH). FIX: re-find the target leaf AFTER detach; if it's gone (a
// self-drop that collapsed the node), abort -- a safe no-op.
describe("self-drops preserve the group", () => {
  it("no loss for any of the four non-center regions", () => {
    for (const region of ["top", "bottom", "left", "right"] as const) {
      const out = dropOnDockedLeaf(twoLeafRow(), ["a"], "left", "La", region);
      expect(refCount(out, "a")).toBe(1); // FIXED: never orphaned
      expect(refCount(out, "b")).toBe(1);
    }
  });
});

describe("insertTabsInto", () => {
  it("moves a tab list larger than JavaScript's call argument limit", () => {
    const panelIds = Array.from(
      { length: 150_000 },
      (_, index) => `panel-${index}`,
    );
    const layout = emptyLayout();
    layout.groups.t = { id: "t", panelIds: ["target"], activeId: "target" };
    layout.groups.s = { id: "s", panelIds, activeId: panelIds.at(-1)! };
    layout.floating = [
      { id: "target-window", x: 0, y: 0, width: 300, stack: ["t"] },
      { id: "source-window", x: 0, y: 0, width: 300, stack: ["s"] },
    ];

    const output = insertTabsInto(layout, "t", ["s"], 1);
    expect(output.groups.t.panelIds).toHaveLength(panelIds.length + 1);
    expect(output.groups.t.panelIds.at(-1)).toBe(panelIds.at(-1));
  });
  it("inserts source panels at the given index, dropping the source group", () => {
    const layout = makeLayout({
      left: row([leaf("t"), leaf("s")]),
      groups: { t: 2, s: 1 },
    });
    const out = insertTabsInto(layout, "t", ["s"], 1);
    expect(out.groups["t"].panelIds).toEqual(["t:0", "s:0", "t:1"]);
    expect(out.groups["s"]).toBeUndefined();
    // s's leaf removed; left collapses to a single leaf t.
    expect(shapeOf(out.docked.left)).toEqual({ leaf: "t" });
  });

  it.each([
    ["clamps a too-large index to the end", 999, ["t:0", "t:1", "s:0"]],
    ["clamps a negative index to 0", -5, ["s:0", "t:0", "t:1"]],
  ] as const)("%s", (_name, index, expected) => {
    const layout = makeLayout({
      left: row([leaf("t"), leaf("s")]),
      groups: { t: 2, s: 1 },
    });
    const out = insertTabsInto(layout, "t", ["s"], index);
    expect(out.groups["t"].panelIds).toEqual([...expected]);
  });

  it("repairs a stale activeId carried by the last source", () => {
    const layout = makeLayout({
      left: row([leaf("t"), leaf("s")]),
      groups: { t: 2, s: 1 },
    });
    // Corrupt the source's activeId (e.g. a group emptied by a concurrent op
    // whose activeId was never repaired); the merge must not propagate it.
    layout.groups["s"].activeId = "ghost";
    const out = insertTabsInto(layout, "t", ["s"], 0);
    expect(out.groups["t"].panelIds).toContain(out.groups["t"].activeId);
  });

  it("merges multiple source groups in order", () => {
    const layout = makeLayout({
      left: col([leaf("t"), leaf("s1"), leaf("s2")]),
      groups: { t: 1, s1: 1, s2: 1 },
    });
    const out = insertTabsInto(layout, "t", ["s1", "s2"], 1);
    expect(out.groups["t"].panelIds).toEqual(["t:0", "s1:0", "s2:0"]);
    expect(out.groups["s1"]).toBeUndefined();
    expect(out.groups["s2"]).toBeUndefined();
  });
});

// regression: insertTabsInto skips an AREA group passed as a SOURCE. An
// area-backing group is a fixed fixture: detachInPlace is a no-op on it, so
// consuming it as a merge source would delete it from layout.groups while
// leaving layout.areas dangling. The guard skips any source that backs an
// area; the area's group (and its panels) must survive untouched.
describe("fixed areas survive tab insertion", () => {
  it("skips ONLY the area source in a mixed source list; plain sources merge", () => {
    const l = areaSourceLayout();
    // Mixed list: the area group (must be skipped) plus a plain group (consumed).
    const out = insertTabsInto(l, "target", ["area-grp", "plain-src"], 1);
    // The plain source merged in at index 1; the area's panels did NOT.
    expect(out.groups["target"].panelIds).toEqual(["scene", "controls"]);
    expect(out.groups["target"].panelIds).not.toContain("props");
    expect(out.groups["target"].panelIds).not.toContain("history");
    // The plain source was consumed; the area's backing group survives.
    expect(out.groups["plain-src"]).toBeUndefined();
    expect(out.groups["area-grp"].panelIds).toEqual(["props", "history"]);
    expect(out.areas!["area-1"].group).toBe("area-grp");
  });
});

// regression: dock/snap ops skip an AREA group in the dragged set. detachInPlace
// is a no-op on an area-backing group (it's a fixed fixture), so docking/
// snapping one would insert a SECOND reference to it while it stays in its
// area -- a duplicated group rendered in two places. The dock/snap ops filter
// area groups out of the dragged set (and no-op when nothing remains),
// mirroring the insertTabsInto source guard.
describe("fixed areas survive docking and snapping", () => {
  function areaDragLayout(): DockLayout {
    const l = areaSourceLayout();
    // A floating window to snap into / drag from.
    l.floating = [
      { id: "w1", x: 0, y: 0, width: 300, stack: ["plain-src"] },
      { id: "w2", x: 350, y: 0, width: 300, stack: ["target"] },
    ];
    return l;
  }

  it("dockToEdge with a mixed set docks only the plain group", () => {
    const l = areaDragLayout();
    const out = dockToEdge(l, ["area-grp", "plain-src"], "left");
    expect(refCount(out, "area-grp")).toBe(0); // never docked/floated
    expect(refCount(out, "plain-src")).toBe(1); // docked
    expect(out.docked.left).not.toBeNull();
    expect(out.areas!["area-1"].group).toBe("area-grp");
  });

  it("snapToWindowStack with a mixed set snaps only the plain group", () => {
    const l = areaDragLayout();
    const out = snapToWindowStack(l, ["area-grp", "plain-src"], "w2", 0);
    expect(out.floating.find((w) => w.id === "w2")!.stack).toEqual([
      "plain-src",
      "target",
    ]);
    expect(refCount(out, "area-grp")).toBe(0);
    expect(out.areas!["area-1"].group).toBe("area-grp");
  });
});

describe("floatGroup", () => {
  it("collapses a split when one of its leaves floats out", () => {
    const layout = makeLayout({ left: row([leaf("a"), leaf("b")]) });
    const { layout: out } = floatGroup(layout, "a", 0, 0, 200);
    expect(shapeOf(out.docked.left)).toEqual({ leaf: "b" }); // single-child collapse
  });

  it("floats a group that was already in another floating window (detaches first)", () => {
    const layout = makeLayout({ floating: [{ id: "w1", stack: ["a", "b"] }] });
    const { layout: out } = floatGroup(layout, "b", 5, 5, 200);
    expect(out.floating).toHaveLength(2);
    expect(out.floating.find((w) => w.id === "w1")!.stack).toEqual(["a"]);
    expect(out.floating[out.floating.length - 1].stack).toEqual(["b"]);
  });
});

describe("tearOutPanel", () => {
  it("multi-panel group: splits the torn panel into a new floating group", () => {
    const layout = makeLayout({ left: leaf("a"), groups: { a: 3 } });
    const res = tearOutPanel(layout, "a", "a:1", 7, 8, 240);
    // Source group keeps the other two panels.
    expect(res.layout.groups["a"].panelIds).toEqual(["a:0", "a:2"]);
    // New floating group holds just the torn panel.
    const newGroup = res.layout.groups[res.floatingGroupId!];
    expect(newGroup.panelIds).toEqual(["a:1"]);
    expect(res.floatingGroupId).not.toBe("a");
    const win = res.layout.floating.find((w) => w.id === res.windowId)!;
    expect(win).toMatchObject({
      x: 7,
      y: 8,
      width: 240,
      stack: [res.floatingGroupId],
    });
    // Source stays docked.
    expect(shapeOf(res.layout.docked.left)).toEqual({ leaf: "a" });
  });
});

describe("snapToWindowStack", () => {
  it("snaps a multi-group stack in as a whole, preserving order", () => {
    const layout = makeLayout({
      floating: [
        { id: "w1", stack: ["a"] },
        { id: "w2", stack: ["b", "c"] },
      ],
    });
    const out = snapToWindowStack(layout, ["b", "c"], "w1", 0);
    expect(out.floating.find((w) => w.id === "w1")!.stack).toEqual([
      "b",
      "c",
      "a",
    ]);
  });

  it("snaps a docked group into a floating stack (detaches from edge)", () => {
    const layout = makeLayout({
      left: leaf("a"),
      floating: [{ id: "w1", stack: ["b"] }],
    });
    const out = snapToWindowStack(layout, ["a"], "w1");
    expect(out.docked.left).toBeNull();
    expect(out.floating.find((w) => w.id === "w1")!.stack).toEqual(["b", "a"]);
  });
});

// ===========================================================================
// snapToWindowStack height preservation. When the dragged (source) window has
// an explicit height and the target auto-sizes, the merged target adopts the
// source's height so a height the user set on the snapped-in panel isn't lost.
// If the target already has its own height, it keeps it.
// ===========================================================================

describe("snapToWindowStack height preservation", () => {
  it("adopts the dragged source's height when the target auto-sizes", () => {
    // Target w1 has no explicit height (auto); the dragged source w2 has 333.
    const layout = makeLayout({
      floating: [
        { id: "w1", stack: ["a"] },
        { id: "w2", stack: ["b"], height: 333 },
      ],
    });
    const out = snapToWindowStack(layout, ["b"], "w1");
    const merged = out.floating.find((w) => w.id === "w1")!;
    expect(merged.stack).toEqual(["a", "b"]);
    // The source height carries over to the merged (previously auto) target.
    expect(merged.height).toBe(333);
  });

  it("keeps the target's own height when it already has one", () => {
    // Target w1 already fixed at 200; the dragged source w2 has 333. The target
    // must keep its OWN height (the source's is discarded with its window).
    const layout = makeLayout({
      floating: [
        { id: "w1", stack: ["a"], height: 200 },
        { id: "w2", stack: ["b"], height: 333 },
      ],
    });
    const out = snapToWindowStack(layout, ["b"], "w1");
    const merged = out.floating.find((w) => w.id === "w1")!;
    expect(merged.stack).toEqual(["a", "b"]);
    expect(merged.height).toBe(200);
  });
});

// regression: snapToWindowStack of a window's entire stack back into that same
// window used to delete the window and orphan the groups (was HIGH; panels
// lost). FIX: detach first, re-find the target window; if it was consumed,
// abort (return the input unchanged) -- a safe no-op.
describe("snapping a stack onto itself", () => {
  it("snapping a window's ENTIRE multi-group stack into itself is a safe no-op", () => {
    const l = emptyLayout();
    l.groups = { a: group("a"), b: group("b") };
    l.floating = [{ id: "w1", x: 0, y: 0, width: 260, stack: ["a", "b"] }];

    const out = snapToWindowStack(l, ["a", "b"], "w1", 0);

    expect(out).toBe(l); // safe no-op
    expect(refCount(out, "a")).toBe(1);
    expect(refCount(out, "b")).toBe(1);
  });

  it("PARTIAL overlap still snaps in correctly (unchanged)", () => {
    const l = emptyLayout();
    l.groups = { a: group("a"), b: group("b"), c: group("c") };
    l.floating = [
      { id: "w1", x: 0, y: 0, width: 260, stack: ["a", "b"] },
      { id: "w2", x: 300, y: 0, width: 260, stack: ["c"] },
    ];
    const out = snapToWindowStack(l, ["a", "c"], "w1", 0);
    expect(out.floating.map((w) => w.id)).toEqual(["w1"]); // w2 cleaned up
    expect(refCount(out, "a")).toBe(1);
    expect(refCount(out, "c")).toBe(1);
  });
});

// ===========================================================================
// setStackWeights
//
// Merges groupId->weight entries into a floating window's stackWeights, keeping
// existing live entries and pruning stale ones. Rejects non-finite /
// non-positive values. A missing window is a no-op (returns the input reference).
// ===========================================================================
describe("setStackWeights", () => {
  it("keeps existing entries and overrides only the provided keys", () => {
    const l = floatingLayout([
      { id: "w1", stack: ["a", "b", "c"], stackWeights: { a: 1, b: 1, c: 1 } },
    ]);
    const out = setStackWeights(l, "w1", { b: 5 });
    const win = out.floating.find((w) => w.id === "w1")!;
    // a and c untouched; b replaced.
    expect(win.stackWeights).toEqual({ a: 1, b: 5, c: 1 });
  });

  it("ignores incoming missing groups and prunes existing stale keys", () => {
    const l = floatingLayout([
      {
        id: "w1",
        stack: ["a", "b"],
        stackWeights: { a: 2, stale: 9 },
      },
    ]);

    const out = setStackWeights(l, "w1", { b: 3, missing: 4 });

    expect(out.floating[0].stackWeights).toEqual({ a: 2, b: 3 });
  });

  it("rejects non-finite and non-positive weights (entry is not written)", () => {
    const l = floatingLayout([
      { id: "w1", stack: ["a", "b"], stackWeights: { a: 4 } },
    ]);
    const out = setStackWeights(l, "w1", {
      a: 0, // non-positive -> rejected, existing 4 kept
      b: -3, // non-positive -> rejected, not added
    });
    const win = out.floating.find((w) => w.id === "w1")!;
    expect(win.stackWeights).toEqual({ a: 4 });

    const out2 = setStackWeights(l, "w1", {
      b: Number.POSITIVE_INFINITY,
    });
    expect(out2.floating.find((w) => w.id === "w1")!.stackWeights).toEqual({
      a: 4,
    });

    const out3 = setStackWeights(l, "w1", { b: NaN });
    expect(out3.floating.find((w) => w.id === "w1")!.stackWeights).toEqual({
      a: 4,
    });
  });
});

describe("restoreStackWeights", () => {
  it("restores an absent map and auto-height to exact layout equality", () => {
    const original = floatingLayout([{ id: "w1", stack: ["a", "b"] }]);
    const resized = resizeWindowHeight(
      setStackWeights(original, "w1", { a: 120, b: 80 }),
      "w1",
      240,
    );

    const restored = resizeWindowHeight(
      restoreStackWeights(resized, "w1", ["a", "b"], undefined),
      "w1",
      undefined,
    );

    expect(restored).toEqual(original);
    expect("stackWeights" in restored.floating[0]).toBe(false);
  });

  it("preserves added groups while never restoring or retaining removed groups", () => {
    const restructured = floatingLayout([
      {
        id: "w1",
        stack: ["a", "c"],
        stackWeights: { a: 120, b: 80, c: 7 },
      },
    ]);

    const restored = restoreStackWeights(restructured, "w1", ["a", "b"], {
      a: 2,
      b: 3,
    });

    expect(restored.floating[0].stackWeights).toEqual({ a: 2, c: 7 });
  });
});

// regression: a group leaving a floating window used to leave its key behind
// in the window's stackWeights; a later snap-in of a DIFFERENT group with a
// recycled id (or just inspection of the record) would see the stale weight.
describe("detaching a group releases its stack weight", () => {
  it("snapping a group from one stack to another prunes it from the source", () => {
    const l = floatingLayout([
      { id: "w1", stack: ["a", "b"], stackWeights: { a: 100, b: 200 } },
      { id: "w2", stack: ["c"] },
    ]);
    l.floating[0].height = 300;
    const out = snapToWindowStack(l, ["b"], "w2", 0);
    const w1 = out.floating.find((w) => w.id === "w1")!;
    expect(w1.stackWeights).toEqual({ a: 100 });
    expect(out.floating.find((w) => w.id === "w2")!.stack).toEqual(["b", "c"]);
  });
});

describe("reorderTab", () => {
  it("moves a panel to a new index", () => {
    const layout = makeLayout({ left: leaf("g"), groups: { g: 3 } });
    const out = reorderTab(layout, "g", "g:0", 2);
    expect(out.groups["g"].panelIds).toEqual(["g:1", "g:2", "g:0"]);
  });
});

describe("toggleCollapsed", () => {
  it("clears the parent-minimize tag (user takes individual control)", () => {
    let layout = makeLayout({ floating: [{ id: "w1", stack: ["a", "b"] }] });
    layout = minimizeStack(layout, ["a", "b"]);
    const out = toggleCollapsed(layout, "a");
    expect(out.groups["a"].collapsed).toBe(false);
    expect(out.groups["a"].collapsedByParent).toBeUndefined();
    // b keeps its tag: it is still "minimized by the parent".
    expect(out.groups["b"].collapsedByParent).toBe(true);
  });
});

describe("minimizeStack / expandStack", () => {
  const stacked = () =>
    makeLayout({ floating: [{ id: "w1", stack: ["a", "b", "c"] }] });

  it("a mixed min/max arrangement round-trips through minimize/expand", () => {
    // a + b minimized individually, c expanded.
    let layout = toggleCollapsed(toggleCollapsed(stacked(), "a"), "b");
    layout = minimizeStack(layout, ["a", "b", "c"]);
    for (const g of ["a", "b", "c"])
      expect(layout.groups[g].collapsed).toBe(true);
    // Only c (expanded at minimize time) is tagged for restore.
    expect(layout.groups["a"].collapsedByParent).toBeUndefined();
    expect(layout.groups["b"].collapsedByParent).toBeUndefined();
    expect(layout.groups["c"].collapsedByParent).toBe(true);

    const out = expandStack(layout, ["a", "b", "c"]);
    expect(out.groups["a"].collapsed).toBe(true);
    expect(out.groups["b"].collapsed).toBe(true);
    expect(out.groups["c"].collapsed).toBe(false);
  });

  it("re-minimizing re-tags from the CURRENT mix, not stale history", () => {
    // Minimize all (everything tagged), then the user expands b by hand.
    let layout = minimizeStack(stacked(), ["a", "b", "c"]);
    layout = toggleCollapsed(layout, "b");
    // Second minimize-all: only b was expanded, so only b is tagged; a and
    // c's tags from the FIRST minimize are reset.
    layout = minimizeStack(layout, ["a", "b", "c"]);
    expect(layout.groups["a"].collapsedByParent).toBeUndefined();
    expect(layout.groups["b"].collapsedByParent).toBe(true);
    expect(layout.groups["c"].collapsedByParent).toBeUndefined();
    const out = expandStack(layout, ["a", "b", "c"]);
    expect(out.groups["a"].collapsed).toBe(true);
    expect(out.groups["b"].collapsed).toBe(false);
    expect(out.groups["c"].collapsed).toBe(true);
  });

  it("expand with no tags (all minimized individually) expands everything", () => {
    let layout = stacked();
    for (const g of ["a", "b", "c"]) layout = toggleCollapsed(layout, g);
    const out = expandStack(layout, ["a", "b", "c"]);
    for (const g of ["a", "b", "c"])
      expect(out.groups[g].collapsed).toBe(false);
  });
});

describe("setActiveTab", () => {
  it("activates a member panel", () => {
    const layout = makeLayout({ left: leaf("g"), groups: { g: 3 } });
    const out = setActiveTab(layout, "g", "g:2");
    expect(out.groups["g"].activeId).toBe("g:2");
  });
});

describe("moveWindow", () => {
  it("deep-clones own prototype-named keys without invoking setters", () => {
    const layout = floatingLayout([{ id: "w1", stack: ["a"] }]);
    Object.defineProperty(layout.groups, "__proto__", {
      configurable: true,
      enumerable: true,
      value: { id: "__proto__", panelIds: ["x"], activeId: "x" },
      writable: true,
    });

    const output = moveWindow(layout, "w1", 30, 40);
    expect(Object.getPrototypeOf(output.groups)).toBeNull();
    expect(Object.hasOwn(output.groups, "__proto__")).toBe(true);
    expect(output.groups.__proto__.id).toBe("__proto__");
  });
  it("sets position", () => {
    const layout = makeLayout({
      floating: [{ id: "w1", stack: ["a"], x: 0, y: 0 }],
    });
    const out = moveWindow(layout, "w1", 30, 40);
    expect(out.floating[0]).toMatchObject({ x: 30, y: 40 });
  });
});

describe("resizeWindow", () => {
  it("sets width and x for a left-edge resize", () => {
    const layout = makeLayout({
      floating: [{ id: "w1", stack: ["a"], x: 5, width: 100 }],
    });
    const out = resizeWindow(layout, "w1", 200, 50);
    expect(out.floating[0]).toMatchObject({ width: 200, x: 50 });
  });
});

describe("resizeWindowHeight", () => {
  it("restores auto-height by removing the explicit height field", () => {
    const layout = makeLayout({
      floating: [{ id: "w1", stack: ["a"], y: 10, height: 333 }],
    });
    const out = resizeWindowHeight(layout, "w1", undefined, 42);
    expect("height" in out.floating[0]).toBe(false);
    expect(out.floating[0].y).toBe(42);
  });
});

describe("numeric geometry validation", () => {
  const layout = () => {
    const value = emptyLayout();
    value.groups = { a: group("a") };
    value.floating = [
      { id: "w1", x: 0, y: 0, width: 260, height: 200, stack: ["a"] },
    ];
    return value;
  };

  it("rejects non-finite window positions", () => {
    const value = layout();
    expect(moveWindow(value, "w1", Number.NaN, 1)).toBe(value);
    expect(moveWindow(value, "w1", 1, Number.POSITIVE_INFINITY)).toBe(value);
  });

  it("rejects non-positive or non-finite widths and invalid left edges", () => {
    const value = layout();
    expect(resizeWindow(value, "w1", Number.NaN)).toBe(value);
    expect(resizeWindow(value, "w1", 0)).toBe(value);
    expect(resizeWindow(value, "w1", -1)).toBe(value);
    expect(resizeWindow(value, "w1", 100, Number.NEGATIVE_INFINITY)).toBe(
      value,
    );
  });

  it("rejects non-positive or non-finite heights and invalid top edges", () => {
    const value = layout();
    expect(resizeWindowHeight(value, "w1", Number.NaN)).toBe(value);
    expect(resizeWindowHeight(value, "w1", 0)).toBe(value);
    expect(resizeWindowHeight(value, "w1", -1)).toBe(value);
    expect(resizeWindowHeight(value, "w1", 100, Number.NaN)).toBe(value);
  });
});

// ===========================================================================
// cascadeResize -- the pure cascading-divider resize shared by docked splits
// and floating snap-stacks (regression pins for grow/shrink conservation,
// min-floor push-through, collapsed-cell exclusion, no-op guards).
//
// Returns per-cell pixel sizes (collapsed -> 0), conserving the live total, or
// null on a no-op. Grow side: deltaPx>0 grows cell `dividerIndex`, taking from
// later siblings in order (push-through); deltaPx<0 grows `dividerIndex+1`,
// taking from earlier siblings in order. Floors the shrink side at `minCell`.
// ===========================================================================
describe("cascadeResize", () => {
  // Sum the live (non-zero) cells. With no collapsed cells this equals the
  // whole container; with collapsed cells (-> 0) it equals the live remainder.
  const liveTotal = (cells: number[]) => cells.reduce((s, c) => s + c, 0);

  it("floors the shrink side at minCell, then pushes through to the next sibling", () => {
    // Three equal cells in 900px -> 300 each. Drag divider 0 right hard (+1000).
    // Cell 1 can only give down to minCell (220), i.e. 80px; the rest of the
    // demand pushes through to cell 2. Total is conserved.
    const min = MIN_PANEL_WIDTH_PX; // 220
    const next = cascadeResize({
      weights: [1, 1, 1],
      collapsed: [false, false, false],
      containerPx: 900,
      dividerIndex: 0,
      deltaPx: 1000,
      minCell: min,
      maxCell: Infinity,
    })!;
    // Siblings 1 and 2 are floored at minCell; cell 0 absorbs the rest.
    expect(next[1]).toBeCloseTo(min, 5);
    expect(next[2]).toBeCloseTo(min, 5);
    expect(next[0]).toBeCloseTo(900 - 2 * min, 5);
    expect(liveTotal(next)).toBeCloseTo(900, 5);
    // And no cell dipped below the floor.
    expect(Math.min(...next)).toBeGreaterThanOrEqual(min - 1e-6);
  });

  it("excludes collapsed cells: they stay 0 and neither give nor take space", () => {
    // Three cells, the middle one collapsed. Live total comes from cells 0 and 2
    // only (1000 split 500/500); the collapsed cell renders at 0 here. Dragging
    // divider 0 right must shrink cell 2 (the next LIVE sibling), skipping cell 1.
    const next = cascadeResize({
      weights: [1, 1, 1],
      collapsed: [false, true, false],
      containerPx: 1000,
      dividerIndex: 0,
      deltaPx: 100,
      minCell: MIN_PANEL_WIDTH_PX,
      maxCell: Infinity,
    })!;
    expect(next[1]).toBe(0); // collapsed -> 0
    expect(next[0]).toBeCloseTo(600, 5);
    expect(next[2]).toBeCloseTo(400, 5);
    // Live total (excluding the collapsed cell) is conserved.
    expect(liveTotal(next)).toBeCloseTo(1000, 5);
  });

  it("caps the grow side at maxCell (excess demand is dropped)", () => {
    // Two cells 500/500 in 1000px, maxCell 600. Drag right by 300: cell 0 can
    // only reach 600 (its cap), so it takes just 100 from cell 1 (-> 400). The
    // surplus 200 of demand is dropped (the boundary stops at the cap).
    const next = cascadeResize({
      weights: [1, 1],
      collapsed: [false, false],
      containerPx: 1000,
      dividerIndex: 0,
      deltaPx: 300,
      minCell: MIN_PANEL_WIDTH_PX,
      maxCell: 600,
    })!;
    expect(next[0]).toBeCloseTo(600, 5);
    expect(next[1]).toBeCloseTo(400, 5);
  });
});

// ===========================================================================
// resizeRegionColumns -- region-edge resize redistributes across columns.
//
// regression: with [wide][narrow][wide] columns, shrinking used to lock up as
// soon as the narrow column hit its minimum, even though the wide neighbours
// had plenty of room. The redistribution clamps violators and hands the
// difference to columns that still have room.
// ===========================================================================
describe("resizeRegionColumns", () => {
  const M = MIN_PANEL_WIDTH_PX;

  it("keeps shrinking past one column's minimum (wide-narrow-wide)", () => {
    // 400 + 220 + 400 = 1020; shrink to 900. The narrow middle column is
    // already at its minimum; the wide columns absorb the whole reduction.
    const w = resizeRegionColumns(
      [400, M, 400],
      [M, M, M],
      [600, 600, 600],
      900,
    );
    expect(w[1]).toBeCloseTo(M); // clamped, not below
    expect(w[0]).toBeCloseTo((900 - M) / 2);
    expect(w[2]).toBeCloseTo((900 - M) / 2);
    expect(w[0] + w[1] + w[2]).toBeCloseTo(900);
  });

  it("keeps growing past one column's maximum", () => {
    // Growing: the column at max stays there; others take the surplus.
    const w = resizeRegionColumns(
      [580, 300, 300],
      [M, M, M],
      [600, 600, 600],
      1400,
    );
    expect(w[0]).toBeCloseTo(600); // clamped at max
    expect(w[1] + w[2]).toBeCloseTo(800);
    expect(w[1]).toBeCloseTo(400);
    expect(w[2]).toBeCloseTo(400);
  });

  it("clamps the target to the columns' aggregate bounds", () => {
    const w = resizeRegionColumns([300, 300], [M, M], [600, 600], 100);
    expect(w[0] + w[1]).toBeCloseTo(2 * M);
    const w2 = resizeRegionColumns([300, 300], [M, M], [600, 600], 5000);
    expect(w2[0] + w2[1]).toBeCloseTo(1200);
  });

  it("cascades: redistribution can push a second column to its limit", () => {
    // Shrink hard: middle hits min first, then the small-ish first column
    // also bottoms out; the wide last column absorbs the rest.
    const w = resizeRegionColumns(
      [260, M, 500],
      [M, M, M],
      [600, 600, 600],
      700,
    );
    expect(w[0]).toBeCloseTo(M);
    expect(w[1]).toBeCloseTo(M);
    expect(w[2]).toBeCloseTo(700 - 2 * M);
  });
});

describe("bringToFront", () => {
  it("moves a window to the end (topmost) of the paint order", () => {
    const layout = makeLayout({
      floating: [
        { id: "w1", stack: ["a"] },
        { id: "w2", stack: ["b"] },
        { id: "w3", stack: ["c"] },
      ],
    });
    const out = bringToFront(layout, "w1");
    expect(out.floating.map((w) => w.id)).toEqual(["w2", "w3", "w1"]);
  });
});
