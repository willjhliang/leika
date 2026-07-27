import * as React from "react";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiVector3Message } from "../WebsocketMessages";
import { VectorInput, GuiInputRow } from "./common";

export default function Vector3Component({
  uuid,
  value,
  props: { hint, label, disabled, min, max, step, precision },
}: GuiVector3Message) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      <VectorInput
        uuid={uuid}
        n={3}
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
