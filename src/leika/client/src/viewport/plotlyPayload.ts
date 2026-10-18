import type { ColorScheme } from "../hooks/useColorScheme";

export interface PlotlyFigure {
  data: unknown;
  layout: Record<string, unknown>;
  config: unknown;
}

/** Plotly.react inputs from the server's figure and theme-template JSON. A
 * figure without its own template takes the one for the viewer's color
 * scheme, and the UI revision is pinned so zoom and pan survive updates. */
export function plotlyFigure(
  figureJson: string,
  themeTemplatesJson: string,
  colorScheme: ColorScheme,
): PlotlyFigure {
  const {
    data,
    layout = {},
    config,
  } = JSON.parse(figureJson) as {
    data: unknown;
    layout?: Record<string, unknown>;
    config: unknown;
  };
  const templates = JSON.parse(themeTemplatesJson) as Record<
    ColorScheme,
    unknown
  >;
  return {
    data,
    layout: {
      ...layout,
      template: layout.template ?? templates[colorScheme],
      uirevision: "true",
    },
    config,
  };
}
