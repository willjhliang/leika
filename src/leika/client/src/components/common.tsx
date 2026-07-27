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
import { guiLabelClassName } from "./guiLabelStyles";
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
  invalid = false,
  children,
}: {
  uuid: string;
  children: React.ReactNode;
  label?: string;
  hint?: string | null;
  hintDisabled?: boolean;
  disabled?: boolean;
  invalid?: boolean;
}) {
  const fieldState = {
    "data-disabled": disabled || undefined,
    "data-invalid": invalid || undefined,
  };

  if (label === undefined) {
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
      className="grid min-h-6 grid-cols-[6rem_minmax(0,1fr)] items-center has-[>[data-slot=field-content]]:items-center"
      {...fieldState}
      data-leika-gui-row
    >
      <FieldLabel
        htmlFor={uuid}
        className={cn("w-full min-w-0 truncate", guiLabelClassName)}
        title={label}
      >
        {label}
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
        const parsed = finiteNumberOrNull(event.currentTarget.value);
        if (parsed === null) setDraft(String(value));
        onBlur?.(event);
      }}
    />
  );
}

export function VectorInput(
  props:
    | {
        uuid: string;
        n: 2;
        value: [number, number];
        min: [number, number] | null;
        max: [number, number] | null;
        step: number;
        precision: number;
        onChange: (value: number[]) => void;
        disabled: boolean;
      }
    | {
        uuid: string;
        n: 3;
        value: [number, number, number];
        min: [number, number, number] | null;
        max: [number, number, number] | null;
        step: number;
        precision: number;
        onChange: (value: number[]) => void;
        disabled: boolean;
      },
) {
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
