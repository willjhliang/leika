import { describe, expect, it } from "vitest";

import * as ops from "./layoutOps";
import { normalizeDockLayout } from "./persistedLayout";
import { emptyLayout, type DockLayout } from "./types";

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
});
