import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  ButtonGroup,
  ButtonGroupSeparator,
} from "@/components/ui/button-group";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiButtonGroupMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

/** Split the options into runs of buttons that are joined to each other.
 *
 * `merge[i]` answers for the gap between option `i` and `i + 1`, so a false
 * starts a new run. One option per run means every button stands alone; one
 * run means the whole row is a single block. */
function runsOf(options: string[], merge: boolean[]): string[][] {
  const runs: string[][] = [];
  options.forEach((option, index) => {
    if (index > 0 && merge[index - 1]) runs[runs.length - 1].push(option);
    else runs.push([option]);
  });
  return runs;
}

/** A row of buttons that share a row and a colorway.
 *
 * Buttons, not toggles: nothing here is "on". The group's value is the option
 * last pressed, which Python reads and acts on -- pressing the same one twice
 * is two presses, not a no-op -- so there is no selected state to draw, and
 * the colorway applies to every option alike, exactly as if each of these were
 * an `add_button` of its own.
 *
 * Joined runs nest a ButtonGroup inside the row's own, which is how the stock
 * component composes: the inner one shares the edges between its buttons, the
 * outer one puts the gaps between the runs.
 */
export default function ButtonGroupComponent({
  uuid,
  props: { hint, label, disabled, options, color, _merge: merge },
}: GuiButtonGroupMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
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
        // width of the row they scroll rather than wrap, so the row stays one
        // row however many options it is given. The gap is the panel's own
        // step, tighter than the stock 8px this component ships with.
        // The stock group overlaps its children by a pixel so joined buttons
        // share an edge. Between RUNS there is no edge to share, and the
        // overlap would eat a pixel of the gap, so it is put back to zero: the
        // step between parted buttons is the panel's own 4px, the same one the
        // toggles use.
        className={cn(
          "no-scrollbar w-full min-w-0 gap-1 overflow-x-auto",
          "has-[>[data-slot=button-group]]:gap-1",
          "[&>[data-slot]~[data-slot]]:ml-0",
        )}
        data-leika-button-group
        data-leika-button-color={color}
      >
        {runs.map((run) => (
          <ButtonGroup key={run[0]} className="min-w-fit flex-1">
            {run.map((option, index) => (
              <React.Fragment key={option}>
                {/* Filled buttons meeting edge to edge would read as one bar
                    with words at intervals, so a joined run of them is divided
                    by a hairline in their own foreground. Outlined ones bring
                    their own borders and need nothing. */}
                {index > 0 && color === "primary" && (
                  <ButtonGroupSeparator className="bg-primary-foreground/25" />
                )}
                <Button
                  variant={color === "secondary" ? "outline" : "default"}
                  className="min-w-fit flex-1"
                  disabled={disabled}
                  data-leika-button
                  onClick={() => setValue(uuid, option)}
                >
                  {option}
                </Button>
              </React.Fragment>
            ))}
          </ButtonGroup>
        ))}
      </ButtonGroup>
    </GuiInputRow>
  );
}
