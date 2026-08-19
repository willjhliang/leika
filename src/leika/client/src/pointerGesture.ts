/** Bind one pointer gesture's move/end/cancel listeners on `window`.
 *
 * Events from other pointers are ignored. Escape is reported as cancellation,
 * and the returned detach function removes every listener exactly once when
 * the caller's scoped gesture ends or its owner unmounts.
 */
export function bindPointerGesture(
  onMove: (event: PointerEvent) => void,
  onEnd: (event: PointerEvent, cancelled: boolean) => void,
  pointerId?: number,
): () => void {
  const handleMove = (event: PointerEvent) => {
    if (pointerId !== undefined && event.pointerId !== pointerId) return;
    onMove(event);
  };
  const handleEnd = (event: PointerEvent) => {
    if (pointerId !== undefined && event.pointerId !== pointerId) return;
    onEnd(event, event.type === "pointercancel");
  };
  const handleKey = (event: KeyboardEvent) => {
    if (event.key !== "Escape") return;
    onEnd(
      new PointerEvent("pointercancel", { pointerId: pointerId ?? undefined }),
      true,
    );
  };
  window.addEventListener("pointermove", handleMove);
  window.addEventListener("pointerup", handleEnd);
  window.addEventListener("pointercancel", handleEnd);
  window.addEventListener("keydown", handleKey);
  let attached = true;
  return () => {
    if (!attached) return;
    attached = false;
    window.removeEventListener("pointermove", handleMove);
    window.removeEventListener("pointerup", handleEnd);
    window.removeEventListener("pointercancel", handleEnd);
    window.removeEventListener("keydown", handleKey);
  };
}

/** Capture a pointer if it is still active. */
export function tryCapture(element: Element, pointerId: number): void {
  try {
    element.setPointerCapture(pointerId);
  } catch {
    // The pointer may already have been released.
  }
}

/** Release a pointer if this element still owns it. */
export function tryRelease(element: Element, pointerId: number): void {
  try {
    element.releasePointerCapture(pointerId);
  } catch {
    // Capture may already have been released by the browser.
  }
}
