export type PlotlyParseResult<T> =
  { ok: true; value: T } | { ok: false; error: string };

export interface ParsedPlotlyFigure {
  data: unknown;
  layout: Record<string, unknown>;
  config: unknown;
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseJson(serialized: string): PlotlyParseResult<unknown> {
  try {
    return { ok: true, value: JSON.parse(serialized) as unknown };
  } catch {
    return { ok: false, error: "Plotly data contains invalid JSON." };
  }
}

/** Parse and validate the figure envelope used by Plotly.react. */
export function parsePlotlyFigure(
  serialized: string,
): PlotlyParseResult<ParsedPlotlyFigure | null> {
  if (serialized === "") return { ok: true, value: null };
  const parsed = parseJson(serialized);
  if (!parsed.ok) return parsed;
  if (!isJsonObject(parsed.value)) {
    return { ok: false, error: "Plotly figure data must be a JSON object." };
  }
  const layout = parsed.value.layout;
  if (layout !== undefined && !isJsonObject(layout)) {
    return { ok: false, error: "Plotly figure layout must be a JSON object." };
  }
  return {
    ok: true,
    value: {
      data: parsed.value.data,
      layout: { ...(layout ?? {}), uirevision: "true" },
      config: parsed.value.config,
    },
  };
}

/** Parse the optional light/dark Plotly template map. */
export function parsePlotlyThemeTemplates(
  serialized: string,
): PlotlyParseResult<Record<string, unknown> | null> {
  if (serialized === "") return { ok: true, value: null };
  const parsed = parseJson(serialized);
  if (!parsed.ok) return parsed;
  if (!isJsonObject(parsed.value)) {
    return {
      ok: false,
      error: "Plotly theme templates must be a JSON object.",
    };
  }
  return { ok: true, value: parsed.value };
}
