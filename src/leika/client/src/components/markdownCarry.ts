/** A fixed beat: quick enough for navigation, long enough to show direction. */
export const MARKDOWN_CARRY_DURATION_MS = 200;

/** Let late layout settle without retaining a document indefinitely. */
export const MARKDOWN_CARRY_SETTLEMENT_FRAMES = 12;

const USER_CANCEL_EVENTS = [
  "wheel",
  "touchstart",
  "pointerdown",
  "keydown",
] as const;

export interface MarkdownCarryPlatform {
  now: () => number;
  requestFrame: (callback: (now: number) => void) => number;
  cancelFrame: (handle: number) => void;
}

type CarryOwner = object;
type ActiveCarry = {
  owner: CarryOwner;
  cancel: () => void;
};

let activeCarry: ActiveCarry | null = null;

const browserPlatform: MarkdownCarryPlatform = {
  now: () => performance.now(),
  requestFrame: (callback) => requestAnimationFrame(callback),
  cancelFrame: (handle) => cancelAnimationFrame(handle),
};

/** Cancel either the global carry or only the exact renderer being unmounted. */
export function cancelMarkdownCarry(owner?: CarryOwner): void {
  const active = activeCarry;
  if (active === null || (owner !== undefined && active.owner !== owner))
    return;
  activeCarry = null;
  active.cancel();
}

/** Scroll one reading frame, replacing the previous document's animation. */
export function startMarkdownCarry(
  frame: HTMLElement,
  target: HTMLElement,
  owner: CarryOwner,
  platform: MarkdownCarryPlatform = browserPlatform,
): void {
  cancelMarkdownCarry();
  const from = frame.scrollTop;
  const started = platform.now();
  let frameRef: HTMLElement | null = frame;
  let targetRef: HTMLElement | null = target;
  let handle: number | null = null;
  let finished = false;
  let settling = false;
  let settlementFrames = 0;

  const liveDestination = (
    liveFrame: HTMLElement,
    liveTarget: HTMLElement,
  ): number => {
    const offset =
      liveTarget.getBoundingClientRect().top -
      liveFrame.getBoundingClientRect().top;
    const maximum = Math.max(
      0,
      liveFrame.scrollHeight - liveFrame.clientHeight,
    );
    return Math.max(0, Math.min(liveFrame.scrollTop + offset, maximum));
  };

  const cancelOnInteraction = () => {
    // A removed listener may already have been dispatched. It owns only this
    // generation, even when a later carry happens to have the same owner.
    if (activeCarry === active) active.cancel();
  };

  const release = (cancelPendingFrame: boolean) => {
    if (finished) return;
    finished = true;
    if (cancelPendingFrame && handle !== null) platform.cancelFrame(handle);
    handle = null;
    const liveFrame = frameRef;
    if (liveFrame !== null) {
      for (const event of USER_CANCEL_EVENTS)
        liveFrame.removeEventListener(event, cancelOnInteraction);
    }
    frameRef = null;
    targetRef = null;
    if (activeCarry === active) activeCarry = null;
  };

  const active: ActiveCarry = {
    owner,
    cancel: () => release(true),
  };
  const step = (now: number) => {
    // A callback already dispatched before cancellation cannot cancel or
    // reschedule the newer generation that superseded it.
    if (finished || activeCarry !== active) return;
    handle = null;
    const liveFrame = frameRef;
    const liveTarget = targetRef;
    if (
      liveFrame === null ||
      liveTarget === null ||
      !liveFrame.isConnected ||
      !liveTarget.isConnected
    ) {
      release(false);
      return;
    }

    const to = liveDestination(liveFrame, liveTarget);
    if (!settling) {
      const at = Math.min(1, (now - started) / MARKDOWN_CARRY_DURATION_MS);
      liveFrame.scrollTop = from + (to - from) * (1 - (1 - at) ** 3);
      if (at === 1) settling = true;
    } else {
      liveFrame.scrollTop = to;
      settlementFrames += 1;
      if (settlementFrames >= MARKDOWN_CARRY_SETTLEMENT_FRAMES) {
        release(false);
        return;
      }
    }

    handle = platform.requestFrame(step);
  };

  for (const event of USER_CANCEL_EVENTS) {
    if (event === "keydown") frame.addEventListener(event, cancelOnInteraction);
    else
      frame.addEventListener(event, cancelOnInteraction, {
        passive: true,
      });
  }
  activeCarry = active;
  handle = platform.requestFrame(step);
}

/** Test/diagnostic seam: completed and unmounted renders own no DOM closure. */
export function markdownCarryIsActive(owner?: CarryOwner): boolean {
  return (
    activeCarry !== null && (owner === undefined || activeCarry.owner === owner)
  );
}
