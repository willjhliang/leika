import React from "react";
import { usePlotlyRenderer } from "../hooks/usePlotlyRenderer";
import { useColorScheme } from "../hooks/useColorScheme";
import { useElementSize } from "../hooks/useElementSize";
import { plotlyFigure } from "./plotlyPayload";
import type { ViewportPlotlyPane } from "./ViewportState";

/** Interactive Plotly renderer that always fills its pane, tracking pane
 * resizes via ResizeObserver. */
export function ViewportPlotlyRenderer({ pane }: { pane: ViewportPlotlyPane }) {
  const { ref, width, height } = useElementSize();
  // Figures without an explicit template follow Leika theme, which can
  // change at runtime (server-configured, URL-forced, or auto-detected).
  const colorScheme = useColorScheme();
  const figure = React.useMemo(
    () =>
      plotlyFigure(
        pane.props._plotly_json_str,
        pane.props._theme_templates,
        colorScheme,
      ),
    [pane.props._plotly_json_str, pane.props._theme_templates, colorScheme],
  );
  const request = React.useMemo(
    () => ({
      figure,
      layout: { ...figure.layout, width, height, autosize: false },
    }),
    [figure, width, height],
  );
  const { plotRef, message: plotlyMessage } = usePlotlyRenderer({
    request,
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
