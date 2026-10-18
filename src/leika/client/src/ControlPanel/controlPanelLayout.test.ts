import { describe, expect, it } from "vitest";

import {
  createControlPanelSession,
  readControlPanelLayout,
  type ControlPanelStorage,
} from "./controlPanelLayout";

class MemoryStorage implements ControlPanelStorage {
  values = new Map<string, string>();
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
}

const KEY = "leika.control-panel:ws://one:lab";

describe("control panel session", () => {
  it("follows the theme until the viewer arranges the panel", () => {
    const session = createControlPanelSession(new MemoryStorage());
    session.sync("ws://one", "lab", "right");
    expect(session.store.get()).toMatchObject({
      placement: "right",
      width: 320,
      collapsed: false,
    });

    session.sync("ws://one", "lab", "left");
    expect(session.store.get().placement).toBe("left");

    session.save({ placement: "floating", right: 40, top: 60 });
    session.sync("ws://one", "lab", "right");
    expect(session.store.get()).toMatchObject({
      placement: "floating",
      right: 40,
      top: 60,
    });
  });

  it("remembers one arrangement per server and workspace", () => {
    const storage = new MemoryStorage();
    const first = createControlPanelSession(storage);
    first.sync("ws://one", "lab", "floating");
    first.preview({ width: 500 });
    expect(storage.values.size).toBe(0);
    first.save({ placement: "left", collapsed: true });

    const reloaded = createControlPanelSession(storage);
    reloaded.sync("ws://one", "lab", "right");
    expect(reloaded.store.get()).toEqual({
      placement: "left",
      right: 15,
      top: 15,
      width: 500,
      collapsed: true,
    });

    const other = createControlPanelSession(storage);
    other.sync("ws://one", "other", "right");
    expect(other.store.get().placement).toBe("right");
  });

  it("keeps the panel in place while the workspace is unknown", () => {
    const storage = new MemoryStorage();
    const session = createControlPanelSession(storage);
    session.sync("ws://one", "lab", "floating");
    session.save({ placement: "right" });

    session.sync("ws://one", null, "floating");
    expect(session.store.get().placement).toBe("right");
    session.save({ collapsed: true });
    expect(JSON.parse(storage.values.get(KEY)!).collapsed).toBe(false);
  });

  it("forgets the arrangement on reset", () => {
    const storage = new MemoryStorage();
    const session = createControlPanelSession(storage);
    session.sync("ws://one", "lab", "left");
    session.save({ placement: "floating", width: 400, collapsed: true });

    session.reset();
    expect(storage.values.has(KEY)).toBe(false);
    expect(session.store.get()).toMatchObject({
      placement: "left",
      width: 320,
      collapsed: false,
    });
    session.sync("ws://one", "lab", "right");
    expect(session.store.get().placement).toBe("right");
  });
});

describe("readControlPanelLayout", () => {
  it("ignores anything that is not a saved arrangement", () => {
    const storage = new MemoryStorage();
    for (const value of [
      "{not json",
      "null",
      JSON.stringify({ placement: "top", right: 0, top: 0, width: 320 }),
      JSON.stringify({ placement: "left", right: "0", top: 0, width: 320 }),
      JSON.stringify({ placement: "left", right: 0, top: 0, width: 320 }),
    ]) {
      storage.values.set(KEY, value);
      expect(readControlPanelLayout(storage, KEY)).toBeNull();
    }
    expect(readControlPanelLayout(null, KEY)).toBeNull();
  });

  it("clamps a saved width to the resizable range", () => {
    const storage = new MemoryStorage();
    storage.values.set(
      KEY,
      JSON.stringify({
        placement: "left",
        right: 0,
        top: 0,
        width: 5_000,
        collapsed: false,
      }),
    );
    expect(readControlPanelLayout(storage, KEY)?.width).toBe(600);
  });
});
