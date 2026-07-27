import * as React from "react";

import { ColorPickerPopover } from "./ColorPicker";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiInputRow } from "./common";

/** Swatch + popover color editor shared by the RGB and RGBA inputs. */
export function ColorInputComponent<V extends NonNullable<unknown>>({
  uuid,
  value,
  label,
  hint,
  disabled,
  format,
  toString,
  parse,
  equal,
}: {
  uuid: string;
  value: V;
  label: string;
  hint: string | null;
  disabled: boolean;
  format: "rgb" | "rgba";
  toString: (value: V) => string;
  parse: (value: string) => V | null;
  equal: (a: V, b: V) => boolean;
}) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  const [localValue, setLocalValue] = React.useState(toString(value));

  React.useEffect(() => {
    setLocalValue((current) => {
      const parsed = parse(current);
      return parsed && equal(parsed, value) ? current : toString(value);
    });
  }, [equal, parse, toString, value]);

  const updateValue = (next: string) => {
    const parsed = parse(next);
    if (!parsed) return;
    const canonical = toString(parsed);
    setLocalValue(canonical);
    if (!equal(parsed, value)) setValue(uuid, parsed);
  };

  return (
    <GuiInputRow {...{ uuid, hint, label }} disabled={disabled}>
      <ColorPickerPopover
        id={uuid}
        value={localValue}
        label={label}
        format={format}
        disabled={disabled}
        onValueChange={updateValue}
      />
    </GuiInputRow>
  );
}
