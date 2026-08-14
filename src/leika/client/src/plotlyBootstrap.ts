import { getPlotly, notePlotlyMaybeLoaded } from "./plotlyReady";
import type { Message } from "./WebsocketMessages";

/** Python bounds the UTF-8 runtime at 32 MiB; this allocation-free UTF-16
 * ceiling independently protects the browser execution boundary. */
export const MAX_PLOTLY_BOOTSTRAP_CODE_UNITS = 32 * 1024 * 1024;

export class PlotlyBootstrapGate {
  private loaded = false;

  constructor(
    private readonly evaluate: (source: string) => void = (source) =>
      new Function(source)(),
    private readonly ready: () => boolean = () => getPlotly() !== undefined,
    private readonly onReady: () => void = notePlotlyMaybeLoaded,
    private readonly maxSourceCodeUnits = MAX_PLOTLY_BOOTSTRAP_CODE_UNITS,
  ) {}

  preflight(messages: readonly Message[]): string | null {
    let declarations = 0;
    for (const message of messages) {
      if (message.type !== "RunJavascriptMessage") continue;
      declarations += 1;
      if (message.source.length > this.maxSourceCodeUnits) {
        return "Plotly bootstrap exceeds the browser source limit";
      }
    }
    if (declarations > 1 || (declarations === 1 && this.loaded)) {
      return "Plotly bootstrap may run only once per connection";
    }
    return null;
  }

  execute(messages: readonly Message[]): string | null {
    const message = messages.find(
      (candidate) => candidate.type === "RunJavascriptMessage",
    );
    if (message?.type !== "RunJavascriptMessage") return null;
    try {
      this.evaluate(message.source);
      if (!this.ready()) {
        return "Server bootstrap did not install the Plotly runtime";
      }
      this.loaded = true;
      this.onReady();
      return null;
    } catch (error) {
      const detail =
        error instanceof Error && error.message.length > 0
          ? ": " + error.message
          : "";
      return "Plotly bootstrap execution failed" + detail;
    }
  }

  reset(): void {
    this.loaded = false;
  }
}

export const plotlyBootstrap = new PlotlyBootstrapGate();
