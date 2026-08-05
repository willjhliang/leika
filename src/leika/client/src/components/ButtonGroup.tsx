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

/** Split the options into runs of buttons that are joined to each other, as
 * indices into the row -- an option's place is what says which colorway it
 * wears, so the runs carry that rather than the text.
 *
 * `merge[i]` answers for the gap between option `i` and `i + 1`, so a false
 * starts a new run. One option per run means every button stands alone; one
 * run means the whole row is a single block. */
function runsOf(options: string[], merge: boolean[]): number[][] {
  const runs: number[][] = [];
  options.forEach((_option, index) => {
    if (index > 0 && merge[index - 1]) runs[runs.length - 1].push(index);
    else runs.push([index]);
  });
  return runs;
}

/** A row of buttons.
 *
 * Buttons, not toggles: nothing here is "on". The group's value is the option
 * last pressed, which Python reads and acts on -- pressing the same one twice
 * is two presses, not a no-op -- so there is no selected state to draw. Each
 * option wears its own colorway, exactly as if it were an `add_button` of its
 * own; a row that names one role for all of them arrives as that role repeated.
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
        // width of the row they wrap onto another line. Scrolling was the
        // earlier answer, and it hid an option behind an edge with no
        // scrollbar to say so -- a button whose words are cut in half is not a
        // button anyone can read. The gap is the panel's own step, tighter
        // than the stock 8px this component ships with.
        // The stock group overlaps its children by a pixel so joined buttons
        // share an edge. Between RUNS there is no edge to share, and the
        // overlap would eat a pixel of the gap, so it is put back to zero: the
        // step between parted buttons is the panel's own 4px, the same one the
        // toggles use.
        className={cn(
          "w-full min-w-0 flex-wrap gap-1",
          "has-[>[data-slot=button-group]]:gap-1",
          "[&>[data-slot]~[data-slot]]:ml-0",
        )}
        data-leika-button-group
      >
        {runs.map((run) => (
          <ButtonGroup
            key={options[run[0]]}
            className="min-w-fit flex-1 flex-wrap"
          >
            {run.map((option, place) => (
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
                  variant={color[option] === "inverse" ? "default" : "outline"}
                  className="min-w-fit flex-1"
                  disabled={disabled}
                  data-leika-button
                  data-leika-button-color={color[option]}
                  onClick={() => setValue(uuid, options[option])}
                >
                  {options[option]}
                </Button>
              </React.Fragment>
            ))}
          </ButtonGroup>
        ))}
      </ButtonGroup>
    </GuiInputRow>
  );
}
