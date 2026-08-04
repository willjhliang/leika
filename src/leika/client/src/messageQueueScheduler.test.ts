import { describe, expect, it, vi } from "vitest";

import { makeMessageQueueScheduler } from "./messageQueueScheduler";

function makeHarness(initiallyHidden: boolean) {
  let hidden = initiallyHidden;
  let nextHandle = 0;
  const frames = new Map<number, () => void>();
  const timers = new Map<number, () => void>();
  const run = vi.fn();
  const scheduler = makeMessageQueueScheduler(run, {
    isHidden: () => hidden,
    requestFrame: (callback) => {
      const handle = ++nextHandle;
      frames.set(handle, callback);
      return handle;
    },
    cancelFrame: (handle) => frames.delete(handle),
    setTimer: (callback) => {
      const handle = ++nextHandle;
      timers.set(handle, callback);
      return handle;
    },
    clearTimer: (handle) => timers.delete(handle),
  });
  return {
    frames,
    timers,
    run,
    scheduler,
    setHidden: (value: boolean) => {
      hidden = value;
    },
  };
}

describe("makeMessageQueueScheduler", () => {
  it("moves a pending frame to a timer when the tab becomes hidden", () => {
    const harness = makeHarness(false);
    harness.scheduler.schedule();
    expect(harness.frames.size).toBe(1);

    harness.setHidden(true);
    harness.scheduler.visibilityChanged();
    expect(harness.frames.size).toBe(0);
    expect(harness.timers.size).toBe(1);

    [...harness.timers.values()][0]();
    expect(harness.run).toHaveBeenCalledOnce();
  });

  it("moves a hidden-tab timer back to a frame and cancels on stop", () => {
    const harness = makeHarness(true);
    harness.scheduler.schedule();
    expect(harness.timers.size).toBe(1);

    harness.setHidden(false);
    harness.scheduler.visibilityChanged();
    expect(harness.timers.size).toBe(0);
    expect(harness.frames.size).toBe(1);

    harness.scheduler.stop();
    expect(harness.frames.size).toBe(0);
    harness.scheduler.schedule();
    expect(harness.frames.size).toBe(0);
  });
});
