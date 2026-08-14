import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiToggleGroupMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { GroupRun } from "./GroupRun";
import {
  GROUP_RUN_ITEM_CLASS,
  runCornerClasses,
  runSeamClasses,
  runsOf,
} from "./groupRuns";
import { TOGGLE_CLASSES } from "./toggleStyles";

/** A row of toggles, laid out like a row of buttons and holding its state.
 *
 * One ToggleGroup, never nested: the group is what enforces "one at a time",
 * and a second one per run would give each run a choice of its own, which is
 * not what a row of toggles is. The runs are plain boxes inside it, holding no
 * state and drawing nothing: they are what a wrapped run's corners are measured
 * against.
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
  const { setValue } = useGuiComponent();
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
        // Zero spacing so neighbours can share an edge; the step between runs
        // is the gap below, the panel's own 4px.
        spacing={0}
        variant="outline"
        className="w-full min-w-0 flex-wrap justify-start gap-1"
        data-leika-toggle-group
      >
        {/* A box per run, as the buttons do it. The group is still one group --
            the toggles inside these are all still its items, so "one at a time"
            is unchanged -- and the box draws nothing; it is what the corners of
            a wrapped run are measured against. */}
        {runsOf(options, merge).map((run) => (
          <GroupRun key={options[run[0]]} count={run.length}>
            {(placements) =>
              run.map((index, place) => (
                <ToggleGroupItem
                  key={options[index]}
                  value={options[index]}
                  className={cn(
                    GROUP_RUN_ITEM_CLASS,
                    TOGGLE_CLASSES[color[index]],
                    runCornerClasses(placements[place]),
                    // Along a line neighbours share their edge -- but only along
                    // one: a toggle that OPENS a line has nothing to its left,
                    // and pulling left would hang it a pixel off the run.
                    // `-mt-px` in the shared class joins the lines.
                    runSeamClasses(placements[place]),
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
                    place > 0 &&
                      color[index] === "inverse" &&
                      color[run[place - 1]] === "inverse" &&
                      "border-l-(--leika-panel-surface)",
                  )}
                  data-leika-toggle
                  data-leika-run-item
                  data-leika-joined={!placements[place].startsLine || undefined}
                  data-leika-button-color={color[index]}
                >
                  {options[index]}
                </ToggleGroupItem>
              ))
            }
          </GroupRun>
        ))}
      </ToggleGroup>
    </GuiInputRow>
  );
}
