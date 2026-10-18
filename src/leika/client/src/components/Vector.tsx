import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiVectorMessage } from "../WebsocketMessages";
import { GuiInputRow, VectorInput } from "./common";

/** A vector of two or three number fields in one row. */
export default function VectorComponent({
  uuid,
  value,
  props: { hint, label, disabled, min, max, step, precision },
}: GuiVectorMessage) {
  const { setValue } = useGuiComponent();
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      <VectorInput
        uuid={uuid}
        n={value.length === 3 ? 3 : 2}
        value={value}
        onChange={(next: number[]) => setValue(uuid, next)}
        min={min}
        max={max}
        step={step}
        precision={precision}
        disabled={disabled}
      />
    </GuiInputRow>
  );
}
