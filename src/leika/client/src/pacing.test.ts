import { describe, expect, it } from "vitest";

import { newPacingState, paceBatch } from "./pacing";

describe("paceBatch", () => {
  it("delivers the first batch immediately", () => {
    const state = newPacingState();
    expect(paceBatch(state, 1000, 1000, 0)).toBe(0);
  });

  it("holds an early batch back toward the server's rhythm, damped", () => {
    const state = newPacingState();
    paceBatch(state, 1000, 1000, 0);
    // Sent 50ms after the first, arrived after only 10ms: 40ms early,
    // released at 95% of that.
    expect(paceBatch(state, 1010, 1010, 50)).toBeCloseTo(38);
  });

  it("flushes on a wide server-side gap, where timing cannot matter", () => {
    const state = newPacingState();
    paceBatch(state, 1000, 1000, 0);
    expect(paceBatch(state, 1150, 1150, 200)).toBe(0);
  });

  it("flushes when behind real time instead of smoothing", () => {
    const state = newPacingState();
    paceBatch(state, 1000, 1000, 0);
    // The batch stamped 50ms is handled 200ms after the first arrived.
    expect(paceBatch(state, 1200, 1200, 50)).toBe(0);
  });

  it("delivers an on-time batch immediately", () => {
    const state = newPacingState();
    paceBatch(state, 1000, 1000, 0);
    expect(paceBatch(state, 1049, 1049, 50)).toBe(0);
  });
});
