import { afterEach, describe, expect, it, vi } from "vitest";

import {
  previewFullscreenStore,
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
