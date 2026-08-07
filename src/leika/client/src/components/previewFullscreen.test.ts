import { afterEach, describe, expect, it, vi } from "vitest";

import {
  previewFullscreenStore,
  previewMediaClassName,
  setPreviewFullscreen,
} from "./previewFullscreen";

afterEach(() => {
  // Module state on purpose, so a test that leaves a key set would hand the
  // next one a full-window preview it never asked for.
  for (const key of ["notes.md", "field.png", "pane-1"]) {
    setPreviewFullscreen(key, false);
  }
});

describe("the fullscreen flag", () => {
  it("outlives the preview that set it", () => {
    // The whole point. Closing a preview does not put the flag back, so the
    // next look at the SAME thing opens the way the last one was left.
    setPreviewFullscreen("notes.md", true);
    expect(previewFullscreenStore.snapshot("notes.md")).toBe(true);
    setPreviewFullscreen("notes.md", false);
    expect(previewFullscreenStore.snapshot("notes.md")).toBe(false);
  });

  it("says nothing about anything else", () => {
    // The correction this exists for. Enlarging one file is a decision about
    // that file being hard to read at the size it opens; the next file is a
    // different file, and opens small until somebody says otherwise.
    setPreviewFullscreen("notes.md", true);
    expect(previewFullscreenStore.snapshot("field.png")).toBe(false);
    expect(previewFullscreenStore.snapshot("pane-1")).toBe(false);

    setPreviewFullscreen("field.png", true);
    setPreviewFullscreen("notes.md", false);
    // And putting one back does not put the others back with it.
    expect(previewFullscreenStore.snapshot("field.png")).toBe(true);
  });

  it("remembers nothing about a preview nobody enlarged", () => {
    expect(previewFullscreenStore.snapshot("never-opened.txt")).toBe(false);
  });

  it("tells its readers when it changes, and only then", () => {
    const listener = vi.fn();
    const stop = previewFullscreenStore.subscribe(listener);

    setPreviewFullscreen("notes.md", true);
    expect(listener).toHaveBeenCalledTimes(1);

    // Setting a key to what it already holds is not a change. Every preview
    // that mounts reads this; waking each other reader for a no-op would
    // re-render them all for nothing.
    setPreviewFullscreen("notes.md", true);
    expect(listener).toHaveBeenCalledTimes(1);

    setPreviewFullscreen("notes.md", false);
    expect(listener).toHaveBeenCalledTimes(2);

    stop();
    setPreviewFullscreen("notes.md", true);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe("previewMediaClassName", () => {
  it("fills the popup's width windowed, and sets its own height", () => {
    // The popup is already the shape of the picture, so there is nothing to
    // fit the picture into.
    const windowed = previewMediaClassName(false);
    expect(windowed).toContain("w-full");
    expect(windowed).toContain("h-auto");
    expect(windowed).not.toContain("object-contain");
  });

  it("takes the whole window and fits the picture inside it", () => {
    // The window is not the shape of the picture, so the element takes the
    // area and `object-contain` letterboxes what is drawn in it. Without
    // `h-full` a portrait ran off the bottom of the screen.
    const full = previewMediaClassName(true);
    expect(full).toContain("h-full");
    expect(full).toContain("w-full");
    expect(full).toContain("object-contain");
  });

  it("drops the corner radius where there is no corner", () => {
    expect(previewMediaClassName(false)).toContain("rounded-lg");
    expect(previewMediaClassName(true)).not.toContain("rounded");
  });

  it("never asks for a height twice", () => {
    // The two sizings are a branch rather than one class list with `in-*`
    // variants on it, because Tailwind wraps an `in-*` ancestor in `:where()`
    // and the override then ties on specificity with the utility it is meant
    // to beat -- `h-full` lost to `h-auto` and the picture overflowed. A list
    // carrying both is that bug coming back.
    for (const fullscreen of [false, true]) {
      const heights = previewMediaClassName(fullscreen)
        .split(" ")
        .filter((name) => name.startsWith("h-"));
      expect(heights).toHaveLength(1);
    }
  });
});
