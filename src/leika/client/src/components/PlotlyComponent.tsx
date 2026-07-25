import { Maximize2Icon } from "lucide-react";
import React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { GuiPlotlyMessage } from "../WebsocketMessages";
import { HintTooltip } from "./common";

function useElementWidth() {
  const [node, setNode] = React.useState<HTMLDivElement | null>(null);
  const [width, setWidth] = React.useState(0);
  const ref = React.useCallback((element: HTMLDivElement | null) => {
    setNode(element);
  }, []);
  React.useLayoutEffect(() => {
    if (node === null) return;
    const update = () => setWidth(node.getBoundingClientRect().width);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  return { ref, width };
}

function PlotWithAspect(props: {
  jsonStr: string;
  aspectRatio: number;
  onExpand?: () => void;
}) {
  if (props.jsonStr === "") return null;
  return <PlotWithAspectInner {...props} />;
}

const PlotWithAspectInner = React.memo(function PlotWithAspectInner({
  jsonStr,
  aspectRatio,
  onExpand,
}: {
  jsonStr: string;
  aspectRatio: number;
  onExpand?: () => void;
}) {
  const { ref, width } = useElementWidth();
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
      { ...plotJson.layout, width, height: width * aspectRatio },
      plotJson.config,
    );
  }, [plotJson, width, aspectRatio]);

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
    <div ref={ref} className="relative overflow-hidden">
      <div ref={plotRef} />
      {onExpand === undefined ? null : (
        <HintTooltip hint="Expand plot">
          <Button
            type="button"
            variant="secondary"
            size="icon-sm"
            className="absolute right-2 bottom-2"
            onClick={onExpand}
            aria-label="Expand plot"
          >
            <Maximize2Icon />
          </Button>
        </HintTooltip>
      )}
    </div>
  );
});

export default function PlotlyComponent(message: GuiPlotlyMessage) {
  if (!message.props.visible) return null;
  return <PlotlyComponentInner {...message} />;
}

function PlotlyComponentInner({
  props: { _plotly_json_str: plotlyJsonString, aspect },
}: GuiPlotlyMessage) {
  const [opened, setOpened] = React.useState(false);
  return (
    <>
      <PlotWithAspect
        jsonStr={plotlyJsonString}
        aspectRatio={aspect}
        onExpand={() => setOpened(true)}
      />
      <Dialog open={opened} onOpenChange={setOpened}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-auto sm:max-w-4xl">
          <DialogHeader className="sr-only">
            <DialogTitle>Expanded Plotly plot</DialogTitle>
          </DialogHeader>
          <PlotWithAspect jsonStr={plotlyJsonString} aspectRatio={aspect} />
        </DialogContent>
      </Dialog>
    </>
  );
}
