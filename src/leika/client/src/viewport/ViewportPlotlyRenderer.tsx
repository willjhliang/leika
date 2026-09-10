import React from "react";
import { usePlotlyRenderer } from "../hooks/usePlotlyRenderer";
import { useColorScheme } from "../hooks/useColorScheme";
import { useElementSize } from "../hooks/useElementSize";
import { parsePlotlyFigure, parsePlotlyThemeTemplates } from "./plotlyPayload";
import type { ViewportPlotlyPane } from "./ViewportState";

/** Interactive Plotly renderer that always fills its pane, tracking pane
 * resizes via ResizeObserver. */
export function ViewportPlotlyRenderer({ pane }: { pane: ViewportPlotlyPane }) {
  const { ref, width, height } = useElementSize();
  // Figures without an explicit template follow Leika theme, which can
  // change at runtime (server-configured, URL-forced, or auto-detected).
  const colorScheme = useColorScheme();
  const themeParseResult = React.useMemo(
    () => parsePlotlyThemeTemplates(pane.props._theme_templates),
    [pane.props._theme_templates],
  );
  const figureParseResult = React.useMemo(
    () => parsePlotlyFigure(pane.props._plotly_json_str),
    [pane.props._plotly_json_str],
  );

  const themeTemplates = themeParseResult.ok ? themeParseResult.value : null;
  const plotJson = figureParseResult.ok ? figureParseResult.value : null;
  const parseError = !figureParseResult.ok
    ? figureParseResult.error
    : !themeParseResult.ok
      ? themeParseResult.error
      : null;

  const layoutTemplate =
    plotJson?.layout.template ??
    (themeTemplates === null
      ? undefined
      : (themeTemplates[colorScheme] ?? themeTemplates.light));

  const request = React.useMemo(
    () =>
      plotJson === null
        ? null
        : {
            figure: plotJson,
            layout: {
              ...plotJson.layout,
              template: layoutTemplate,
              width,
              height,
              autosize: false,
            },
          },
    [plotJson, layoutTemplate, width, height],
  );
  const { plotRef, message: plotlyMessage } = usePlotlyRenderer({
    request,
    inputError: parseError,
    ready: width > 0 && height > 0,
  });

  return (
    <div
      ref={ref}
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        background: "var(--background)",
      }}
    >
      <div ref={plotRef} />
      {plotlyMessage === null ? null : (
        <div
          role="status"
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--muted-foreground)",
            fontSize: "var(--text-sm)",
            background: "var(--background)",
            zIndex: 1,
          }}
        >
          {plotlyMessage}
        </div>
      )}
    </div>
  );
}
