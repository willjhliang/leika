import { Checkbox } from "@/components/ui/checkbox";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiCheckboxMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

export default function CheckboxComponent({
  uuid,
  value,
  props: { disabled, hint, label },
}: GuiCheckboxMessage) {
  const { setValue } = useGuiComponent();
  return (
    <GuiInputRow {...{ uuid, label, hint, disabled }}>
      <Checkbox
        id={uuid}
        checked={value}
        onCheckedChange={(checked) => setValue(uuid, checked)}
        disabled={disabled}
      />
    </GuiInputRow>
  );
}
