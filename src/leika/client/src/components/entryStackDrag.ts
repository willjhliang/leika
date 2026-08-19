import { bindPointerGesture, tryCapture, tryRelease } from "../pointerGesture";

/** An entry held by the pointer. Rows are uniform and the list does not move
 * under a drag, so the geometry is read once, when the grip goes down. */
export type EntryStackDrag = {
  /** The entry in hand, by its place in the list. */
  entry: number;
  /** The middle of the first row, and the distance from one row to the next
   * (not the row height: hugging rows overlap by the border they share). */
  origin: number;
  stride: number;
  /** Where the pointer is, and where in the row it took hold -- so the entry
   * travels with the cursor instead of jumping its middle up to meet it. */
  pointerY: number;
  grab: number;
};

/** How the held row is drawn and where it would land. */
export function entryStackDragPosition(drag: EntryStackDrag, count: number) {
  if (count <= 0) {
    return { entry: drag.entry, stride: drag.stride, landing: 0, lift: 0 };
  }
  const restingAt = (place: number) => drag.origin + place * drag.stride;
  const middle = Math.min(
    Math.max(drag.pointerY - drag.grab, restingAt(0)),
    restingAt(count - 1),
  );
  return {
    entry: drag.entry,
    stride: drag.stride,
    landing: Math.round((middle - drag.origin) / drag.stride),
    lift: middle - restingAt(drag.entry),
  };
}

/** Move one entry to another place, as a new array. */
export function moveEntryStackItem<T>(
  entries: readonly T[],
  from: number,
  to: number,
): T[] {
  const next = [...entries];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/** Where a released row belongs and how far it must travel to settle there. */
export function settleEntryStackDrag(
  drag: EntryStackDrag,
  count: number,
  dropped: boolean,
) {
  const { landing, lift } = entryStackDragPosition(drag, count);
  // Cancellation returns the entry to its own row; a real release commits the
  // landing that was drawn under the pointer.
  const place = dropped ? landing : drag.entry;
  return {
    place,
    offset: lift - (place - drag.entry) * drag.stride,
  };
}

/** Props whose change makes an index-based drag stale. */
export type EntryStackDragGeneration = {
  items: readonly unknown[];
  disabled: boolean;
  frozen: boolean;
};

type StartOptions = {
  grip: Element;
  pointerId: number;
  drag: EntryStackDrag;
  finish: (drag: EntryStackDrag, dropped: boolean) => void;
};

export interface EntryStackDragController {
  /** Reconcile committed props, cancelling an incompatible drag. */
  sync(generation: EntryStackDragGeneration): void;
  /** Start at pointerdown. False means another pointer owns the stack. */
  start(options: StartOptions): boolean;
  /** Detach during unmount without scheduling React work. */
  dispose(): void;
}

type Session = Omit<StartOptions, "drag"> & {
  generation: EntryStackDragGeneration;
  held: EntryStackDrag;
  detach: () => void;
};

type CloseReason = "drop" | "cancel" | "invalidate" | "dispose";

function sameGeneration(
  left: EntryStackDragGeneration,
  right: EntryStackDragGeneration,
): boolean {
  return (
    left.items === right.items &&
    left.disabled === right.disabled &&
    left.frozen === right.frozen
  );
}

/** One scoped pointer session for an EntryStack.
 *
 * It is installed synchronously in pointerdown, owns exactly one pointer, and
 * keeps its latest coordinate outside React so pointerup cannot outrun a
 * render. No listeners exist while the stack is idle.
 */
export function createEntryStackDragController(
  initialGeneration: EntryStackDragGeneration,
  draw: (drag: EntryStackDrag | null) => void,
): EntryStackDragController {
  let generation = initialGeneration;
  let active: Session | null = null;

  const close = (session: Session, reason: CloseReason) => {
    if (active !== session) return;
    active = null;
    session.detach();
    tryRelease(session.grip, session.pointerId);
    if (reason !== "dispose") draw(null);
    if (
      (reason === "drop" || reason === "cancel") &&
      sameGeneration(generation, session.generation)
    ) {
      session.finish(session.held, reason === "drop");
    }
  };

  return {
    sync(next) {
      const changed = !sameGeneration(generation, next);
      generation = next;
      if (changed && active !== null) close(active, "invalidate");
    },
    start(options) {
      if (
        active !== null ||
        generation.disabled ||
        generation.frozen ||
        options.drag.entry < 0 ||
        options.drag.entry >= generation.items.length
      ) {
        return false;
      }
      const session: Session = {
        ...options,
        generation,
        held: options.drag,
        detach: () => {},
      };
      active = session;
      tryCapture(session.grip, session.pointerId);
      try {
        session.detach = bindPointerGesture(
          (event) => {
            if (active !== session) return;
            session.held = { ...session.held, pointerY: event.clientY };
            draw(session.held);
          },
          (_event, cancelled) => close(session, cancelled ? "cancel" : "drop"),
          session.pointerId,
        );
        draw(session.held);
      } catch (error) {
        close(session, "dispose");
        throw error;
      }
      return true;
    },
    dispose() {
      if (active !== null) close(active, "dispose");
    },
  };
}
