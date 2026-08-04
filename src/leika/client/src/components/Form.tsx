import { ClipboardPen, SendIcon } from "lucide-react";
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
import { useContainerIsEmpty } from "./useContainerIsEmpty";
import { GuiInputRow } from "./common";
import { POPOUT_WIDTH_CLASS } from "../ControlPanel/controlWidth";

/** A form: values committed together rather than reported as they are typed.
 *
 * Two shapes, by how much there is to ask: several fields go behind a door,
 * one field keeps its row and grows a send button. */
export default function FormComponent(message: GuiFormMessage) {
  return message.props.mini ? (
    <MiniForm {...message} />
  ) : (
    <PopoutForm {...message} />
  );
}

/** A form around one field, drawn as that field's own row.
 *
 * A popout for a single question is a door in front of a doorway, so the field
 * stays where it would have been and the commit joins it: a send button on the
 * end of the row, sized and placed like the undo a color row carries, because
 * it is the same kind of thing -- a small square that acts on the control
 * beside it rather than a row of its own. */
function MiniForm({ uuid }: GuiFormMessage) {
  const guiContext = React.useContext(GuiComponentContext)!;
  return (
    <form
      className="flex min-w-0 items-center gap-1"
      onSubmit={(event) => {
        event.preventDefault();
        guiContext.messageSender(
          { type: "GuiFormSubmitMessage", uuid },
          { coalesce: false },
        );
      }}
    >
      <div className="min-w-0 flex-1">
        <guiContext.GuiContainer containerUuid={uuid} unwrapped />
      </div>
      {/* A real submit button, so it is also what Enter in a single-line text
          input activates -- one control for both ways of sending. */}
      <Button
        type="submit"
        variant="outline"
        size="icon-xs"
        className="shrink-0"
        aria-label="Send"
        title="Send"
        data-leika-form-send
      >
        <SendIcon />
      </Button>
    </form>
  );
}

/** A form of several fields, kept in a popout off a single row.
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
function PopoutForm({ uuid, props: { label } }: GuiFormMessage) {
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
          data-leika-button-color="default"
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
        className={POPOUT_WIDTH_CLASS}
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
          // The actions sit a step further down than the fields sit from each
          // other: they are what to do with the answer rather than another
          // part of it, and the panel's own row gap reads as neither. The
          // server keeps them last (see GuiFormHandle.__exit__), so the last
          // child is who they are.
          className="flex w-full min-w-0 flex-col gap-2 [&>:last-child]:mt-2"
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
