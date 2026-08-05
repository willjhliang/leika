import { describe, expect, it } from "vitest";

import { markLabelMaxWidths, snapMultiSliderValue } from "./sliderValues";

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

describe("markLabelMaxWidths", () => {
  it("gives a lone mark the whole track", () => {
    expect(markLabelMaxWidths([40])).toEqual([100]);
  });

  it("splits the track between two ends, so neither can reach the other", () => {
    // Each label lies wholly on one side of its own tick, so half the track
    // each is exactly the room available before they would touch.
    expect(markLabelMaxWidths([0, 100])).toEqual([50, 50]);
  });

  it("tiles the track across three marks", () => {
    const widths = markLabelMaxWidths([0, 50, 100]);
    expect(widths).toEqual([25, 50, 25]);
    // The middle label is centred on its mark, so half of its 50% lies either
    // side of the midpoint -- meeting, and never crossing, the ends' 25%.
    expect(widths[1] / 2 + widths[0]).toBe(50);
  });

  it("reads neighbours by position rather than by the order given", () => {
    expect(markLabelMaxWidths([100, 0, 50])).toEqual([25, 25, 50]);
  });

  it("leaves nothing for marks stacked on one position", () => {
    // There is nowhere for the second label to go; saying so beats drawing
    // one on top of the other.
    expect(markLabelMaxWidths([30, 30])).toEqual([0, 0]);
  });

  it("scales the room by how much of the label sits on each side", () => {
    // The room is divided at the midpoint, 40%, but a label does not sit
    // squarely in its share: at 20% four fifths of it lies to the right of the
    // tick, so filling the 20% of room on that side takes a label of 25%. The
    // mark at 60% keeps only a third of the track for the same reason,
    // measured against the 20% on its left.
    const widths = markLabelMaxWidths([20, 60]);
    expect(widths[0]).toBe(25);
    expect(widths[1]).toBeCloseTo(100 / 3, 10);
  });
});
