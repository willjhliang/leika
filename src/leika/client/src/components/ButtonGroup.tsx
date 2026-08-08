import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  ButtonGroup,
  ButtonGroupSeparator,
} from "@/components/ui/button-group";
import { cn } from "@/lib/utils";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiButtonGroupMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { GroupRun } from "./GroupRun";
import {
  GROUP_RUN_ITEM_CLASS,
  runCornerClasses,
  runSeamClasses,
  runsOf,
} from "./groupRuns";

/** A row of buttons.
 *
 * Buttons, not toggles: nothing here is "on". The group's value is the option
 * last pressed, which Python reads and acts on -- pressing the same one twice
 * is two presses, not a no-op -- so there is no selected state to draw. Each
 * option wears its own colorway, exactly as if it were an `add_button` of its
 * own; a row that names one role for all of them arrives as that role repeated.
 *
 * Joined runs are boxes inside the row: each shares the edges between its own
 * buttons, and the row puts the gaps between the runs. The rounding belongs to
 * the buttons themselves -- see `useRunPlacements`.
 */
export default function ButtonGroupComponent({
  uuid,
  props: { hint, label, disabled, options, color, _merge: merge },
}: GuiButtonGroupMessage) {
  const { setValue } = useGuiComponent();
  const runs = runsOf(options, merge);
  return (
    <GuiInputRow
      {...{ uuid, hint, label, disabled }}
      // No `htmlFor`: the row names a set of buttons, not one control, and a
      // label tied to a button would fire it when clicked.
      associateLabel={false}
    >
      <ButtonGroup
        id={uuid}
        // Unlabelled, the group goes unnamed rather than inventing a name:
        // every option is a button that reads out its own text.
        aria-label={label ?? undefined}
        // Options keep their own width and share what is left over; past the
        // width of the row they wrap onto another line. Scrolling was the
        // earlier answer, and it hid an option behind an edge with no
        // scrollbar to say so -- a button whose words are cut in half is not a
        // button anyone can read. The step between parted runs is the panel's
        // own 4px, the same one the toggles use, rather than the stock 8px this
        // component ships with.
        className="w-full min-w-0 flex-wrap gap-1"
        data-leika-button-group
      >
        {/* A box per run, not a nested ButtonGroup: that component rounds the
            last child of a run from the parent, which is an answer about the
            run rather than about the line a button landed on. */}
        {runs.map((run) => (
          <GroupRun key={options[run[0]]} count={run.length}>
            {(placements) =>
              run.map((option, place) => (
                <React.Fragment key={options[option]}>
                  {/* Filled buttons meeting edge to edge would read as one bar
                      with words at intervals, so a joined pair of them is divided
                      by a hairline in their own foreground. An outlined one on
                      either side brings a border of its own and needs nothing. */}
                  {place > 0 &&
                    color[option] === "inverse" &&
                    color[run[place - 1]] === "inverse" && (
                      <ButtonGroupSeparator className="bg-primary-foreground/25" />
                    )}
                  <Button
                    variant={
                      color[option] === "inverse" ? "default" : "outline"
                    }
                    className={cn(
                      GROUP_RUN_ITEM_CLASS,
                      runCornerClasses(placements[place]),
                      // Along a line, neighbours share one edge rather than
                      // stacking two -- but only along one: a button that OPENS
                      // a line has nothing to its left, and pulling left would
                      // hang it a pixel off the run. `-mt-px` joins the lines.
                      runSeamClasses(placements[place]),
                    )}
                    disabled={disabled}
                    data-leika-button
                    data-leika-run-item
                    data-leika-joined={
                      !placements[place].startsLine || undefined
                    }
                    data-leika-button-color={color[option]}
                    onClick={() => setValue(uuid, options[option])}
                  >
                    {options[option]}
                  </Button>
                </React.Fragment>
              ))
            }
          </GroupRun>
        ))}
      </ButtonGroup>
    </GuiInputRow>
  );
}
