import React from "react";

import { Slider } from "@/components/ui/slider";
import { SliderAnnotations, type SliderMark } from "./SliderAnnotations";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiSliderMessage } from "../WebsocketMessages";
import { NumericInput, GuiInputRow } from "./common";

function defaultMarks(min: number, max: number): SliderMark[] {
  return [min, max].map((value) => ({
    value,
    label: value.toFixed(6).replace(/\.?0+$/, ""),
  }));
}

export default function SliderComponent({
  uuid,
  value,
  props: {
    label,
    hint,
    visible,
    disabled,
    min,
    max,
    precision,
    step,
    _marks: marks,
  },
}: GuiSliderMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  const [dragging, setDragging] = React.useState(false);
  const controlledValue = React.useMemo(() => [value], [value]);
  const getThumbAriaLabel = React.useCallback(() => label, [label]);

  React.useEffect(() => {
    if (!dragging) return;
    const stop = () => setDragging(false);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    return () => {
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
  }, [dragging]);

  if (!visible) return null;
  const renderedMarks = marks === null ? defaultMarks(min, max) : marks;

  return (
    <GuiInputRow
      uuid={uuid}
      hint={hint}
      label={label}
      hintDisabled={dragging}
      disabled={disabled}
    >
      <div className="flex items-center gap-2">
        <div className="min-w-0 flex-1">
          <Slider
            id={uuid}
            data-leika-slider
            getThumbAriaLabel={getThumbAriaLabel}
            value={controlledValue}
            min={min}
            max={max}
            step={step ?? 1}
            disabled={disabled}
            onPointerDown={() => setDragging(true)}
            onPointerCancel={() => setDragging(false)}
            onPointerUp={() => setDragging(false)}
            onValueChange={(next) => {
              const scalar = Array.isArray(next) ? next[0] : next;
              if (scalar !== undefined) setValue(uuid, scalar);
            }}
            onValueCommitted={() => setDragging(false)}
          />
          <SliderAnnotations marks={renderedMarks} min={min} max={max} />
        </div>
        <NumericInput
          aria-label={`${label} value`}
          className="w-16"
          value={value}
          onValueChange={(next) => setValue(uuid, next)}
          min={min}
          max={max}
          step={step ?? undefined}
          precision={precision}
          disabled={disabled}
        />
      </div>
    </GuiInputRow>
  );
}
