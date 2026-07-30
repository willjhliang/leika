import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiListMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { EntryStack } from "./EntryStack";
import { ENTRY_BOX_CONTROLS, entryBoxClassName } from "./entryStackStyles";

/** An editable list of text entries, stacked into one block.
 *
 * The entries are the value: everything a viewer can do to them -- type in
 * one, add one, throw one away, move one -- reports the whole list as it now
 * reads. Frozen, the list is its entries and nothing else; the typing stays,
 * which `disabled` is for.
 */
export default function ListInputComponent({
  uuid,
  value,
  props: { label, hint, disabled, frozen },
}: GuiListMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  const commit = (next: string[]) => setValue(uuid, next);

  const stack = (
    <EntryStack
      items={[...value]}
      commit={commit}
      blank={() => ""}
      disabled={disabled}
      frozen={frozen}
    >
      {(entry, row) => (
        <Input
          value={entry}
          aria-label={`${label ?? "List"} entry ${row.place + 1}`}
          className={cn(entryBoxClassName(row), !frozen && ENTRY_BOX_CONTROLS)}
          disabled={disabled}
          onChange={(event) => {
            const next = [...value];
            next[row.place] = event.currentTarget.value;
            commit(next);
          }}
          data-leika-list-entry
        />
      )}
    </EntryStack>
  );

  // Labelled, the stack sits beside its label like any other control, but the
  // label aligns to its FIRST entry rather than halfway down the pile.
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
