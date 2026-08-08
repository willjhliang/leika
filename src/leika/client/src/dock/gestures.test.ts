import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createGestureCoordinator,
  dragGesture,
  grabbingCursor,
  suppressTextSelection,
} from "./gestures";

function stubBodyStyle(userSelect = "text", cursor = "crosshair") {
  const style = { userSelect, cursor };
  vi.stubGlobal("document", { body: { style } });
  return style;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createGestureCoordinator", () => {
  it("cancels the previous owner and ignores a stale unregister token", () => {
    const coordinator = createGestureCoordinator();
    const cleanups: string[] = [];
    const unregisterFirst = coordinator.register(() => cleanups.push("first"));
    const unregisterSecond = coordinator.register(() =>
      cleanups.push("second"),
    );

    expect(cleanups).toEqual(["first"]);
    unregisterFirst();
    coordinator.cancel();
    coordinator.cancel();
    unregisterSecond();

    expect(cleanups).toEqual(["first", "second"]);
  });

  it("lets cleanup synchronously transfer ownership", () => {
    const coordinator = createGestureCoordinator();
    const cleanups: string[] = [];
    coordinator.register(() => {
      cleanups.push("outer");
      coordinator.register(() => cleanups.push("inner"));
    });

    coordinator.cancel();
    coordinator.cancel();

    expect(cleanups).toEqual(["outer", "inner"]);
  });
});

describe("global gesture style leases", () => {
  it("restores selection only after every manager releases its lease", () => {
    const style = stubBodyStyle();
    const releaseFirst = suppressTextSelection();
    const releaseSecond = suppressTextSelection();

    releaseFirst();
    releaseFirst();
    expect(style.userSelect).toBe("none");

    releaseSecond();
    expect(style.userSelect).toBe("text");
  });

  it("tracks cursor and selection independently", () => {
    const style = stubBodyStyle();
    const releaseSelection = suppressTextSelection();
    const releaseCursor = grabbingCursor();

    releaseSelection();
    expect(style).toEqual({ userSelect: "text", cursor: "grabbing" });

    releaseCursor();
    expect(style).toEqual({ userSelect: "text", cursor: "crosshair" });
  });
});

describe("dragGesture ownership", () => {
  it("cancels the old manager gesture before starting the new one", () => {
    const style = stubBodyStyle();
    const listeners = new Map<string, Set<EventListener>>();
    vi.stubGlobal("window", {
      addEventListener(type: string, listener: EventListener) {
        const byType = listeners.get(type) ?? new Set<EventListener>();
        byType.add(listener);
        listeners.set(type, byType);
      },
      removeEventListener(type: string, listener: EventListener) {
        listeners.get(type)?.delete(listener);
      },
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const grip = {
      setPointerCapture: vi.fn(),
      releasePointerCapture: vi.fn(),
    } as unknown as Element;
    const coordinator = createGestureCoordinator();
    const events: string[] = [];

    const cancelFirst = dragGesture({
      grip,
      pointerId: 1,
      update: vi.fn(),
      flush: vi.fn(),
      coordinator,
      onStart: () => events.push("first:start"),
      onEnd: (cancelled) => events.push(`first:end:${cancelled}`),
    });
    const cancelSecond = dragGesture({
      grip,
      pointerId: 2,
      update: vi.fn(),
      flush: vi.fn(),
      coordinator,
      onStart: () => events.push("second:start"),
      onEnd: (cancelled) => events.push(`second:end:${cancelled}`),
    });

    expect(events).toEqual(["first:start", "first:end:true", "second:start"]);
    expect(style.userSelect).toBe("none");
    expect(grip.releasePointerCapture).toHaveBeenCalledWith(1);
    cancelFirst();
    expect(style.userSelect).toBe("none");

    cancelSecond();
    expect(events).toEqual([
      "first:start",
      "first:end:true",
      "second:start",
      "second:end:true",
    ]);
    expect(style.userSelect).toBe("text");
    expect(grip.releasePointerCapture).toHaveBeenCalledWith(2);
  });
});
