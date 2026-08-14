import { describe, expect, it } from "vitest";

import {
  MAX_PENDING_RAW_FRAME_BYTES,
  MAX_PENDING_RAW_FRAMES,
  PendingRawFrameBudget,
} from "./pendingFrameBudget";

describe("PendingRawFrameBudget", () => {
  it("accepts the exact aggregate byte boundary and releases it", () => {
    const budget = new PendingRawFrameBudget();
    const exact = budget.admit(MAX_PENDING_RAW_FRAME_BYTES);
    expect(exact).not.toBeNull();
    expect(budget.bytes).toBe(MAX_PENDING_RAW_FRAME_BYTES);
    expect(budget.admit(1)).toBeNull();

    exact!.release();
    expect(budget.bytes).toBe(0);
    expect(budget.count).toBe(0);
    expect(budget.admit(MAX_PENDING_RAW_FRAME_BYTES + 1)).toBeNull();
  });

  it("bounds tiny pending frame objects independently of bytes", () => {
    const budget = new PendingRawFrameBudget();
    const leases = Array.from({ length: MAX_PENDING_RAW_FRAMES }, () =>
      budget.admit(16),
    );
    expect(leases.every((lease) => lease !== null)).toBe(true);
    expect(budget.count).toBe(MAX_PENDING_RAW_FRAMES);
    expect(budget.admit(16)).toBeNull();

    leases[0]!.release();
    expect(budget.admit(16)).not.toBeNull();
  });

  it("resets old-generation accounting and makes late release harmless", () => {
    const budget = new PendingRawFrameBudget();
    const first = budget.admit(40)!;
    const second = budget.admit(80)!;
    budget.reset();

    expect(budget.count).toBe(0);
    expect(budget.bytes).toBe(0);
    expect(first.isActive).toBe(false);
    first.release();
    second.release();
    expect(budget.bytes).toBe(0);
    expect(budget.admit(MAX_PENDING_RAW_FRAME_BYTES)).not.toBeNull();
  });
});
