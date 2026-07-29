import * as React from "react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiTextMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

export default function TextInputComponent({
  uuid,
  value,
  props: { hint, label, disabled, multiline, rows },
}: GuiTextMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      {multiline ? (
        <Textarea
          id={uuid}
          value={value}
          onChange={(event) => setValue(uuid, event.currentTarget.value)}
          disabled={disabled}
          rows={rows}
          // `rows` only means anything to a box that is not sizing itself:
          // the stock textarea grows with its content from a floor of its
          // own, which overrode the attribute at every value and left a
          // pasted page of text pushing the rest of the panel off the screen.
          // Fixed, the field is the height it was asked for and scrolls.
          className="field-sizing-fixed min-h-0"
        />
      ) : (
        <Input
          id={uuid}
          value={value}
          onChange={(event) => setValue(uuid, event.currentTarget.value)}
          disabled={disabled}
        />
      )}
    </GuiInputRow>
  );
}
