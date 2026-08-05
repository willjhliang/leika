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
  it("leaves labels alone when they do not reach each other", () => {
    // The whole point: a long label beside a short one is not a problem until
    // the two actually meet, and nothing here is rationed in advance.
    expect(markLabelMaxWidths([0, 100], [40, 10])).toEqual([100, 100]);
    expect(markLabelMaxWidths([0, 50, 100], [20, 20, 20])).toEqual([
      100, 100, 100,
    ]);
  });

  it("lets one label take almost the whole track if nothing is beside it", () => {
    expect(markLabelMaxWidths([40], [100])).toEqual([100]);
  });

  it("splits a contested gap in proportion to what each label wanted", () => {
    // Both lean wholly into the gap between them -- one at each end -- and
    // together they want 150% of the 100% available, so each keeps two thirds.
    const widths = markLabelMaxWidths([0, 100], [100, 50]);
    expect(widths[0]).toBeCloseTo((100 * 100) / 150, 10);
    expect(widths[1]).toBeCloseTo((100 * 50) / 150, 10);
    // Which is exactly the track: they meet and neither crosses.
    expect(widths[0] + widths[1]).toBeCloseTo(100, 10);
  });

  it("cuts back only the pair that collides", () => {
    // The first two want more of their gap than it holds; the third is far
    // enough away to be untouched by any of it.
    const widths = markLabelMaxWidths([0, 20, 100], [40, 40, 5]);
    expect(widths[0]).toBeLessThan(40);
    expect(widths[1]).toBeLessThan(40);
    expect(widths[2]).toBe(100);
  });

  it("keeps the two labels in proportion to what each asked for", () => {
    // Whatever the positions, a cut-back pair ends up sharing the gap in the
    // ratio of their natural widths: a label four times the length of its
    // neighbour keeps four times the room. Neither is cut to the other's size.
    const widths = markLabelMaxWidths([0, 20], [80, 20]);
    expect(widths[0] / widths[1]).toBeCloseTo(4, 10);
  });

  it("reads neighbours by position rather than by the order given", () => {
    const inOrder = markLabelMaxWidths([0, 50, 100], [80, 80, 80]);
    const shuffled = markLabelMaxWidths([100, 0, 50], [80, 80, 80]);
    expect(shuffled).toEqual([inOrder[2], inOrder[0], inOrder[1]]);
  });

  it("never lets a label off the ends of the track", () => {
    // Anchored at its own tick, a label of 100% reaches exactly one end and
    // no further, so that is the cap even where nothing is beside it.
    expect(markLabelMaxWidths([50], [400])).toEqual([100]);
  });

  it("leaves nothing for the label that loses a stacked position", () => {
    // There is nowhere for it to go; saying so beats drawing one on top of
    // the other.
    expect(markLabelMaxWidths([30, 30], [20, 20])).toEqual([0, 0]);
  });
});
