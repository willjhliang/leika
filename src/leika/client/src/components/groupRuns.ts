/** Splitting a row of options into runs, and drawing one.
 *
 * Shared by the button row and the toggle row: the two differ in what a press
 * means, not in how a row of them is put together.
 */

import * as React from "react";

/** Split the options into runs of controls that are joined to each other, as
 * indices into the row -- an option's place is what says which colorway it
 * wears, so the runs carry that rather than the text.
 *
 * `merge[i]` answers for the gap between option `i` and `i + 1`, so a false
 * starts a new run. One option per run means every control stands alone; one
 * run means the whole row is a single block. */
export function runsOf(options: string[], merge: boolean[]): number[][] {
  const runs: number[][] = [];
  options.forEach((_option, index) => {
    if (index > 0 && merge[index - 1]) runs[runs.length - 1].push(index);
    else runs.push([index]);
  });
  return runs;
}

/** How a run of joined controls is laid out, shared by the buttons and toggles.
 *
 * A run is the block a reader sees: neighbours share an edge, and the block as
 * a whole is what carries the rounding. `pt-px` pays for the `-mt-px` every
 * control carries: a control pulls itself up by the width of a border so a line
 * meets the line above it on one shared edge, exactly as `-ml-px` does along a
 * line. Applied to all of them, the first line would sit a pixel high, and this
 * is the pixel it sits back down on.
 */
export const GROUP_RUN_CLASS = "flex min-w-fit flex-1 flex-wrap pt-px";

/** One control inside such a run: stretched, and sharing the edge above it.
 * Its corners and its left edge are decided per control, since both depend on
 * the line it lands on -- see `useRunPlacements`. */
export const GROUP_RUN_ITEM_CLASS = "-mt-px min-w-fit flex-1";

/** Marks a control whose place in the run's lines has to be measured. */
export const RUN_ITEM_ATTR = "data-leika-run-item";

/** Where a control sits in the run once the run has been laid out: which of
 * its corners are the run's own, and whether it opens a line. */
export type RunPlacement = {
  topLeft: boolean;
  topRight: boolean;
  bottomLeft: boolean;
  bottomRight: boolean;
  /** First on its line, so there is nothing to its left to share an edge with.
   * A control that shares one pulls left by a border's width; one that opens a
   * line pulling left would hang a pixel off the run, out past the line above
   * it. */
  startsLine: boolean;
};

/** Where the controls of a run sit while it fits on one line, which is both the
 * common case and the right answer before anything is measured. */
function singleLinePlacements(count: number): RunPlacement[] {
  return Array.from({ length: count }, (_item, index) => ({
    topLeft: index === 0,
    bottomLeft: index === 0,
    topRight: index === count - 1,
    bottomRight: index === count - 1,
    startsLine: index === 0,
  }));
}

function samePlacements(a: RunPlacement[], b: RunPlacement[]): boolean {
  return (
    a.length === b.length &&
    a.every(
      (placement, index) =>
        placement.topLeft === b[index].topLeft &&
        placement.topRight === b[index].topRight &&
        placement.bottomLeft === b[index].bottomLeft &&
        placement.bottomRight === b[index].bottomRight &&
        placement.startsLine === b[index].startsLine,
    )
  );
}

/** Work out where each control in a run sits once the run has been laid out.
 *
 * The rounding cannot be put on the run's own box and clipped out of the
 * controls: what clipping cuts off is their OUTLINE, so a corner would lose the
 * border that every other edge of the control has -- and that border is the
 * part that changes color under the pointer, so the corner would sit out the
 * hover it belongs to. Each control has to round itself.
 *
 * Which corners those are is a question about lines, and a run wraps: the
 * control that ends the first LINE is the one holding the block's top-right
 * corner, and no selector can ask which control that is. So the lines are
 * measured, and measured again whenever the run is resized.
 *
 * Every line of a run is full width -- the controls stretch to fill it -- so
 * the block is a rectangle, and its four corners are the run's first control,
 * the last on its first line, the first on its last line, and its last.
 *
 * The same measurement answers which controls open a line, which is the other
 * thing a run cannot tell from source order alone.
 */
export function useRunPlacements(
  runRef: React.RefObject<HTMLElement | null>,
  count: number,
): RunPlacement[] {
  const [placements, setPlacements] = React.useState<RunPlacement[]>(() =>
    singleLinePlacements(count),
  );

  React.useLayoutEffect(() => {
    const run = runRef.current;
    if (run === null) return;

    const measure = () => {
      const items = [
        ...run.querySelectorAll<HTMLElement>(`[${RUN_ITEM_ATTR}]`),
      ];
      if (items.length === 0) return;

      // Controls in source order, grouped into the lines they landed on.
      const lines: number[][] = [];
      let previousTop: number | null = null;
      items.forEach((item, index) => {
        const top = Math.round(item.getBoundingClientRect().top);
        if (previousTop === null || top !== previousTop) lines.push([index]);
        else lines[lines.length - 1].push(index);
        previousTop = top;
      });

      const firstLine = lines[0];
      const lastLine = lines[lines.length - 1];
      const opensLine = new Set(lines.map((line) => line[0]));
      const next = items.map((_item, index) => ({
        topLeft: index === 0,
        topRight: index === firstLine[firstLine.length - 1],
        bottomLeft: index === lastLine[0],
        bottomRight: index === items.length - 1,
        startsLine: opensLine.has(index),
      }));
      setPlacements((current) =>
        samePlacements(current, next) ? current : next,
      );
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(run);
    return () => observer.disconnect();
  }, [runRef, count]);

  return placements.length === count ? placements : singleLinePlacements(count);
}

/** A control's left edge as classes: shared with the control beside it, or
 * squarely on the line's own edge.
 *
 * The zero is marked important because the stock toggle pulls every item but
 * the first of its box left for itself. That is an answer about the box, and
 * once a run wraps the control opening the second line is not the first of
 * anything -- so it took the pull, and hung a pixel out past the line above. */
export function runSeamClasses(placement: RunPlacement): string {
  return placement.startsLine ? "ml-0!" : "-ml-px";
}

/** A control's corners as classes. Marked important because the stock toggle
 * rounds the first and last item of a group for itself, which is an answer
 * about the group rather than about the line the control landed on. */
export function runCornerClasses(placement: RunPlacement): string {
  return [
    placement.topLeft ? "rounded-tl-lg!" : "rounded-tl-none!",
    placement.topRight ? "rounded-tr-lg!" : "rounded-tr-none!",
    placement.bottomLeft ? "rounded-bl-lg!" : "rounded-bl-none!",
    placement.bottomRight ? "rounded-br-lg!" : "rounded-br-none!",
  ].join(" ");
}
