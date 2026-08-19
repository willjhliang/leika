import { PipetteIcon, RotateCcwIcon } from "lucide-react";
import * as React from "react";

import {
  colorDisplayString,
  colorFromHex,
  colorFromRgb,
  colorValueToHex,
  colorWithOpacity,
  hsvToRgb,
  hslToRgb,
  parseToRgba,
  rgbEqual,
  rgbToHsl,
  rgbToHsv,
  type HsvColor,
  type RgbTuple,
  type RgbaTuple,
} from "./colorUtils";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { HoverScrollText } from "./HoverScrollText";
import { POPOUT_WIDTH_CLASS } from "../ControlPanel/controlWidth";
import {
  type ColorFormat,
  useColorFormatPreference,
} from "./colorFormatPreference";

const FORMATS: ColorFormat[] = ["hex", "rgb", "css", "hsl"];
const CHECKERBOARD =
  'url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAMUlEQVQ4T2NkYGAQYcAP3uCTZhw1gGGYhAGBZIA/nYDCgBDAm9BGDWAAJyRCgLaBCAAgXwixzAS0pgAAAABJRU5ErkJggg==") left center';
// Matches a stock slider thumb's outline: 1px in `--input`. The block pointer
// is a bare span, so it spells the border out; the slider thumbs already carry
// it from the Slider base and only restate it here for the same reason.
const COLOR_POINTER_CLASS =
  "size-4 rounded-full border border-input shadow-[0_0_0_1px_var(--background)]";
// The footer packs the eyedropper, the format select, and the output fields
// onto one popover line, so those controls run a step below stock form sizing.
const FOOTER_CONTROL_CLASS = "h-6 text-xs font-normal leading-none";

type EyeDropperConstructor = new () => {
  open: () => Promise<{ sRGBHex: string }>;
};

function PickerSlider({
  value,
  max,
  label,
  disabled,
  trackClassName,
  trackStyle,
  thumbColor,
  onValueChange,
  testId,
}: {
  value: number;
  max: number;
  label: string;
  disabled: boolean;
  trackClassName?: string;
  trackStyle?: React.CSSProperties;
  thumbColor: string;
  onValueChange: (value: number) => void;
  testId: string;
}) {
  const getThumbAriaLabel = React.useCallback(() => label, [label]);
  return (
    <Slider
      value={[value]}
      min={0}
      max={max}
      step={1}
      disabled={disabled}
      className="relative h-4 w-full"
      getThumbAriaLabel={getThumbAriaLabel}
      showIndicator={false}
      trackClassName={cn("data-horizontal:h-3", trackClassName)}
      trackStyle={trackStyle}
      thumbClassName={COLOR_POINTER_CLASS}
      thumbStyle={{ backgroundColor: thumbColor }}
      onValueChange={(next) => {
        const scalar = Array.isArray(next) ? next[0] : next;
        if (scalar !== undefined) onValueChange(scalar);
      }}
      data-leika-color-slider={testId}
    />
  );
}

function OutputInput({
  value,
  label,
  className,
  disabled,
  onValueChange,
}: {
  value: string | number;
  label: string;
  className?: string;
  disabled: boolean;
  onValueChange: (value: string) => boolean;
}) {
  const displayValue = String(value);
  const [draft, setDraft] = React.useState(displayValue);
  const [editing, setEditing] = React.useState(false);
  const [invalid, setInvalid] = React.useState(false);

  React.useEffect(() => {
    if (!editing) {
      setDraft(displayValue);
      setInvalid(false);
    }
  }, [displayValue, editing]);

  return (
    <Input
      value={draft}
      disabled={disabled}
      aria-label={label}
      aria-invalid={invalid || undefined}
      // Corner rounding is left to the enclosing ButtonGroup, which knows
      // which field is first and last.
      className={cn(FOOTER_CONTROL_CLASS, "min-w-0 px-2 py-0", className)}
      onFocus={() => setEditing(true)}
      onChange={(event) => {
        const next = event.currentTarget.value;
        setDraft(next);
        setInvalid(!onValueChange(next));
      }}
      onBlur={() => {
        setEditing(false);
        setDraft(displayValue);
        setInvalid(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          event.currentTarget.blur();
        } else if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          setDraft(displayValue);
          setInvalid(false);
          event.currentTarget.blur();
        }
      }}
      data-leika-color-output
    />
  );
}

function ColorPicker({
  value,
  format,
  disabled = false,
  selectionRef,
  className,
  onValueChange,
}: {
  value: string;
  format: "rgb" | "rgba";
  disabled?: boolean;
  selectionRef?: React.MutableRefObject<HTMLDivElement | null>;
  className?: string;
  onValueChange: (value: string) => void;
}) {
  const rgba = React.useMemo<RgbaTuple>(
    () => parseToRgba(value) ?? [0, 0, 0, 255],
    [value],
  );
  const rgb = React.useMemo(() => rgba.slice(0, 3) as RgbTuple, [rgba]);
  const alpha = (rgba[3] / 255) * 100;
  const [draftHsv, setDraftHsv] = React.useState<HsvColor>(() => rgbToHsv(rgb));
  // Where the hue and saturation controls sit cannot be recovered from the
  // color they produced, so the picker remembers them rather than deriving
  // them fresh each render:
  //
  //   - every hue maps to the same greyscale RGB once saturation is 0, and to
  //     black once brightness is 0, so a derived hue snaps back to 0 and the
  //     slider looks dead until something else adds color;
  //   - hue 360 and hue 0 are the same red, so dragging to the far right
  //     derived 0 and threw the thumb to the far left.
  //
  // The draft is only overruled when the incoming color is one it does not
  // produce -- an edit from the output fields, the eyedropper, or the server.
  const hsv = rgbEqual(hsvToRgb(draftHsv), rgb) ? draftHsv : rgbToHsv(rgb);
  const [outputFormat, setOutputFormat] = useColorFormatPreference();
  const [dragging, setDragging] = React.useState(false);
  const selectionElementRef = React.useRef<HTMLDivElement | null>(null);

  const setSelectionRef = React.useCallback(
    (element: HTMLDivElement | null) => {
      selectionElementRef.current = element;
      if (selectionRef) selectionRef.current = element;
    },
    [selectionRef],
  );

  const updateRgb = React.useCallback(
    (next: HsvColor) => {
      setDraftHsv(next);
      onValueChange(colorFromRgb(hsvToRgb(next), format, value));
    },
    [format, onValueChange, value],
  );

  const updateSelection = React.useCallback(
    (clientX: number, clientY: number) => {
      const element = selectionElementRef.current;
      if (!element || disabled) return;
      const bounds = element.getBoundingClientRect();
      const saturation =
        100 * Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width));
      const brightness =
        100 *
        (1 - Math.max(0, Math.min(1, (clientY - bounds.top) / bounds.height)));
      updateRgb({ h: hsv.h, s: saturation, v: brightness });
    },
    [disabled, hsv.h, updateRgb],
  );

  const eyedropper =
    typeof window === "undefined"
      ? undefined
      : (
          window as typeof window & {
            EyeDropper?: EyeDropperConstructor;
          }
        ).EyeDropper;

  const pickFromScreen = React.useCallback(async () => {
    if (disabled || !eyedropper) return;
    try {
      const result = await new eyedropper().open();
      const picked = parseToRgba(result.sRGBHex);
      if (picked) {
        onValueChange(
          colorFromRgb(picked.slice(0, 3) as RgbTuple, format, value),
        );
      }
    } catch {
      // Closing the native eyedropper is expected and requires no UI error.
    }
  }, [disabled, eyedropper, format, onValueChange, value]);

  const output = React.useMemo(() => {
    const roundedRgb = rgb.map(Math.round) as RgbTuple;
    if (outputFormat === "hex") {
      return [colorValueToHex(value).toUpperCase()];
    }
    if (outputFormat === "rgb") {
      return roundedRgb.map(String);
    }
    if (outputFormat === "css") {
      return [
        format === "rgba"
          ? `rgba(${roundedRgb.join(", ")}, ${(rgba[3] / 255).toFixed(2)})`
          : `rgb(${roundedRgb.join(", ")})`,
      ];
    }
    return rgbToHsl(roundedRgb).map((channel) => String(Math.round(channel)));
  }, [format, outputFormat, rgb, rgba, value]);
  const showOpacityOutput = format === "rgba" && outputFormat !== "css";

  const updateOutput = React.useCallback(
    (index: number, draft: string): boolean => {
      const trimmed = draft.trim();
      if (trimmed === "") return false;

      if (outputFormat === "hex") {
        if (!/^#(?:[\da-f]{3}|[\da-f]{6})$/i.test(trimmed)) return false;
        const parsed = parseToRgba(trimmed);
        if (!parsed) return false;
        onValueChange(
          colorFromRgb(parsed.slice(0, 3) as RgbTuple, format, value),
        );
        return true;
      }

      if (outputFormat === "css") {
        if (!/^rgba?\(/i.test(trimmed)) return false;
        const parsed = parseToRgba(trimmed);
        if (!parsed) return false;
        const channels = parsed.slice(0, 3) as RgbTuple;
        onValueChange(
          format === "rgba"
            ? `rgba(${channels.join(", ")}, ${(parsed[3] / 255).toFixed(4)})`
            : colorFromRgb(channels, format, value),
        );
        return true;
      }

      const channel = Number(trimmed);
      if (!Number.isFinite(channel)) return false;
      if (outputFormat === "rgb") {
        if (channel < 0 || channel > 255) return false;
        const channels = [...rgb] as RgbTuple;
        channels[index] = channel;
        onValueChange(colorFromRgb(channels, format, value));
        return true;
      }

      const max = index === 0 ? 360 : 100;
      if (channel < 0 || channel > max) return false;
      const channels = rgbToHsl(rgb).map(Math.round) as [
        number,
        number,
        number,
      ];
      channels[index] = channel;
      onValueChange(colorFromRgb(hslToRgb(channels), format, value));
      return true;
    },
    [format, onValueChange, outputFormat, rgb, value],
  );

  const updateOpacityOutput = React.useCallback(
    (draft: string): boolean => {
      const opacity = Number(draft.trim());
      if (draft.trim() === "" || !Number.isFinite(opacity)) return false;
      if (opacity < 0 || opacity > 100) return false;
      onValueChange(colorWithOpacity(value, opacity / 100));
      return true;
    },
    [onValueChange, value],
  );

  return (
    <div
      className={cn("flex w-full flex-col gap-4", className)}
      data-slot="color-picker"
      data-leika-color-picker
    >
      <div
        ref={setSelectionRef}
        role="group"
        tabIndex={disabled ? -1 : 0}
        aria-label="Color saturation and brightness"
        aria-disabled={disabled}
        className="relative h-40 w-full cursor-crosshair rounded-lg border border-input transition-colors outline-none focus-visible:border-ring"
        // Longhands rather than the `background` shorthand, which would reset
        // the origin and repeat below it.
        //
        // Both matter here. A gradient is sized to the origin box but painted
        // across the clip box, which defaults to padding and border
        // respectively -- so the default leaves each gradient one pixel short
        // of the area it is painted into, and the default `repeat` fills that
        // last pixel with the START of the next tile: opaque white down the
        // right edge, and the transparent end of the black ramp along the
        // bottom. Sizing to the border box removes the shortfall, and
        // `no-repeat` means rounding at fractional sizes or scale factors
        // cannot bring the seam back.
        //
        // The border box is also the one the pointer reads (`updateSelection`
        // measures `getBoundingClientRect`), so this is the box that agrees
        // with what a click at the far edge resolves to.
        style={{
          backgroundImage: `linear-gradient(0deg, rgba(0,0,0,1), rgba(0,0,0,0)),
            linear-gradient(90deg, rgba(255,255,255,1), rgba(255,255,255,0))`,
          backgroundColor: `hsl(${hsv.h}, 100%, 50%)`,
          backgroundOrigin: "border-box",
          backgroundRepeat: "no-repeat",
        }}
        onKeyDown={(event) => {
          const amount = event.shiftKey ? 10 : 1;
          let next = hsv;
          if (event.key === "ArrowLeft") {
            next = { ...hsv, s: Math.max(0, hsv.s - amount) };
          } else if (event.key === "ArrowRight") {
            next = { ...hsv, s: Math.min(100, hsv.s + amount) };
          } else if (event.key === "ArrowDown") {
            next = { ...hsv, v: Math.max(0, hsv.v - amount) };
          } else if (event.key === "ArrowUp") {
            next = { ...hsv, v: Math.min(100, hsv.v + amount) };
          } else {
            return;
          }
          event.preventDefault();
          updateRgb(next);
        }}
        onPointerDown={(event) => {
          if (disabled) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
          updateSelection(event.clientX, event.clientY);
        }}
        onPointerMove={(event) => {
          if (dragging) updateSelection(event.clientX, event.clientY);
        }}
        onPointerUp={(event) => {
          setDragging(false);
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
        }}
        onPointerCancel={() => setDragging(false)}
        data-leika-color-selection
      >
        <span
          aria-hidden
          className={cn(
            "pointer-events-none absolute -translate-x-1/2 -translate-y-1/2",
            COLOR_POINTER_CLASS,
          )}
          style={{
            left: `${hsv.s}%`,
            top: `${100 - hsv.v}%`,
          }}
          data-leika-color-selection-thumb
        />
      </div>

      <PickerSlider
        value={hsv.h}
        max={360}
        label="Hue"
        disabled={disabled}
        trackClassName="bg-[linear-gradient(90deg,#FF0000,#FFFF00,#00FF00,#00FFFF,#0000FF,#FF00FF,#FF0000)]"
        thumbColor={`hsl(${hsv.h}, 100%, 50%)`}
        onValueChange={(hue) => updateRgb({ ...hsv, h: hue })}
        testId="hue"
      />

      {format === "rgba" && (
        <PickerSlider
          value={alpha}
          max={100}
          label="Opacity"
          disabled={disabled}
          trackStyle={{
            background: `linear-gradient(to right, rgba(${rgb.join(", ")}, 0), rgb(${rgb.join(", ")})), ${CHECKERBOARD}`,
          }}
          thumbColor={`rgba(${rgb.join(", ")}, ${alpha / 100})`}
          onValueChange={(next) =>
            onValueChange(colorWithOpacity(value, next / 100))
          }
          testId="alpha"
        />
      )}

      <div className="flex min-w-0 items-center gap-2">
        {/* Without `EyeDropper` the pick goes through the platform's own color
            panel -- on macOS the one carrying the magnifier that samples the
            screen, the same job by the only route WebKit leaves open. The input
            is laid OVER the button at full size rather than clicked from
            script: a real click on a real color input is what opens that panel,
            where a synthetic click on a zero-sized one does nothing in WebKit.
            The button underneath is then decoration, so it stops taking focus
            and the input carries the naming. */}
        <span className="relative inline-flex shrink-0">
          <Button
            type="button"
            variant="outline"
            size="icon-xs"
            disabled={disabled}
            aria-hidden={!eyedropper}
            tabIndex={eyedropper ? undefined : -1}
            aria-label={eyedropper ? "Pick a color from the screen" : undefined}
            title={eyedropper ? "Pick a color from the screen" : undefined}
            onClick={eyedropper ? pickFromScreen : undefined}
            data-leika-color-eyedropper
          >
            <PipetteIcon />
          </Button>
          {eyedropper ? null : (
            <input
              type="color"
              disabled={disabled}
              aria-label="Pick a color with the system color picker"
              title="Pick a color with the system color picker, which on macOS can sample the screen"
              // `inset-0` alone leaves it 44px wide and overhanging the select
              // beside it: WebKit gives a color input an intrinsic minimum
              // width, which only `min-w-0` and `appearance-none` give up.
              className="absolute inset-0 size-full min-h-0 min-w-0 cursor-pointer appearance-none border-0 p-0 opacity-0"
              value={colorValueToHex(value)}
              onChange={(event) =>
                onValueChange(
                  colorFromHex(event.currentTarget.value, format, value),
                )
              }
              data-leika-color-native
            />
          )}
        </span>

        <Select
          value={outputFormat}
          onValueChange={(next) => {
            if (next) setOutputFormat(next as ColorFormat);
          }}
          disabled={disabled}
        >
          <SelectTrigger
            size="sm"
            className={cn(
              FOOTER_CONTROL_CLASS,
              // `data-[size=sm]` outranks a plain height utility, so the
              // shared height has to be restated in the same variant.
              "w-[4.5rem] shrink-0 rounded-lg px-2 data-[size=sm]:h-6",
            )}
            aria-label="Color format"
            data-leika-color-format
          >
            <SelectValue>{outputFormat.toUpperCase()}</SelectValue>
          </SelectTrigger>
          <SelectContent>
            {FORMATS.map((item) => (
              <SelectItem key={item} value={item} className="text-xs">
                {item.toUpperCase()}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* One joined run of fields: ButtonGroup owns the shared borders, the
            end rounding, and raising whichever field has focus. */}
        <ButtonGroup className="relative w-full min-w-0 flex-1">
          {output.map((channel, index) => (
            <OutputInput
              key={`${outputFormat}-${index}`}
              value={channel}
              label={`${outputFormat.toUpperCase()} color value ${index + 1}`}
              disabled={disabled}
              onValueChange={(next) => updateOutput(index, next)}
            />
          ))}
          {showOpacityOutput && (
            <>
              <OutputInput
                value={Math.round(alpha)}
                label="Opacity percentage"
                disabled={disabled}
                onValueChange={updateOpacityOutput}
                // Narrower than an even share, and forced past the group's
                // own `[&>input]:flex-1`, which is the more specific rule.
                className="min-w-12 flex-[0_1_3.25rem]! pr-5"
              />
              {/* Positioned against the group rather than a wrapper of its
                  own, so every field stays a direct child of the group. */}
              <span
                aria-hidden
                className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 text-xs text-muted-foreground"
              >
                %
              </span>
            </>
          )}
        </ButtonGroup>
      </div>
    </div>
  );
}

/** A color swatch that opens the picker in a popover. Not exported:
 * `ColorRow` below is the one way a color is placed. */
function ColorPickerPopover({
  id,
  value,
  label,
  format,
  disabled = false,
  text,
  className,
  anchor,
  onValueChange,
}: {
  id: string;
  /** The color the swatch shows and the picker opens on, as a CSS string. */
  value: string;
  /** Names the popover for assistive technology. */
  label: string;
  format: "rgb" | "rgba";
  disabled?: boolean;
  /** Trigger text, when the color itself is not what to say. */
  text?: string;
  className?: string;
  /** What the popover aligns to, when the trigger is not the stable edge --
   * a row that reveals a reset button shrinks its trigger, and the popover
   * would slide across with it. */
  anchor?: React.ComponentProps<typeof PopoverContent>["anchor"];
  onValueChange: (value: string) => void;
}) {
  const selectionRef = React.useRef<HTMLDivElement>(null);
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            id={id}
            variant="outline"
            // The swatch is centered vertically inside the 24px row, which
            // leaves 3px above and below it. Matching that on the left squares
            // up its inset; the text keeps the full padding on the right.
            className={cn(
              "w-full justify-start pl-[3px] font-normal",
              className,
            )}
            disabled={disabled}
            data-leika-color-trigger
          />
        }
      >
        <span
          aria-hidden
          className="size-4 shrink-0 rounded-sm"
          style={{ backgroundColor: value }}
        />
        <HoverScrollText className="flex-1 text-left">
          {text ?? colorDisplayString(value)}
        </HoverScrollText>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        anchor={anchor}
        className={POPOUT_WIDTH_CLASS}
        initialFocus={(interactionType) =>
          interactionType === "touch" ? true : selectionRef.current
        }
        data-leika-color-popover
      >
        <PopoverHeader className="sr-only">
          <PopoverTitle>{label}</PopoverTitle>
          <PopoverDescription>
            Choose a color by saturation, brightness, hue
            {format === "rgba" ? ", and opacity" : ""}.
          </PopoverDescription>
        </PopoverHeader>
        <ColorPicker
          value={value}
          format={format}
          disabled={disabled}
          selectionRef={selectionRef}
          onValueChange={onValueChange}
        />
      </PopoverContent>
    </Popover>
  );
}

/** A color as it sits in a row: the swatch, and the reset beside it.
 *
 * The one place this geometry lives. Both callers -- the GUI's RGB and RGBA
 * inputs, and the settings pane's accent -- differ in what they store and what
 * "reset" restores, but not in how the two controls share a row, and holding
 * that in one component is what keeps them from drifting apart:
 *
 *   - the swatch takes the whole row until there is something to undo, so an
 *     untouched row looks as it did before the button existed;
 *   - the trigger's own `w-full` would claim the row and push the button off
 *     the end of a panel dragged narrow, so it takes basis zero and truncates
 *     instead;
 *   - the popover aligns to the ROW, since the trigger shortens when the button
 *     appears and a popover anchored to it would slide across by its width.
 */
export function ColorRow({
  id,
  value,
  label,
  format,
  text,
  disabled = false,
  className,
  onReset,
  onValueChange,
}: {
  id: string;
  value: string;
  label: string;
  format: "rgb" | "rgba";
  /** Trigger text, when the color itself is not what to say. */
  text?: string;
  disabled?: boolean;
  /** Extra classes for the row itself, not the controls in it. */
  className?: string;
  /** What to undo to, or null when there is nothing to undo. */
  onReset: (() => void) | null;
  onValueChange: (value: string) => void;
}) {
  const rowRef = React.useRef<HTMLDivElement>(null);
  return (
    <div
      ref={rowRef}
      className={cn("flex min-w-0 items-center gap-1", className)}
    >
      <ColorPickerPopover
        id={id}
        value={value}
        label={label}
        format={format}
        text={text}
        disabled={disabled}
        className="min-w-0 flex-1"
        anchor={rowRef}
        onValueChange={onValueChange}
      />
      {onReset === null ? null : (
        // Typed like the eyedropper in the popover below it: the same outlined
        // icon button, so the two reads as one kind of control wherever a color
        // is being edited.
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          className="shrink-0"
          aria-label={`Reset ${label}`}
          title={`Reset ${label}`}
          disabled={disabled}
          onClick={onReset}
          data-leika-color-reset
        >
          <RotateCcwIcon />
        </Button>
      )}
    </div>
  );
}
