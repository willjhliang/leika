import * as React from "react";

import { observeElementSize } from "./elementSizeObserver";

/** Track an element's border-box size with a ResizeObserver.
 *
 * Returns a callback ref: attach it to the element to measure. The size only
 * changes identity when the measured dimensions change, so consumers can use
 * it directly as an effect dependency. */
export function useElementSize<T extends HTMLElement = HTMLDivElement>() {
  const [element, setElement] = React.useState<T | null>(null);
  const [size, setSize] = React.useState({ width: 0, height: 0 });
  const ref = React.useCallback((node: T | null) => setElement(node), []);

  React.useLayoutEffect(() => {
    if (element === null) return;
    return observeElementSize(element, (size) => {
      setSize((current) =>
        current.width === size.width && current.height === size.height
          ? current
          : size,
      );
    });
  }, [element]);

  return { ref, ...size };
}
