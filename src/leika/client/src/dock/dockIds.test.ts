import { describe, expect, it } from "vitest";

import { createDockIdAllocator } from "./dockIds";
import { emptyLayout } from "./types";

describe("createDockIdAllocator", () => {
  it("skips ids restored in every layout namespace and reserves new ids", () => {
    const layout = emptyLayout();
    layout.groups["group-restored"] = {
      id: "group-restored",
      panelIds: ["panel-a"],
      activeId: "panel-a",
    };
    layout.groups["group-floating"] = {
      id: "group-floating",
      panelIds: ["panel-b"],
      activeId: "panel-b",
    };
    layout.docked.left = {
      type: "leaf",
      id: "node-restored",
      group: "group-restored",
      weight: 1,
    };
    layout.floating.push({
      id: "window-restored",
      x: 0,
      y: 0,
      width: 300,
      stack: ["group-floating"],
    });

    const candidates = {
      group: ["group-restored", "group-new", "group-new", "group-next"],
      node: ["node-restored", "node-new"],
      window: ["window-restored", "window-new"],
    };
    const allocateId = createDockIdAllocator(layout, (prefix) => {
      const id = candidates[prefix].shift();
      if (id === undefined) throw new Error(`missing ${prefix} candidate`);
      return id;
    });

    expect(allocateId("group")).toBe("group-new");
    expect(allocateId("group")).toBe("group-next");
    expect(allocateId("node")).toBe("node-new");
    expect(allocateId("window")).toBe("window-new");
  });

  it("also treats a mismatched group record key as occupied", () => {
    const layout = emptyLayout();
    layout.groups["restored-key"] = {
      id: "restored-value",
      panelIds: ["panel"],
      activeId: "panel",
    };
    const candidates = ["restored-key", "restored-value", "group-new"];
    const allocateId = createDockIdAllocator(layout, () => candidates.shift()!);

    expect(allocateId("group")).toBe("group-new");
  });
});
