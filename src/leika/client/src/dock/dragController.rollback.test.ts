import type { PointerEvent as ReactPointerEvent } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createDragController } from "./dragController";
import { group, leaf } from "./testUtils";
import { DockLayout, emptyLayout } from "./types";

const gestureBindings = vi.hoisted(
  () =>
    [] as {
      onMove: (event: PointerEvent) => void;
      onEnd: (event: PointerEvent, cancelled: boolean) => void;
      detach: ReturnType<typeof vi.fn>;
    }[],
);
const animationFrames = vi.hoisted(() => [] as FrameRequestCallback[]);

vi.mock("react-dom", () => ({
  flushSync: (callback: () => void) => callback(),
}));

vi.mock("./gestures", () => ({
  bindPointerGesture: (
    onMove: (event: PointerEvent) => void,
    onEnd: (event: PointerEvent, cancelled: boolean) => void,
  ) => {
    const detach = vi.fn();
    gestureBindings.push({ onMove, onEnd, detach });
    return detach;
  },
  grabbingCursor: () => vi.fn(),
  motionExceedsThreshold: () => true,
  suppressTextSelection: () => vi.fn(),
  tryCapture: vi.fn(),
  tryRelease: vi.fn(),
}));

function gestureCoordinator() {
  let cleanup: (() => void) | null = null;
  return {
    cancel() {
      const current = cleanup;
      cleanup = null;
      current?.();
    },
    register(next: () => void) {
      this.cancel();
      cleanup = next;
      return () => {
        if (cleanup === next) cleanup = null;
      };
    },
  };
}

function box(
  left: number,
  top: number,
  width: number,
  height: number,
): DOMRect {
  return {
    x: left,
    y: top,
    left,
    top,
    right: left + width,
    bottom: top + height,
    width,
    height,
    toJSON: () => ({}),
  } as DOMRect;
}

function pointer(clientX: number, clientY: number): PointerEvent {
  return {
    type: "pointermove",
    pointerId: 7,
    clientX,
    clientY,
  } as PointerEvent;
}

function beginDeferredGroupDrag(trigger = true) {
  const before = emptyLayout();
  before.groups = { a: group("a") };
  before.docked.left = leaf("a");

  const sourceElement = {
    getBoundingClientRect: () => box(0, 0, 300, 400),
  } as HTMLElement;
  const floatingElement = {
    getBoundingClientRect: () => box(0, 0, 300, 400),
    isConnected: true,
    offsetLeft: 0,
    offsetTop: 0,
    style: {},
  } as HTMLElement;
  const container = {
    getBoundingClientRect: () => box(0, 0, 800, 600),
    querySelector: (selector: string) =>
      selector.includes("data-floating-window")
        ? floatingElement
        : selector.includes("data-dock-group")
          ? sourceElement
          : null,
    querySelectorAll: () => [],
  } as unknown as HTMLDivElement;

  const layoutRef = { current: before };
  const restoreLayout = vi.fn((snapshot: DockLayout) => {
    layoutRef.current = snapshot;
  });
  const applyOp = vi.fn((next: DockLayout) => {
    layoutRef.current = next;
  });
  const controller = createDragController({
    containerRef: { current: container },
    layoutRef,
    reservedWidthRef: { current: { left: 0, right: 0 } },
    draggingWindowIdRef: { current: null },
    gestureCoordinator: gestureCoordinator(),
    settleTimer: { current: undefined },
    panelsRef: { current: {} },
    applyOp,
    restoreLayout,
    showHint: vi.fn(),
    setDraggingGroupId: vi.fn(),
    setDraggingTabId: vi.fn(),
  });
  const target = { contains: () => true } as unknown as HTMLElement;
  controller.startGroupDrag(
    {
      button: 0,
      clientX: 10,
      clientY: 10,
      pointerId: 7,
      currentTarget: target,
      target,
    } as unknown as ReactPointerEvent<HTMLElement>,
    "a",
  );

  expect(gestureBindings).toHaveLength(1);
  if (trigger) {
    gestureBindings[0].onMove(pointer(80, 80));
    expect(gestureBindings).toHaveLength(2);
    expect(layoutRef.current).not.toBe(before);
  }

  return {
    before,
    layoutRef,
    restoreLayout,
    controller,
    target,
    move: (event: PointerEvent) => gestureBindings[1].onMove(event),
    cancel: () => gestureBindings[1].onEnd(pointer(80, 80), true),
  };
}

beforeEach(() => {
  gestureBindings.length = 0;
  animationFrames.length = 0;
  vi.stubGlobal(
    "requestAnimationFrame",
    (callback: FrameRequestCallback): number => {
      animationFrames.push(callback);
      return animationFrames.length;
    },
  );
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("manager gesture ownership", () => {
  it("cancels an armed press before a second press takes ownership", () => {
    const { controller, target } = beginDeferredGroupDrag(false);
    const firstPress = gestureBindings[0];

    controller.startGroupDrag(
      {
        button: 0,
        clientX: 20,
        clientY: 20,
        pointerId: 8,
        currentTarget: target,
        target,
      } as unknown as ReactPointerEvent<HTMLElement>,
      "a",
    );

    expect(firstPress.detach).toHaveBeenCalledOnce();
    expect(gestureBindings).toHaveLength(2);
    firstPress.onMove(pointer(80, 80));
    expect(gestureBindings).toHaveLength(2);

    gestureBindings[1].onMove({ ...pointer(80, 80), pointerId: 8 });
    expect(gestureBindings).toHaveLength(3);
    gestureBindings[2].onEnd({ ...pointer(80, 80), pointerId: 8 }, true);
  });
});

describe("deferred drag cancellation", () => {
  it("restores the pre-drag snapshot when its up-front commit is still current", () => {
    const { before, layoutRef, restoreLayout, cancel } =
      beginDeferredGroupDrag();

    cancel();

    expect(restoreLayout).toHaveBeenCalledOnce();
    expect(restoreLayout).toHaveBeenCalledWith(before);
    expect(layoutRef.current).toBe(before);
  });

  it("preserves a concurrent layout commit before the first drag frame", () => {
    const { layoutRef, restoreLayout, cancel } = beginDeferredGroupDrag();
    const concurrent = emptyLayout();
    layoutRef.current = concurrent;

    cancel();

    expect(restoreLayout).not.toHaveBeenCalled();
    expect(layoutRef.current).toBe(concurrent);
  });

  it("preserves a concurrent layout commit after hit targets rebase to it", () => {
    const { layoutRef, restoreLayout, move, cancel } = beginDeferredGroupDrag();
    const concurrent = emptyLayout();
    layoutRef.current = concurrent;
    move(pointer(500, 300));
    expect(animationFrames).toHaveLength(1);
    animationFrames[0](0);

    cancel();

    expect(restoreLayout).not.toHaveBeenCalled();
    expect(layoutRef.current).toBe(concurrent);
  });
});
