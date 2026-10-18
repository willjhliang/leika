import { afterEach, describe, expect, it, vi } from "vitest";

import type { PlotlyRenderRequest } from "./usePlotlyRenderer";

interface FakeElement {
  children: unknown[];
  classList: { remove(): void };
  replaceChildren(...children: unknown[]): void;
}

function fakeElement(): FakeElement {
  const element: FakeElement = {
    children: [],
    classList: { remove: () => undefined },
    replaceChildren: (...children) => {
      element.children = children;
    },
  };
  return element;
}

const asDiv = (element: FakeElement) => element as unknown as HTMLDivElement;

const request = (): PlotlyRenderRequest => ({
  figure: { data: [], layout: {}, config: {} },
  layout: {},
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

/** Fresh modules, so each test starts before the runtime has loaded. */
async function load() {
  vi.resetModules();
  vi.stubGlobal("document", { createElement: fakeElement });
  const { runPlotlyBootstrap } = await import("../plotlyReady");
  const { renderPlotly } = await import("./usePlotlyRenderer");
  return { runPlotlyBootstrap, renderPlotly };
}

/** Install a Plotly whose `react()` calls settle only when a test says so. */
async function loadWithRuntime() {
  const { runPlotlyBootstrap, renderPlotly } = await load();
  const renders: {
    node: HTMLElement;
    resolve(): void;
    reject(error: unknown): void;
  }[] = [];
  const plotly = {
    react: vi.fn(
      (node: HTMLElement) =>
        new Promise<void>((resolve, reject) =>
          renders.push({ node, resolve, reject }),
        ),
    ),
    purge: vi.fn(),
  };
  vi.stubGlobal("window", { Plotly: plotly });
  runPlotlyBootstrap("");
  return { renderPlotly, plotly, renders };
}

describe("renderPlotly", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps a superseded pending render off the newer plot", async () => {
    const { renderPlotly, plotly, renders } = await loadWithRuntime();
    const root = fakeElement();
    const host = { current: null };
    const setFailure = vi.fn();

    const cancelStale = renderPlotly(asDiv(root), host, request(), setFailure);
    await flush();
    cancelStale();
    renderPlotly(asDiv(root), host, request(), setFailure);
    await flush();
    const [stale, newer] = renders;
    expect(newer.node).not.toBe(stale.node);
    expect(root.children).toEqual([newer.node]);

    stale.reject(new Error("superseded"));
    newer.resolve();
    await flush();
    expect(root.children).toEqual([newer.node]);
    expect(plotly.purge).toHaveBeenCalledWith(stale.node);
    expect(plotly.purge).not.toHaveBeenCalledWith(newer.node);
    expect(setFailure.mock.calls).toEqual([[null], [null]]);
  });

  it("renders an update into the same node once the last render settled", async () => {
    const { renderPlotly, renders } = await loadWithRuntime();
    const root = fakeElement();
    const host = { current: null };

    const cancelFirst = renderPlotly(asDiv(root), host, request(), vi.fn());
    await flush();
    renders[0].resolve();
    await flush();
    cancelFirst();
    renderPlotly(asDiv(root), host, request(), vi.fn());
    await flush();

    expect(renders[1].node).toBe(renders[0].node);
  });

  it("reports a failure of the current render", async () => {
    const { renderPlotly, plotly } = await loadWithRuntime();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    plotly.react.mockImplementationOnce(() => {
      throw new Error("bad figure");
    });
    const setFailure = vi.fn();
    const current = request();

    renderPlotly(asDiv(fakeElement()), { current: null }, current, setFailure);
    await flush();

    expect(setFailure).toHaveBeenLastCalledWith({
      request: current,
      message: "Plotly failed to render.",
    });
  });

  it("reports a runtime that has not loaded after 10 seconds", async () => {
    const { renderPlotly } = await load();
    vi.useFakeTimers();
    const setFailure = vi.fn();
    const current = request();

    renderPlotly(asDiv(fakeElement()), { current: null }, current, setFailure);
    vi.advanceTimersByTime(9_999);
    expect(setFailure).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);

    expect(setFailure).toHaveBeenCalledExactlyOnceWith({
      request: current,
      message: "Plotly failed to load.",
    });
  });
});
