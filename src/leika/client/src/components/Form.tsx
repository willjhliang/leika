import { ClipboardPen } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { ViewerContext } from "../ViewerContext";
import { GuiFormMessage } from "../WebsocketMessages";
import { useContainerIsEmpty } from "./GuiSection";
import { GuiInputRow } from "./common";

/** A form: fields committed together, kept in a popout off a single row.
 *
 * Not the collapsible section it reads like in the tree. A section is a place
 * to keep things, and its contents are the panel's own rows -- live, each one
 * acting the moment it is touched. A form's are none of that: they are one
 * question asked in several parts, and answered only on submit. Opened out
 * among the live rows it looked like more of them, and its submit like one
 * more button in the column.
 *
 * So the panel keeps one row for it -- what it is called, and a way in -- and
 * the parts live in the popout, where they are plainly a thing apart from the
 * controls behind them and a submit is plainly the way out. */
export default function FormComponent({
  uuid,
  props: { label },
}: GuiFormMessage) {
  const viewer = React.useContext(ViewerContext)!;
  const guiContext = React.useContext(GuiComponentContext)!;
  const [open, setOpen] = React.useState(false);
  // Submitting is the way out, and the server says when that happened -- so
  // the popout closes on the press of its own submit, on Enter, and on a
  // `submit_form()` from Python alike, rather than only on the ones the
  // browser can see. Counted rather than flagged: the next submit has to read
  // as a new one. (It also fires once on mount, closing what is already
  // closed.)
  const submitCount = viewer.useGui((state) =>
    state.lastFormSubmit?.uuid === uuid ? state.lastFormSubmit.count : 0,
  );
  React.useEffect(() => setOpen(false), [submitCount]);
  // An empty form has nothing to open. The trigger stays put rather than
  // disappearing: a Python-built panel fills its containers in its own time,
  // and a row that came and went would be worse than one briefly dimmed.
  const isEmpty = useContainerIsEmpty(uuid);

  const trigger = (
    <PopoverTrigger
      render={
        <Button
          id={uuid}
          // The panel's outlined role, as the secondary GUI buttons wear it:
          // the way into a form is not the accent-carrying thing in a row.
          variant="outline"
          className="w-full"
          disabled={isEmpty}
          data-leika-button
          data-leika-button-color="secondary"
          data-leika-form-trigger
        />
      }
    >
      <ClipboardPen data-icon="inline-start" />
      Open form
    </PopoverTrigger>
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      {/* Labelled, the trigger is an ordinary control in the right-hand
          column. Unlabelled it takes the row, the same rule every button in
          the panel follows. */}
      {label === null ? (
        trigger
      ) : (
        <GuiInputRow uuid={uuid} label={label} associateLabel={false}>
          {trigger}
        </GuiInputRow>
      )}
      <PopoverContent
        align="end"
        className="w-[min(20rem,calc(100vw-1rem))]"
        data-leika-form-popover
      >
        {/* The row already says the name out loud; this is for the popup's own
            accessible name, which the row is not attached to. */}
        <PopoverHeader className="sr-only">
          <PopoverTitle>{label ?? "Form"}</PopoverTitle>
          <PopoverDescription>
            Fill in the fields, then submit them together.
          </PopoverDescription>
        </PopoverHeader>
        <form
          className="flex w-full min-w-0 flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            guiContext.messageSender(
              { type: "GuiFormSubmitMessage", uuid },
              { coalesce: false },
            );
          }}
        >
          {/* What makes Enter in a single-line text input submit the form:
              implicit submission needs a submit button to activate. */}
          <button type="submit" hidden tabIndex={-1} />
          <guiContext.GuiContainer containerUuid={uuid} unwrapped />
        </form>
      </PopoverContent>
    </Popover>
  );
}
