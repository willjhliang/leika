import { describe, expect, it } from "vitest";

import * as ops from "./layoutOps";
import { normalizeDockLayout } from "./persistedLayout";
import { emptyLayout, type DockLayout } from "./types";
import {
  MAX_LAYOUT_CHILDREN,
  MAX_LAYOUT_DEPTH,
  MAX_LAYOUT_ID_CODE_UNITS,
  MAX_LAYOUT_ITEMS,
} from "../persistenceLimits";

function validLayout(): DockLayout {
  let layout = ops.addFloatingPanel(
    emptyLayout(),
    "control",
    10,
    20,
    320,
  ).layout;
  layout = ops.addPanelToArea(layout, "tabs", "alpha");
  layout = ops.addPanelToArea(layout, "tabs", "beta");
  return layout;
}

function copy(layout: DockLayout): DockLayout {
  return JSON.parse(JSON.stringify(layout)) as DockLayout;
}

describe("normalizeDockLayout", () => {
  it("round-trips a valid serializable layout", () => {
    const layout = validLayout();
    expect(normalizeDockLayout(copy(layout))).toEqual(layout);
  });

  it("accepts an empty area backing group", () => {
    const layout = ops.removePanel(validLayout(), "alpha");
    const empty = ops.removePanel(layout, "beta");
    expect(normalizeDockLayout(copy(empty))).toEqual(empty);
  });

  it("rejects invalid active tabs, references, and duplicate ownership", () => {
    const wrongActive = copy(validLayout());
    const areaGroup = wrongActive.areas!.tabs.group;
    wrongActive.groups[areaGroup].activeId = "missing";

    const missingGroup = copy(validLayout());
    missingGroup.floating[0].stack = ["missing"];

    const duplicateOwner = copy(validLayout());
    duplicateOwner.floating[0].stack.push(areaGroup);

    expect(normalizeDockLayout(wrongActive)).toBeNull();
    expect(normalizeDockLayout(missingGroup)).toBeNull();
    expect(normalizeDockLayout(duplicateOwner)).toBeNull();
  });

  it("rejects non-finite or malformed geometry", () => {
    const infinite = copy(validLayout());
    infinite.floating[0].x = Number.POSITIVE_INFINITY;

    expect(normalizeDockLayout(infinite)).toBeNull();
    expect(normalizeDockLayout(null)).toBeNull();
    expect(normalizeDockLayout({ groups: {} })).toBeNull();
  });

  it("rejects deep, broad, cyclic, and oversized persisted structures", () => {
    const deep = copy(validLayout()) as unknown as Record<string, unknown>;
    const groups: Record<string, unknown> = {};
    let node: Record<string, unknown> = {
      type: "leaf",
      id: "last-leaf",
      group: "last-group",
      weight: 1,
    };
    groups["last-group"] = {
      id: "last-group",
      panelIds: ["last-panel"],
      activeId: "last-panel",
    };
    for (let depth = MAX_LAYOUT_DEPTH; depth >= 0; depth -= 1) {
      const siblingGroup = `sibling-group-${depth}`;
      groups[siblingGroup] = {
        id: siblingGroup,
        panelIds: [`sibling-panel-${depth}`],
        activeId: `sibling-panel-${depth}`,
      };
      node = {
        type: "split",
        id: `split-${depth}`,
        dir: "row",
        weight: 1,
        children: [
          node,
          {
            type: "leaf",
            id: `sibling-leaf-${depth}`,
            group: siblingGroup,
            weight: 1,
          },
        ],
      };
    }
    deep.groups = groups;
    deep.docked = { left: node, right: null };
    deep.floating = [];
    deep.areas = {};
    expect(normalizeDockLayout(deep)).toBeNull();

    const broad = copy(validLayout());
    broad.floating[0].stack = Array.from(
      { length: MAX_LAYOUT_CHILDREN + 1 },
      (_, index) => `group-${index}`,
    );
    expect(normalizeDockLayout(broad)).toBeNull();

    const cyclic = copy(validLayout()) as unknown as Record<string, unknown>;
    const cycle: Record<string, unknown> = {
      type: "split",
      id: "cycle",
      dir: "row",
      weight: 1,
      children: [],
    };
    (cycle.children as unknown[]).push(cycle, cycle);
    cyclic.docked = { left: cycle, right: null };
    expect(normalizeDockLayout(cyclic)).toBeNull();

    const oversizedId = copy(validLayout());
    const group = oversizedId.groups[oversizedId.floating[0].stack[0]];
    group.panelIds[0] = "x".repeat(MAX_LAYOUT_ID_CODE_UNITS + 1);
    expect(normalizeDockLayout(oversizedId)).toBeNull();

    const tooManyGroups = copy(validLayout()) as unknown as Record<
      string,
      unknown
    >;
    tooManyGroups.groups = Object.fromEntries(
      Array.from({ length: MAX_LAYOUT_ITEMS + 1 }, (_, index) => [
        `g-${index}`,
        { id: `g-${index}`, panelIds: [], activeId: "" },
      ]),
    );
    expect(normalizeDockLayout(tooManyGroups)).toBeNull();
  });

  it("rejects prototype-named persisted IDs as a whole", () => {
    const raw = JSON.parse(JSON.stringify(validLayout())) as DockLayout;
    const [groupId] = raw.floating[0].stack;
    const group = raw.groups[groupId];
    delete raw.groups[groupId];
    Object.defineProperty(raw.groups, "__proto__", {
      configurable: true,
      enumerable: true,
      value: { ...group, id: "__proto__" },
      writable: true,
    });
    raw.floating[0].stack = ["__proto__"];
    expect(normalizeDockLayout(raw)).toBeNull();
    const surrogate = JSON.parse(JSON.stringify(validLayout())) as DockLayout;
    surrogate.groups[surrogate.floating[0].stack[0]].panelIds[0] = "\ud800";
    expect(normalizeDockLayout(surrogate)).toBeNull();
  });
});
