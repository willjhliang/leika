import * as React from "react";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiToggleGroupMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { TOGGLE_CLASSES } from "./toggleStyles";

/** A row of toggles, laid out like a row of buttons and holding its state.
 *
 * One ToggleGroup, never nested: the group is what enforces "one at a time",
 * so runs of merged toggles are drawn by rounding and margins on the items
 * rather than by a group per run the way the buttons do it. Nesting would give
 * each run a choice of its own, which is not what a row of toggles is.
 */
export default function ToggleGroupComponent({
  uuid,
  value,
  props: {
    hint,
    label,
    disabled,
    options,
    color,
    multiple,
    required,
    _merge: merge,
  },
}: GuiToggleGroupMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  return (
    <GuiInputRow
      {...{ uuid, hint, label, disabled }}
      // No `htmlFor`: the row names a set of toggles, not one control.
      associateLabel={false}
    >
      <ToggleGroup
        id={uuid}
        value={value}
        multiple={multiple}
        disabled={disabled}
        onValueChange={(next) => {
          // A required row refuses the press that would empty it, here rather
          // than by correcting the value afterwards: the group is controlled,
          // so declining to report the change leaves the toggle where it was
          // with nothing sent and nothing to undo.
          if (required && next.length === 0) return;
          // Reported in DECLARATION order, not the order they were clicked, so
          // the value reads the same way the row does -- and so two clients
          // that arrived at the same set of toggles report the same tuple.
          setValue(
            uuid,
            options.filter((option) => next.includes(option)),
          );
        }}
        // Unlabelled, the row goes unnamed rather than inventing a name: every
        // toggle reads out its own text.
        aria-label={label ?? undefined}
        // Zero spacing so neighbours can share an edge; the gaps between runs
        // are put back per item below.
        spacing={0}
        variant="outline"
        className="no-scrollbar w-full min-w-0 justify-start overflow-x-auto"
        data-leika-toggle-group
      >
        {options.map((option, index) => {
          const startsRun = index === 0 || !merge[index - 1];
          const endsRun = index === options.length - 1 || !merge[index];
          return (
            <ToggleGroupItem
              key={option}
              value={option}
              className={cn(
                "min-w-fit flex-1",
                TOGGLE_CLASSES[color[index]],
                // A run's ends are rounded and its insides are square, so a
                // run reads as one block however many toggles are in it.
                startsRun ? "rounded-l-lg!" : "rounded-l-none!",
                endsRun ? "rounded-r-lg!" : "rounded-r-none!",
                // Inside a run neighbours overlap by their shared edge; between
                // runs they take the panel's own gap.
                startsRun ? index > 0 && "ml-1!" : "-ml-px",
                // Filled toggles have no border to share, so a joined pair
                // needs a line of its own, drawn in the surface the row sits
                // on. That is what a joined pair of filled BUTTONS shows:
                // those are parted by a pixel of the panel rather than by a
                // rule of their own, and the panel stands opposite the filled
                // colorway in either theme, so the seam reads alike here. A
                // quarter-opacity foreground -- what this drew before -- lands
                // a quarter as far from the fill and all but disappears. A
                // joined pair with an outlined half already has that half's
                // border.
                !startsRun &&
                  color[index] === "inverse" &&
                  color[index - 1] === "inverse" &&
                  "border-l-(--leika-panel-surface)",
              )}
              data-leika-toggle
              data-leika-button-color={color[index]}
            >
              {option}
            </ToggleGroupItem>
          );
        })}
      </ToggleGroup>
    </GuiInputRow>
  );
}
