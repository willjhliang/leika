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
 * is split in that ratio. That share is what decides how far a label of a
 * given width REACHES into the gap beside it, which is the quantity two
 * neighbours actually contend over.
 *
 * Nothing is rationed in advance. Each pair of neighbours is asked only
 * whether what they naturally want to occupy adds up to more than the gap
 * between them; if it does not -- a long label beside a short one that still
 * clears it -- both keep every pixel they asked for. Only a pair that would
 * genuinely collide is cut back, and then the gap is split between them in
 * proportion to what each wanted, so neither is punished for its neighbour's
 * length alone.
 *
 * `naturalWidths` is each label's own content width, in the same percentage
 * units. Positions are expected already clamped to 0..100 and may arrive in
 * any order; the 100 cap that remains is the track itself, which the anchoring
 * makes exactly the width at which a label reaches an end and no further.
 */
export function markLabelMaxWidths(
  positions: number[],
  naturalWidths: number[],
): number[] {
  const byPosition = positions
    .map((position, index) => ({ position, index }))
    .sort((a, b) => a.position - b.position);

  const widths = new Array<number>(positions.length).fill(100);
  for (let place = 0; place < byPosition.length - 1; place += 1) {
    const left = byPosition[place];
    const right = byPosition[place + 1];
    const gap = right.position - left.position;
    // What each of the two reaches into the gap at its natural width. A label
    // on the left end of the track leans entirely right; one on the right end
    // leans entirely left, and reaches nothing.
    const leftReach =
      ((naturalWidths[left.index] ?? 0) * (100 - left.position)) / 100;
    const rightReach =
      ((naturalWidths[right.index] ?? 0) * right.position) / 100;
    const wanted = leftReach + rightReach;
    if (wanted <= gap) continue;

    const boundary =
      left.position + (wanted === 0 ? gap / 2 : (gap * leftReach) / wanted);
    if (left.position < 100) {
      widths[left.index] = Math.min(
        widths[left.index],
        ((boundary - left.position) * 100) / (100 - left.position),
      );
    }
    if (right.position > 0) {
      widths[right.index] = Math.min(
        widths[right.index],
        ((right.position - boundary) * 100) / right.position,
      );
    }
  }
  return widths.map((width) => Math.max(0, Math.min(100, width)));
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
