import { cn } from "@/lib/utils";

/** One row as an entry stack is drawing it, which a drag can put at odds with
 * where the entry actually lives. */
export type EntryRow = {
  /** The entry's own place in the list. */
  place: number;
  /** What the entry IS, as opposed to where it currently sits: a number the
   * stack keeps with it while the entries are shuffled. Rows are keyed by
   * their place and rewritten where they stand, so anything inside a row that
   * carries state of its own -- a control that eases between colours, say --
   * needs this to tell "the same thing, changed" from "a different thing,
   * arrived". Two entries reading the same still have ids of their own. */
  id: number;
  /** The place the row is DRAWN in, which is not the place it holds while an
   * entry is being carried over it. */
  slot: number;
  /** Whether the row is off the list: the pointer has it, or it is still on
   * its way to where the pointer left it. */
  aloft: boolean;
  /** How many entries there are, so a row can tell an end from a middle. */
  count: number;
};

/** The shape a row's text box wears where it is drawn.
 *
 * Aloft it is a box of its own: full rounding, opaque -- and opaque at once,
 * or it is a see-through row for most of the drag. Otherwise it wears the
 * shape of the place it is DRAWN in, since rows an entry displaces take over
 * the ends it left.
 */
export function entryBoxClassName({ slot, aloft, count }: EntryRow) {
  return cn(
    // Focused, it draws its own border over its neighbours'.
    "relative w-full focus-visible:z-10",
    // A cut-off entry ends in an ellipsis -- except while the box has the
    // caret, when the browser rightly shows where the typing is going instead.
    "text-ellipsis",
    aloft
      ? "bg-(--leika-panel-surface) pr-10 transition-none"
      : cn(slot > 0 && "rounded-t-none", slot < count - 1 && "rounded-b-none"),
  );
}

/** The room a row keeps for the controls that come out over it, and the border
 * it lights when the keys are on one of them. Only for a stack whose entries
 * can be reordered and removed; frozen, nothing comes out. */
export const ENTRY_BOX_CONTROLS = cn(
  // Room for the controls only while they are shown, on the same two counts
  // that bring them out.
  "group-hover/entry:pr-10",
  "group-has-[[data-leika-list-controls]_:focus-visible]/entry:pr-10",
  // Keys on a control light this border exactly as the caret does; the z-lift
  // goes with it, or the neighbour below paints over the lit edge.
  "group-has-[[data-leika-list-controls]_:focus-visible]/entry:border-ring",
  "group-has-[[data-leika-list-controls]_:focus-visible]/entry:z-10",
);
