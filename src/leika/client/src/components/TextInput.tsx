import * as React from "react";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiTextMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";

export default function TextInputComponent({
  uuid,
  value,
  props: { hint, label, disabled, visible, multiline },
}: GuiTextMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;
  if (!visible) return null;
  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      {multiline ? (
        <Textarea
          id={uuid}
          value={value}
          onChange={(event) => setValue(uuid, event.currentTarget.value)}
          disabled={disabled}
          rows={2}
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
