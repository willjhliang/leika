import { GripVerticalIcon, PlusIcon, XIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { prefersReducedMotion } from "../utils/motion";
import { GuiListMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

/** How long a row takes to travel, whether it is stepping aside for an entry
 * being carried past it or catching up with one that has just landed. */
const SLIDE_MS = 150;

/** An entry's controls, out of the way until its row is the one being worked
 * on: the pointer is over it, or the keyboard is on one of the controls and
 * showing it -- `:focus-visible` rather than `:focus`, which is the difference
 * between the keys working a row and a drag having left them on it.
 *
 * Faded rather than unmounted or `display: none`, either of which would take
 * the buttons out of the tab order, and out of reach of `focus()` -- which is
 * how a reorder hands the keyboard on to the row its entry moved into. */
const CONTROLS = cn(
  "pointer-events-none opacity-0",
  "group-hover/entry:pointer-events-auto group-hover/entry:opacity-100",
  "has-[:focus-visible]:pointer-events-auto has-[:focus-visible]:opacity-100",
);

/** One of those controls: an icon filling its half of the end of the box, so
 * the two of them tile it and a pointer crossing between them never falls
 * through to the text box behind. */
const CONTROL = cn(
  "flex h-full w-4 shrink-0 items-center justify-center rounded-sm",
  "text-muted-foreground hover:text-foreground",
  // The keys darken the control they are on, which is all the pointer does to
  // it, and light the row they are on by its own border -- see the entry
  // below. Nothing in this panel rings itself with an outline.
  "outline-none focus-visible:text-foreground",
  "disabled:pointer-events-none disabled:opacity-50",
);

/** An entry held by the pointer. Rows are uniform and the list does not move
 * under a drag -- only its contents do -- so the geometry is read once, when
 * the grip goes down, and the pointer is all that changes afterwards. */
type Drag = {
  /** The entry in hand, by its place in the list. */
  entry: number;
  /** The middle of the first row, and the distance from one row to the next.
   * Not the row height: hugging rows overlap by the border they share. */
  origin: number;
  stride: number;
  /** Where the pointer is, and where in the row it took hold -- so the entry
   * travels with the cursor instead of jumping its middle up to meet it. */
  pointerY: number;
  grab: number;
};

/** What a drag comes to: how far the entry is drawn from where its row rests,
 * and the place it would take if it were let go now. Both follow from one
 * number, so the two can never disagree about where the entry is. */
function carriedTo(drag: Drag, count: number) {
  const restingAt = (place: number) => drag.origin + place * drag.stride;
  // Bounded by the ends of the list: an entry sailing on past them would
  // promise a place to drop it that does not exist.
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
function moved(entries: string[], from: number, to: number): string[] {
  const next = [...entries];
  next.splice(to, 0, ...next.splice(from, 1));
  return next;
}

/** An editable list of text entries, stacked into one block.
 *
 * The entries are the value, and everything a viewer can do to them -- type in
 * one, add one, throw one away, move one -- reports the whole list as it now
 * reads. There is no separate "commit": a list is a value like any other row's.
 *
 * Frozen, the list is its entries and nothing else: the grips, the removes and
 * the add all go, since a control that cannot do anything is worse than no
 * control. The typing stays, which `disabled` is for.
 *
 * A drag changes only where rows are DRAWN. The list is left as it is until
 * the entry lands, so the reorder is reported once, for the move the viewer
 * meant, rather than at every row the entry crossed on the way.
 */
export default function ListInputComponent({
  uuid,
  value,
  props: { label, hint, disabled, frozen },
}: GuiListMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  const rowsRef = React.useRef<HTMLDivElement>(null);
  const [drag, setDrag] = React.useState<Drag | null>(null);
  // The row still on its way to where its entry now belongs, and the animation
  // carrying it: a moved entry is off the list until it arrives, exactly as it
  // is while the pointer has hold of it. Cleared by the travel itself rather
  // than by a clock, and only if it is still the travel in the air -- a second
  // move can start before the first has landed.
  const [flying, setFlying] = React.useState<{
    place: number;
    travel: Animation;
  } | null>(null);

  const commit = (next: string[]) => setValue(uuid, next);
  const rows = () => [...(rowsRef.current?.children ?? [])] as HTMLElement[];

  /** Hand the keyboard to the grip of the row an entry has moved into. Rows
   * are keyed by place, so a reorder rewrites their contents rather than
   * moving them, and the grip in use is left holding whichever entry stepped
   * aside.
   *
   * `ringed` decides both the ring and, through `:focus-visible`, whether the
   * row keeps its controls out once the pointer leaves. The keys hand the grip
   * on ringed, since they are working that row and will go on working it; a
   * drag hands it on bare, since the pointer has finished with it -- and a row
   * still lit next to a cursor that is somewhere else reads as stuck. */
  const followEntry = (place: number, ringed: boolean) => {
    const row = rows()[place];
    row?.querySelector<HTMLElement>("[data-leika-list-grip]")?.focus({
      focusVisible: ringed,
    });
  };

  /** Slide a row in from where its contents were drawn a moment ago. The move
   * itself is already done: this is the entry being seen to travel, so that a
   * reorder can be followed rather than flickering into place. */
  const slideIn = (place: number, from: number) =>
    from === 0 || prefersReducedMotion()
      ? undefined
      : rows()[place]?.animate(
          [{ transform: `translateY(${from}px)` }, { transform: "none" }],
          { duration: SLIDE_MS, easing: "ease" },
        );

  /** Send an entry to the row it now lives in: the keyboard follows it there,
   * and the row stays in the air until it arrives -- above the list, opaque,
   * and a box of its own. Let down at the moment of the move instead, it
   * finished its travel UNDER the entries it was still crossing, wearing
   * their lines and their letters for the sixth of a second it had left. */
  const land = (place: number, from: number, ringed: boolean) => {
    followEntry(place, ringed);
    const travel = slideIn(place, from);
    if (travel === undefined) return;
    setFlying({ place, travel });
    const landed = () =>
      setFlying((current) => (current?.travel === travel ? null : current));
    travel.finished.then(landed, landed);
  };

  /** Take hold of an entry. The list is not touched until the drop. */
  const takeHold = (
    event: React.PointerEvent<HTMLButtonElement>,
    entry: number,
  ) => {
    if (event.button !== 0) return;
    // The default here is the text selection a drag across the panel would
    // otherwise paint -- and with it the focus a press gives the grip, which
    // the arrow keys need once the drag is over.
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
    if (step === 0 || to < 0 || to >= value.length) return;
    event.preventDefault();
    const { stride } = geometryOf(rows());
    commit(moved(value, place, to));
    // The two entries change places, so each is seen to come from the other's
    // -- the one the keys are moving over the one stepping aside for it.
    slideIn(place, step * stride);
    land(to, -step * stride, true);
  };

  // The closed hand belongs to the whole document while an entry is in it: the
  // pointer leaves the grip as soon as the row starts travelling, and a cursor
  // that turned into a text beam on the way would read as having let go.
  const dragging = drag !== null;
  React.useEffect(() => {
    if (!dragging) return;
    const root = document.documentElement;
    root.classList.add("leika-carrying");
    return () => root.classList.remove("leika-carrying");
  }, [dragging]);

  // A drag is the window's to follow: it carries on off the grip, off the list
  // and out of the panel. Listened for afresh on each move, since letting go
  // has to read the drag and the list as they stand at that moment.
  React.useEffect(() => {
    if (drag === null) return;
    const move = (event: PointerEvent) =>
      setDrag((held) => held && { ...held, pointerY: event.clientY });
    const release = (landed: boolean) => {
      setDrag(null);
      const { landing, lift } = carriedTo(drag, value.length);
      // Cancelled is not dropped: the gesture was taken away rather than
      // finished, so the entry goes back where it came from.
      const place = landed ? landing : drag.entry;
      if (place !== drag.entry) commit(moved(value, drag.entry, place));
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
  }, [drag, value]);

  const carry = drag === null ? null : carriedTo(drag, value.length);

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

  const stack = (
    <div className="flex w-full min-w-0 flex-col gap-1">
      {/* No gap between the entries: they are one list, so they hug the way a
          merged row of buttons does -- ends rounded, insides square,
          neighbours sharing an edge rather than each drawing its own. The Add
          keeps its step below, being a control rather than an entry.

          Deaf to the pointer while an entry is in hand, since the rows are
          moving out from under the cursor: which one it happens to be over
          says nothing about which one is being worked on, and answering it lit
          up whichever row had slid beneath it. */}
      <div
        ref={rowsRef}
        className={cn(
          "flex w-full min-w-0 flex-col",
          dragging && "pointer-events-none",
        )}
      >
        {value.map((entry, place) => {
          const inHand = carry !== null && place === carry.entry;
          // Off the list, whether the pointer has it or it is still on its way
          // to where the pointer left it. Both are a box travelling over the
          // others, and both are drawn as one.
          const aloft = inHand || flying?.place === place;
          const slot = slotOf(place);
          const offset = offsetOf(place);
          return (
            // Keyed by place, since entries are strings and two of them may
            // read the same. A reorder rewrites the boxes in place, which is
            // what `followEntry` is for.
            <div
              key={place}
              className={cn(
                "group/entry relative min-w-0",
                // The shared edge, taken out of the row below it.
                place > 0 && "-mt-px",
                // Over the rows it is travelling past.
                aloft && "z-30",
              )}
              style={{
                transform: offset === 0 ? undefined : `translateY(${offset}px)`,
                // A row eases out of the way of the entry passing it; the
                // entry itself answers to the pointer, which needs no easing.
                // Dropped, the transition goes in the same breath as the
                // offsets it would otherwise unwind in front of the viewer.
                transition:
                  inHand || carry === null || prefersReducedMotion()
                    ? undefined
                    : `transform ${SLIDE_MS}ms ease`,
              }}
              data-leika-list-item
              data-leika-list-carried={inHand || undefined}
            >
              <Input
                value={entry}
                aria-label={`${label ?? "List"} entry ${place + 1}`}
                className={cn(
                  // Focused, it draws its own border over its neighbours'
                  // rather than under them.
                  "relative w-full focus-visible:z-10",
                  // An entry too long for its box ends in an ellipsis rather
                  // than at a cut letter -- whether the box was always too
                  // narrow for it, or the controls just took the end of it.
                  // The browser drops the ellipsis while the box has the
                  // caret, which is right: an entry being edited has to show
                  // where the typing is going, not where the reading stopped.
                  "text-ellipsis",
                  !frozen &&
                    cn(
                      // Room for the controls made only when they are there,
                      // on the same two counts that bring them out. A row at
                      // rest is an ordinary text box, its text running the
                      // full width of the column like every other one in the
                      // panel.
                      "group-hover/entry:pr-10",
                      "group-has-[[data-leika-list-controls]_:focus-visible]/entry:pr-10",
                      // And the keys on one of those controls light this
                      // border, exactly as the caret in this box does: the
                      // panel says where the keyboard is by the edge of the
                      // thing that has it. The lift goes with it, or the
                      // neighbour below paints over the lit edge.
                      "group-has-[[data-leika-list-controls]_:focus-visible]/entry:border-ring",
                      "group-has-[[data-leika-list-controls]_:focus-visible]/entry:z-10",
                    ),
                  aloft
                    ? // Aloft it is a box of its own rather than part of a
                      // run: it keeps its full rounding, and it is opaque, or
                      // the entries it passes over show through it. Opaque at
                      // once, too -- a box fades its colours, and a surface
                      // arriving over a sixth of a second is a see-through row
                      // for most of a drag.
                      "bg-(--leika-panel-surface) pr-10 transition-none"
                    : // Otherwise it wears the shape of its place in the run,
                      // which is the place it is DRAWN in: the rows an entry
                      // displaces take over the ends it left behind.
                      cn(
                        slot > 0 && "rounded-t-none",
                        slot < value.length - 1 && "rounded-b-none",
                      ),
                )}
                disabled={disabled}
                onChange={(event) => {
                  const next = [...value];
                  next[place] = event.currentTarget.value;
                  commit(next);
                }}
                data-leika-list-entry
              />
              {/* Both controls live INSIDE the box, at its end. They belong to
                  this entry -- one takes hold of it, the other throws it away
                  -- and buttons of their own alongside would read as further
                  controls in the column rather than as what to do with the row
                  they are on.

                  Above the box, not merely over it: the box lifts itself with
                  a z-index when focused so its border paints over the
                  neighbours it hugs, and that lift put a focused entry on top
                  of its own controls -- visible, and taking every click meant
                  for them. */}
              {!frozen && (
                <span
                  className={cn(
                    "absolute inset-y-0 right-1.5 z-20 flex items-center",
                    // In hand, out for as long as the drag lasts: the stack
                    // has stopped answering the pointer, and the grip under
                    // the cursor is being used rather than merely focused.
                    inHand ? "opacity-100" : CONTROLS,
                  )}
                  data-leika-list-controls
                >
                  <button
                    type="button"
                    className={cn(CONTROL, "cursor-grab")}
                    // "Reorder", not "Move": "Remove entry 1" CONTAINS "Move
                    // entry 1", so the two names would match each other by
                    // substring -- for a screen reader working through them
                    // and for anything else searching by name.
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
                    onClick={() =>
                      commit(value.filter((_, other) => other !== place))
                    }
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
          onClick={() => commit([...value, ""])}
          data-leika-button
          data-leika-button-color="secondary"
          data-leika-list-add
        >
          <PlusIcon data-icon="inline-start" />
          Add
        </Button>
      )}
    </div>
  );

  // Labelled, the stack takes the controls column like any other row's control
  // -- but the label sits against its FIRST entry rather than halfway down the
  // pile, which is where a column of one thing would put it.
  return (
    <GuiInputRow
      {...{ uuid, hint, label }}
      disabled={disabled}
      associateLabel={false}
      alignLabelToFirstRow
    >
      {stack}
    </GuiInputRow>
  );
}
