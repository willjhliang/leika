import React from "react";

import { Slider } from "@/components/ui/slider";
import { SliderAnnotations } from "./SliderAnnotations";
import { defaultMarks, snapMultiSliderValue } from "./sliderValues";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { usePointerDrag } from "../hooks/usePointerDrag";
import { GuiMultiSliderMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

export default function MultiSliderComponent({
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
    _marks: marks,
    fixed_endpoints: fixedEndpoints,
    min_range: minRange,
  },
}: GuiMultiSliderMessage) {
  const { setValue } = useGuiComponent();
  const [dragging, startDrag] = usePointerDrag();
  const controlledValue = React.useMemo(() => [...value], [value]);
  const endpointValues = React.useRef({ first: value[0], last: value.at(-1) });
  React.useEffect(() => {
    endpointValues.current = { first: value[0], last: value.at(-1) };
  }, [value]);
  const getThumbAriaLabel = React.useCallback(
    (index: number) => `${label ?? "Value"} handle ${index + 1}`,
    [label],
  );

  const separation = minRange ?? step;
  const minStepsBetweenValues =
    step <= 0 ? 0 : Math.max(0, Math.ceil(separation / step));

  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }} hintDisabled={dragging}>
      <div data-leika-slider="multi">
        <Slider
          id={uuid}
          getThumbAriaLabel={getThumbAriaLabel}
          value={controlledValue}
          min={min}
          max={max}
          step={step}
          minStepsBetweenValues={minStepsBetweenValues}
          thumbCollisionBehavior="none"
          disabled={disabled}
          onPointerDown={startDrag}
          onValueChange={(nextValue) => {
            if (disabled || !Array.isArray(nextValue)) return;
            const next = nextValue.map((item) =>
              snapMultiSliderValue(item, min, max, step, precision),
            );
            if (fixedEndpoints && next.length > 0) {
              next[0] = endpointValues.current.first ?? next[0];
              next[next.length - 1] =
                endpointValues.current.last ?? next.at(-1)!;
            }
            if (next.some((item, index) => !Object.is(item, value[index]))) {
              setValue(uuid, next);
            }
          }}
        />
        <SliderAnnotations
          marks={marks ?? defaultMarks(min, max)}
          min={min}
          max={max}
        />
      </div>
    </GuiInputRow>
  );
}
