import * as React from "react";

import { Toggle } from "@/components/ui/toggle";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiToggleMessage } from "../WebsocketMessages";
import { ButtonLabel, GuiButtonRow, IconHtml } from "./common";
import { TOGGLE_CLASSES } from "./toggleStyles";

/** One toggle: a button that stays pressed, laid out exactly like a button. */
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
      {iconHtml === null ? null : <IconHtml html={iconHtml} />}
      <ButtonLabel>{text}</ButtonLabel>
    </Toggle>
  );
  return (
    <GuiButtonRow {...{ uuid, label, hint, disabled }}>{toggle}</GuiButtonRow>
  );
}
