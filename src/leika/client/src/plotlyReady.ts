/** Plotly arrives as a script the server sends through RunJavascriptMessage,
 * so nothing can import it. Renderers wait on `plotlyRuntime` instead. */

export type PlotlyGlobal = {
  react(
    node: HTMLElement,
    data: unknown,
    layout: unknown,
    config: unknown,
  ): unknown;
  purge(node: HTMLElement): void;
};

const runtime = Promise.withResolvers<PlotlyGlobal>();

/** Resolves with `window.Plotly` once a server script has installed it. */
export const plotlyRuntime = runtime.promise;

/** Run one server-sent script, then resolve the runtime if it now exists. */
export function runPlotlyBootstrap(source: string): void {
  new Function(source)();
  const plotly = (window as unknown as { Plotly?: PlotlyGlobal }).Plotly;
  if (plotly !== undefined) runtime.resolve(plotly);
}
