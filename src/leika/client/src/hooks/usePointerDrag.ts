import * as React from "react";

/** True from pointerdown until the pointer is released or cancelled anywhere
 * on the page — a drag's release usually lands outside the control. */
export function usePointerDrag(): [dragging: boolean, start: () => void] {
  const [dragging, setDragging] = React.useState(false);
  React.useEffect(() => {
    if (!dragging) return;
    const stop = () => setDragging(false);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, [dragging]);
  const start = React.useCallback(() => setDragging(true), []);
  return [dragging, start];
}
