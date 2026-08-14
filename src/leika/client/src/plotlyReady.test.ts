import { describe, expect, it, vi } from "vitest";

import { PlotlyReadiness, type PlotlyGlobal } from "./plotlyReady";

const runtime = (): PlotlyGlobal => ({
  react: vi.fn(),
  purge: vi.fn(),
});

describe("PlotlyReadiness", () => {
  it("retains only the latest request while the runtime is missing", async () => {
    const available: { plotly?: PlotlyGlobal } = {};
    const readiness = new PlotlyReadiness(() => available.plotly);
    const rendered: number[] = [];
    let unsubscribe: () => void = () => undefined;

    for (let index = 0; index < 32; index += 1) {
      unsubscribe();
      const request = { index };
      unsubscribe = readiness.subscribe(() => rendered.push(request.index));
      expect(readiness.pendingSubscriptionCount).toBe(1);
    }

    available.plotly = runtime();
    readiness.noteMaybeLoaded();
    // Delivery is a microtask, matching the former Promise boundary.
    expect(rendered).toEqual([]);
    expect(readiness.pendingSubscriptionCount).toBe(1);
    await Promise.resolve();

    expect(rendered).toEqual([31]);
    expect(readiness.pendingSubscriptionCount).toBe(0);
  });

  it("releases an unmounted renderer before late readiness", async () => {
    const available: { plotly?: PlotlyGlobal } = {};
    const readiness = new PlotlyReadiness(() => available.plotly);
    const request = { figure: "removed" };
    const render = vi.fn(() => request.figure);
    const unsubscribe = readiness.subscribe(render);
    expect(readiness.pendingSubscriptionCount).toBe(1);

    unsubscribe();
    expect(readiness.pendingSubscriptionCount).toBe(0);
    available.plotly = runtime();
    readiness.noteMaybeLoaded();
    await Promise.resolve();

    expect(render).not.toHaveBeenCalled();
    expect(readiness.pendingSubscriptionCount).toBe(0);
  });

  it("can cancel readiness already scheduled for the next microtask", async () => {
    const readiness = new PlotlyReadiness(() => runtime());
    const render = vi.fn();
    const unsubscribe = readiness.subscribe(render);
    expect(readiness.pendingSubscriptionCount).toBe(1);

    unsubscribe();
    await Promise.resolve();

    expect(render).not.toHaveBeenCalled();
    expect(readiness.pendingSubscriptionCount).toBe(0);
  });
});
