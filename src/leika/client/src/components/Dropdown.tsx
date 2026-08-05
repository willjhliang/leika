import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
  ComboboxValue,
} from "@/components/ui/combobox";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiDropdownMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

/** The default dropdown: a plain Select, which opens with the current option
 * already under the cursor and lets the rest of the list run above the trigger
 * rather than stacking all of it below. */
function PlainDropdown({
  uuid,
  value,
  options,
  disabled,
  onValueChange,
}: {
  uuid: string;
  value: string;
  options: string[];
  disabled: boolean;
  onValueChange: (next: string) => void;
}) {
  // `items` is what SelectValue renders the trigger's label from, so it takes
  // the {label, value} pairs rather than the bare strings.
  const items = React.useMemo(
    () => options.map((option) => ({ label: option, value: option })),
    [options],
  );
  return (
    <Select
      items={items}
      value={value}
      onValueChange={(next) => next !== null && onValueChange(next)}
      disabled={disabled}
    >
      <SelectTrigger id={uuid} className="w-full" disabled={disabled}>
        {/* The trigger already asks for a clamped line, but it makes the value
            a flex box in the same breath, and neither `line-clamp` nor
            `text-overflow` survives that -- a long option was cut off mid-word
            against the chevron. Forced back to a block, and marked important
            because the rule losing here is the trigger's own child selector,
            which outranks a class on the child. */}
        <SelectValue className="block! min-w-0 truncate" />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {items.map((item) => (
            <SelectItem key={item.value} value={item.value}>
              {item.label}
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

/** The `searchable` dropdown: a Combobox, whose popup is a filter box over the
 * options. It anchors below the trigger, since a list that changes length as
 * you type cannot keep the selected item in place. */
function SearchableDropdown({
  uuid,
  value,
  options,
  disabled,
  onValueChange,
}: {
  uuid: string;
  value: string;
  options: string[];
  disabled: boolean;
  onValueChange: (next: string) => void;
}) {
  return (
    <Combobox
      items={options}
      value={value}
      onValueChange={(next) => next !== null && onValueChange(next)}
      itemToStringLabel={(option) => option}
      itemToStringValue={(option) => option}
      disabled={disabled}
    >
      <ComboboxTrigger
        id={uuid}
        render={
          <Button
            variant="outline"
            className="w-full justify-between"
            disabled={disabled}
          />
        }
      >
        <ComboboxValue placeholder="Select…" />
      </ComboboxTrigger>
      <ComboboxContent>
        <ComboboxInput
          showTrigger={false}
          placeholder="Search…"
          aria-label="Search options"
        />
        <ComboboxEmpty>No options found.</ComboboxEmpty>
        <ComboboxList>
          {(option: string) => (
            <ComboboxItem key={option} value={option}>
              {option}
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}

export default function DropdownComponent({
  uuid,
  value,
  props: { hint, label, disabled, options, searchable },
}: GuiDropdownMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  const shared = {
    uuid,
    value,
    options,
    disabled,
    onValueChange: (next: string) => setValue(uuid, next),
  };
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      {searchable ? (
        <SearchableDropdown {...shared} />
      ) : (
        <PlainDropdown {...shared} />
      )}
    </GuiInputRow>
  );
}
