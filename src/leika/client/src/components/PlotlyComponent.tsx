import React from "react";

import { GuiPlotlyMessage } from "../WebsocketMessages";
import { useElementSize } from "../hooks/useElementSize";
import { getPlotly, plotlyReady, PlotlyGlobal } from "../plotlyReady";
import { MediaDialog, MediaSurface } from "./MediaExpand";

type PlotDescription = {
  data: unknown;
  layout?: Record<string, unknown>;
  config?: unknown;
};

const PlotWithAspect = React.memo(function PlotWithAspect({
  jsonStr,
  aspect,
  onExpand,
}: {
  jsonStr: string;
  /** Width divided by height. */
  aspect: number;
  onExpand?: () => void;
}) {
  const { ref, width } = useElementSize();
  const plotRef = React.useRef<HTMLDivElement>(null);
  const plot = React.useMemo(() => {
    const parsed = JSON.parse(jsonStr) as PlotDescription;
    return {
      ...parsed,
      layout: { ...parsed.layout, uirevision: "true" },
    };
  }, [jsonStr]);

  React.useEffect(() => {
    const node = plotRef.current;
    if (width <= 0 || node === null) return;
    let active = true;
    const render = (plotly: PlotlyGlobal) => {
      if (!active) return;
      plotly.react(
        node,
        plot.data,
        { ...plot.layout, width, height: width / aspect },
        plot.config,
      );
    };
    const plotly = getPlotly();
    if (plotly === undefined) void plotlyReady.then(render);
    else render(plotly);
    return () => {
      active = false;
    };
  }, [plot, width, aspect]);

  React.useEffect(() => {
    const node = plotRef.current;
    return () => {
      const plotly = getPlotly();
      if (node !== null && plotly !== undefined) plotly.purge(node);
    };
  }, []);

  return (
    <MediaSurface
      subject="plot"
      className="overflow-hidden"
      ref={ref}
      onExpand={onExpand}
    >
      <div ref={plotRef} />
    </MediaSurface>
  );
});

export default function PlotlyComponent({
  props: { _plotly_json_str: plotlyJsonString, aspect },
}: GuiPlotlyMessage) {
  const [opened, setOpened] = React.useState(false);
  // Stable, so the memo above can actually skip re-renders of the inline copy.
  const expand = React.useCallback(() => setOpened(true), []);
  return (
    <>
      <PlotWithAspect
        jsonStr={plotlyJsonString}
        aspect={aspect}
        onExpand={expand}
      />
      <MediaDialog
        open={opened}
        onOpenChange={setOpened}
        title="Expanded Plotly plot"
      >
        <PlotWithAspect jsonStr={plotlyJsonString} aspect={aspect} />
      </MediaDialog>
    </>
  );
}
