import * as React from "react";

import { Toggle } from "@/components/ui/toggle";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiToggleMessage } from "../WebsocketMessages";
import { GuiInputRow, HintTooltip } from "./common";
import { TOGGLE_CLASSES } from "./toggleStyles";

/** One toggle: a button that stays pressed.
 *
 * Laid out exactly like a single button -- the whole row when unlabelled, the
 * control column beside a label otherwise -- since it is the same object with
 * a state that sticks.
 */
export default function ToggleComponent({
  uuid,
  value,
  props: { hint, label, text, disabled, color, _icon_html: iconHtml },
}: GuiToggleMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  const toggle = (
    <Toggle
      id={uuid}
      pressed={value}
      disabled={disabled}
      onPressedChange={(pressed) => setValue(uuid, pressed)}
      className={cn("w-full", TOGGLE_CLASSES[color])}
      data-leika-toggle
      data-leika-button-color={color}
    >
      {iconHtml === null ? null : (
        <span
          data-icon="inline-start"
          className="size-3.5 [&_svg]:size-full"
          dangerouslySetInnerHTML={{ __html: iconHtml }}
        />
      )}
      {text}
    </Toggle>
  );
  // The same two forms a button takes, for the same reasons: see Button.tsx.
  if (label !== null) {
    return (
      <GuiInputRow
        {...{ uuid, hint, label }}
        disabled={disabled ?? false}
        associateLabel={false}
      >
        {toggle}
      </GuiInputRow>
    );
  }
  if (hint === null) return toggle;
  return (
    <HintTooltip hint={hint}>
      <span className="block w-full">{toggle}</span>
    </HintTooltip>
  );
}
