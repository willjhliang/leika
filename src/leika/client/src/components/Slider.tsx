import React from "react";

import { Slider } from "@/components/ui/slider";
import { SliderAnnotations } from "./SliderAnnotations";
import { defaultMarks } from "./sliderValues";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { usePointerDrag } from "../hooks/usePointerDrag";
import { GuiSliderMessage } from "../WebsocketMessages";
import { NumericInput, GuiInputRow } from "./common";

export default function SliderComponent({
  uuid,
  value,
  props: {
    label,
    hint,
    disabled,
    min,
    max,
    precision,
    step,
    show_value: showValue,
    _marks: marks,
  },
}: GuiSliderMessage) {
  const { setValue } = useGuiComponent();
  const [dragging, startDrag] = usePointerDrag();
  const controlledValue = React.useMemo(() => [value], [value]);
  // The protocol allows an unlabelled row; a slider's Python API does not, so
  // this fallback is a floor rather than a case that happens.
  const ariaLabel = label ?? "Value";
  const getThumbAriaLabel = React.useCallback(() => ariaLabel, [ariaLabel]);

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
            step={step}
            disabled={disabled}
            onPointerDown={startDrag}
            onValueChange={(next) => {
              const scalar = Array.isArray(next) ? next[0] : next;
              if (scalar !== undefined) setValue(uuid, scalar);
            }}
          />
          <SliderAnnotations
            marks={marks ?? defaultMarks(min, max)}
            min={min}
            max={max}
          />
        </div>
        {/* Absent, the track takes the row on its own: the annotations below
            still name the range, so the number is an addition rather than the
            only reading of the value. */}
        {showValue ? (
          <NumericInput
            aria-label={`${ariaLabel} value`}
            className="w-16"
            value={value}
            onValueChange={(next) => setValue(uuid, next)}
            min={min}
            max={max}
            step={step}
            precision={precision}
            disabled={disabled}
          />
        ) : null}
      </div>
    </GuiInputRow>
  );
}
