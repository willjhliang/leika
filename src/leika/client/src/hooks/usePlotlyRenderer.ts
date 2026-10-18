import * as React from "react";

import { plotlyRuntime, type PlotlyGlobal } from "../plotlyReady";
import type { ParsedPlotlyFigure } from "../viewport/plotlyPayload";

export interface PlotlyRenderRequest {
  figure: ParsedPlotlyFigure;
  layout: Record<string, unknown>;
}

type PlotlyFailure = {
  request: PlotlyRenderRequest;
  message: string;
};

/** The child node Plotly renders into. It is created only once the runtime
 * has loaded, so it keeps the runtime that must purge it. */
interface PlotlyHost {
  node: HTMLDivElement;
  plotly: PlotlyGlobal;
  /** A `react()` call on `node` has not settled yet. */
  pending: boolean;
}

/** Leave a Plotly node clean even if Plotly's own cleanup rejects it. */
function purgePlotlyHost({ node, plotly }: PlotlyHost): void {
  try {
    plotly.purge(node);
  } catch (error) {
    console.error("Plotly cleanup failed:", error);
  }
  node.replaceChildren();
  // Plotly decorates the host itself. `purge()` does not consistently remove
  // that marker in every supported browser, so a failed render could otherwise
  // look like a live plot after all of its children were gone.
  node.classList.remove("js-plotly-plot");
}

function releasePlotlyHost(host: { current: PlotlyHost | null }): void {
  if (host.current !== null) purgePlotlyHost(host.current);
  host.current = null;
}

/** Render `request` into the root's Plotly child once the runtime has loaded.
 * Returns the effect cleanup, after which this render can no longer report a
 * failure or claim the visible node. */
export function renderPlotly(
  root: HTMLDivElement,
  host: { current: PlotlyHost | null },
  request: PlotlyRenderRequest,
  setFailure: (failure: PlotlyFailure | null) => void,
): () => void {
  let current = true;
  const loadTimeout = setTimeout(
    () => setFailure({ request, message: "Plotly failed to load." }),
    10_000,
  );
  void plotlyRuntime.then((plotly) => {
    clearTimeout(loadTimeout);
    if (!current) return;
    setFailure(null);
    // Plotly has no cancellation API. Move a still-pending render off screen
    // before starting this one, so its eventual mutations land only on a
    // detached node and cannot block or overwrite current data.
    if (host.current === null || host.current.pending) {
      releasePlotlyHost(host);
      const node = document.createElement("div");
      root.replaceChildren(node);
      host.current = { node, plotly, pending: false };
    }
    const target = host.current;
    target.pending = true;
    // The executor turns a synchronous throw into a rejection.
    void new Promise((resolve) =>
      resolve(
        plotly.react(
          target.node,
          request.figure.data,
          request.layout,
          request.figure.config,
        ),
      ),
    )
      .catch((error: unknown) => {
        purgePlotlyHost(target);
        if (!current) return;
        console.error("Plotly render failed:", error);
        setFailure({ request, message: "Plotly failed to render." });
      })
      .finally(() => {
        target.pending = false;
        // A superseded render may mutate its detached node until it settles.
        if (host.current !== target) purgePlotlyHost(target);
      });
  });
  return () => {
    current = false;
    clearTimeout(loadTimeout);
  };
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
  const host = React.useRef<PlotlyHost | null>(null);
  const [failure, setFailure] = React.useState<PlotlyFailure | null>(null);

  React.useEffect(() => {
    const root = plotRef.current;
    if (root === null) return;
    if (inputError !== null || request === null) {
      setFailure(null);
      root.replaceChildren();
      releasePlotlyHost(host);
      return;
    }
    // Keep the last plot while the host has no size to give Plotly.
    if (!ready) return;
    return renderPlotly(root, host, request, setFailure);
  }, [request, inputError, ready]);

  React.useEffect(() => () => releasePlotlyHost(host), []);

  return {
    plotRef,
    message:
      inputError ??
      (request !== null && failure?.request === request
        ? failure.message
        : null),
  };
}
