import { describe, expect, it } from "vitest";

import {
  COLOR_FORMAT_STORAGE_KEY,
  createColorFormatPreference,
  type ColorFormatStorage,
} from "./colorFormatPreference";

class MemoryStorage implements ColorFormatStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThrowingStorage implements ColorFormatStorage {
  getItem(): string | null {
    throw new Error("storage unavailable");
  }

  setItem(): void {
    throw new Error("storage unavailable");
  }
}

describe("the color format preference", () => {
  it("restores the last selected format", () => {
    const storage = new MemoryStorage();
    createColorFormatPreference(storage).set("hsl");

    const restored = createColorFormatPreference(storage);
    expect(restored.store.snapshot()).toBe("hsl");
    expect(storage.values.get(COLOR_FORMAT_STORAGE_KEY)).toBe("hsl");
  });

  it("falls back to hex for an unknown stored format", () => {
    const storage = new MemoryStorage();
    storage.values.set(COLOR_FORMAT_STORAGE_KEY, "cmyk");
    expect(createColorFormatPreference(storage).store.snapshot()).toBe("hex");
  });

  it("stays usable without writable storage", () => {
    for (const storage of [null, new ThrowingStorage()]) {
      const preference = createColorFormatPreference(storage);
      preference.set("css");
      expect(preference.store.snapshot()).toBe("css");
    }
  });
});
