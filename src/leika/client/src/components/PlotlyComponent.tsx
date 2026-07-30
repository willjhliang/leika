import React from "react";

import { GuiPlotlyMessage } from "../WebsocketMessages";
import { useElementSize } from "../hooks/useElementSize";
import { MediaDialog, MediaSurface } from "./MediaExpand";

const PlotWithAspect = React.memo(function PlotWithAspect({
  jsonStr,
  aspect,
  onExpand,
}: {
  jsonStr: string;
  /** Width divided by height, read the same way as `GuiUplotProps.aspect`. */
  aspect: number;
  onExpand?: () => void;
}) {
  const { ref, width } = useElementSize();
  const plotRef = React.useRef<HTMLDivElement>(null);
  const plotJson = React.useMemo(() => {
    const parsed = JSON.parse(jsonStr);
    parsed.layout.uirevision = "true";
    return parsed;
  }, [jsonStr]);

  React.useEffect(() => {
    if (width <= 0) return;
    // @ts-ignore - Plotly.js is dynamically imported with an eval() call.
    Plotly.react(
      plotRef.current!,
      plotJson.data,
      { ...plotJson.layout, width, height: width / aspect },
      plotJson.config,
    );
  }, [plotJson, width, aspect]);

  React.useEffect(() => {
    const node = plotRef.current;
    return () => {
      const plotly = (
        window as unknown as { Plotly?: { purge(node: HTMLElement): void } }
      ).Plotly;
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
