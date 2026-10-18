import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  NativeRadioGroupItem,
  RadioGroup,
  RadioGroupItem,
} from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { MAX_GUI_COLLECTION_ITEM_CODE_UNITS } from "../ControlPanel/guiConstants";
import { GuiListMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { EntryStack } from "./EntryStack";
import { HoverScrollText } from "./HoverScrollText";
import { ENTRY_BOX_CONTROLS, entryBoxClassName } from "./entryStackStyles";

/** One row: what it says, and whether it is marked. */
type Row = [string, boolean];
type Mark = GuiListMessage["props"]["mark"];

/** A row's mark: a box to tick, or one of the list's radios.
 *
 * Drawn with reach beyond its 16px, trimmed to the 24px row it sits in, so it
 * fills that row's height exactly rather than biting into its neighbours. A
 * frozen radio list's rows belong to one Base UI radio group; editable rows use
 * native same-name radios, which keep platform group semantics without taking
 * the caret away from the neighbouring text fields. */
function RowMark({
  id,
  name,
  place,
  row: [text, marked],
  mark,
  frozen,
  disabled,
  onMark,
}: {
  id: string;
  name: string;
  place: number;
  row: Row;
  mark: "check" | "radio";
  frozen: boolean;
  disabled: boolean;
  onMark: (marked: boolean) => void;
}) {
  if (mark === "check")
    return (
      <Checkbox
        id={id}
        checked={marked}
        onCheckedChange={onMark}
        disabled={disabled}
        className="after:-inset-1"
        data-leika-list-mark
      />
    );
  const label = text || `Option ${place + 1}`;
  if (frozen)
    return (
      <RadioGroupItem
        id={id}
        value={String(place)}
        disabled={disabled}
        aria-label={label}
        className="after:-inset-1"
        data-leika-list-mark
      />
    );
  return (
    <NativeRadioGroupItem
      id={id}
      name={name}
      value={String(place)}
      checked={marked}
      disabled={disabled}
      aria-label={label}
      className="after:-inset-1"
      onChange={(event) => {
        if (event.currentTarget.checked) onMark(true);
      }}
      data-leika-list-mark
    />
  );
}

/** An editable list of text rows, each optionally with a mark.
 *
 * The rows are the value: everything a viewer can do to them -- type in one,
 * mark one, add one, throw one away, move one -- reports the whole list as it
 * now reads. The stack moves whole rows about, so a mark travels with the
 * words it is against rather than staying at a row number.
 *
 * A mark rides INSIDE its row's text box, at its start, the way the grip and
 * the remove ride inside at its end -- so the stack stays one block of fields
 * beginning where every other control in the panel begins.
 *
 * Frozen, the rows can no longer be added, removed, or moved. A marked list
 * goes further and becomes one to work through: the words are drawn as words,
 * the mark is the only thing on the row that answers, and clicking what a row
 * says marks it. An unmarked frozen list keeps its typing, which `disabled` is
 * for.
 */
export default function ListComponent({
  uuid,
  value,
  props: { label, hint, disabled, frozen, mark },
}: GuiListMessage) {
  const { setValue } = useGuiComponent();
  // Rows are pairs whatever the mark; an unmarked list reports only its words.
  const rows: Row[] =
    mark === null
      ? (value as string[]).map((text): Row => [text, false])
      : (value as Row[]);
  const commit = (next: Row[]) =>
    setValue(uuid, mark === null ? next.map(([text]) => text) : next);

  /** Rewrite one row's words, leaving the rest of the list as it is. */
  const rewrite = (place: number, text: string) =>
    commit(
      rows.map((row, where): Row => (where === place ? [text, row[1]] : row)),
    );
  /** Mark or unmark one row; a radio clears the rest. */
  const setMark = (place: number, marked: boolean) =>
    commit(
      rows.map(([text, previous], where): Row => [
        text,
        where === place ? marked : mark === "radio" ? false : previous,
      ]),
    );

  const stack =
    frozen && mark !== null ? (
      <FrozenRows
        uuid={uuid}
        label={label}
        rows={rows}
        mark={mark}
        disabled={disabled}
        setMark={setMark}
      />
    ) : (
      <EntryStack
        items={rows}
        commit={commit}
        blank={(): Row => ["", false]}
        disabled={disabled}
        frozen={frozen}
      >
        {(row, entry) => (
          <>
            <Input
              value={row[0]}
              aria-label={`${label ?? "List"} entry ${entry.place + 1}`}
              className={cn(
                entryBoxClassName(entry),
                !frozen && ENTRY_BOX_CONTROLS,
                // Clears the mark and leaves the panel's own gap after it.
                mark !== null && "pl-7",
              )}
              disabled={disabled}
              maxLength={MAX_GUI_COLLECTION_ITEM_CODE_UNITS}
              onChange={(event) => {
                if (
                  event.currentTarget.value.length >
                  MAX_GUI_COLLECTION_ITEM_CODE_UNITS
                )
                  return;
                rewrite(entry.place, event.currentTarget.value);
              }}
              data-leika-list-entry
            />
            {mark !== null && (
              // `left-1` is the 4px a 16px mark already sits from the top and
              // bottom of a 24px field, so it is the same distance from the
              // border on every side. `z-20` beats the focused field's lift,
              // which would otherwise take the mark's clicks.
              <span className="absolute inset-y-0 left-1 z-20 flex items-center">
                {/* Keyed by the ENTRY, not the row. Rows are keyed by place
                    and rewritten where they stand, so without this a mark is
                    reused as a different row arrives in its place, and eases
                    from that row's predecessor's answer to its own. */}
                <RowMark
                  key={entry.id}
                  id={`${uuid}-${entry.place}`}
                  name={`leika-list-${uuid}`}
                  place={entry.place}
                  row={row}
                  mark={mark}
                  frozen={false}
                  disabled={disabled}
                  onMark={(marked) => setMark(entry.place, marked)}
                />
              </span>
            )}
          </>
        )}
      </EntryStack>
    );

  const list =
    mark === "radio" && !frozen ? (
      <fieldset className="m-0 block w-full min-w-0 border-0 p-0">
        <legend className="sr-only">{label ?? "Radio list"}</legend>
        {stack}
      </fieldset>
    ) : (
      stack
    );

  // Labelled, the stack sits beside its label like any other control, but the
  // label aligns to its FIRST row rather than halfway down the pile.
  return (
    <GuiInputRow
      {...{ uuid, hint, label }}
      disabled={disabled}
      associateLabel={false}
      alignLabelToFirstRow
    >
      {list}
    </GuiInputRow>
  );
}

/** A frozen marked list: rows of words with a mark each, rather than one
 * block of fields. */
function FrozenRows({
  uuid,
  label,
  rows,
  mark,
  disabled,
  setMark,
}: {
  uuid: string;
  label: string | null;
  rows: Row[];
  mark: NonNullable<Mark>;
  disabled: boolean;
  setMark: (place: number, marked: boolean) => void;
}) {
  const items = rows.map((row, place) => (
    <div
      key={place}
      className={cn(
        // `pl-1` is where an editable row's mark sits inside its field, so the
        // marks of the two kinds line up and so do their words. The stack's
        // pitch exactly: the same row height, and the same pixel off the top
        // that hugging fields lose to the border they share.
        "flex min-h-6 w-full min-w-0 items-center gap-2 pl-1",
        place > 0 && "-mt-px",
      )}
      data-leika-list-item
    >
      {/* No `key` needed: nothing here reorders. */}
      <RowMark
        id={`${uuid}-${place}`}
        name={`leika-list-${uuid}`}
        place={place}
        row={row}
        mark={mark}
        frozen
        disabled={disabled}
        onMark={(marked) => setMark(place, marked)}
      />
      {/* A `<label>`, so the words mark the row too -- the row is one thing to
          answer, and a 16px target is a small one. */}
      <label
        htmlFor={`${uuid}-${place}`}
        className={cn(
          "min-w-0 flex-1 text-sm",
          disabled ? "opacity-50" : "cursor-pointer",
        )}
        title={row[0]}
        data-leika-list-entry
      >
        <HoverScrollText>{row[0]}</HoverScrollText>
      </label>
    </div>
  ));
  if (mark === "check")
    return <div className="flex w-full min-w-0 flex-col">{items}</div>;
  const selected = rows.findIndex(([, marked]) => marked);
  return (
    <RadioGroup
      value={selected < 0 ? "" : String(selected)}
      onValueChange={(next) => {
        const place = Number(next);
        if (Number.isInteger(place) && place >= 0 && place < rows.length)
          setMark(place, true);
      }}
      disabled={disabled}
      aria-label={label ?? "Radio list"}
      className="flex w-full min-w-0 flex-col gap-0"
    >
      {items}
    </RadioGroup>
  );
}
