// Shared low-level helpers for pointer-driven gestures (drag, resize). Kept
// here so the docking library has no dependency back on control-panel code.

export { motionExceedsThreshold } from "../dragUtils";

/** Coordinates every pointer gesture owned by one DockManager. Starting a new
 * gesture cancels the previous one before taking ownership. The unregister
 * callback is token-scoped, so a stale gesture ending late cannot clear a
 * newer gesture. */
export interface GestureCoordinator {
  cancel(): void;
  register(cleanup: () => void): () => void;
}

export function createGestureCoordinator(): GestureCoordinator {
  let active: { cleanup: () => void } | null = null;

  const cancel = () => {
    const current = active;
    if (current === null) return;
    // Clear first: cleanup is allowed to synchronously start another gesture.
    active = null;
    current.cleanup();
  };

  return {
    cancel,
    register(cleanup) {
      cancel();
      const token = { cleanup };
      active = token;
      return () => {
        if (active === token) active = null;
      };
    },
  };
}

/** Bind a pointer gesture's move/end/cancel listeners on `window` and return a
 * detach function. Gestures capture the pointer on an element but listen on
 * `window` so the gesture survives the cursor leaving that element; this shares
 * the move + (up/cancel -> end) wiring.
 *
 * When `pointerId` is given, events from any OTHER pointer are ignored -- so on
 * a multi-touch surface a second finger can't drive or end the first finger's
 * gesture (a second finger's `pointerup` must not commit finger A's drop). This
 * mirrors the scene-pointer subsystem (pointer/gestures.ts). The end callback
 * receives the triggering event so callers can release the right pointer, plus
 * a first-class `cancelled` flag: true for anything that is NOT a real release
 * (pointercancel from a browser-stolen touch, or Escape) -- consumers abort
 * their commit on it (a drag drops nothing, a reorder snaps back) instead of
 * sniffing event types. */
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
  return () => {
    window.removeEventListener("pointermove", handleMove);
    window.removeEventListener("pointerup", handleEnd);
    window.removeEventListener("pointercancel", handleEnd);
    window.removeEventListener("keydown", handleKey);
  };
}

/** Suppress page-wide text selection for the duration of a gesture; returns a
 * restore function. Called synchronously inside pointerdown -- before the
 * browser's mousedown default can anchor a selection -- so dragging a tab,
 * grip, or divider across text content can't start highlighting it. */
function bodyStyleLease(
  property: "userSelect" | "cursor",
  value: string,
): () => () => void {
  let leases = 0;
  let previous = "";
  return () => {
    if (leases === 0) previous = document.body.style[property];
    leases += 1;
    document.body.style[property] = value;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      leases -= 1;
      if (leases === 0) document.body.style[property] = previous;
    };
  };
}

const leaseTextSelectionSuppression = bodyStyleLease("userSelect", "none");
const leaseGrabbingCursor = bodyStyleLease("cursor", "grabbing");

export function suppressTextSelection(): () => void {
  return leaseTextSelectionSuppression();
}

/** Show the "grabbing" cursor page-wide while a MOVE drag is in flight (the
 * handles show "grab" at rest; without this the cursor never closes). Returns
 * a restore function. Resize gestures keep their own ew/ns-resize cursors. */
export function grabbingCursor(): () => void {
  return leaseGrabbingCursor();
}

/** Run a rAF-throttled drag gesture: capture the pointer on `grip`, record the
 * latest pointer state via `update(e)` on every move, and apply it via
 * `flush()` at most once per animation frame (plus one final flush on release
 * if a move is still pending). `onEnd` runs exactly once, on release OR
 * cancellation, before the final flush -- the place to clear shared flags. It
 * receives `cancelled: true` when the gesture did NOT end with a real release
 * (Escape, browser-stolen touch, unmount), so callers can revert what their
 * per-frame flushes applied; no flush runs after a cancel.
 *
 * Returns a cancel function for unmount cleanup: it detaches the window
 * listeners, drops any pending frame WITHOUT flushing, and runs `onEnd`.
 * Idempotent, so calling it after a normal release is a no-op.
 *
 * This wraps the pattern shared by every resize/divider gesture (rAF
 * throttling, pointer capture, multitouch filtering, unmount safety) so the
 * call sites only provide the geometry math. */
export function dragGesture(opts: {
  grip: Element;
  pointerId: number;
  update: (event: PointerEvent) => void;
  flush: () => void;
  /** Manager-wide ownership. A new gesture cancels the current owner before
   * this one captures the pointer or acquires global style leases. */
  coordinator?: GestureCoordinator;
  /** Runs after this gesture owns the coordinator. */
  onStart?: () => void;
  onEnd?: (cancelled: boolean) => void;
}): () => void {
  const { grip, pointerId, update, flush, coordinator, onStart, onEnd } = opts;
  coordinator?.cancel();
  tryCapture(grip, pointerId);
  const restoreSelect = suppressTextSelection();
  let raf: number | null = null;
  let done = false;
  let unregister = () => {};
  const frame = () => {
    raf = null;
    flush();
  };
  const cancel = (cancelled = true) => {
    if (done) return;
    done = true;
    detach();
    if (raf !== null) cancelAnimationFrame(raf);
    unregister();
    tryRelease(grip, pointerId);
    restoreSelect();
    onEnd?.(cancelled);
  };
  const detach = bindPointerGesture(
    (e) => {
      update(e);
      if (raf === null) raf = requestAnimationFrame(frame);
    },
    (_endEvent, cancelled) => {
      const pending = raf !== null;
      cancel(cancelled);
      if (pending && !cancelled) flush();
    },
    pointerId, // ignore other pointers so a second finger cannot drive/end this.
  );
  unregister = coordinator?.register(() => cancel(true)) ?? unregister;
  onStart?.();
  return () => cancel(true);
}

/** Try to capture the pointer on an element; swallow the error if the pointer
 * is already gone. */
export function tryCapture(el: Element, pointerId: number): void {
  try {
    el.setPointerCapture(pointerId);
  } catch {
    // Pointer may already be released; ignore.
  }
}

/** Release a captured pointer, ignoring "already released" errors. */
export function tryRelease(el: Element, pointerId: number): void {
  try {
    el.releasePointerCapture(pointerId);
  } catch {
    // Already released; ignore.
  }
}
