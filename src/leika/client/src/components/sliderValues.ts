import type { SliderMark } from "./SliderAnnotations";

/** Value helpers shared by the slider family. Their own module rather than a
 * component file, which fast refresh needs to keep exporting only components. */

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

/** The range's own ends, for a slider whose caller named no marks. */
export function defaultMarks(min: number, max: number): SliderMark[] {
  return [min, max].map((value) => ({
    value,
    label: value.toFixed(6).replace(/\.?0+$/, ""),
  }));
}

/** Snap from the range minimum, rather than from zero. */
export function snapMultiSliderValue(
  value: number,
  min: number,
  max: number,
  step: number,
  precision: number,
) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return min;

  const clamped = clamp(value, min, max);
  if (clamped === min || clamped === max) return clamped;

  const safePrecision = clamp(Math.trunc(precision), 0, 12);
  const snapped =
    Number.isFinite(step) && step > 0
      ? min + Math.round((clamped - min) / step) * step
      : clamped;
  return clamp(Number(snapped.toFixed(safePrecision)), min, max);
}
