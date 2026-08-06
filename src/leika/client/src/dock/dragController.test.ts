import { describe, expect, it } from "vitest";

import {
  expandPlacementChanges,
  floatingStackGroupElements,
} from "./dragController";
import { floatGroup } from "./layoutOps";
import { group, leaf } from "./testUtils";
import { DockLayout, PanelRegistry, emptyLayout } from "./types";

function groupElement(groupId: string): Element {
  return {
    getAttribute: (name: string) =>
      name === "data-dock-group" ? groupId : null,
  } as unknown as Element;
}

describe("floatingStackGroupElements", () => {
  it("leaves nested area groups to the area collector and preserves stack indices", () => {
    const first = groupElement("first");
    const nestedArea = groupElement("nested-area");
    const second = groupElement("second");
    const windowElement = {
      querySelectorAll: () => [first, nestedArea, second],
    } as unknown as Element;

    const targets = floatingStackGroupElements(windowElement, [
      "first",
      "second",
    ]);

    expect(targets).toEqual([
      { element: first, index: 0 },
      { element: second, index: 1 },
    ]);
  });
});

describe("expandPlacementChanges", () => {
  /** Group "a" folded and docked left -- the rail stub a drag picks up. */
  function dockedFolded(): DockLayout {
    const layout = emptyLayout();
    layout.groups = { a: group("a", 1, true) };
    layout.docked.left = leaf("a");
    return layout;
  }
  /** Group "a" folded in its own floating window. */
  function floatingFolded(): DockLayout {
    const layout = emptyLayout();
    layout.groups = { a: group("a", 1, true) };
    layout.floating = [{ id: "w1", x: 0, y: 0, width: 300, stack: ["a"] }];
    return layout;
  }

  it("expands a folded group dropped from docked to floating", () => {
    const origin = dockedFolded();
    const floated = floatGroup(origin, "a", 10, 10, 300).layout;
    const next = expandPlacementChanges(floated, origin, {}, ["a"], {
      kind: "floating",
    });
    expect(next.groups["a"].collapsed).not.toBe(true);
  });

  it("expands a folded group docked onto a different edge", () => {
    const origin = dockedFolded();
    const next = expandPlacementChanges(origin, origin, {}, ["a"], {
      kind: "docked",
      edge: "right",
    });
    expect(next.groups["a"].collapsed).not.toBe(true);
  });

  it("keeps the fold when the drop lands back on the same edge", () => {
    const origin = dockedFolded();
    const next = expandPlacementChanges(origin, origin, {}, ["a"], {
      kind: "docked",
      edge: "left",
    });
    expect(next.groups["a"].collapsed).toBe(true);
  });

  it("keeps the fold when a floating window is merely nudged", () => {
    const origin = floatingFolded();
    const next = expandPlacementChanges(origin, origin, {}, ["a"], {
      kind: "floating",
    });
    expect(next.groups["a"].collapsed).toBe(true);
  });

  it("gives a panel that owns its fold first refusal (onExpand)", () => {
    const origin = dockedFolded();
    const floated = floatGroup(origin, "a", 10, 10, 300).layout;
    let opened = 0;
    const panels: PanelRegistry = {
      "a.0": {
        id: "a.0",
        title: "A",
        render: () => null,
        onExpand: () => {
          opened += 1;
          return true;
        },
      },
    };
    const next = expandPlacementChanges(floated, origin, panels, ["a"], {
      kind: "floating",
    });
    expect(opened).toBe(1);
    // The group flag is the panel's sync's to clear, not ours.
    expect(next.groups["a"].collapsed).toBe(true);
  });
});
