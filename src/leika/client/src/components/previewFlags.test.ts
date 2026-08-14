import { describe, expect, it } from "vitest";

import {
  MAX_PREVIEW_FLAG_ENTRIES,
  MAX_PREVIEW_FLAG_KEY_CODE_UNITS,
  previewFlag,
  type PreviewFlagStorage,
} from "./previewFlags";

class MemoryStorage implements PreviewFlagStorage {
  readonly values = new Map<string, string>();

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

class ThrowingStorage implements PreviewFlagStorage {
  getItem(): string | null {
    throw new Error("storage unavailable");
  }

  setItem(): void {
    throw new Error("storage unavailable");
  }
}

describe("a persisted preview flag", () => {
  it("restores enabled preview keys after a reload", () => {
    const storage = new MemoryStorage();
    const beforeReload = previewFlag("preview.flag", storage);
    beforeReload.set("notes.md", true);
    beforeReload.set("field.png", true);

    const afterReload = previewFlag("preview.flag", storage);
    expect(afterReload.store.snapshot("notes.md")).toBe(true);
    expect(afterReload.store.snapshot("field.png")).toBe(true);
    expect(afterReload.store.snapshot("other.md")).toBe(false);
  });

  it("forgets a preview when its toggle returns to the default", () => {
    const storage = new MemoryStorage();
    const flag = previewFlag("preview.flag", storage);
    flag.set("notes.md", true);
    flag.set("field.png", true);
    flag.set("notes.md", false);

    expect(JSON.parse(storage.values.get("preview.flag")!)).toEqual([
      "field.png",
    ]);
    expect(
      previewFlag("preview.flag", storage).store.snapshot("notes.md"),
    ).toBe(false);
  });

  it("ignores malformed stored values", () => {
    const storage = new MemoryStorage();
    for (const value of ["{not json", "null", '{"notes.md":true}']) {
      storage.values.set("preview.flag", value);
      expect(
        previewFlag("preview.flag", storage).store.snapshot("notes.md"),
      ).toBe(false);
    }
  });

  it("bounds stored and newly added keys", () => {
    const storage = new MemoryStorage();
    storage.values.set(
      "preview.flag",
      JSON.stringify(
        Array.from(
          { length: MAX_PREVIEW_FLAG_ENTRIES + 1 },
          (_, index) => `file-${index}`,
        ),
      ),
    );
    expect(previewFlag("preview.flag", storage).store.snapshot("file-0")).toBe(
      false,
    );

    const flag = previewFlag("fresh.flag", storage);
    for (let index = 0; index < MAX_PREVIEW_FLAG_ENTRIES + 1; index += 1) {
      flag.set(`file-${index}`, true);
    }
    expect(flag.store.snapshot(`file-${MAX_PREVIEW_FLAG_ENTRIES - 1}`)).toBe(
      true,
    );
    expect(flag.store.snapshot(`file-${MAX_PREVIEW_FLAG_ENTRIES}`)).toBe(false);
    const oversized = "x".repeat(MAX_PREVIEW_FLAG_KEY_CODE_UNITS + 1);
    flag.set(oversized, true);
    expect(flag.store.snapshot(oversized)).toBe(false);
  });

  it("stays usable when storage is absent or inaccessible", () => {
    for (const storage of [null, new ThrowingStorage()]) {
      const flag = previewFlag("preview.flag", storage);
      flag.set("notes.md", true);
      expect(flag.store.snapshot("notes.md")).toBe(true);
    }
  });
});
