/** Plotly arrives as a script the server sends through RunJavascriptMessage,
 * so nothing can import it. The message handler reports each evaluated script
 * and renderers subscribe without polling `window.Plotly` on a timer. */

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

type PlotlyReadyListener = (plotly: PlotlyGlobal) => void;

interface PlotlyReadySubscription {
  listener: PlotlyReadyListener | null;
  scheduled: boolean;
}

/** Cancellable delivery of the optional runtime to every waiting renderer.
 *
 * A missing runtime may stay missing forever. Unlike Promise reactions,
 * cancelled subscriptions release their callback immediately, so repeated
 * figure updates retain only the latest request per mounted renderer. */
export class PlotlyReadiness {
  private subscriptions = new Set<PlotlyReadySubscription>();

  constructor(
    private readonly current: () => PlotlyGlobal | undefined = getPlotly,
  ) {}

  subscribe(listener: PlotlyReadyListener): () => void {
    const subscription: PlotlyReadySubscription = {
      listener,
      scheduled: false,
    };
    this.subscriptions.add(subscription);
    const plotly = this.current();
    if (plotly !== undefined) this.schedule(subscription, plotly);

    return () => {
      this.subscriptions.delete(subscription);
      subscription.listener = null;
    };
  }

  noteMaybeLoaded(): void {
    const plotly = this.current();
    if (plotly === undefined) return;
    for (const subscription of this.subscriptions) {
      this.schedule(subscription, plotly);
    }
  }

  get pendingSubscriptionCount(): number {
    return this.subscriptions.size;
  }

  private schedule(
    subscription: PlotlyReadySubscription,
    plotly: PlotlyGlobal,
  ): void {
    if (subscription.scheduled || subscription.listener === null) return;
    subscription.scheduled = true;
    // Match the old Promise-based readiness boundary: render after the script
    // message finishes, while leaving one turn in which unmount can cancel it.
    queueMicrotask(() => {
      this.subscriptions.delete(subscription);
      const listener = subscription.listener;
      subscription.listener = null;
      listener?.(plotly);
    });
  }
}

const plotlyReadiness = new PlotlyReadiness();

export function subscribePlotlyReady(
  listener: PlotlyReadyListener,
): () => void {
  return plotlyReadiness.subscribe(listener);
}

/** Called after every server-sent script runs; notifies once Plotly exists. */
export function notePlotlyMaybeLoaded(): void {
  plotlyReadiness.noteMaybeLoaded();
}
