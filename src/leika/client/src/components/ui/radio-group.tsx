import { Radio as RadioPrimitive } from "@base-ui/react/radio";
import { RadioGroup as RadioGroupPrimitive } from "@base-ui/react/radio-group";

import { cn } from "@/lib/utils";

const RADIO_ITEM_CLASS_NAME =
  "relative flex aspect-square size-4 shrink-0 rounded-full border border-input outline-none group-has-[:focus-visible]/field-label:ring-0 group-has-[:focus-visible]/field-label:not-data-checked:border-input after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 aria-invalid:aria-checked:border-primary dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground group-has-[:focus-visible]/field-label:data-checked:border-primary dark:data-checked:bg-primary";

function RadioGroup({ className, ...props }: RadioGroupPrimitive.Props) {
  return (
    <RadioGroupPrimitive
      data-slot="radio-group"
      className={cn("grid w-full gap-2", className)}
      {...props}
    />
  );
}

function RadioGroupItem({ className, ...props }: RadioPrimitive.Root.Props) {
  return (
    <RadioPrimitive.Root
      data-slot="radio-group-item"
      className={cn(
        "group/radio-group-item peer disabled:cursor-not-allowed disabled:opacity-50",
        RADIO_ITEM_CLASS_NAME,
        className,
      )}
      {...props}
    >
      <RadioPrimitive.Indicator
        data-slot="radio-group-indicator"
        className="flex size-4 items-center justify-center"
      >
        <span className="absolute top-1/2 left-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-foreground" />
      </RadioPrimitive.Indicator>
    </RadioPrimitive.Root>
  );
}

/** A native radio wearing the same control as the composite Base UI item.
 *
 * This exists for rows that also contain an editable text field. Base UI's
 * RadioGroup is a roving-focus composite: any native input below its root is
 * deliberately treated as part of that composite, so an arrow at the edge of
 * a text field moves focus to a radio. A native radio group (same `name`) keeps
 * the platform's radio semantics and arrow navigation without taking ownership
 * of neighbouring editors.
 */
function NativeRadioGroupItem({
  className,
  checked = false,
  disabled = false,
  ...props
}: Omit<React.ComponentPropsWithoutRef<"input">, "type">) {
  return (
    <label
      data-slot="radio-group-item"
      data-checked={checked ? "" : undefined}
      data-disabled={disabled ? "" : undefined}
      className={cn(
        RADIO_ITEM_CLASS_NAME,
        "has-[:focus-visible]:border-ring has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/50 data-disabled:cursor-not-allowed data-disabled:opacity-50",
        className,
      )}
    >
      <input
        type="radio"
        checked={checked}
        disabled={disabled}
        className="absolute inset-0 z-10 m-0 size-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
        {...props}
      />
      {checked ? (
        <span
          aria-hidden="true"
          data-slot="radio-group-indicator"
          className="flex size-4 items-center justify-center"
        >
          <span className="absolute top-1/2 left-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-foreground" />
        </span>
      ) : null}
    </label>
  );
}

export { NativeRadioGroupItem, RadioGroup, RadioGroupItem };
