import { Separator } from "@/components/ui/separator";
import { markLabelMaxWidths } from "./sliderValues";

export type SliderMark = { value: number; label?: string | null };

/** User-provided slider annotations composed with the stock Separator. */
export function SliderAnnotations({
  marks,
  min,
  max,
}: {
  marks: SliderMark[];
  min: number;
  max: number;
}) {
  const positions = marks.map((mark) => {
    const raw = max === min ? 0 : ((mark.value - min) / (max - min)) * 100;
    return Math.min(100, Math.max(0, raw));
  });
  // Each label is capped at its own share of the track, so a long one ends in
  // an ellipsis rather than running through the label beside it.
  const labelWidths = markLabelMaxWidths(positions);

  return (
    <div
      // Decorative only. Without `pointer-events-none` this box swallows the
      // lower half of the thumb's hit area: it sits below the slider but
      // overlaps it, and both are positioned at `z-index: auto`, so DOM order
      // puts it on top until Base UI raises the thumb on first interaction.
      className="pointer-events-none relative h-5 text-xs text-muted-foreground"
      aria-hidden
      data-leika-slider-annotations
    >
      {marks.map((mark, index) => {
        const position = positions[index];
        const positionStyle = {
          left: `${position}%`,
          transform: `translateX(-${position}%)`,
        };
        return (
          <span
            key={`${mark.value}-${index}`}
            className="absolute inset-x-0 top-0 h-5"
            data-leika-slider-mark-wrapper
          >
            <Separator
              orientation="vertical"
              className="absolute h-1"
              style={positionStyle}
              data-leika-slider-mark
            />
            {mark.label == null ? null : (
              <span
                className="absolute top-1 block truncate whitespace-nowrap"
                style={{
                  ...positionStyle,
                  maxWidth: `${labelWidths[index]}%`,
                }}
                data-leika-slider-mark-label
              >
                {mark.label}
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}
