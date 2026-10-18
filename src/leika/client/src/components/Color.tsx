import * as React from "react";

import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiColorMessage } from "../WebsocketMessages";
import { ColorRow } from "./ColorPicker";
import {
  colorEqual,
  parseToRgb,
  parseToRgba,
  rgbToString,
  rgbaToString,
} from "./colorUtils";
import { GuiInputRow } from "./common";

type Color = GuiColorMessage["value"];

function colorToString(color: Color): string {
  return color.length === 4 ? rgbaToString(color) : rgbToString(color);
}

function parseColor(text: string, channels: number): Color | null {
  return channels === 4 ? parseToRgba(text) : parseToRgb(text);
}

/** A swatch and popover editor for an RGB color, or an RGBA one with four
 * channels. */
export default function ColorComponent({
  uuid,
  value,
  props: { label, hint, disabled },
}: GuiColorMessage) {
  const { setValue } = useGuiComponent();
  const channels = value.length;
  const [localValue, setLocalValue] = React.useState(colorToString(value));
  // What the row was declared with. A ref rather than state: it is the one
  // thing here that must not follow the value, and nothing re-renders on it.
  const initialValue = React.useRef(value);

  React.useEffect(() => {
    setLocalValue((current) => {
      const parsed = parseColor(current, channels);
      return parsed && colorEqual(parsed, value)
        ? current
        : colorToString(value);
    });
  }, [channels, value]);

  const updateValue = (next: string) => {
    const parsed = parseColor(next, channels);
    if (!parsed) return;
    setLocalValue(colorToString(parsed));
    if (!colorEqual(parsed, value)) setValue(uuid, parsed);
  };

  const reset = () => {
    const initial = initialValue.current;
    setLocalValue(colorToString(initial));
    if (!colorEqual(initial, value)) setValue(uuid, initial);
  };

  return (
    <GuiInputRow {...{ uuid, hint, label }} disabled={disabled}>
      <ColorRow
        id={uuid}
        value={localValue}
        label={label ?? "Color"}
        format={channels === 4 ? "rgba" : "rgb"}
        disabled={disabled}
        // Undo restores what Python declared the row with.
        onReset={colorEqual(value, initialValue.current) ? null : reset}
        onValueChange={updateValue}
      />
    </GuiInputRow>
  );
}
