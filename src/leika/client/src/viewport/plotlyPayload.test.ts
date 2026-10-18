import { describe, expect, it } from "vitest";

import { parsePlotlyFigure, parsePlotlyThemeTemplates } from "./plotlyPayload";

describe("parsePlotlyFigure", () => {
  it("treats an empty payload as no figure", () => {
    expect(parsePlotlyFigure("")).toEqual({ ok: true, value: null });
  });

  it("rejects malformed JSON without throwing", () => {
    expect(parsePlotlyFigure("{")).toEqual({
      ok: false,
      error: "Plotly data contains invalid JSON.",
    });
  });

  it("rejects non-object figures and layouts", () => {
    expect(parsePlotlyFigure("[]")).toEqual({
      ok: false,
      error: "Plotly figure data must be a JSON object.",
    });
    expect(parsePlotlyFigure('{"data":[],"layout":[]}')).toEqual({
      ok: false,
      error: "Plotly figure layout must be a JSON object.",
    });
  });

  it("extracts Plotly inputs and pins UI revision", () => {
    expect(
      parsePlotlyFigure(
        '{"data":[{"x":[1]}],"layout":{"title":"A","uirevision":"old"},"config":{"responsive":true}}',
      ),
    ).toEqual({
      ok: true,
      value: {
        data: [{ x: [1] }],
        layout: { title: "A", uirevision: "true" },
        config: { responsive: true },
      },
    });
  });
});

describe("parsePlotlyThemeTemplates", () => {
  it("accepts an empty or object payload", () => {
    expect(parsePlotlyThemeTemplates("")).toEqual({ ok: true, value: null });
    expect(
      parsePlotlyThemeTemplates('{"light":{"paper_bgcolor":"white"}}'),
    ).toEqual({
      ok: true,
      value: { light: { paper_bgcolor: "white" } },
    });
  });

  it("rejects malformed and non-object template payloads", () => {
    expect(parsePlotlyThemeTemplates("{").ok).toBe(false);
    expect(parsePlotlyThemeTemplates("null")).toEqual({
      ok: false,
      error: "Plotly theme templates must be a JSON object.",
    });
  });
});
