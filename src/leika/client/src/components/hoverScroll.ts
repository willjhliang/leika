import { prefersReducedMotion } from "@/utils/motion";

/** Shared timing for hover-revealed text, whether it is drawn or editable. */
export const HOVER_SCROLL_PIXELS_PER_SECOND = 40;
export const HOVER_SCROLL_START_DELAY_MS = 500;
export const HOVER_SCROLL_PAUSE_MS = 500;

type HoverScrollCycleOptions = {
  /** The distance between the beginning and end at the moment hover starts. */
  maximum: number;
  /** Draw either a transform or a native text viewport at this distance. */
  setPosition: (position: number) => void;
  /** Mark the surface as actively revealing clipped text. */
  onStart?: () => void;
  /** Remove that mark when the surface no longer has clipped text. */
  onStop?: () => void;
  /** Inputs stop giving hover ownership to the cycle when they gain focus. */
  shouldStop?: () => boolean;
};

/** A live hover owner. Geometry is measured by its surface, never per frame. */
export interface HoverScrollCycle {
  /** Reconcile a newly measured distance without abandoning pointer ownership. */
  reconcileMaximum(maximum: number): void;
  /** Permanently release pointer ownership and any scheduled animation. */
  stop(): void;
}

type InputFocusViewportResetOptions = {
  /** Restore the prefix that the outgoing hover cycle had displaced. */
  reset: () => void;
  /** Keep the handoff scoped to the input which received focus. */
  shouldReset: () => boolean;
};

/** A pending handoff from a hover-owned viewport to native input focus. */
export interface InputFocusViewportReset {
  /** Abandon the reset when another interaction takes ownership. */
  cancel(): void;
}

/**
 * Restore an input viewport after native focus has finished revealing its caret.
 *
 * Focus is dispatched before Firefox and WebKit finish that native work, and
 * WebKit may perform a second adjustment during the following rendering
 * update. Resetting at both frame boundaries keeps the prefix stable without
 * touching later pointer-driven focus, selection, or manual scrolling.
 */
export function scheduleInputFocusViewportReset({
  reset,
  shouldReset,
}: InputFocusViewportResetOptions): InputFocusViewportReset {
  let frame: number | null = null;
  let framesRemaining = 2;

  const cancel = () => {
    if (frame === null) return;
    cancelAnimationFrame(frame);
    frame = null;
  };

  const finishFrame = () => {
    frame = null;
    if (!shouldReset()) return;
    reset();
    framesRemaining -= 1;
    if (framesRemaining > 0) {
      frame = requestAnimationFrame(finishFrame);
    }
  };

  frame = requestAnimationFrame(finishFrame);
  return { cancel };
}

function boundedMaximum(maximum: number): number {
  return Number.isFinite(maximum) ? Math.max(0, maximum) : 0;
}

/**
 * Run the one hover-scroll sequence used by both drawn text and native inputs:
 *
 * initial rest -> forward travel -> end rest -> reset -> start rest -> repeat.
 *
 * The surface explicitly reconciles resize and content measurements. Keeping
 * that cached endpoint here avoids forcing layout from every animation frame.
 * Fixed millisecond rests also give a barely clipped option and a long list
 * entry the same amount of reading time at either end.
 */
export function startHoverScrollCycle({
  maximum: initialMaximum,
  setPosition,
  onStart,
  onStop,
  shouldStop,
}: HoverScrollCycleOptions): HoverScrollCycle {
  type Phase = "initial-rest" | "moving" | "end-rest" | "start-rest";

  let owned = true;
  let revealing = false;
  let reducedMotion = false;
  let frame: number | null = null;
  let maximum = boundedMaximum(initialMaximum);
  let phase: Phase = "initial-rest";
  let position = 0;
  let previous = 0;
  let heldUntil = 0;

  const cancelFrame = () => {
    if (frame === null) return;
    cancelAnimationFrame(frame);
    frame = null;
  };

  const stopRevealing = () => {
    if (!revealing) return;
    cancelFrame();
    revealing = false;
    onStop?.();
  };

  const schedule = () => {
    if (!owned || !revealing || reducedMotion || frame !== null) return;
    frame = requestAnimationFrame(tick);
  };

  const startRevealing = () => {
    if (!owned || revealing || maximum <= 1) return;
    revealing = true;
    reducedMotion = prefersReducedMotion();
    position = 0;
    setPosition(position);
    onStart?.();
    if (reducedMotion) {
      position = maximum;
      setPosition(position);
      return;
    }
    phase = "initial-rest";
    previous = performance.now();
    heldUntil = previous + HOVER_SCROLL_START_DELAY_MS;
    schedule();
  };

  const reconcileMaximum = (nextMaximum: number) => {
    if (!owned) return;
    const previousMaximum = maximum;
    maximum = boundedMaximum(nextMaximum);

    if (maximum <= 1) {
      if (revealing) setPosition(0);
      stopRevealing();
      return;
    }
    if (!revealing) {
      startRevealing();
      return;
    }
    if (reducedMotion) {
      position = maximum;
      setPosition(position);
      return;
    }

    const now = performance.now();
    if (phase === "end-rest" && maximum > position) {
      // New text or a narrower box adds unread distance. Continue from the old
      // endpoint at the normal speed instead of snapping to the new one.
      phase = "moving";
      previous = now;
      schedule();
      return;
    }

    if (position > maximum) {
      position = maximum;
      setPosition(position);
    }
    if (
      phase === "moving" &&
      maximum < previousMaximum &&
      position >= maximum
    ) {
      phase = "end-rest";
      heldUntil = now + HOVER_SCROLL_PAUSE_MS;
    }
  };

  const stop = () => {
    if (!owned) return;
    owned = false;
    stopRevealing();
  };

  function tick(now: number) {
    frame = null;
    if (!owned || !revealing || reducedMotion) return;
    if (shouldStop?.()) {
      stop();
      return;
    }

    const elapsed = Math.min(Math.max(0, now - previous), 64);
    previous = now;
    if (phase === "initial-rest" || phase === "start-rest") {
      if (now >= heldUntil) {
        phase = "moving";
        previous = now;
      }
    } else if (phase === "end-rest") {
      if (now >= heldUntil) {
        position = 0;
        setPosition(position);
        phase = "start-rest";
        heldUntil = now + HOVER_SCROLL_PAUSE_MS;
      }
    } else {
      position += HOVER_SCROLL_PIXELS_PER_SECOND * (elapsed / 1000);
      if (position >= maximum) {
        position = maximum;
        phase = "end-rest";
        heldUntil = now + HOVER_SCROLL_PAUSE_MS;
      }
      setPosition(position);
    }
    schedule();
  }

  startRevealing();
  return { reconcileMaximum, stop };
}
