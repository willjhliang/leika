import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkerBatchReceiptGate } from "./workerBatchReceipt";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("WorkerBatchReceiptGate", () => {
  it("holds exactly one batch until the matching main-thread receipt", () => {
    const firstRelease = vi.fn();
    const secondRelease = vi.fn();
    const firstPost = vi.fn(() => true);
    const secondPost = vi.fn(() => true);
    const gate = new WorkerBatchReceiptGate(7, vi.fn());

    expect(gate.post(1, firstRelease, firstPost)).toBe(true);
    expect(gate.post(2, secondRelease, secondPost)).toBe(false);
    expect(firstPost).toHaveBeenCalledOnce();
    expect(secondPost).not.toHaveBeenCalled();
    expect(firstRelease).not.toHaveBeenCalled();
    expect(secondRelease).not.toHaveBeenCalled();

    expect(gate.acknowledge(6, 1)).toBe(false);
    expect(gate.acknowledge(7, 2)).toBe(false);
    expect(gate.acknowledge(7, 1)).toBe(true);
    expect(firstRelease).toHaveBeenCalledOnce();
    expect(gate.post(2, secondRelease, secondPost)).toBe(true);
  });

  it("releases a failed post and every close/reset exactly once", () => {
    const failedRelease = vi.fn();
    const liveRelease = vi.fn();
    const gate = new WorkerBatchReceiptGate(1, vi.fn());
    expect(gate.post(0, failedRelease, () => false)).toBe(false);
    expect(failedRelease).toHaveBeenCalledOnce();

    expect(gate.post(1, liveRelease, () => true)).toBe(true);
    gate.reset();
    gate.reset();
    expect(liveRelease).toHaveBeenCalledOnce();
    expect(gate.acknowledge(1, 1)).toBe(false);
  });

  it("fails and releases a generation whose receipt times out", () => {
    vi.useFakeTimers();
    const release = vi.fn();
    const timeout = vi.fn();
    const gate = new WorkerBatchReceiptGate(3, timeout, 25);
    expect(gate.post(4, release, () => true)).toBe(true);

    vi.advanceTimersByTime(25);
    expect(release).toHaveBeenCalledOnce();
    expect(timeout).toHaveBeenCalledOnce();
    expect(gate.hasPendingReceipt).toBe(false);
  });
});
