import React from "react";

import { Slider } from "@/components/ui/slider";
import { SliderAnnotations, type SliderMark } from "./SliderAnnotations";
import { snapMultiSliderValue } from "./multiSliderUtils";

interface MultiSliderProps {
  min: number;
  max: number;
  step?: number;
  value: number[];
  onChange: (value: number[]) => void;
  marks?: SliderMark[] | null;
  fixedEndpoints?: boolean;
  minRange?: number;
  precision?: number;
  id?: string;
  disabled?: boolean;
  label: string;
}

function defaultMarks(min: number, max: number): SliderMark[] {
  return [min, max].map((value) => ({
    value,
    label: value.toFixed(6).replace(/\.?0+$/, ""),
  }));
}

export function MultiSlider({
  min,
  max,
  step,
  value,
  onChange,
  marks,
  fixedEndpoints = false,
  minRange,
  precision = 2,
  id,
  disabled = false,
  label,
}: MultiSliderProps) {
  const effectiveStep = step ?? 1;
  const controlledValue = React.useMemo(() => [...value], [value]);
  const endpointValues = React.useRef({ first: value[0], last: value.at(-1) });
  React.useEffect(() => {
    endpointValues.current = { first: value[0], last: value.at(-1) };
  }, [value]);
  const getThumbAriaLabel = React.useCallback(
    (index: number) => `${label} handle ${index + 1}`,
    [label],
  );

  const renderedMarks = marks === null ? defaultMarks(min, max) : (marks ?? []);
  const separation = minRange ?? effectiveStep;
  const minStepsBetweenValues =
    effectiveStep <= 0 ? 0 : Math.max(0, Math.ceil(separation / effectiveStep));

  return (
    <div data-leika-slider="multi">
      <Slider
        id={id}
        getThumbAriaLabel={getThumbAriaLabel}
        value={controlledValue}
        min={min}
        max={max}
        step={effectiveStep}
        minStepsBetweenValues={minStepsBetweenValues}
        thumbCollisionBehavior="none"
        disabled={disabled}
        onValueChange={(nextValue) => {
          if (disabled || !Array.isArray(nextValue)) return;
          const next = nextValue.map((item) =>
            snapMultiSliderValue(item, min, max, effectiveStep, precision),
          );
          if (fixedEndpoints && next.length > 0) {
            next[0] = endpointValues.current.first ?? next[0];
            next[next.length - 1] = endpointValues.current.last ?? next.at(-1)!;
          }
          if (next.some((item, index) => !Object.is(item, value[index]))) {
            onChange(next);
          }
        }}
      />
      <SliderAnnotations marks={renderedMarks} min={min} max={max} />
    </div>
  );
}
