import { describe, expect, it } from "vitest";

import * as ops from "../dock/layoutOps";
import {
  emptyLayout,
  type DockLayout,
  type PanelRegistry,
  type PanelSpec,
} from "../dock/types";
import {
  controlDockLayoutStorageKey,
  readControlDockLayout,
  reconcileControlDockLayout,
  type ControlDockLayoutStorage,
} from "./controlDockPersistenceModel";

class MemoryStorage implements ControlDockLayoutStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

function panel(id: string): PanelSpec {
  return { id, title: id, render: () => null };
}

function currentLayout(): DockLayout {
  let layout = ops.addFloatingPanel(
    emptyLayout(),
    "control",
    600,
    15,
    320,
  ).layout;
  for (const id of ["alpha", "beta", "gamma"]) {
    layout = ops.addPanelToArea(layout, "tabs", id);
  }
  return layout;
}

function storedLayout(): DockLayout {
  let layout = currentLayout();
  layout = ops.removePanel(layout, "gamma");
  layout = ops.removePanel(layout, "alpha");
  layout = ops.addFloatingPanel(layout, "alpha", 100, 80, 280).layout;
  layout = ops.addFloatingPanel(layout, "removed", 150, 120, 260).layout;
  return layout;
}

describe("control dock persistence", () => {
  it("names layouts by server and workspace", () => {
    expect(controlDockLayoutStorageKey("ws://one", "lab")).not.toBe(
      controlDockLayoutStorageKey("ws://one", "other"),
    );
    expect(controlDockLayoutStorageKey("ws://one", "lab")).not.toBe(
      controlDockLayoutStorageKey("ws://two", "lab"),
    );
  });

  it("reads only valid stored layouts", () => {
    const storage = new MemoryStorage();
    const key = controlDockLayoutStorageKey("ws://one", "lab");
    const layout = storedLayout();
    storage.values.set(key, JSON.stringify(layout));
    expect(readControlDockLayout(storage, key)).toEqual(layout);

    storage.values.set(key, "{not json");
    expect(readControlDockLayout(storage, key)).toBeNull();
  });

  it("prunes removed panels and homes newly introduced panels", () => {
    const current = currentLayout();
    const panels: PanelRegistry = Object.fromEntries(
      ["control", "alpha", "beta", "gamma"].map((id) => [id, panel(id)]),
    );
    const reconciled = reconcileControlDockLayout(
      storedLayout(),
      current,
      panels,
    );

    expect(ops.findPanelGroup(reconciled, "removed")).toBeNull();
    const alphaGroup = ops.findPanelGroup(reconciled, "alpha");
    const gammaGroup = ops.findPanelGroup(reconciled, "gamma");
    expect(alphaGroup).not.toBeNull();
    expect(gammaGroup).not.toBeNull();
    expect(ops.findGroupLocation(reconciled, alphaGroup!)).toMatchObject({
      kind: "floating",
    });
    expect(ops.findGroupLocation(reconciled, gammaGroup!)).toEqual({
      kind: "area",
      areaId: "tabs",
    });
  });
});
