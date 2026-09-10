import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getColorScheme, subscribeColorScheme } from "./colorSchemeStore";

class TestMutationObserver {
  static instances: TestMutationObserver[] = [];
  observe = vi.fn();
  disconnect = vi.fn();
  constructor(private readonly callback: MutationCallback) {
    TestMutationObserver.instances.push(this);
  }
  emit() {
    this.callback([], this as unknown as MutationObserver);
  }
}

const classes = new Set<string>();
const cleanup: (() => void)[] = [];
beforeEach(() => {
  classes.clear();
  TestMutationObserver.instances = [];
  vi.stubGlobal("MutationObserver", TestMutationObserver);
  vi.stubGlobal("document", {
    documentElement: {
      classList: { contains: (name: string) => classes.has(name) },
    },
  });
});
afterEach(() => {
  for (const unsubscribe of cleanup.splice(0)) unsubscribe();
  vi.unstubAllGlobals();
});

describe("shared resolved color scheme", () => {
  it("uses one native observer and notifies only when the resolved scheme changes", () => {
    const callbacks = Array.from({ length: 100 }, () => vi.fn());
    cleanup.push(...callbacks.map(subscribeColorScheme));
    expect(TestMutationObserver.instances).toHaveLength(1);
    const observer = TestMutationObserver.instances[0];
    expect(getColorScheme()).toBe("light");
    classes.add("unrelated-class");
    observer.emit();
    expect(
      callbacks.every((callback) => callback.mock.calls.length === 0),
    ).toBe(true);
    classes.add("dark");
    observer.emit();
    expect(getColorScheme()).toBe("dark");
    expect(
      callbacks.every((callback) => callback.mock.calls.length === 1),
    ).toBe(true);
    classes.delete("dark");
    observer.emit();
    expect(getColorScheme()).toBe("light");
    expect(
      callbacks.every((callback) => callback.mock.calls.length === 2),
    ).toBe(true);
  });

  it("releases observation at the last unsubscribe and ignores late callbacks", () => {
    const callback = vi.fn();
    const first = subscribeColorScheme(callback);
    const second = subscribeColorScheme(callback);
    cleanup.push(first, second);
    const observer = TestMutationObserver.instances[0];
    first();
    first();
    expect(observer.disconnect).not.toHaveBeenCalled();
    second();
    expect(observer.disconnect).toHaveBeenCalledTimes(1);
    const nextCallback = vi.fn();
    cleanup.push(subscribeColorScheme(nextCallback));
    classes.add("dark");
    observer.emit();
    expect(nextCallback).not.toHaveBeenCalled();
    TestMutationObserver.instances[1].emit();
    expect(nextCallback).toHaveBeenCalledTimes(1);
    expect(callback).not.toHaveBeenCalled();
  });

  it("supplies a stable light snapshot without a browser document", () => {
    vi.stubGlobal("document", undefined);
    expect(getColorScheme()).toBe("light");
    cleanup.push(subscribeColorScheme(vi.fn()));
    expect(TestMutationObserver.instances).toHaveLength(0);
  });
});
