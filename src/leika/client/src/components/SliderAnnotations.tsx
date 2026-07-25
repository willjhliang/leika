import { Separator } from "@/components/ui/separator";

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
  return (
    <div
      className="relative h-5 text-xs text-muted-foreground"
      aria-hidden
      data-leika-slider-annotations
    >
      {marks.map((mark, index) => {
        const rawPosition =
          max === min ? 0 : ((mark.value - min) / (max - min)) * 100;
        const position = Math.min(100, Math.max(0, rawPosition));
        const positionStyle = {
          left: `${position}%`,
          transform: `translateX(-${position}%)`,
        };
        return (
          <span
            key={`${mark.value}-${index}`}
            className="pointer-events-none absolute inset-x-0 top-0 h-5"
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
                className="absolute top-1 block max-w-full truncate whitespace-nowrap"
                style={positionStyle}
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
