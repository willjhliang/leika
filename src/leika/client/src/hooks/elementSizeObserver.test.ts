import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { observeElementSize } from "./elementSizeObserver";

class TestResizeObserver {
  static instances: TestResizeObserver[] = [];
  observe = vi.fn();
  unobserve = vi.fn();
  disconnect = vi.fn();
  constructor(private readonly callback: ResizeObserverCallback) {
    TestResizeObserver.instances.push(this);
  }
  emit(target: HTMLElement, width: number, height: number, borderBox = true) {
    this.callback(
      [
        {
          target,
          borderBoxSize: borderBox
            ? [{ inlineSize: width, blockSize: height }]
            : [],
        } as unknown as ResizeObserverEntry,
      ],
      this as unknown as ResizeObserver,
    );
  }
}

function element(width = 100, height = 50) {
  return {
    getBoundingClientRect: vi.fn(() => ({ width, height })),
  } as unknown as HTMLElement;
}

const cleanup: (() => void)[] = [];
beforeEach(() => {
  TestResizeObserver.instances = [];
  vi.stubGlobal("ResizeObserver", TestResizeObserver);
});
afterEach(() => {
  for (const unsubscribe of cleanup.splice(0)) unsubscribe();
  vi.unstubAllGlobals();
});

describe("shared plot size observer", () => {
  it("measures initially, then uses delivered border boxes without layout reads", () => {
    const target = element();
    const onSize = vi.fn();
    cleanup.push(observeElementSize(target, onSize));
    const observer = TestResizeObserver.instances[0];
    expect(onSize).toHaveBeenLastCalledWith({ width: 100, height: 50 });
    expect(observer.observe).toHaveBeenCalledWith(target, {
      box: "border-box",
    });

    // Native RO includes an initial delivery. It should not update React again.
    observer.emit(target, 100, 50);
    expect(onSize).toHaveBeenCalledTimes(1);
    for (let width = 101; width <= 1100; width += 1)
      observer.emit(target, width, 50);
    expect(onSize).toHaveBeenCalledTimes(1001);
    expect(onSize).toHaveBeenLastCalledWith({ width: 1100, height: 50 });
    expect(target.getBoundingClientRect).toHaveBeenCalledTimes(1);

    // Hidden hosts report zero and must stop submitting Plotly renders.
    observer.emit(target, 0, 0);
    expect(onSize).toHaveBeenLastCalledWith({ width: 0, height: 0 });
  });

  it("shares one observer and retains a target until its final subscriber leaves", () => {
    const first = element();
    const second = element();
    const onSize = vi.fn();
    const unsubscribeFirst = observeElementSize(first, onSize);
    const unsubscribeAgain = observeElementSize(first, onSize);
    const unsubscribeSecond = observeElementSize(second, onSize);
    cleanup.push(unsubscribeFirst, unsubscribeAgain, unsubscribeSecond);
    expect(TestResizeObserver.instances).toHaveLength(1);
    const observer = TestResizeObserver.instances[0];
    expect(observer.observe).toHaveBeenCalledTimes(2);
    expect(first.getBoundingClientRect).toHaveBeenCalledTimes(1);

    unsubscribeFirst();
    unsubscribeFirst();
    expect(observer.unobserve).not.toHaveBeenCalled();
    unsubscribeAgain();
    expect(observer.unobserve).toHaveBeenCalledExactlyOnceWith(first);
    expect(observer.disconnect).not.toHaveBeenCalled();
    unsubscribeSecond();
    expect(observer.disconnect).toHaveBeenCalledTimes(1);
  });

  it("ignores late deliveries from released observers, including remounted targets", () => {
    const target = element();
    const firstCallback = vi.fn();
    const unsubscribe = observeElementSize(target, firstCallback);
    const firstObserver = TestResizeObserver.instances[0];
    unsubscribe();
    const nextCallback = vi.fn();
    cleanup.push(observeElementSize(target, nextCallback));
    firstObserver.emit(target, 200, 200);
    expect(firstCallback).toHaveBeenCalledTimes(1);
    expect(nextCallback).toHaveBeenCalledExactlyOnceWith({
      width: 100,
      height: 50,
    });
    TestResizeObserver.instances[1].emit(target, 300, 100);
    expect(nextCallback).toHaveBeenLastCalledWith({ width: 300, height: 100 });
  });

  it("falls back to DOM measurement when a browser has no border-box entry", () => {
    const target = element();
    cleanup.push(observeElementSize(target, vi.fn()));
    TestResizeObserver.instances[0].emit(target, 100, 50, false);
    expect(target.getBoundingClientRect).toHaveBeenCalledTimes(2);
  });

  it("keeps initial measurement available without ResizeObserver", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    const onSize = vi.fn();
    cleanup.push(observeElementSize(element(), onSize));
    expect(onSize).toHaveBeenCalledExactlyOnceWith({ width: 100, height: 50 });
    expect(TestResizeObserver.instances).toHaveLength(0);
  });
});
