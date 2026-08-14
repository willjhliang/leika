import * as React from "react";

import {
  getPlotly,
  subscribePlotlyReady,
  type PlotlyGlobal,
} from "../plotlyReady";
import { PlotlyRenderQueue } from "../plotlyRenderQueue";
import type { ParsedPlotlyFigure } from "../viewport/plotlyPayload";

export interface PlotlyRenderRequest {
  figure: ParsedPlotlyFigure;
  layout: Record<string, unknown>;
}

type PlotlyFailure = {
  request: PlotlyRenderRequest;
  message: string;
};

/** Leave a Plotly host clean even if the optional server-sent runtime is
 * missing or its own cleanup rejects the node it was handed. */
function purgePlotlyNode(node: HTMLDivElement): void {
  const plotly = getPlotly();
  if (plotly !== undefined) {
    try {
      plotly.purge(node);
    } catch (error) {
      console.error("Plotly cleanup failed:", error);
    }
  }
  node.replaceChildren();
  // Plotly decorates the host itself. `purge()` does not consistently remove
  // that marker in every supported browser, so invalid input could otherwise
  // look like a live plot after all of its children were gone.
  node.classList.remove("js-plotly-plot");
}

function freshPlotlyNode(root: HTMLDivElement): HTMLDivElement {
  const node = document.createElement("div");
  root.replaceChildren(node);
  return node;
}

/** Own one imperative Plotly host.
 *
 * Both inline plots and viewport panes use this lifecycle: input errors clear
 * stale content, a missing runtime becomes visible, synchronous and async
 * render failures are contained, superseded promises cannot overwrite newer
 * state, and unmount always purges Plotly listeners/WebGL resources. */
export function usePlotlyRenderer({
  request,
  inputError,
  ready,
}: {
  request: PlotlyRenderRequest | null;
  inputError: string | null;
  /** False while the host has no non-zero dimensions to give Plotly. */
  ready: boolean;
}): {
  plotRef: React.RefObject<HTMLDivElement | null>;
  message: string | null;
} {
  // React owns this stable root; Plotly owns exactly one child. Keeping that
  // boundary lets a superseded pending render be detached without asking
  // React to reconcile DOM Plotly may still mutate.
  const plotRef = React.useRef<HTMLDivElement>(null);
  const activeNode = React.useRef<HTMLDivElement | null>(null);
  const [failure, setFailure] = React.useState<PlotlyFailure | null>(null);
  const queue = React.useRef(new PlotlyRenderQueue<HTMLDivElement>()).current;

  React.useEffect(() => {
    const root = plotRef.current;
    if (root === null) return;
    const generation = queue.begin();
    if (inputError !== null || request === null) {
      setFailure(null);
      const node = activeNode.current;
      activeNode.current = null;
      root.replaceChildren();
      if (node !== null) {
        queue.release(node);
        purgePlotlyNode(node);
      }
      return () => queue.invalidate(generation);
    }
    if (!ready) {
      const node = activeNode.current;
      if (node !== null && queue.isPending(node)) {
        activeNode.current = null;
        root.replaceChildren();
        queue.release(node);
        purgePlotlyNode(node);
      }
      return () => queue.invalidate(generation);
    }

    const render = (plotly: PlotlyGlobal) => {
      if (!queue.isCurrent(generation)) return;
      setFailure(null);

      let node = activeNode.current;
      // Plotly has no cancellation API. Move a still-pending generation off
      // screen before starting the next one, so its eventual mutations land
      // only on a detached node and cannot block or overwrite current data.
      if (node === null) {
        node = freshPlotlyNode(root);
        activeNode.current = node;
      } else if (queue.isPending(node)) {
        const staleNode = node;
        node = freshPlotlyNode(root);
        activeNode.current = node;
        queue.release(staleNode);
        purgePlotlyNode(staleNode);
      }

      const nodeRef = new WeakRef(node);
      const purgeReleasedNode = () => {
        const releasedNode = nodeRef.deref();
        if (releasedNode !== undefined) purgePlotlyNode(releasedNode);
      };
      void queue.run(
        generation,
        node,
        () =>
          plotly.react(
            node,
            request.figure.data,
            request.layout,
            request.figure.config,
          ),
        purgeReleasedNode,
        (error: unknown) => {
          console.error("Plotly render failed:", error);
          purgeReleasedNode();
          setFailure({ request, message: "Plotly failed to render." });
        },
      );
    };

    const plotly = getPlotly();
    let fallback: number | null = null;
    let unsubscribeReady: (() => void) | null = null;
    if (plotly === undefined) {
      unsubscribeReady = subscribePlotlyReady(render);
      fallback = window.setTimeout(() => {
        if (queue.isCurrent(generation) && getPlotly() === undefined) {
          setFailure({ request, message: "Plotly failed to load." });
        }
      }, 10_000);
    } else {
      render(plotly);
    }

    return () => {
      queue.invalidate(generation);
      unsubscribeReady?.();
      if (fallback !== null) clearTimeout(fallback);
    };
  }, [request, inputError, ready, queue]);

  React.useEffect(() => {
    const root = plotRef.current;
    return () => {
      queue.dispose(() => {
        const node = activeNode.current;
        activeNode.current = null;
        if (root !== null) root.replaceChildren();
        if (node !== null) purgePlotlyNode(node);
      });
    };
  }, [queue]);

  return {
    plotRef,
    message:
      inputError ??
      (request !== null && failure?.request === request
        ? failure.message
        : null),
  };
}
