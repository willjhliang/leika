import * as React from "react";
import { ErrorBoundary } from "react-error-boundary";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiTextMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { MarkdownRenderer } from "./MarkdownRenderer";

/** How tall an editable box is when no height was asked for. Fixed rather than
 * fitted, because it is being typed into: a box that grew with the typing would
 * push the rest of the panel down a line at a time. */
const EDITABLE_ROWS = 3;

/** Text the viewer reads rather than writes. Tinted, because a surface that
 * looks like the panel's other boxes but takes no caret reads as one that is
 * broken -- and tinted rather than disabled-looking, since nothing here is
 * disabled: there was never anything to type into.
 *
 * `bg-muted`, which is what the inactive length of a slider's track wears: the
 * panel already has a tone for "this part is not yours to work", and a second
 * one at some other strength would only be a near-miss of it. At two fifths of
 * it the box was four values off the panel behind it, which is to say invisible. */
const READING = "min-w-0 rounded-lg bg-muted px-2.5 text-sm";

export default function TextInputComponent({
  uuid,
  value,
  props: {
    hint,
    label,
    disabled,
    editable,
    markdown,
    multiline,
    rows,
    _source,
  },
}: GuiTextMessage) {
  const { setValue } = React.useContext(GuiComponentContext)!;

  if (!editable) {
    return (
      <GuiInputRow
        {...{ uuid, hint, label, disabled }}
        // A div takes no caret, so a `<label for>` on it would promise
        // something to focus; and a block beside a label starts at its first
        // line rather than halfway down.
        associateLabel={false}
        alignLabelToFirstRow={multiline}
      >
        <div
          id={uuid}
          className={cn(
            READING,
            multiline
              ? cn(
                  "py-2 leading-snug",
                  // A height was asked for: keep it and scroll the text inside
                  // it. Left out, the box is as tall as what it holds --
                  // nothing is being typed here, so there is no typing for
                  // growth to push around.
                  rows !== null && "overflow-y-auto",
                  // Only the characters carry their own newlines; markdown's
                  // blocks bring their own spacing, and preserving the source's
                  // whitespace as well would open a blank line between each.
                  !markdown && "whitespace-pre-wrap",
                )
              : // One line, high as the panel's other rows, ending in an
                // ellipsis rather than at a cut letter.
                "flex h-6 items-center truncate",
          )}
          style={
            multiline && rows !== null
              ? // In the box's OWN lines: `lh` is its line-height, so the
                // height follows the leading instead of restating it.
                { height: `calc(${rows} * 1lh + 1rem)` }
              : undefined
          }
          data-leika-text-reading
          data-leika-text-markdown={markdown || undefined}
        >
          {markdown ? (
            <ErrorBoundary
              fallback={
                <p className="text-center">Markdown failed to render</p>
              }
            >
              <MarkdownRenderer>{_source}</MarkdownRenderer>
            </ErrorBoundary>
          ) : (
            value
          )}
        </div>
      </GuiInputRow>
    );
  }

  return (
    <GuiInputRow {...{ uuid, hint, label, disabled }}>
      {multiline ? (
        <Textarea
          id={uuid}
          value={value}
          onChange={(event) => setValue(uuid, event.currentTarget.value)}
          disabled={disabled}
          rows={rows ?? EDITABLE_ROWS}
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
