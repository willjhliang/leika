import { ColorInputComponent } from "./ColorInputComponent";
import { GuiRgbaMessage } from "../WebsocketMessages";
import { rgbaToString, parseToRgba, rgbaEqual } from "./colorUtils";

export default function RgbaComponent({
  uuid,
  value,
  props: { label, hint, disabled },
}: GuiRgbaMessage) {
  return (
    <ColorInputComponent
      {...{ uuid, value, label, hint, disabled }}
      format="rgba"
      toString={rgbaToString}
      parse={parseToRgba}
      equal={rgbaEqual}
    />
  );
}
