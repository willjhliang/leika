import { describe, expect, it, vi } from "vitest";

import { PlotlyBootstrapGate } from "./plotlyBootstrap";
import type { Message } from "./WebsocketMessages";

const bootstrap = (source: string): Message => ({
  type: "RunJavascriptMessage",
  source,
});

describe("PlotlyBootstrapGate", () => {
  it("preflights source size and one declaration per connection", () => {
    const gate = new PlotlyBootstrapGate(
      () => undefined,
      () => true,
      () => {},
      4,
    );
    expect(gate.preflight([bootstrap("1234")])).toBeNull();
    expect(gate.preflight([bootstrap("12345")])).toContain("source limit");
    expect(gate.preflight([bootstrap("a"), bootstrap("b")])).toContain(
      "only once",
    );
  });

  it("executes once, requires Plotly, and permits a new connection reset", () => {
    const evaluate = vi.fn();
    let ready = true;
    const onReady = vi.fn();
    const gate = new PlotlyBootstrapGate(evaluate, () => ready, onReady);
    const message = bootstrap("runtime");

    expect(gate.execute([message])).toBeNull();
    expect(evaluate).toHaveBeenCalledWith("runtime");
    expect(onReady).toHaveBeenCalledOnce();
    expect(gate.preflight([message])).toContain("only once");

    gate.reset();
    ready = false;
    expect(gate.preflight([message])).toBeNull();
    expect(gate.execute([message])).toContain("did not install");
  });

  it("contains evaluation failures as connection-fatal reasons", () => {
    const gate = new PlotlyBootstrapGate(
      () => {
        throw new Error("syntax failed");
      },
      () => false,
    );
    expect(gate.execute([bootstrap("bad")])).toBe(
      "Plotly bootstrap execution failed: syntax failed",
    );
  });
});
