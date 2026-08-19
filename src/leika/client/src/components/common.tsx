import * as React from "react";

import { Field, FieldContent, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ButtonGroup } from "@/components/ui/button-group";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { HoverScrollText } from "./HoverScrollText";
import { guiLabelClassName, guiRowGridClassName } from "./guiLabelStyles";
import { finiteNumberOrNull } from "./numberInputUtils";

/** Keep the tooltip tree mounted while it is disabled so pointer gestures on
 * its child are never interrupted by a wrapper remount. */
export function HintTooltip({
  hint,
  disabled = false,
  children,
}: {
  hint?: string | null;
  disabled?: boolean;
  children: React.ReactElement;
}) {
  if (hint === undefined || hint === null) return children;
  return (
    <Tooltip disabled={disabled}>
      <TooltipTrigger render={children} />
      <TooltipContent className="max-w-60 whitespace-normal">
        {hint}
      </TooltipContent>
    </Tooltip>
  );
}

export function GuiInputRow({
  uuid,
  label,
  hint,
  hintDisabled,
  disabled = false,
  associateLabel = true,
  alignLabelToFirstRow = false,
  children,
}: {
  uuid: string;
  children: React.ReactNode;
  /** Null is the protocol's way of saying "no label", and means the same as
   * omitting it: the control fills the row instead of taking the right-hand
   * column beside a label. */
  label?: string | null;
  hint?: string | null;
  hintDisabled?: boolean;
  disabled?: boolean;
  /** Whether the label names the control through `htmlFor`. Off for a button:
   * a `<label for>` would both take over its accessible name -- so it would
   * announce as the row's label instead of the word on its face -- and fire it
   * on a click, since a label forwards clicks to what it labels. */
  associateLabel?: boolean;
  /** For a control that is a STACK rather than one thing: put the label beside
   * its first row instead of halfway down the pile. A column of one thing
   * centres, which is what every other row wants. */
  alignLabelToFirstRow?: boolean;
}) {
  const fieldState = {
    "data-disabled": disabled || undefined,
  };

  if (label === undefined || label === null) {
    const field = <Field {...fieldState}>{children}</Field>;
    return hint === undefined || hint === null ? (
      field
    ) : (
      <HintTooltip hint={hint} disabled={hintDisabled}>
        {field}
      </HintTooltip>
    );
  }

  const content = (
    <FieldContent className="gui-row-controls min-w-0">{children}</FieldContent>
  );
  return (
    <Field
      orientation="horizontal"
      // A GUI row is a fixed label column next to its controls, both centered.
      // The `has-` half restates the alignment because Field's horizontal
      // variant top-aligns any row that holds a FieldContent, which is the
      // stacked-description layout rather than this one.
      className={cn(
        guiRowGridClassName,
        "has-[>[data-slot=field-content]]:items-center",
        alignLabelToFirstRow &&
          "items-start has-[>[data-slot=field-content]]:items-start",
      )}
      {...fieldState}
      data-leika-gui-row
    >
      <FieldLabel
        htmlFor={associateLabel ? uuid : undefined}
        className={cn(
          "w-full min-w-0",
          // Top-aligned, the label still centres against the row it names --
          // that row being the panel's own 24px.
          alignLabelToFirstRow && "flex min-h-6 items-center",
          guiLabelClassName,
        )}
        title={label}
      >
        {/* The ellipsis has to be asked for on a box of its own. `FieldLabel`
            is a flex container, and `text-overflow` does nothing on one: the
            words are laid out in an anonymous item it cannot style, so a long
            label was cut through the middle of a letter with no sign that
            anything was missing. As a flex ITEM this span is blockified, which
            is the box `truncate` needs. */}
        <HoverScrollText className="w-full">{label}</HoverScrollText>
      </FieldLabel>
      {hint === undefined || hint === null ? (
        content
      ) : (
        <HintTooltip hint={hint} disabled={hintDisabled}>
          {content}
        </HintTooltip>
      )}
    </Field>
  );
}

/** The words on a button's face, in a box that can give way.
 *
 * A button is `inline-flex` and `whitespace-nowrap`, so bare text inside one
 * is an anonymous flex item: it cannot be shrunk and it cannot be styled, and
 * a label longer than the button paints straight out of both sides of it and
 * over the panel. Wrapped, the label is an item the button can shrink, and it
 * ends in an ellipsis at the border instead of ignoring it. */
export function ButtonLabel({ children }: { children: React.ReactNode }) {
  return <HoverScrollText>{children}</HoverScrollText>;
}

/** Server-rendered icon markup, sized to sit inline before a control's text. */
export function IconHtml({ html }: { html: string }) {
  return (
    <span
      data-icon="inline-start"
      className="size-3.5 [&_svg]:size-full"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

/** The two forms a button-shaped control takes. Labelled, it is an ordinary
 * control in the right-hand column, and the row owns the label and the hint.
 * Unlabelled -- the default -- it takes the whole width instead: the text on
 * its face is what a label would have said, so a column beside it would be one
 * fixed width of nothing. */
export function GuiButtonRow({
  uuid,
  label,
  hint,
  disabled = false,
  children,
}: {
  uuid: string;
  label: string | null;
  hint: string | null;
  disabled?: boolean;
  children: React.ReactElement;
}) {
  if (label !== null) {
    return (
      <GuiInputRow {...{ uuid, hint, label, disabled }} associateLabel={false}>
        {children}
      </GuiInputRow>
    );
  }
  if (hint === null) return children;
  return (
    <HintTooltip hint={hint}>
      <span className="block w-full">{children}</span>
    </HintTooltip>
  );
}

/** A stock shadcn Input with local draft state for incomplete numeric text. */
export function NumericInput({
  value,
  onValueChange,
  precision,
  onBlur,
  ...props
}: Omit<React.ComponentProps<typeof Input>, "value" | "onChange" | "type"> & {
  value: number;
  onValueChange: (value: number) => void;
  precision?: number;
}) {
  const [draft, setDraft] = React.useState(() => String(value));

  React.useEffect(() => {
    setDraft((current) => {
      const parsed = finiteNumberOrNull(current);
      return parsed === null || !Object.is(parsed, value)
        ? String(value)
        : current;
    });
  }, [value]);

  return (
    <Input
      {...props}
      type="number"
      value={draft}
      onChange={(event) => {
        const nextDraft = event.currentTarget.value;
        setDraft(nextDraft);
        const parsed = finiteNumberOrNull(nextDraft);
        if (parsed === null) return;
        const next =
          precision === undefined
            ? parsed
            : Number(parsed.toFixed(Math.max(0, precision)));
        if (Number.isFinite(next)) onValueChange(next);
      }}
      onBlur={(event) => {
        // Whatever the draft held -- unparseable text or extra precision the
        // commit rounded away -- the field shows the committed value again.
        setDraft(String(value));
        onBlur?.(event);
      }}
    />
  );
}

export function VectorInput(props: {
  uuid: string;
  n: 2 | 3;
  value: readonly number[];
  min: readonly number[] | null;
  max: readonly number[] | null;
  step: number;
  precision: number;
  onChange: (value: number[]) => void;
  disabled: boolean;
}) {
  return (
    <ButtonGroup className="w-full min-w-0">
      {[...Array(props.n).keys()].map((index) => (
        <NumericInput
          id={index === 0 ? props.uuid : undefined}
          aria-label={`Component ${index + 1}`}
          key={index}
          value={props.value[index]}
          onValueChange={(next) => {
            const updated = [...props.value];
            updated[index] = next;
            props.onChange(updated);
          }}
          className="min-w-0 flex-1 text-right"
          precision={props.precision}
          step={props.step}
          min={props.min === null ? undefined : props.min[index]}
          max={props.max === null ? undefined : props.max[index]}
          disabled={props.disabled}
        />
      ))}
    </ButtonGroup>
  );
}
