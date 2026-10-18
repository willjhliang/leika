import { describe, expect, it } from "vitest";

import { colorFormatPreference } from "../components/colorFormatPreference";
import { previewFlag } from "../components/previewFlags";
import { persisted, type PersistedStorage } from "./persisted";

class MemoryStorage implements PersistedStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThrowingStorage implements PersistedStorage {
  getItem(): string | null {
    throw new Error("storage unavailable");
  }

  setItem(): void {
    throw new Error("storage unavailable");
  }
}

const count = (stored: unknown) => (typeof stored === "number" ? stored : 0);

describe("persisted", () => {
  it("restores a value after a reload and notifies readers", () => {
    const storage = new MemoryStorage();
    const before = persisted("count", count, storage);
    let notified = 0;
    before.subscribe(() => (notified += 1));
    before.set(3);
    expect(notified).toBe(1);
    expect(persisted("count", count, storage).get()).toBe(3);
  });

  it("parses malformed or unreadable storage to its default", () => {
    const storage = new MemoryStorage();
    storage.values.set("count", "{not json");
    expect(persisted("count", count, storage).get()).toBe(0);
    expect(persisted("count", count, new ThrowingStorage()).get()).toBe(0);
  });

  it("stays usable without writable storage", () => {
    for (const storage of [null, new ThrowingStorage()]) {
      const value = persisted("count", count, storage);
      value.set(5);
      expect(value.get()).toBe(5);
    }
  });

  it("keeps only valid preview keys and colour formats", () => {
    const storage = new MemoryStorage();
    storage.values.set("preview.flag", JSON.stringify(["notes.md", 4, null]));
    expect(previewFlag("preview.flag", storage).get()).toEqual(["notes.md"]);
    storage.values.set("leika.color-format.v1", JSON.stringify("cmyk"));
    expect(colorFormatPreference(storage).get()).toBe("hex");
  });
});
