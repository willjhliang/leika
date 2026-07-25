function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

/** Convert a value to a finite percentage, including for a zero-width range. */
export function getMultiSliderPercentage(value: number, min: number, max: number) {
  const range = max - min;
  if (!Number.isFinite(range) || range <= 0) return 0;
  return clamp(((value - min) / range) * 100, 0, 100);
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

export function getMultiSliderValueFromFraction(
  fraction: number,
  min: number,
  max: number,
  step: number,
  precision: number,
) {
  if (max <= min) return min;
  const rawValue = clamp(fraction, 0, 1) * (max - min) + min;
  return snapMultiSliderValue(rawValue, min, max, step, precision);
}
