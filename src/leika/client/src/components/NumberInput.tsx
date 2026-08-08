import * as React from "react";

import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiNumberMessage } from "../WebsocketMessages";
import { NumericInput, GuiInputRow } from "./common";

export default function NumberInputComponent({
  uuid,
  value,
  props: { label, hint, disabled, precision, min, max, step },
}: GuiNumberMessage) {
  const { setValue } = useGuiComponent();
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      <NumericInput
        id={uuid}
        value={value}
        precision={precision}
        min={min ?? undefined}
        max={max ?? undefined}
        step={step}
        onValueChange={(next) => setValue(uuid, next)}
        disabled={disabled}
      />
    </GuiInputRow>
  );
}
