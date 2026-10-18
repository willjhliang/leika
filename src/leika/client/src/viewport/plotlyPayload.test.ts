import { describe, expect, it } from "vitest";

import { plotlyFigure } from "./plotlyPayload";

const templates = '{"light":{"name":"white"},"dark":{"name":"dark"}}';

describe("plotlyFigure", () => {
  it("extracts Plotly inputs, themes the figure and pins UI revision", () => {
    expect(
      plotlyFigure(
        '{"data":[{"x":[1]}],"layout":{"title":"A","uirevision":"old"},"config":{"responsive":true}}',
        templates,
        "dark",
      ),
    ).toEqual({
      data: [{ x: [1] }],
      layout: { title: "A", template: { name: "dark" }, uirevision: "true" },
      config: { responsive: true },
    });
  });

  it("keeps a figure's own template", () => {
    expect(
      plotlyFigure(
        '{"data":[],"layout":{"template":"own"}}',
        templates,
        "light",
      ).layout.template,
    ).toBe("own");
  });
});
