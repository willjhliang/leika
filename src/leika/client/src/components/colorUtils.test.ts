import { describe, it, expect } from "vitest";
import {
  rgbToString,
  rgbaToString,
  parseToRgb,
  parseToRgba,
  colorFromRgb,
  hsvToRgb,
  hslToRgb,
  rgbToHsl,
  rgbToHsv,
  rgbEqual,
  rgbaEqual,
  colorValueToHex,
  colorAlpha,
  colorFromHex,
  colorWithOpacity,
  relativeLuminance,
  accentForeground,
} from "./colorUtils";

describe("rgbToString / rgbaToString", () => {
  it("rounds RGB components", () => {
    expect(rgbToString([0.4, 127.6, 255])).toBe("rgb(0, 128, 255)");
  });
  it("emits alpha in [0, 1] with 4 decimals", () => {
    expect(rgbaToString([10, 20, 30, 255])).toBe("rgba(10, 20, 30, 1.0000)");
    expect(rgbaToString([10, 20, 30, 0])).toBe("rgba(10, 20, 30, 0.0000)");
  });
});

describe("parseToRgb", () => {
  it("parses rgb() strings", () => {
    expect(parseToRgb("rgb(1, 2, 3)")).toEqual([1, 2, 3]);
  });
  it("parses #RGB shorthand hex", () => {
    expect(parseToRgb("#f00")).toEqual([255, 0, 0]);
  });
  it("parses #RRGGBB hex", () => {
    expect(parseToRgb("#0a141e")).toEqual([10, 20, 30]);
  });
  it("returns null for unparseable input", () => {
    expect(parseToRgb("not a color")).toBeNull();
  });
  it("rejects trailing text and out-of-range channels", () => {
    expect(parseToRgb("rgb(1, 2, 3) trailing")).toBeNull();
    expect(parseToRgb("rgb(256, 2, 3)")).toBeNull();
  });
});

describe("parseToRgba", () => {
  it("parses rgba() strings and scales alpha to [0, 255]", () => {
    expect(parseToRgba("rgba(1, 2, 3, 1)")).toEqual([1, 2, 3, 255]);
    expect(parseToRgba("rgba(1, 2, 3, 0.5)")).toEqual([1, 2, 3, 128]);
  });
  it("parses #RGBA shorthand hex", () => {
    expect(parseToRgba("#f00f")).toEqual([255, 0, 0, 255]);
  });
  it("parses #RRGGBBAA hex", () => {
    expect(parseToRgba("#0a141e80")).toEqual([10, 20, 30, 128]);
  });
  it("falls back to RGB parsing with full alpha", () => {
    expect(parseToRgba("rgb(1, 2, 3)")).toEqual([1, 2, 3, 255]);
    expect(parseToRgba("#f00")).toEqual([255, 0, 0, 255]);
  });
  it("returns null for unparseable input", () => {
    expect(parseToRgba("nope")).toBeNull();
  });
  it("rejects out-of-range channels and opacity", () => {
    expect(parseToRgba("rgba(1, 2, 999, 0.5)")).toBeNull();
    expect(parseToRgba("rgba(1, 2, 3, 1.1)")).toBeNull();
    expect(parseToRgba("rgba(1, 2, 3, 0.5) trailing")).toBeNull();
  });
});

describe("rgbEqual / rgbaEqual", () => {
  it("compares element-wise", () => {
    expect(rgbEqual([1, 2, 3], [1, 2, 3])).toBe(true);
    expect(rgbEqual([1, 2, 3], [1, 2, 4])).toBe(false);
    expect(rgbaEqual([1, 2, 3, 4], [1, 2, 3, 4])).toBe(true);
    expect(rgbaEqual([1, 2, 3, 4], [1, 2, 3, 5])).toBe(false);
  });
});

describe("native color input conversion", () => {
  it("shows shorthand and alpha hex values without falling back to black", () => {
    expect(colorValueToHex("#0af")).toBe("#00aaff");
    expect(colorValueToHex("#0af8")).toBe("#00aaff");
    expect(colorValueToHex("#0a141e80")).toBe("#0a141e");
  });

  it("preserves hex alpha when the native picker changes RGB", () => {
    expect(colorAlpha("#0a141e80")).toBe("0.5020");
    expect(colorFromHex("#123456", "rgba", "#0a141e80")).toBe(
      "rgba(18, 52, 86, 0.5020)",
    );
  });

  it("changes opacity without changing RGB channels", () => {
    expect(colorWithOpacity("#0a141e80", 0.25)).toBe(
      "rgba(10, 20, 30, 0.2500)",
    );
  });

  it("clamps opacity and keeps the current value for non-finite input", () => {
    expect(colorWithOpacity("rgba(10, 20, 30, 0.5)", 2)).toBe(
      "rgba(10, 20, 30, 1.0000)",
    );
    expect(colorWithOpacity("rgba(10, 20, 30, 0.5)", Number.NaN)).toBe(
      "rgba(10, 20, 30, 0.5020)",
    );
  });
});

describe("picker color conversions", () => {
  it("round-trips representative RGB colors through HSV", () => {
    for (const rgb of [
      [255, 0, 0],
      [52, 120, 246],
      [10, 20, 30],
      [255, 255, 255],
      [0, 0, 0],
    ] as const) {
      expect(hsvToRgb(rgbToHsv([...rgb]))).toEqual([...rgb]);
    }
  });

  it("converts RGB to expected HSL channels", () => {
    expect(rgbToHsl([255, 0, 0])).toEqual([0, 100, 50]);
    expect(rgbToHsl([255, 255, 255])).toEqual([0, 0, 100]);
    expect(rgbToHsl([0, 0, 0])).toEqual([0, 0, 0]);
  });

  it("converts HSL channels to expected RGB colors", () => {
    expect(hslToRgb([0, 100, 50])).toEqual([255, 0, 0]);
    expect(hslToRgb([120, 100, 50])).toEqual([0, 255, 0]);
    expect(hslToRgb([240, 100, 50])).toEqual([0, 0, 255]);
    expect(hslToRgb([0, 0, 50])).toEqual([128, 128, 128]);
    expect(hslToRgb([360, 100, 50])).toEqual([255, 0, 0]);
  });

  it("preserves alpha when replacing RGBA channels", () => {
    expect(colorFromRgb([18, 52, 86], "rgba", "rgba(1, 2, 3, 0.5020)")).toBe(
      "rgba(18, 52, 86, 0.5020)",
    );
    expect(colorFromRgb([18, 52, 86], "rgb", "rgb(1, 2, 3)")).toBe(
      "rgb(18, 52, 86)",
    );
  });
});

describe("relativeLuminance", () => {
  it("spans the full range from black to white", () => {
    expect(relativeLuminance([0, 0, 0])).toBe(0);
    expect(relativeLuminance([255, 255, 255])).toBeCloseTo(1, 6);
    expect(relativeLuminance([128, 128, 128])).toBeCloseTo(0.2158, 3);
  });

  it("weights green above red above blue", () => {
    expect(relativeLuminance([0, 255, 0])).toBeGreaterThan(
      relativeLuminance([255, 0, 0]),
    );
    expect(relativeLuminance([255, 0, 0])).toBeGreaterThan(
      relativeLuminance([0, 0, 255]),
    );
  });

  it("clamps channels outside the byte range", () => {
    expect(relativeLuminance([300, 300, 300])).toBe(
      relativeLuminance([255, 255, 255]),
    );
    expect(relativeLuminance([-5, -5, -5])).toBe(relativeLuminance([0, 0, 0]));
  });
});

describe("accentForeground", () => {
  const LIGHT = "oklch(0.985 0 0)";
  const DARK = "oklch(0.205 0 0)";

  it("prints dark on pale accents and light on deep ones", () => {
    expect(accentForeground("rgb(255, 255, 255)")).toBe(DARK);
    expect(accentForeground("rgb(255, 255, 0)")).toBe(DARK);
    expect(accentForeground("rgb(0, 0, 0)")).toBe(LIGHT);
    expect(accentForeground("rgb(0, 0, 255)")).toBe(LIGHT);
    // The theme's own near-black accent, which is what the picker opens on.
    expect(accentForeground("rgb(38, 38, 38)")).toBe(LIGHT);
  });

  it("keeps light text on saturated mid-tones", () => {
    // These sit between the equal-contrast crossover and the threshold, which
    // is the whole point of putting the threshold above the crossover.
    for (const midtone of [
      "rgb(52, 120, 246)", // #3478F6, a strong blue
      "rgb(217, 72, 15)", // #D9480F, a strong orange
      "rgb(13, 148, 136)", // #0D9488, a strong teal
    ]) {
      expect(relativeLuminance(parseToRgb(midtone)!)).toBeGreaterThan(0.179);
      expect(accentForeground(midtone)).toBe(LIGHT);
    }
  });

  it("flips once an accent is genuinely light", () => {
    expect(accentForeground("rgb(255, 243, 176)")).toBe(DARK); // pale yellow
    expect(accentForeground("rgb(190, 190, 190)")).toBe(DARK); // light grey
    expect(accentForeground("rgb(120, 120, 120)")).toBe(LIGHT); // mid grey
  });

  it("accepts hex as well as rgb()", () => {
    expect(accentForeground("#ffffff")).toBe(DARK);
    expect(accentForeground("#000")).toBe(LIGHT);
  });

  it("falls back to the light foreground for an unparseable accent", () => {
    expect(accentForeground("not-a-color")).toBe(LIGHT);
  });
});
