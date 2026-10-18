import { afterEach, describe, expect, it, vi } from "vitest";

import { plotlyRuntime, runPlotlyBootstrap } from "./plotlyReady";

describe("runPlotlyBootstrap", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("resolves the runtime once a server script installs Plotly", async () => {
    const page: { Plotly?: unknown } = {};
    vi.stubGlobal("window", page);
    const pending = Symbol("pending");
    const settled = () => Promise.race([plotlyRuntime, pending]);

    runPlotlyBootstrap("window.other = true;");
    expect(await settled()).toBe(pending);

    runPlotlyBootstrap("window.Plotly = { react() {}, purge() {} };");
    expect(page.Plotly).toBeDefined();
    expect(await settled()).toBe(page.Plotly);
  });
});
