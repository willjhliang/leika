import React from "react";

import { GuiPlotlyMessage } from "../WebsocketMessages";
import { useColorScheme } from "../hooks/useColorScheme";
import { useElementSize } from "../hooks/useElementSize";
import { usePlotlyRenderer } from "../hooks/usePlotlyRenderer";
import { plotlyFigure } from "../viewport/plotlyPayload";
import { MediaPreview, MediaSurface } from "./MediaPreview";

const PlotWithAspect = React.memo(function PlotWithAspect({
  jsonStr,
  themeTemplates,
  aspect,
  onExpand,
}: {
  jsonStr: string;
  themeTemplates: string;
  /** Width divided by height. */
  aspect: number;
  onExpand?: () => void;
}) {
  const { ref, width } = useElementSize();
  // Figures without an explicit template follow the Leika theme.
  const colorScheme = useColorScheme();
  const figure = React.useMemo(
    () => plotlyFigure(jsonStr, themeTemplates, colorScheme),
    [jsonStr, themeTemplates, colorScheme],
  );
  const request = React.useMemo(
    () => ({
      figure,
      layout: { ...figure.layout, width, height: width / aspect },
    }),
    [figure, width, aspect],
  );
  const { plotRef, message: plotlyMessage } = usePlotlyRenderer({
    request,
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
        style={{ minHeight: width > 0 ? width / aspect : undefined }}
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
  props: {
    _plotly_json_str: plotlyJsonString,
    _theme_templates: themeTemplates,
    aspect,
  },
}: GuiPlotlyMessage) {
  const [opened, setOpened] = React.useState(false);
  // Stable, so the memo above can actually skip re-renders of the inline copy.
  const expand = React.useCallback(() => setOpened(true), []);
  return (
    <>
      <PlotWithAspect
        jsonStr={plotlyJsonString}
        themeTemplates={themeTemplates}
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
        <PlotWithAspect
          jsonStr={plotlyJsonString}
          themeTemplates={themeTemplates}
          aspect={aspect}
        />
      </MediaPreview>
    </>
  );
}
