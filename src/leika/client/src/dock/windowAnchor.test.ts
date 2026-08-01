import { describe, expect, it } from "vitest";
import {
  anchorFloatingWindow,
  clampCorner,
  KEEP_VISIBLE_PX,
  translationOf,
} from "./windowAnchor";

// A 300x200 window, positioned per test. Rendered height (not the model
// height) is what anchoring reads, so tests set it explicitly.
const win = (x: number, y: number, width = 300, height = 200) => ({
  x,
  y,
  width,
  height,
});
const size = (width: number, height: number) => ({ width, height });

describe("clampCorner", () => {
  it("keeps the corner inside the container", () => {
    expect(clampCorner(50, 60, 1000, 800)).toEqual([50, 60]);
    expect(clampCorner(-20, -5, 1000, 800)).toEqual([0, 0]);
  });

  it("leaves a sliver of the corner reachable at the far edges", () => {
    expect(clampCorner(9999, 9999, 1000, 800)).toEqual([
      1000 - KEEP_VISIBLE_PX,
      800 - KEEP_VISIBLE_PX,
    ]);
  });

  it("pins to the origin in a container smaller than the reachable margin", () => {
    expect(clampCorner(10, 10, 20, 20)).toEqual([0, 0]);
  });
});

describe("anchorFloatingWindow", () => {
  it("only clamps on the observer's initial fire (no previous size)", () => {
    // No delta exists yet, so deliberate placement must survive untouched...
    expect(anchorFloatingWindow(win(700, 500), null, size(1000, 800))).toEqual([
      700, 500,
    ]);
    // ...but an off-container corner is still pulled back into reach.
    expect(anchorFloatingWindow(win(-30, 900), null, size(1000, 800))).toEqual([
      0,
      800 - KEEP_VISIBLE_PX,
    ]);
  });

  it("is a no-op when the container size is unchanged", () => {
    expect(
      anchorFloatingWindow(win(700, 500), size(1000, 800), size(1000, 800)),
    ).toEqual([700, 500]);
  });

  describe("nearer-edge anchoring on grow", () => {
    it("keeps a right-half window's distance to the right edge", () => {
      // Center at 850 (right half of 1000); container grows by 200.
      expect(
        anchorFloatingWindow(win(700, 40), size(1000, 800), size(1200, 800)),
      ).toEqual([900, 40]);
    });

    it("leaves a left-half window pinned to the left edge", () => {
      // Center at 200 (left half); x must not move when the container grows.
      expect(
        anchorFloatingWindow(win(50, 40), size(1000, 800), size(1200, 800)),
      ).toEqual([50, 40]);
    });

    it("anchors the axes independently", () => {
      // Right half horizontally, top half vertically: x follows, y does not.
      expect(
        anchorFloatingWindow(win(700, 40), size(1000, 800), size(1200, 1000)),
      ).toEqual([900, 40]);
      // Bottom half vertically (center 600 of 800), left half horizontally.
      expect(
        anchorFloatingWindow(win(50, 500), size(1000, 800), size(1200, 1000)),
      ).toEqual([50, 700]);
    });

    it("does not anchor a window wider or taller than the container", () => {
      // It spans both edges, so neither is the "nearer" one.
      expect(
        anchorFloatingWindow(
          win(0, 0, 1200, 900),
          size(1000, 800),
          size(1100, 850),
        ),
      ).toEqual([0, 0]);
    });

    it("does not anchor a window that fills the container's height", () => {
      // The floating control panel: 15px top margin, height at the auto-height
      // budget (700 - 2*15 = 670). Its center is EXACTLY the container's, so
      // the half-test is decided by subpixel rounding of the measured height --
      // 670 and 671 have to land in the same place.
      expect(
        anchorFloatingWindow(
          win(625, 15, 320, 670),
          size(960, 700),
          size(1440, 900),
        ),
      ).toEqual([1105, 15]);
      expect(
        anchorFloatingWindow(
          win(625, 15, 320, 671),
          size(960, 700),
          size(1440, 900),
        ),
      ).toEqual([1105, 15]);
    });

    it("treats an unmeasured window as a zero-height point at its corner", () => {
      // height 0 = no DOM yet: its "center" is its own y, so a top-half corner
      // does not anchor...
      expect(
        anchorFloatingWindow(
          win(50, 100, 300, 0),
          size(1000, 800),
          size(1000, 1000),
        ),
      ).toEqual([50, 100]);
      // ...and a bottom-half corner does.
      expect(
        anchorFloatingWindow(
          win(50, 700, 300, 0),
          size(1000, 800),
          size(1000, 1000),
        ),
      ).toEqual([50, 900]);
    });
  });

  describe("shrink pulls a window back on-screen", () => {
    it("pulls the far edge into view when the window still fits", () => {
      // A left-half window (no anchoring) overhanging the new right edge.
      expect(
        anchorFloatingWindow(win(50, 40), size(1000, 800), size(300, 800)),
      ).toEqual([0, 40]);
      expect(
        anchorFloatingWindow(win(50, 40), size(1000, 800), size(600, 800)),
      ).toEqual([50, 40]);
      expect(
        anchorFloatingWindow(win(200, 40), size(1000, 800), size(400, 800)),
      ).toEqual([100, 40]);
    });

    it("pins an oversized window to the top-left instead of pushing it off", () => {
      expect(
        anchorFloatingWindow(win(100, 100), size(1000, 800), size(200, 150)),
      ).toEqual([0, 0]);
    });

    it("only pulls on the axis that shrank", () => {
      // Width-only shrink must not yank a bottom-overhanging window upward:
      // y stays at 700 even though the window's bottom (900) is off-container.
      expect(
        anchorFloatingWindow(win(50, 700), size(1000, 800), size(400, 800)),
      ).toEqual([50, 700]);
    });

    it("does not pull vertically when the rendered height is unknown", () => {
      // Anchoring still moves the corner by the delta, but there is no height
      // to compute "fully on-screen" from, so no pull is applied on top.
      expect(
        anchorFloatingWindow(
          win(50, 700, 300, 0),
          size(1000, 800),
          size(1000, 400),
        ),
      ).toEqual([50, 300]);
    });

    it("leaves a container-filling window on its top margin", () => {
      // Its height re-derives from the new container, so pulling with the
      // stale one would drag it off the 15px margin and flush to the edge.
      expect(
        anchorFloatingWindow(
          win(1105, 15, 320, 870),
          size(1440, 900),
          size(800, 700),
        ),
      ).toEqual([465, 15]);
    });

    it("does not cancel deliberate overhang when the container grows", () => {
      // Dragged deliberately past the right edge; a grow loses nothing, so the
      // overhang is preserved (modulo the nearer-edge anchor, which applies
      // because the window fits and its center is in the right half).
      expect(
        anchorFloatingWindow(win(900, 40), size(1000, 800), size(1400, 800)),
      ).toEqual([1300, 40]);
    });
  });

  it("clamps after anchoring so the handle stays reachable", () => {
    // A narrow window flush against the right/bottom edge: anchoring adds the
    // full delta, which would put its corner past the container. The clamp
    // runs last and catches it on both axes.
    expect(
      anchorFloatingWindow(
        win(990, 40, 40, 200),
        size(1000, 800),
        size(1010, 800),
      ),
    ).toEqual([1010 - KEEP_VISIBLE_PX, 40]);
    expect(
      anchorFloatingWindow(
        win(50, 780, 300, 10),
        size(1000, 800),
        size(1000, 820),
      ),
    ).toEqual([50, 820 - KEEP_VISIBLE_PX]);
  });
});

describe("translationOf", () => {
  it("reads the translation out of a 2D matrix", () => {
    expect(translationOf("matrix(1, 0, 0, 1, 12, -34)")).toEqual([12, -34]);
  });

  it("reads the translation out of a 3D matrix", () => {
    const values = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 12, -34, 0, 1];
    expect(translationOf(`matrix3d(${values.join(", ")})`)).toEqual([12, -34]);
  });

  it("keeps the translation of a matrix that also scales or rotates", () => {
    expect(translationOf("matrix(2, 0, 0, 2, 5, 7)")).toEqual([5, 7]);
  });

  it("reads no translation from an untransformed element", () => {
    expect(translationOf("none")).toEqual([0, 0]);
    expect(translationOf("")).toEqual([0, 0]);
  });

  it("reads no translation from an unparseable value", () => {
    // Neither a 6- nor 16-value matrix, no parens, or non-numeric components:
    // a wrong guess would offset every measured tab rect, so fall back to 0.
    expect(translationOf("matrix(1, 0, 0)")).toEqual([0, 0]);
    expect(translationOf("translateX(10px)")).toEqual([0, 0]);
    expect(translationOf("garbage")).toEqual([0, 0]);
    expect(translationOf("matrix(1, 0, 0, 1, none, 4)")).toEqual([0, 0]);
  });
});
