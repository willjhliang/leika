export type ElementSize = { width: number; height: number };
type SizeListener = (size: ElementSize) => void;
type ObservedElement = { listeners: Set<SizeListener>; size: ElementSize };

const observed = new Map<HTMLElement, ObservedElement>();
let observer: ResizeObserver | null = null;

function measure(element: HTMLElement): ElementSize {
  const { width, height } = element.getBoundingClientRect();
  return { width, height };
}

/** Share resize delivery across plot hosts. Their horizontal border boxes have
 * already been measured by the browser, so reading their DOM rectangles again
 * would add a synchronous layout read for every plot on every resize frame. */
export function observeElementSize(
  element: HTMLElement,
  onSize: SizeListener,
): () => void {
  if (typeof ResizeObserver === "undefined") {
    onSize(measure(element));
    return () => undefined;
  }
  if (observer === null) {
    const instance = new ResizeObserver((entries) => {
      // Ignore a delivery queued by an observer whose last owner unmounted.
      if (observer !== instance) return;
      for (const entry of entries) {
        const target = entry.target as HTMLElement;
        const record = observed.get(target);
        if (record === undefined) continue;
        const box = entry.borderBoxSize?.[0];
        const size =
          box === undefined || entry.borderBoxSize.length !== 1
            ? measure(target)
            : { width: box.inlineSize, height: box.blockSize };
        if (
          size.width === record.size.width &&
          size.height === record.size.height
        )
          continue;
        record.size = size;
        for (const listener of record.listeners) listener(size);
      }
    });
    observer = instance;
  }

  let record = observed.get(element);
  if (record === undefined) {
    record = { listeners: new Set(), size: measure(element) };
    observed.set(element, record);
    observer.observe(element, { box: "border-box" });
  }
  const listener: SizeListener = (size) => onSize(size);
  record.listeners.add(listener);
  onSize(record.size);

  let subscribed = true;
  return () => {
    if (!subscribed) return;
    subscribed = false;
    record.listeners.delete(listener);
    if (record.listeners.size > 0) return;
    observed.delete(element);
    observer?.unobserve(element);
    if (observed.size === 0) {
      observer?.disconnect();
      observer = null;
    }
  };
}
