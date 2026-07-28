import * as React from "react";

import { Button } from "@/components/ui/button";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiButtonGroupMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

/** A row of buttons that share a row and a colorway.
 *
 * Buttons, not toggles: nothing here is "on". The group's value is the option
 * last pressed, which Python reads and acts on -- pressing the same one twice
 * is two presses, not a no-op -- so there is no selected state to draw, and
 * the colorway applies to every option alike, exactly as it would if each of
 * these were an `add_button` of its own.
 *
 * A gap rather than joined segments, because primary means all of them are
 * filled: butted together they would read as one accent-colored bar with words
 * at intervals rather than as the several buttons they are.
 */
export default function ButtonGroupComponent({
  uuid,
  props: { hint, label, disabled, options, color },
}: GuiButtonGroupMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  return (
    <GuiInputRow
      {...{ uuid, hint, label, disabled }}
      // No `htmlFor`: the row names a set of buttons, not one control, and a
      // label tied to a button would fire it when clicked.
      associateLabel={false}
    >
      <div
        id={uuid}
        role="group"
        // Unlabelled, the group goes unnamed rather than inventing a name:
        // every option is a button that reads out its own text.
        aria-label={label ?? undefined}
        // Options keep their own width and share what is left over; past the
        // width of the row they scroll rather than wrap, so the row stays one
        // row however many options it is given.
        className="no-scrollbar flex w-full min-w-0 items-center gap-1 overflow-x-auto"
        data-leika-button-group
        data-leika-button-color={color}
      >
        {options.map((option) => (
          <Button
            key={option}
            variant={color === "secondary" ? "outline" : "default"}
            className="min-w-fit flex-1"
            disabled={disabled}
            data-leika-button
            onClick={() => setValue(uuid, option)}
          >
            {option}
          </Button>
        ))}
      </div>
    </GuiInputRow>
  );
}
