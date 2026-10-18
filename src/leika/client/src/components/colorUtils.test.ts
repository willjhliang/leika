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
