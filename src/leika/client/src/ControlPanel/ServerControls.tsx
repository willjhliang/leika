import { PlugIcon } from "lucide-react";
import React from "react";

import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "../components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "../components/ui/input-group";

import { ViewerContext } from "../ViewerContext";

/** Connection settings shown behind the control-panel settings toggle. */
export default function ServerControls() {
  const viewer = React.useContext(ViewerContext)!;
  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor="leika-server-url">Server URL</FieldLabel>
        <InputGroup>
          <InputGroupAddon>
            <PlugIcon />
          </InputGroupAddon>
          <InputGroupInput
            id="leika-server-url"
            defaultValue={viewer.useGui((state) => state.server)}
            onBlur={(event) =>
              viewer.useGui.set({ server: event.currentTarget.value })
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
            }}
          />
        </InputGroup>
        <FieldDescription>
          Leika reconnects automatically when this address changes.
        </FieldDescription>
      </Field>
    </FieldGroup>
  );
}
