import { expect, test, vi } from "vitest";

import { observeMarkdownImageViewport } from "./markdownImageViewport";

test("Markdown images follow proximity to their nearest reading frame", () => {
  const readingFrame = {} as Element;
  const node = {
    closest: vi.fn(() => readingFrame),
  } as unknown as Element;
  const observe = vi.fn();
  const disconnect = vi.fn();
  let report!: (
    entries: readonly Pick<IntersectionObserverEntry, "isIntersecting">[],
  ) => void;
  const createObserver = vi.fn((callback, options) => {
    report = callback;
    expect(options).toEqual({
      root: readingFrame,
      rootMargin: "800px 0px",
    });
    return { disconnect, observe };
  });
  const onNearChange = vi.fn();

  const stop = observeMarkdownImageViewport(node, onNearChange, createObserver);
  expect(node.closest).toHaveBeenCalledWith(
    '[data-slot="file-preview-reading-frame"]',
  );
  expect(observe).toHaveBeenCalledWith(node);

  report([{ isIntersecting: true }]);
  report([{ isIntersecting: false }]);
  expect(onNearChange.mock.calls).toEqual([[true], [false]]);

  stop();
  expect(disconnect).toHaveBeenCalledOnce();
});

test("Markdown images fall back to the browser viewport", () => {
  let observedOptions: IntersectionObserverInit | undefined;
  const node = {
    closest: () => null,
  } as unknown as Element;
  const createObserver = vi.fn(
    (
      callback: (
        entries: readonly Pick<IntersectionObserverEntry, "isIntersecting">[],
      ) => void,
      options: IntersectionObserverInit,
    ) => {
      void callback;
      observedOptions = options;
      return { disconnect: vi.fn(), observe: vi.fn() };
    },
  );

  observeMarkdownImageViewport(node, vi.fn(), createObserver);

  expect(observedOptions).toMatchObject({ root: null });
});
