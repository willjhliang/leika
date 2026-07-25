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
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiDropdownMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

export default function DropdownComponent({
  uuid,
  value,
  props: { hint, label, disabled, visible, options },
}: GuiDropdownMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  if (!visible) return null;
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      <Combobox
        items={options}
        value={value}
        onValueChange={(next) => next !== null && setValue(uuid, next)}
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
    </GuiInputRow>
  );
}
