import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SliderAnnotations } from "./SliderAnnotations";

describe("SliderAnnotations", () => {
  it("clamps marks and aligns their content inside the track width", () => {
    const markup = renderToStaticMarkup(
      React.createElement(SliderAnnotations, {
        min: 0,
        max: 10,
        marks: [
          { value: -2, label: "below" },
          { value: 5, label: "middle" },
          { value: 12, label: "above" },
        ],
      }),
    );

    expect(markup).toContain("data-leika-slider-annotations");
    expect(markup.match(/data-leika-slider-mark-wrapper/g)).toHaveLength(3);
    expect(markup.match(/left:0%;transform:translateX\(-0%\)/g)).toHaveLength(
      2,
    );
    expect(markup.match(/left:50%;transform:translateX\(-50%\)/g)).toHaveLength(
      2,
    );
    expect(
      markup.match(/left:100%;transform:translateX\(-100%\)/g),
    ).toHaveLength(2);
    expect(markup).toContain("truncate");
    // Marks land at 0%, 50% and 100%, so the room between the midpoints gives
    // the ends a quarter of the track each and the middle one half of it --
    // which tiles the track exactly, leaving no two labels a point in common.
    expect(markup).toContain("max-width:25%");
    expect(markup).toContain("max-width:50%");
  });

  it("places degenerate-range marks at the safe leading edge", () => {
    const markup = renderToStaticMarkup(
      React.createElement(SliderAnnotations, {
        min: 3,
        max: 3,
        marks: [{ value: 3, label: "only" }],
      }),
    );
    expect(markup.match(/left:0%;transform:translateX\(-0%\)/g)).toHaveLength(
      2,
    );
  });
});
