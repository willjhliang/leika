import * as React from "react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiButtonGroupMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

export default function ButtonGroupComponent({
  uuid,
  value,
  props: { hint, label, disabled, options },
}: GuiButtonGroupMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      <ToggleGroup
        id={uuid}
        value={[value]}
        disabled={disabled}
        aria-label={label}
        variant="outline"
        spacing={0}
        className="no-scrollbar w-full min-w-0 justify-start overflow-x-auto"
      >
        {options.map((option) => (
          <ToggleGroupItem
            key={option}
            value={option}
            className="min-w-fit flex-1"
            data-leika-button
            onClick={() => setValue(uuid, option)}
          >
            {option}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
    </GuiInputRow>
  );
}
