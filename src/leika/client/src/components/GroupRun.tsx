import * as React from "react";

import {
  GROUP_RUN_CLASS,
  useRunPlacements,
  type RunPlacement,
} from "./groupRuns";

/** One run of joined controls, and where each of them turns out to sit in it.
 *
 * The run is a box for layout only -- it draws nothing. What a run looks like
 * is the sum of the controls in it, which is what lets a control keep its own
 * outline all the way around its own corner. See `useRunPlacements`.
 *
 * The placements arrive through a render prop rather than as a class the caller
 * applies afterwards, because they are measured: the caller cannot know which
 * line a control will land on when it decides what to render, and the hook that
 * finds out has to hang off this box.
 */
export function GroupRun({
  count,
  children,
}: {
  /** How many controls the run holds; separators between them do not count. */
  count: number;
  children: (placements: RunPlacement[]) => React.ReactNode;
}) {
  const run = React.useRef<HTMLDivElement>(null);
  const placements = useRunPlacements(run, count);
  return (
    <div ref={run} className={GROUP_RUN_CLASS} data-leika-group-run>
      {children(placements)}
    </div>
  );
}
