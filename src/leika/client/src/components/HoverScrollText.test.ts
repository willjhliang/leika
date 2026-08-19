import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HoverScrollText } from "./HoverScrollText";

const motion = vi.hoisted(() => ({
  prefersReducedMotion: vi.fn(() => false),
}));
vi.mock("@/utils/motion", () => motion);

import {
  HOVER_SCROLL_PAUSE_MS,
  HOVER_SCROLL_START_DELAY_MS,
  startHoverScrollCycle,
} from "./hoverScroll";

function installFrameHarness() {
  const callbacks = new Map<number, FrameRequestCallback>();
  let nextFrame = 0;
  let now = 0;
  vi.stubGlobal("performance", { now: () => now });
  vi.stubGlobal(
    "requestAnimationFrame",
    (callback: FrameRequestCallback): number => {
      const frame = ++nextFrame;
      callbacks.set(frame, callback);
      return frame;
    },
  );
  vi.stubGlobal("cancelAnimationFrame", (frame: number) => {
    callbacks.delete(frame);
  });

  return {
    callbacks,
    advance(nextNow: number) {
      now = nextNow;
      const frame = callbacks.entries().next().value;
      if (frame === undefined) throw new Error("No animation frame queued");
      callbacks.delete(frame[0]);
      frame[1](nextNow);
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  motion.prefersReducedMotion.mockReset();
  motion.prefersReducedMotion.mockReturnValue(false);
});

describe("HoverScrollText", () => {
  it("keeps one accessible copy of the text in a clipped measurement box", () => {
    const markup = renderToStaticMarkup(
      React.createElement(
        HoverScrollText,
        { className: "flex-1", title: "A long label" },
        "A long label",
      ),
    );

    expect(markup.match(/>A long label</g)).toHaveLength(1);
    expect(markup).toContain("data-leika-hover-scroll");
    expect(markup).toContain("data-leika-hover-scroll-content");
    expect(markup).toContain("truncate");
    expect(markup).toContain("flex-1");
    expect(markup).toContain('title="A long label"');
  });

  it("does not mark text as overflowing or active before measurement", () => {
    const markup = renderToStaticMarkup(
      React.createElement(HoverScrollText, null, "Short"),
    );

    expect(markup).not.toContain("data-leika-hover-scroll-overflow");
    expect(markup).not.toContain("data-leika-hover-scroll-active");
  });
});

describe("startHoverScrollCycle", () => {
  it("uses the same fixed rests and instant reset for every surface", () => {
    const frames = installFrameHarness();
    let position = -1;
    const lifecycle: string[] = [];
    const cycle = startHoverScrollCycle({
      maximum: 2,
      setPosition: (next) => {
        position = next;
      },
      onStart: () => lifecycle.push("start"),
      onStop: () => lifecycle.push("stop"),
    });

    expect(position).toBe(0);
    expect(lifecycle).toEqual(["start"]);

    frames.advance(HOVER_SCROLL_START_DELAY_MS - 1);
    expect(position).toBe(0);
    frames.advance(HOVER_SCROLL_START_DELAY_MS);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 64);
    expect(position).toBe(2);

    frames.advance(
      HOVER_SCROLL_START_DELAY_MS + 64 + HOVER_SCROLL_PAUSE_MS - 1,
    );
    expect(position).toBe(2);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 64 + HOVER_SCROLL_PAUSE_MS);
    expect(position).toBe(0);

    frames.advance(
      HOVER_SCROLL_START_DELAY_MS + 64 + HOVER_SCROLL_PAUSE_MS * 2 - 1,
    );
    expect(position).toBe(0);
    frames.advance(
      HOVER_SCROLL_START_DELAY_MS + 64 + HOVER_SCROLL_PAUSE_MS * 2,
    );
    frames.advance(
      HOVER_SCROLL_START_DELAY_MS + 128 + HOVER_SCROLL_PAUSE_MS * 2,
    );
    expect(position).toBe(2);

    cycle.stop();
    expect(lifecycle).toEqual(["start", "stop"]);
    expect(frames.callbacks.size).toBe(0);
  });

  it("travels at 40 pixels per second regardless of overflow distance", () => {
    const positionAfterOneFrame = (maximum: number): number => {
      const frames = installFrameHarness();
      let position = -1;
      const cycle = startHoverScrollCycle({
        maximum,
        setPosition: (next) => {
          position = next;
        },
      });

      frames.advance(HOVER_SCROLL_START_DELAY_MS);
      frames.advance(HOVER_SCROLL_START_DELAY_MS + 16);
      cycle.stop();
      return position;
    };

    expect(positionAfterOneFrame(8)).toBeCloseTo(0.64);
    expect(positionAfterOneFrame(80)).toBeCloseTo(0.64);
  });

  it("keeps pointer ownership while overflow disappears and returns", () => {
    const frames = installFrameHarness();
    const positions: number[] = [];
    const lifecycle: string[] = [];
    const cycle = startHoverScrollCycle({
      maximum: 0,
      setPosition: (position) => positions.push(position),
      onStart: () => lifecycle.push("start"),
      onStop: () => lifecycle.push("stop"),
    });

    expect(positions).toEqual([]);
    expect(lifecycle).toEqual([]);
    expect(frames.callbacks.size).toBe(0);

    cycle.reconcileMaximum(8);
    expect(positions).toEqual([0]);
    expect(lifecycle).toEqual(["start"]);
    expect(frames.callbacks.size).toBe(1);

    cycle.reconcileMaximum(0);
    expect(positions.at(-1)).toBe(0);
    expect(lifecycle).toEqual(["start", "stop"]);
    expect(frames.callbacks.size).toBe(0);

    cycle.reconcileMaximum(12);
    expect(positions.at(-1)).toBe(0);
    expect(lifecycle).toEqual(["start", "stop", "start"]);
    expect(frames.callbacks.size).toBe(1);

    cycle.stop();
    expect(lifecycle).toEqual(["start", "stop", "start", "stop"]);
  });

  it("resumes at 40 pixels per second when overflow grows at the old endpoint", () => {
    const frames = installFrameHarness();
    let position = -1;
    const cycle = startHoverScrollCycle({
      maximum: 2,
      setPosition: (next) => {
        position = next;
      },
    });

    frames.advance(HOVER_SCROLL_START_DELAY_MS);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 50);
    expect(position).toBe(2);

    cycle.reconcileMaximum(10);
    expect(position).toBe(2);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 66);
    expect(position).toBeCloseTo(2.64);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 130);
    expect(position).toBeCloseTo(5.2);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 194);
    expect(position).toBeCloseTo(7.76);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 250);
    expect(position).toBe(10);

    // Growth invalidates the old endpoint's rest. Arrival at the new endpoint
    // starts a fresh full pause instead.
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 549);
    expect(position).toBe(10);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 749);
    expect(position).toBe(10);
    frames.advance(HOVER_SCROLL_START_DELAY_MS + 750);
    expect(position).toBe(0);

    cycle.stop();
  });

  it("tracks the reconciled endpoint under reduced motion", () => {
    motion.prefersReducedMotion.mockReturnValue(true);
    const requestFrame = vi.fn();
    vi.stubGlobal("requestAnimationFrame", requestFrame);

    let position = -1;
    const lifecycle: string[] = [];
    const cycle = startHoverScrollCycle({
      maximum: 24,
      setPosition: (next) => {
        position = next;
      },
      onStart: () => lifecycle.push("start"),
      onStop: () => lifecycle.push("stop"),
    });

    expect(position).toBe(24);
    expect(lifecycle).toEqual(["start"]);
    expect(requestFrame).not.toHaveBeenCalled();

    cycle.reconcileMaximum(40);
    expect(position).toBe(40);
    cycle.reconcileMaximum(0);
    expect(position).toBe(0);
    expect(lifecycle).toEqual(["start", "stop"]);

    cycle.reconcileMaximum(12);
    expect(position).toBe(12);
    expect(lifecycle).toEqual(["start", "stop", "start"]);
    expect(requestFrame).not.toHaveBeenCalled();

    cycle.stop();
    expect(lifecycle).toEqual(["start", "stop", "start", "stop"]);
  });
});
