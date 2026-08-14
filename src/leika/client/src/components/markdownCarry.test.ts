import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelMarkdownCarry,
  markdownCarryIsActive,
  MARKDOWN_CARRY_DURATION_MS,
  MARKDOWN_CARRY_SETTLEMENT_FRAMES,
  startMarkdownCarry,
  type MarkdownCarryPlatform,
} from "./markdownCarry";

function elements(initialTargetTop: number) {
  const frame = new EventTarget() as unknown as HTMLElement;
  const target = {} as HTMLElement;
  let targetTop = initialTargetTop;
  let frameConnected = true;
  let targetConnected = true;
  Object.defineProperties(frame, {
    clientHeight: { configurable: true, value: 100 },
    getBoundingClientRect: {
      configurable: true,
      value: () => ({ top: 0 }) as DOMRect,
    },
    isConnected: { configurable: true, get: () => frameConnected },
    scrollHeight: { configurable: true, value: 1_000 },
    scrollTop: { configurable: true, writable: true, value: 0 },
  });
  Object.defineProperties(target, {
    getBoundingClientRect: {
      configurable: true,
      value: () => ({ top: targetTop - frame.scrollTop }) as DOMRect,
    },
    isConnected: { configurable: true, get: () => targetConnected },
  });
  return {
    disconnect: (element: "frame" | "target") => {
      if (element === "frame") frameConnected = false;
      else targetConnected = false;
    },
    frame,
    target,
    setTargetTop: (top: number) => {
      targetTop = top;
    },
  };
}

function fakeFrames() {
  let next = 0;
  const callbacks = new Map<number, (now: number) => void>();
  const platform: MarkdownCarryPlatform = {
    now: () => 0,
    requestFrame: (callback) => {
      next += 1;
      callbacks.set(next, callback);
      return next;
    },
    cancelFrame: vi.fn((handle: number) => callbacks.delete(handle)),
  };
  const run = (now: number) => {
    const entry = callbacks.entries().next().value as
      [number, (at: number) => void] | undefined;
    expect(entry).toBeDefined();
    callbacks.delete(entry![0]);
    entry![1](now);
  };
  return { callbacks, platform, run };
}

afterEach(() => {
  cancelMarkdownCarry();
  vi.restoreAllMocks();
});

describe("markdown carry ownership", () => {
  it("tracks layout changes during animation and bounded settlement", () => {
    const owner = {};
    const { frame, target, setTargetTop } = elements(500);
    const { callbacks, platform, run } = fakeFrames();
    startMarkdownCarry(frame, target, owner, platform);
    expect(markdownCarryIsActive(owner)).toBe(true);

    run(MARKDOWN_CARRY_DURATION_MS / 2);
    expect(frame.scrollTop).toBe(437.5);
    setTargetTop(700);
    run(MARKDOWN_CARRY_DURATION_MS);
    expect(frame.scrollTop).toBe(700);
    expect(markdownCarryIsActive(owner)).toBe(true);

    setTargetTop(760);
    run(MARKDOWN_CARRY_DURATION_MS + 16);
    expect(frame.scrollTop).toBe(760);
    for (let at = 2; at <= MARKDOWN_CARRY_SETTLEMENT_FRAMES; at += 1)
      run(MARKDOWN_CARRY_DURATION_MS + at * 16);
    expect(markdownCarryIsActive()).toBe(false);
    expect(callbacks.size).toBe(0);
  });

  it("corrects a layout shift after two quiet settlement frames", () => {
    const owner = {};
    const { frame, target, setTargetTop } = elements(500);
    const { callbacks, platform, run } = fakeFrames();
    startMarkdownCarry(frame, target, owner, platform);

    run(MARKDOWN_CARRY_DURATION_MS);
    run(MARKDOWN_CARRY_DURATION_MS + 16);
    expect(markdownCarryIsActive(owner)).toBe(true);
    run(MARKDOWN_CARRY_DURATION_MS + 32);
    expect(markdownCarryIsActive(owner)).toBe(true);

    setTargetTop(700);
    run(MARKDOWN_CARRY_DURATION_MS + 48);
    expect(frame.scrollTop).toBe(700);
    expect(markdownCarryIsActive(owner)).toBe(true);

    for (let at = 4; at < MARKDOWN_CARRY_SETTLEMENT_FRAMES; at += 1)
      run(MARKDOWN_CARRY_DURATION_MS + at * 16);
    expect(markdownCarryIsActive(owner)).toBe(true);
    run(MARKDOWN_CARRY_DURATION_MS + MARKDOWN_CARRY_SETTLEMENT_FRAMES * 16);
    expect(markdownCarryIsActive()).toBe(false);
    expect(callbacks.size).toBe(0);
  });

  it("releases ownership after the settlement hard cap", () => {
    const owner = {};
    const { frame, target, setTargetTop } = elements(500);
    const { callbacks, platform, run } = fakeFrames();
    startMarkdownCarry(frame, target, owner, platform);
    run(MARKDOWN_CARRY_DURATION_MS);

    for (let at = 1; at <= MARKDOWN_CARRY_SETTLEMENT_FRAMES; at += 1) {
      setTargetTop(500 + at * 10);
      run(MARKDOWN_CARRY_DURATION_MS + at * 16);
    }
    expect(markdownCarryIsActive()).toBe(false);
    expect(callbacks.size).toBe(0);
  });

  it("a stale callback cannot clear or reschedule a newer generation", () => {
    const first = {};
    const second = {};
    const { callbacks, platform } = fakeFrames();
    const firstElements = elements(100);
    const secondElements = elements(200);
    startMarkdownCarry(
      firstElements.frame,
      firstElements.target,
      first,
      platform,
    );
    const stale = callbacks.get(1)!;
    startMarkdownCarry(
      secondElements.frame,
      secondElements.target,
      second,
      platform,
    );

    stale(MARKDOWN_CARRY_DURATION_MS);
    expect(markdownCarryIsActive(first)).toBe(false);
    expect(markdownCarryIsActive(second)).toBe(true);
    expect(callbacks.size).toBe(1);
    cancelMarkdownCarry(second);
  });

  it("renderer cleanup cancels only its own active carry", () => {
    const first = {};
    const second = {};
    const { callbacks, platform } = fakeFrames();
    const firstElements = elements(100);
    const secondElements = elements(100);
    startMarkdownCarry(
      firstElements.frame,
      firstElements.target,
      first,
      platform,
    );
    cancelMarkdownCarry(first);
    expect(markdownCarryIsActive()).toBe(false);

    startMarkdownCarry(
      secondElements.frame,
      secondElements.target,
      second,
      platform,
    );
    cancelMarkdownCarry(first);
    expect(markdownCarryIsActive(second)).toBe(true);
    cancelMarkdownCarry(second);
    expect(callbacks.size).toBe(0);
  });

  it.each(["wheel", "touchstart", "pointerdown", "keydown"])(
    "cancels and removes listeners on %s",
    (event) => {
      const owner = {};
      const { frame, target } = elements(100);
      const add = vi.spyOn(frame, "addEventListener");
      const remove = vi.spyOn(frame, "removeEventListener");
      const { callbacks, platform } = fakeFrames();
      startMarkdownCarry(frame, target, owner, platform);

      frame.dispatchEvent(new Event(event));

      expect(markdownCarryIsActive()).toBe(false);
      expect(callbacks.size).toBe(0);
      expect(remove).toHaveBeenCalledTimes(4);
      if (event !== "keydown")
        expect(add).toHaveBeenCalledWith(event, expect.any(Function), {
          passive: true,
        });
    },
  );

  it.each(["frame", "target"] as const)(
    "cancels and removes listeners when the %s disconnects",
    (disconnected) => {
      const owner = {};
      const { disconnect, frame, target } = elements(100);
      const remove = vi.spyOn(frame, "removeEventListener");
      const { callbacks, platform, run } = fakeFrames();
      startMarkdownCarry(frame, target, owner, platform);
      disconnect(disconnected);

      run(16);

      expect(markdownCarryIsActive()).toBe(false);
      expect(callbacks.size).toBe(0);
      expect(remove).toHaveBeenCalledTimes(4);
    },
  );

  it("clamps the live destination to the scrolling range", () => {
    const owner = {};
    const { frame, target } = elements(2_000);
    const { platform, run } = fakeFrames();
    startMarkdownCarry(frame, target, owner, platform);
    run(MARKDOWN_CARRY_DURATION_MS);
    expect(frame.scrollTop).toBe(900);
  });
});
