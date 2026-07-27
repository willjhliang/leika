import * as React from "react";

import { Button } from "@/components/ui/button";
import { ColorPicker } from "./ColorPicker";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
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
  const selectionRef = React.useRef<HTMLDivElement>(null);

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
      <Popover>
        <PopoverTrigger
          render={
            <Button
              id={uuid}
              variant="outline"
              className="w-full justify-start font-normal"
              disabled={disabled}
              data-leika-color-trigger
            />
          }
        >
          <span
            aria-hidden
            className="size-4 shrink-0 rounded-sm border border-border"
            style={{ backgroundColor: localValue }}
          />
          <span className="truncate">{localValue}</span>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-[min(20rem,calc(100vw-1rem))]"
          initialFocus={(interactionType) =>
            interactionType === "touch" ? true : selectionRef.current
          }
          data-leika-color-popover
        >
          <PopoverHeader className="sr-only">
            <PopoverTitle>{label}</PopoverTitle>
            <PopoverDescription>
              Choose a color by saturation, brightness, hue
              {format === "rgba" ? ", and opacity" : ""}.
            </PopoverDescription>
          </PopoverHeader>
          <ColorPicker
            value={localValue}
            format={format}
            disabled={disabled}
            selectionRef={selectionRef}
            onValueChange={updateValue}
          />
        </PopoverContent>
      </Popover>
    </GuiInputRow>
  );
}
