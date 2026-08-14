import { describe, expect, it, vi } from "vitest";

import { RasterPixelBudget } from "./rasterPixelBudget";

describe("RasterPixelBudget", () => {
  it("admits the exact aggregate pixel boundary and rejects +1 atomically", () => {
    const budget = new RasterPixelBudget(10);
    const first = budget.reserve({ width: 2, height: 3 });
    const second = budget.reserve({ width: 2, height: 2 });
    expect(first?.pixels).toBe(6);
    expect(second?.pixels).toBe(4);
    expect(budget.usedPixels).toBe(10);
    expect(budget.reserve({ width: 1, height: 1 })).toBeNull();
    expect(budget.usedPixels).toBe(10);
  });

  it("releases once and notifies denied owners that capacity changed", () => {
    const budget = new RasterPixelBudget(4);
    const listener = vi.fn();
    const unsubscribe = budget.subscribe(listener);
    const lease = budget.reserve({ width: 2, height: 2 })!;
    expect(listener).not.toHaveBeenCalled();

    lease.release();
    lease.release();
    expect(budget.usedPixels).toBe(0);
    expect(listener).toHaveBeenCalledOnce();
    expect(budget.reserve({ width: 2, height: 2 })).not.toBeNull();
    unsubscribe();
  });

  it("rejects unsafe, empty, and individually over-budget dimensions", () => {
    const budget = new RasterPixelBudget(10);
    expect(budget.reserve({ width: 0, height: 1 })).toBeNull();
    expect(budget.reserve({ width: 11, height: 1 })).toBeNull();
    expect(
      budget.reserve({ width: Number.MAX_SAFE_INTEGER, height: 2 }),
    ).toBeNull();
    expect(budget.usedPixels).toBe(0);
  });

  it("atomically transfers a mounted owner's replacement delta", () => {
    const budget = new RasterPixelBudget(10);
    const first = budget.reserve({ width: 2, height: 3 })!;
    const other = budget.reserve({ width: 1, height: 2 })!;

    const replacement = budget.replace(first, { width: 2, height: 4 });
    expect(replacement?.pixels).toBe(8);
    expect(first.active).toBe(false);
    expect(replacement?.active).toBe(true);
    expect(budget.usedPixels).toBe(10);

    const rejected = budget.replace(replacement, { width: 3, height: 3 });
    expect(rejected).toBeNull();
    expect(replacement?.active).toBe(true);
    expect(budget.usedPixels).toBe(10);

    replacement?.release();
    other.release();
    expect(budget.usedPixels).toBe(0);
  });

  it("invalidates stale connection leases without later underflow", () => {
    const budget = new RasterPixelBudget(4);
    const listener = vi.fn();
    budget.subscribe(listener);
    const stale = budget.reserve({ width: 2, height: 2 })!;

    budget.reset();
    expect(stale.active).toBe(false);
    expect(budget.usedPixels).toBe(0);
    expect(listener).toHaveBeenCalledOnce();
    expect(budget.reserve({ width: 2, height: 2 })).not.toBeNull();
    expect(() => stale.release()).not.toThrow();
    expect(budget.usedPixels).toBe(4);
  });
});
