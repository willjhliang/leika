import * as React from "react";
import { ErrorBoundary } from "react-error-boundary";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useGuiComponent } from "../ControlPanel/GuiComponentContext";
import { GuiTextMessage } from "../WebsocketMessages";
import { GuiInputRow } from "./common";
import { MarkdownRenderer } from "./MarkdownRenderer";

/** How tall an editable box is when no height was asked for. Fixed rather than
 * fitted: a box that grew with the typing would push the panel down a line at
 * a time. */
const EDITABLE_ROWS = 3;

/** Text the viewer reads rather than writes. `bg-muted` is the tone the panel
 * already uses for a part that is not the viewer's to work -- the inactive
 * length of a slider's track -- as opposed to the disabled tone: nothing here
 * is disabled, there was never anything to type into.
 *
 * `text-sm` is also the base a markdown document is set from here: the panel's
 * own size, so prose lines up with the inputs above and below it. A preview
 * dialog, which has no inputs to line up with, sets a larger one. */
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
  const { setValue } = useGuiComponent();

  if (!editable) {
    // A document is blocks -- headings, lists, code -- and takes as many lines
    // as it has. `multiline` says whether a plain STRING runs to more than one
    // line, which is not a question a markdown document is asked: rendered
    // into the one-line box, its ink was sliced through the middle and the
    // rest of it thrown away.
    const stacked = multiline || markdown;
    return (
      <GuiInputRow
        {...{ uuid, hint, label, disabled }}
        // A div takes no caret, so a `<label for>` would promise something to
        // focus; and a block beside a label aligns to its first line.
        associateLabel={false}
        alignLabelToFirstRow={stacked}
      >
        <div
          id={uuid}
          className={cn(
            READING,
            stacked
              ? cn(
                  "py-2 leading-snug",
                  // A path or a URL is one long "word" with nowhere to break:
                  // left alone it runs out of the box and takes a scrollbar
                  // with it, rather than wrapping like the prose around it.
                  // Code keeps its own scroll -- `pre` forbids wrapping, so
                  // this cannot reach inside one.
                  "break-words",
                  // An asked-for height scrolls; left out, the box fits its text.
                  rows !== null && "overflow-y-auto",
                  // Markdown's blocks bring their own spacing; keeping the
                  // source's newlines too would blank-line between each.
                  !markdown && "whitespace-pre-wrap",
                )
              : // The value inside carries the truncation; this box is here to
                // hold it on one 24px line, centred against the row's label.
                "flex h-6 items-center",
          )}
          style={
            stacked && rows !== null
              ? // `lh` is the box's own line-height, so the height follows
                // the leading instead of restating it.
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
          ) : stacked ? (
            value
          ) : (
            // The one-line box centres its text by being a flex box, and
            // `text-overflow` does nothing on one -- so the ellipsis this row
            // promises has to be asked for on a box inside it. See
            // `ButtonLabel`, which is the same fix on a button's face.
            <span className="min-w-0 truncate">{value}</span>
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
          // The stock textarea sizes itself to its content, which overrides
          // `rows`; fixed, the field is the asked-for height and scrolls.
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
