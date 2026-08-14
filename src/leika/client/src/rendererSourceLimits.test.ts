import { describe, expect, it } from "vitest";

import {
  GUI_HTML_MAX_SOURCE_CODE_UNITS,
  MATPLOTLIB_SVG_MAX_SOURCE_CODE_UNITS,
  guiHtmlSourceError,
  matplotlibSvgSourceError,
} from "./rendererSourceLimits";

describe("renderer source limits", () => {
  it("accepts HTML at the exact boundary and rejects the next code unit", () => {
    expect(guiHtmlSourceError("x".repeat(GUI_HTML_MAX_SOURCE_CODE_UNITS))).toBe(
      null,
    );
    expect(
      guiHtmlSourceError("x".repeat(GUI_HTML_MAX_SOURCE_CODE_UNITS + 1)),
    ).toContain("1 Mi-character");
  });

  it("accepts SVG at the exact boundary and rejects the next code unit", () => {
    expect(
      matplotlibSvgSourceError(
        "x".repeat(MATPLOTLIB_SVG_MAX_SOURCE_CODE_UNITS),
      ),
    ).toBe(null);
    expect(
      matplotlibSvgSourceError(
        "x".repeat(MATPLOTLIB_SVG_MAX_SOURCE_CODE_UNITS + 1),
      ),
    ).toContain("16 Mi-character");
  });

  it("rejects malformed non-string wire values", () => {
    expect(guiHtmlSourceError(null)).toBe("HTML content is invalid.");
    expect(matplotlibSvgSourceError(new Uint8Array())).toBe(
      "Matplotlib figure is invalid.",
    );
  });
});
