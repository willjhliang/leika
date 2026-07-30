import { describe, expect, it } from "vitest";

import { snapMultiSliderValue } from "./sliderValues";

describe("MultiSlider value geometry", () => {
  it("snaps steps relative to a non-zero minimum", () => {
    expect(snapMultiSliderValue(0.52, 0.1, 1.1, 0.2, 2)).toBe(0.5);
  });

  it("keeps exact endpoints and clamps out-of-range positions", () => {
    expect(snapMultiSliderValue(1.1, 0.1, 1.1, 0.2, 2)).toBe(1.1);
    expect(snapMultiSliderValue(-1, 0.1, 1.1, 0.2, 2)).toBe(0.1);
    expect(snapMultiSliderValue(2, 0.1, 1.1, 0.2, 2)).toBe(1.1);
  });

  it("returns the minimum for a zero-width range", () => {
    expect(snapMultiSliderValue(0.75, 4, 4, 1, 0)).toBe(4);
  });
});
