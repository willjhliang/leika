import * as React from "react";

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

  const trackRef = React.useRef<HTMLDivElement>(null);
  const labelRefs = React.useRef<(HTMLSpanElement | null)[]>([]);
  // Null until measured, and `max-w-full` until then: the same cap the track
  // itself imposes, so nothing can escape it on the first paint or in markup
  // rendered without a browser to measure in.
  const [widths, setWidths] = React.useState<number[] | null>(null);

  // What a label asks for is its own text, so the layout cannot be computed
  // from the marks alone -- it has to be measured. `scrollWidth` reports the
  // full content width even while the box is truncating it, so measuring does
  // not depend on the cap this then applies, and the two cannot chase each
  // other.
  const layout = marks
    .map((mark, index) => `${positions[index]}:${mark.label ?? ""}`)
    .join("|");
  React.useLayoutEffect(() => {
    const track = trackRef.current;
    if (track === null) return;

    const measure = () => {
      const trackWidth = track.clientWidth;
      if (trackWidth === 0) return;
      const natural = positions.map((_position, index) => {
        const label = labelRefs.current[index];
        return label == null ? 0 : (label.scrollWidth / trackWidth) * 100;
      });
      const next = markLabelMaxWidths(positions, natural);
      // Settling for the widths already in place ends the render loop rather
      // than handing back an equal array that is a new object every time.
      setWidths((current) =>
        current !== null &&
        current.length === next.length &&
        current.every((width, index) => Math.abs(width - next[index]) < 0.01)
          ? current
          : next,
      );
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(track);
    return () => observer.disconnect();
    // `layout` stands in for the marks: a string, so a parent that rebuilds the
    // array every render does not restart this every render.
  }, [layout]);

  return (
    <div
      // Decorative only. Without `pointer-events-none` this box swallows the
      // lower half of the thumb's hit area: it sits below the slider but
      // overlaps it, and both are positioned at `z-index: auto`, so DOM order
      // puts it on top until Base UI raises the thumb on first interaction.
      className="pointer-events-none relative h-5 text-xs text-muted-foreground"
      aria-hidden
      data-leika-slider-annotations
      ref={trackRef}
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
                  maxWidth:
                    widths === null ? "100%" : `${widths[index] ?? 100}%`,
                }}
                ref={(element) => {
                  labelRefs.current[index] = element;
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
