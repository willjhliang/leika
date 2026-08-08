import { GripVerticalIcon, PlusIcon, XIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { prefersReducedMotion } from "../utils/motion";
import { EntryRow } from "./entryStackStyles";

/** How long a row takes to travel, stepping aside or landing. */
const SLIDE_MS = 150;

/** An entry's controls, out of the way until the row is being worked on: the
 * pointer is over it, or the keyboard is on a control and showing it.
 * `:focus-visible` rather than `:focus` -- the difference between the keys
 * working a row and a drag having left them on it. Faded rather than
 * unmounted, which would take the buttons out of the tab order and out of
 * reach of the `focus()` that hands a reorder on. */
const CONTROLS = cn(
  "pointer-events-none opacity-0",
  "group-hover/entry:pointer-events-auto group-hover/entry:opacity-100",
  "has-[:focus-visible]:pointer-events-auto has-[:focus-visible]:opacity-100",
);

/** One control: an icon filling its half of the end of the box, so the pair
 * tile it and the pointer never falls through between them. Focus darkens the
 * glyph, as hover does -- nothing in this panel rings itself with an outline. */
const CONTROL = cn(
  "flex h-full w-4 shrink-0 items-center justify-center rounded-sm",
  "text-muted-foreground hover:text-foreground",
  "outline-none focus-visible:text-foreground",
  "disabled:pointer-events-none disabled:opacity-50",
);

/** An entry held by the pointer. Rows are uniform and the list does not move
 * under a drag, so the geometry is read once, when the grip goes down. */
type Drag = {
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

/** How far the entry is drawn from where its row rests, and the place it
 * would take if let go now. Both follow from one number, clamped to the ends
 * of the list, so the two can never disagree. */
function carriedTo(drag: Drag, count: number) {
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

/** Where the rows sit, read off the document. */
function geometryOf(rows: HTMLElement[]) {
  const first = rows[0].getBoundingClientRect();
  const next = rows[1]?.getBoundingClientRect();
  return {
    origin: first.top + first.height / 2,
    stride: next === undefined ? first.height : next.top - first.top,
  };
}

/** Move one entry to another place, as a new array. */
function moved<T>(entries: T[], from: number, to: number): T[] {
  const next = [...entries];
  next.splice(to, 0, ...next.splice(from, 1));
  return next;
}

/** An id per entry, kept with the entry as the stack shuffles them.
 *
 * The entries themselves cannot say which is which: they are the caller's, and
 * two of them may be equal -- a list holding "Write" twice is a list holding
 * two different entries that read the same. So the stack numbers them, and
 * every move it makes to the entries it makes to the numbers in the same
 * breath.
 *
 * What it cannot do is follow a change it did not make. Entries arriving from
 * the server -- assigned in Python, or edited by somebody else's browser --
 * come with no account of where each one came from, so a list that has changed
 * length is renumbered from scratch. Guessing would be worse than admitting
 * it: the point of an id is that it is only ever handed out when this stack
 * knows the answer.
 */
function useEntryIds(count: number) {
  const ids = React.useRef<number[]>([]);
  const minted = React.useRef(0);
  if (ids.current.length !== count) {
    ids.current = Array.from(
      { length: count },
      (_, place) => ids.current[place] ?? minted.current++,
    );
  }
  const follow = React.useCallback((move: (ids: number[]) => number[]) => {
    ids.current = move(ids.current);
  }, []);
  const mint = React.useCallback(() => minted.current++, []);
  return {
    ids: ids.current,
    /** Do to the ids what is about to be done to the entries. */
    follow,
    mint,
  };
}

/** A stack of entries the viewer can add to, throw away from, and reorder.
 *
 * What an entry IS belongs to the caller: the stack holds an array of them,
 * draws each through `children`, and reports the array it now is. Everything
 * it does itself moves whole entries about, so whatever else a row carries --
 * a ticked box, say -- travels with the words it belongs to.
 *
 * A drag changes only where rows are DRAWN. The array is left as it is until
 * the entry lands, so the reorder is reported once, for the move the viewer
 * meant, rather than at every row the entry crossed on the way.
 */
export function EntryStack<T>({
  items,
  commit,
  blank,
  disabled,
  frozen,
  children,
}: {
  items: T[];
  commit: (next: T[]) => void;
  /** A new entry, made when the viewer presses Add. */
  blank: () => T;
  disabled: boolean;
  /** Whether the length and the order are fixed. Frozen, the grips, the
   * removes, and the add are not drawn -- a control that cannot do anything is
   * worse than no control. */
  frozen: boolean;
  children: (item: T, row: EntryRow) => React.ReactNode;
}) {
  const { ids, follow, mint } = useEntryIds(items.length);
  /** Reorder, remove, add: the entries and their ids, always together. */
  const reorder = React.useCallback(
    (from: number, to: number) => {
      follow((order) => moved(order, from, to));
      commit(moved(items, from, to));
    },
    [commit, follow, items],
  );
  const discard = (place: number) => {
    follow((order) => order.filter((_, other) => other !== place));
    commit(items.filter((_, other) => other !== place));
  };
  const append = () => {
    follow((order) => [...order, mint()]);
    commit([...items, blank()]);
  };

  const rowsRef = React.useRef<HTMLDivElement>(null);
  const [drag, setDrag] = React.useState<Drag | null>(null);
  // The row still on its way to where its entry now belongs. Cleared by the
  // travel itself, and only if it is still the travel in the air -- a second
  // move can start before the first has landed.
  const [flying, setFlying] = React.useState<{
    place: number;
    travel: Animation;
  } | null>(null);

  const rows = React.useCallback(
    () => [...(rowsRef.current?.children ?? [])] as HTMLElement[],
    [],
  );

  /** Hand the keyboard to the grip of the row an entry has moved into (rows
   * are keyed by place, so a reorder rewrites their contents rather than
   * moving them). `ringed` decides, through `:focus-visible`, whether the row
   * keeps its controls out: the keys hand the grip on ringed because they will
   * go on working it; a drag hands it on bare because the pointer is done. */
  const followEntry = React.useCallback(
    (place: number, ringed: boolean) => {
      const row = rows()[place];
      row?.querySelector<HTMLElement>("[data-leika-list-grip]")?.focus({
        focusVisible: ringed,
      });
    },
    [rows],
  );

  /** Slide a row in from where its contents were drawn a moment ago -- the
   * move itself is already done. */
  const slideIn = React.useCallback(
    (place: number, from: number) =>
      from === 0 || prefersReducedMotion()
        ? undefined
        : rows()[place]?.animate(
            [{ transform: `translateY(${from}px)` }, { transform: "none" }],
            { duration: SLIDE_MS, easing: "ease" },
          ),
    [rows],
  );

  /** Send an entry to the row it now lives in: the keyboard follows it there,
   * and the row stays aloft until it arrives -- otherwise it would finish its
   * travel under the entries it is still crossing, wearing their lines. */
  const land = React.useCallback(
    (place: number, from: number, ringed: boolean) => {
      followEntry(place, ringed);
      const travel = slideIn(place, from);
      if (travel === undefined) return;
      setFlying({ place, travel });
      const landed = () =>
        setFlying((current) => (current?.travel === travel ? null : current));
      travel.finished.then(landed, landed);
    },
    [followEntry, slideIn],
  );

  /** Take hold of an entry. The list is not touched until the drop. */
  const takeHold = (
    event: React.PointerEvent<HTMLButtonElement>,
    entry: number,
  ) => {
    if (event.button !== 0) return;
    // The default is the text selection a drag would paint -- and with it the
    // focus a press gives the grip, which the arrow keys need afterwards.
    event.preventDefault();
    event.currentTarget.focus({ focusVisible: false });
    const { origin, stride } = geometryOf(rows());
    setDrag({
      entry,
      origin,
      stride,
      pointerY: event.clientY,
      grab: event.clientY - (origin + entry * stride),
    });
  };

  /** The same move from the keyboard, which cannot be asked to drag. */
  const nudge = (event: React.KeyboardEvent, place: number) => {
    const step =
      event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
    const to = place + step;
    if (step === 0 || to < 0 || to >= items.length) return;
    event.preventDefault();
    const { stride } = geometryOf(rows());
    reorder(place, to);
    // The two entries change places, so each is seen to come from the other's.
    slideIn(place, step * stride);
    land(to, -step * stride, true);
  };

  // The closed hand belongs to the whole document while an entry is in it: a
  // cursor that turned into a text beam mid-drag would read as having let go.
  const dragging = drag !== null;
  React.useEffect(() => {
    if (!dragging) return;
    const root = document.documentElement;
    root.classList.add("leika-carrying");
    return () => root.classList.remove("leika-carrying");
  }, [dragging]);

  // A drag is the window's to follow: it carries on off the grip and out of
  // the panel. Listened for afresh on each move, since letting go has to read
  // the drag and the list as they stand at that moment.
  React.useEffect(() => {
    if (drag === null) return;
    const move = (event: PointerEvent) =>
      setDrag((held) => held && { ...held, pointerY: event.clientY });
    const release = (landed: boolean) => {
      setDrag(null);
      const { landing, lift } = carriedTo(drag, items.length);
      // Cancelled is not dropped: the gesture was taken away rather than
      // finished, so the entry goes back where it came from.
      const place = landed ? landing : drag.entry;
      if (place !== drag.entry) reorder(drag.entry, place);
      land(place, lift - (place - drag.entry) * drag.stride, false);
    };
    const drop = () => release(true);
    const abandon = () => release(false);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", drop);
    window.addEventListener("pointercancel", abandon);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", drop);
      window.removeEventListener("pointercancel", abandon);
    };
  }, [drag, items, land, reorder]);

  const carry = drag === null ? null : carriedTo(drag, items.length);

  /** The place a row is DRAWN in, which is not the place it holds while an
   * entry is being carried over it. */
  const slotOf = (place: number) => {
    if (carry === null) return place;
    const { entry, landing } = carry;
    if (place === entry) return landing;
    if (place > entry && place <= landing) return place - 1;
    if (place < entry && place >= landing) return place + 1;
    return place;
  };

  /** How far from home a row is drawn: the entry in hand follows the pointer,
   * and the rows between it and its landing place step aside by one. */
  const offsetOf = (place: number) =>
    carry === null
      ? 0
      : place === carry.entry
        ? carry.lift
        : (slotOf(place) - place) * carry.stride;

  return (
    <div className="flex w-full min-w-0 flex-col gap-1">
      {/* No gap: the entries hug the way a merged row of buttons does, ends
          rounded, insides square. Deaf to the pointer while an entry is in
          hand -- the rows are moving out from under the cursor, so hover says
          nothing about which row is being worked on. */}
      <div
        ref={rowsRef}
        className={cn(
          "flex w-full min-w-0 flex-col",
          dragging && "pointer-events-none",
        )}
      >
        {items.map((item, place) => {
          const inHand = carry !== null && place === carry.entry;
          // Off the list, whether the pointer has it or it is still on its
          // way to where the pointer left it.
          const aloft = inHand || flying?.place === place;
          const slot = slotOf(place);
          const offset = offsetOf(place);
          return (
            // Keyed by place, since two entries may read the same. A reorder
            // rewrites the rows in place, which is what `followEntry` is for.
            <div
              key={place}
              className={cn(
                "group/entry relative min-w-0",
                // The shared edge, taken out of the row below it.
                place > 0 && "-mt-px",
                aloft && "z-30",
              )}
              style={{
                transform: offset === 0 ? undefined : `translateY(${offset}px)`,
                // A row eases out of the way; the entry in hand answers to the
                // pointer, which needs no easing. Dropped, the transition goes
                // in the same breath as the offsets it would unwind on screen.
                transition:
                  inHand || carry === null || prefersReducedMotion()
                    ? undefined
                    : `transform ${SLIDE_MS}ms ease`,
              }}
              data-leika-list-item
              data-leika-list-carried={inHand || undefined}
            >
              {children(item, {
                place,
                id: ids[place],
                slot,
                aloft,
                count: items.length,
              })}
              {/* Inside the box, at its end: they are what to do with this
                  entry, not further controls in the column. `z-20` beats the
                  focused box's own lift, which would otherwise sit on top of
                  them and take their clicks. */}
              {!frozen && (
                <span
                  className={cn(
                    "absolute inset-y-0 right-1.5 z-20 flex items-center",
                    // In hand, out for as long as the drag lasts.
                    inHand ? "opacity-100" : CONTROLS,
                  )}
                  data-leika-list-controls
                >
                  <button
                    type="button"
                    className={cn(CONTROL, "cursor-grab")}
                    // "Reorder", not "Move": "Remove entry 1" CONTAINS "Move
                    // entry 1", and the two names would match by substring.
                    aria-label={`Reorder entry ${place + 1}`}
                    title="Drag to reorder"
                    disabled={disabled}
                    onPointerDown={(event) => takeHold(event, place)}
                    onKeyDown={(event) => nudge(event, place)}
                    data-leika-list-grip
                  >
                    <GripVerticalIcon className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    className={CONTROL}
                    aria-label={`Remove entry ${place + 1}`}
                    title="Remove"
                    disabled={disabled}
                    onClick={() => discard(place)}
                    data-leika-list-remove
                  >
                    <XIcon className="size-3.5" />
                  </button>
                </span>
              )}
            </div>
          );
        })}
      </div>
      {!frozen && (
        // A new entry starts empty, which is where the viewer was going to
        // type anyway.
        <Button
          type="button"
          variant="outline"
          className="w-full"
          disabled={disabled}
          onClick={append}
          data-leika-button
          data-leika-button-color="default"
          data-leika-list-add
        >
          <PlusIcon data-icon="inline-start" />
          Add
        </Button>
      )}
    </div>
  );
}
