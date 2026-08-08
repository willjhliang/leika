import * as React from "react";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiVector2Message } from "../WebsocketMessages";
import { VectorInput, GuiInputRow } from "./common";

export default function Vector2Component({
  uuid,
  value,
  props: { hint, label, disabled, min, max, step, precision },
}: GuiVector2Message) {
  const { setValue } = useGuiComponent();
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      <VectorInput
        uuid={uuid}
        n={2}
        value={value}
        onChange={(value: number[]) => setValue(uuid, value)}
        min={min}
        max={max}
        step={step}
        precision={precision}
        disabled={disabled}
      />
    </GuiInputRow>
  );
}
