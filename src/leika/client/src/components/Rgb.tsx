import { ColorInputComponent } from "./ColorInputComponent";
import { GuiRgbMessage } from "../WebsocketMessages";
import { rgbToString, parseToRgb, rgbEqual } from "./colorUtils";

export default function RgbComponent({
  uuid,
  value,
  props: { label, hint, disabled },
}: GuiRgbMessage) {
  return (
    <ColorInputComponent
      {...{ uuid, value, label, hint, disabled }}
      format="rgb"
      toString={rgbToString}
      parse={parseToRgb}
      equal={rgbEqual}
    />
  );
}
