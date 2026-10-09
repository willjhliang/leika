import { ViewportVideoRenderer } from "./ViewportVideoRenderer";
import type { ViewportPane } from "./ViewportState";
import { ViewportImageRenderer } from "./ViewportImageRenderer";
import ViewportMatplotlibRenderer from "./ViewportMatplotlibRenderer";
import { ViewportPlotlyRenderer } from "./ViewportPlotlyRenderer";
import { ViewportViserRenderer } from "./ViewportViserRenderer";

export function ViewportPaneRenderer({ pane }: { pane: ViewportPane }) {
  if (pane.kind !== "root" && pane.refreshPending !== undefined) return null;
  switch (pane.kind) {
    case "root":
      return null;
    case "image":
      return <ViewportImageRenderer pane={pane} />;
    case "matplotlib":
      return <ViewportMatplotlibRenderer pane={pane} />;
    case "plotly":
      return <ViewportPlotlyRenderer pane={pane} />;
    case "video":
      return <ViewportVideoRenderer pane={pane} />;
    case "viser":
      return <ViewportViserRenderer pane={pane} />;
  }
}
