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

const installed = () => (window as unknown as { Plotly?: PlotlyGlobal }).Plotly;

/** Run the server's runtime script once, then resolve the runtime. Replays
 * after a reconnect keep the runtime already installed. */
export function runPlotlyBootstrap(source: string): void {
  if (installed() === undefined) new Function(source)();
  const plotly = installed();
  if (plotly !== undefined) runtime.resolve(plotly);
}
