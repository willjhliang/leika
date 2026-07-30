import * as React from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiChecklistMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { EntryStack } from "./EntryStack";
import { ENTRY_BOX_CONTROLS, entryBoxClassName } from "./entryStackStyles";

/** One item: what it says, and whether it has been ticked. */
type Item = GuiChecklistMessage["value"][number];

/** An entry's box: the one thing on the row that is always out, since it is
 * the row's answer rather than something to do TO the row the way the grip and
 * the remove at the other end are.
 *
 * A checkbox is drawn with reach beyond its 16px -- generous for one standing
 * in open space, too much for one at the end of a 24px row, where it took a
 * bite out of the row above and the row below and out of the text beside it.
 * Trimmed to the row it belongs to, it fills that row's height exactly, which
 * is the rule the controls at the other end already follow.
 *
 * It is otherwise the panel's checkbox and nothing else, filling the way every
 * other checkbox in the GUI fills -- which is what the `key` on it, out at the
 * call, is there to protect.
 */
function ItemBox({
  id,
  item: [, checked],
  disabled,
  onCheck,
}: {
  id: string;
  item: Item;
  disabled: boolean;
  onCheck: (checked: boolean) => void;
}) {
  return (
    <Checkbox
      id={id}
      checked={checked}
      onCheckedChange={onCheck}
      disabled={disabled}
      className="after:-inset-1"
      data-leika-checklist-box
    />
  );
}

/** A list whose entries carry an answer: text, each with a box to tick.
 *
 * The value is the pairs, so ticking a box reports the whole list exactly as
 * editing an entry does -- and because the stack moves whole items about, a
 * tick travels with the words it is against rather than staying at a row
 * number.
 *
 * The box rides INSIDE the entry, at its start, the way the grip and the
 * remove ride inside at its end -- so the stack stays one block of fields
 * beginning where every other control in the panel begins, rather than a
 * column of boxes with the fields indented past them.
 *
 * Frozen, it stops being a list to write and becomes one to work through: the
 * words are drawn as words, the box is the only thing on the row that answers,
 * and clicking what an item says ticks it. That is a stronger `frozen` than a
 * list's, which leaves the typing alone, and it is the difference between the
 * two components -- a checklist is asked for its ticks.
 */
export default function ChecklistComponent({
  uuid,
  value,
  props: { label, hint, disabled, frozen },
}: GuiChecklistMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  const commit = (next: Item[]) => setValue(uuid, next);

  /** Rewrite one item, leaving the rest of the list exactly as it is. */
  const rewrite = (place: number, item: Item) =>
    commit(value.map((other, where) => (where === place ? item : other)));

  const stack = frozen ? (
    // Nothing to add to, nothing to reorder, nothing to type in: rows of words
    // with a box each, rather than one block of fields.
    <div className="flex w-full min-w-0 flex-col">
      {value.map((item, place) => (
        <div
          key={place}
          className={cn(
            // `pl-1` is where a writable row's box sits inside its field, so
            // the boxes of the two kinds line up and so do their words. There
            // is no border here to sit in from, but there is one next door.
            "flex min-h-6 w-full min-w-0 items-center gap-2 pl-1",
            // The stack's pitch exactly: same row height, and the same pixel
            // off the top that hugging fields lose to the border they share.
            // Whether an item's words can be typed in is not a reason for a
            // checklist to sit at a different rhythm.
            place > 0 && "-mt-px",
          )}
          data-leika-list-item
        >
          {/* No `key` needed: nothing here reorders, so a row holds the same
              item for as long as it exists. */}
          <ItemBox
            id={`${uuid}-${place}`}
            item={item}
            disabled={disabled}
            onCheck={(checked) => rewrite(place, [item[0], checked])}
          />
          {/* A `<label>`, so the words tick the box too -- the row is one
              thing to answer, and a 16px target is a small one. */}
          <label
            htmlFor={`${uuid}-${place}`}
            className={cn(
              "min-w-0 truncate text-sm",
              disabled ? "opacity-50" : "cursor-pointer",
            )}
            title={item[0]}
            data-leika-checklist-entry
          >
            {item[0]}
          </label>
        </div>
      ))}
    </div>
  ) : (
    <EntryStack
      items={[...value]}
      commit={commit}
      blank={(): Item => ["", false]}
      disabled={disabled}
      frozen={false}
    >
      {(item, row) => (
        <>
          {/* `pl-7` clears the box and leaves the same gap after it that the
              panel puts between a control and its neighbour. */}
          <Input
            value={item[0]}
            aria-label={`${label ?? "Checklist"} entry ${row.place + 1}`}
            className={cn(entryBoxClassName(row), ENTRY_BOX_CONTROLS, "pl-7")}
            disabled={disabled}
            onChange={(event) =>
              rewrite(row.place, [event.currentTarget.value, item[1]])
            }
            data-leika-checklist-entry
          />
          {/* Inside the box at its start, as its controls are inside at its
              end. `left-1` is the 4px a 16px box already sits from the top and
              the bottom of a 24px field, so it is the same distance from the
              border on every side rather than a left margin of its own.
              `z-20` beats the focused field's lift, which would otherwise sit
              over the checkbox and take its clicks. */}
          <span className="absolute inset-y-0 left-1 z-20 flex items-center">
            {/* Keyed by the ENTRY, not by the row. Rows are keyed by their
                place and rewritten where they stand, so without this a box is
                reused as a different item arrives in its row -- and a control
                that eases between its states then eases from the answer that
                item's predecessor gave to the answer this one gives. Dropping
                a ticked entry further down lit the row it had come from and
                put it out again. With it, a box that stays is the same box and
                a tick is a tick, eased like every other in the GUI; a box whose
                entry has moved on is a different control, mounted already
                showing its own answer with no previous state to ease out of. */}
            <ItemBox
              key={row.id}
              id={`${uuid}-${row.place}`}
              item={item}
              disabled={disabled}
              onCheck={(checked) => rewrite(row.place, [item[0], checked])}
            />
          </span>
        </>
      )}
    </EntryStack>
  );

  // Labelled, the stack sits beside its label like any other control, but the
  // label aligns to its FIRST item rather than halfway down the pile.
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
