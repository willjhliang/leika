import React from "react";

import { GuiPlotlyMessage } from "../WebsocketMessages";
import { useElementSize } from "../hooks/useElementSize";
import { usePlotlyRenderer } from "../hooks/usePlotlyRenderer";
import { parsePlotlyFigure } from "../viewport/plotlyPayload";
import { MediaPreview, MediaSurface } from "./MediaPreview";

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
  const parseResult = React.useMemo(
    () => parsePlotlyFigure(jsonStr),
    [jsonStr],
  );
  const plot = parseResult.ok ? parseResult.value : null;
  const parseError = parseResult.ok ? null : parseResult.error;
  const aspectError =
    Number.isFinite(aspect) && aspect > 0
      ? null
      : "Plot aspect must be a positive number.";
  const displayAspect = aspectError === null ? aspect : 1;
  const request = React.useMemo(
    () =>
      plot === null || aspectError !== null
        ? null
        : {
            figure: plot,
            layout: {
              ...plot.layout,
              width,
              height: width / displayAspect,
            },
          },
    [plot, width, displayAspect, aspectError],
  );
  const { plotRef, message: plotlyMessage } = usePlotlyRenderer({
    request,
    inputError: parseError ?? aspectError,
    ready: width > 0,
  });

  return (
    <MediaSurface
      subject="plot"
      className="overflow-hidden"
      ref={ref}
      onExpand={onExpand}
    >
      <div
        ref={plotRef}
        style={{ minHeight: width > 0 ? width / displayAspect : undefined }}
      />
      {plotlyMessage === null ? null : (
        <div
          role="status"
          className={
            "absolute inset-0 z-10 flex items-center justify-center " +
            "bg-background text-sm text-muted-foreground"
          }
        >
          {plotlyMessage}
        </div>
      )}
    </MediaSurface>
  );
});

export default function PlotlyComponent({
  uuid,
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
      {/* "Plot" for the same reason an unlabelled image says "Image": the
          protocol gives a plot no label to show, so the preview names its
          kind rather than going untitled. */}
      <MediaPreview
        open={opened}
        onOpenChange={setOpened}
        title="Plot"
        rememberAs={uuid}
      >
        <PlotWithAspect jsonStr={plotlyJsonString} aspect={aspect} />
      </MediaPreview>
    </>
  );
}
