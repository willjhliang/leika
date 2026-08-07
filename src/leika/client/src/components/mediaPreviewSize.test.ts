import { describe, expect, it } from "vitest";

import { mediaPreviewWidth } from "./mediaPreviewSize";

describe("mediaPreviewWidth", () => {
  it("opens at the picture's own width", () => {
    expect(mediaPreviewWidth({ width: 1600, height: 900 })).toBe(
      "min(90vw, calc((100dvh - 6rem) * 1.7777777777777777), 1600px)",
    );
  });

  it("brings a small picture up to the floor, not to a postage stamp", () => {
    // 880, not 8: a thumbnail fills the popup instead of sitting in the
    // middle of one.
    expect(mediaPreviewWidth({ width: 8, height: 6 })).toContain(", 880px)");
  });

  it("lets the window's height talk a tall picture down", () => {
    // The term that makes a portrait fit. 0.5 of the height left over is a
    // narrower popup than either the floor or the window's width would give,
    // and `min` takes it -- so the whole picture is on screen rather than
    // scrolled to.
    expect(mediaPreviewWidth({ width: 520, height: 1040 })).toBe(
      "min(90vw, calc((100dvh - 6rem) * 0.5), 880px)",
    );
  });

  it("never opens wider than the window", () => {
    // A 4K frame does not open a popup wider than the screen it is being
    // looked at on.
    expect(mediaPreviewWidth({ width: 3840, height: 2160 })).toContain(
      "min(90vw,",
    );
  });

  it("opens at the floor when there is no size to read", () => {
    // Audio, which has none, and anything still being decoded. No aspect
    // ratio means no way to convert the window's height, so all that is left
    // is "as much as fits".
    expect(mediaPreviewWidth(null)).toBe("min(90vw, 880px)");
  });
});
