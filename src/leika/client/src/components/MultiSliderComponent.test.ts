import { describe, expect, it } from "vitest";

import {
  getMultiSliderPercentage,
  getMultiSliderValueFromFraction,
  snapMultiSliderValue,
} from "./multiSliderUtils";

describe("MultiSlider value geometry", () => {
  it("snaps steps relative to a non-zero minimum", () => {
    expect(snapMultiSliderValue(0.52, 0.1, 1.1, 0.2, 2)).toBe(0.5);
    expect(getMultiSliderValueFromFraction(0.42, 0.1, 1.1, 0.2, 2)).toBe(0.5);
  });

  it("keeps exact endpoints and clamps out-of-range positions", () => {
    expect(snapMultiSliderValue(1.1, 0.1, 1.1, 0.2, 2)).toBe(1.1);
    expect(getMultiSliderValueFromFraction(-1, 0.1, 1.1, 0.2, 2)).toBe(0.1);
    expect(getMultiSliderValueFromFraction(2, 0.1, 1.1, 0.2, 2)).toBe(1.1);
  });

  it("returns finite values for a zero-width range", () => {
    expect(getMultiSliderPercentage(4, 4, 4)).toBe(0);
    expect(getMultiSliderValueFromFraction(0.75, 4, 4, 1, 0)).toBe(4);
  });
});
