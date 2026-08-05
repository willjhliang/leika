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

/** How wide each mark's label may be, as a percentage of the track.
 *
 * A label is anchored on its own mark and pulled back by its own width in
 * proportion to where that mark sits: at the left end it runs entirely to the
 * right of the tick, at the right end entirely to the left, and in between it
 * is split in that ratio. So the room a label has is not simply the gap to its
 * neighbour -- it is that gap divided by the share of the label lying on that
 * side.
 *
 * Each mark is given the space up to the midpoint between it and the mark on
 * either side, which tiles the track: two labels can then never reach the same
 * point, whatever they say. Without this a slider told to name three points on
 * a 190px track drew them straight through each other.
 *
 * Positions are expected already clamped to 0..100 and may arrive in any
 * order. Marks sharing one position leave each other no room and are capped to
 * nothing, which is the honest answer -- there is nowhere for the second label
 * to go.
 */
export function markLabelMaxWidths(positions: number[]): number[] {
  const byPosition = positions
    .map((position, index) => ({ position, index }))
    .sort((a, b) => a.position - b.position);

  const widths = new Array<number>(positions.length).fill(100);
  byPosition.forEach(({ position, index }, place) => {
    const before = place === 0 ? null : byPosition[place - 1].position;
    const after =
      place === byPosition.length - 1 ? null : byPosition[place + 1].position;
    const leftBound = before === null ? 0 : (before + position) / 2;
    const rightBound = after === null ? 100 : (position + after) / 2;
    // At either end one of the two constraints does not bind: nothing of the
    // label lies on that side of the tick to run into anything.
    const fromLeft =
      position <= 0 ? Infinity : ((position - leftBound) * 100) / position;
    const fromRight =
      position >= 100
        ? Infinity
        : ((rightBound - position) * 100) / (100 - position);
    widths[index] = Math.max(0, Math.min(100, fromLeft, fromRight));
  });
  return widths;
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
