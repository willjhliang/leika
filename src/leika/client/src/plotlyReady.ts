/** Plotly arrives as a script the server sends through RunJavascriptMessage,
 * so nothing can import it: renderers wait on this promise instead of polling
 * `window.Plotly` on a timer. The message handler reports each evaluated
 * script; the one that defines the global settles the promise. */

export type PlotlyGlobal = {
  react(
    node: HTMLElement,
    data: unknown,
    layout: unknown,
    config: unknown,
  ): unknown;
  purge(node: HTMLElement): void;
};

export function getPlotly(): PlotlyGlobal | undefined {
  return (window as unknown as { Plotly?: PlotlyGlobal }).Plotly;
}

let resolvePlotlyReady: (plotly: PlotlyGlobal) => void;
export const plotlyReady = new Promise<PlotlyGlobal>((resolve) => {
  resolvePlotlyReady = resolve;
});

/** Called after every server-sent script runs; settles once Plotly exists. */
export function notePlotlyMaybeLoaded(): void {
  const plotly = getPlotly();
  if (plotly !== undefined) resolvePlotlyReady(plotly);
}
