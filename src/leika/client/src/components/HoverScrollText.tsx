import * as React from "react";

import { cn } from "@/lib/utils";
import { type HoverScrollCycle, startHoverScrollCycle } from "./hoverScroll";

/**
 * One-line display text that keeps its ellipsis until it is hovered, then
 * travels far enough to reveal its hidden end.
 *
 * The distance is measured rather than guessed from the string: proportional
 * fonts, nested styling, and a panel resize all change how much ink is hidden.
 * The shared cycle also drives native inputs, so every clipped-text surface
 * moves and pauses identically.
 */
export function HoverScrollText({
  className,
  children,
  onPointerEnter,
  onPointerLeave,
  ...props
}: React.ComponentPropsWithoutRef<"span">) {
  const containerRef = React.useRef<HTMLSpanElement>(null);
  const contentRef = React.useRef<HTMLSpanElement>(null);
  const cycleRef = React.useRef<HoverScrollCycle | null>(null);
  const pointerInsideRef = React.useRef(false);

  const stopHoverScroll = React.useCallback(() => {
    cycleRef.current?.stop();
    cycleRef.current = null;
    containerRef.current?.removeAttribute("data-leika-hover-scroll-active");
    contentRef.current?.style.removeProperty("transform");
  }, []);

  /** Measure only when geometry can have changed, then update the cached end. */
  const reconcileGeometry = React.useCallback((): number => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (container === null || content === null) return 0;

    const maximum = Math.max(
      0,
      Math.ceil(content.scrollWidth - container.clientWidth),
    );
    if (maximum > 1) {
      container.setAttribute("data-leika-hover-scroll-overflow", "");
    } else {
      container.removeAttribute("data-leika-hover-scroll-overflow");
    }
    if (pointerInsideRef.current) {
      cycleRef.current?.reconcileMaximum(maximum);
    }
    return maximum;
  }, []);

  React.useLayoutEffect(() => {
    const container = containerRef.current;
    const content = contentRef.current;
    if (container === null || content === null) return;

    let mounted = true;
    const reconcileMountedGeometry = () => {
      if (mounted) reconcileGeometry();
    };
    reconcileMountedGeometry();

    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(reconcileMountedGeometry);
    observer?.observe(container);
    // The clipped box can stay the same size while its text or font grows.
    observer?.observe(content);

    // A webfont can change the natural text width without resizing its
    // container, so reconcile once the document's pending fonts have settled.
    void document.fonts?.ready.then(reconcileMountedGeometry);

    return () => {
      mounted = false;
      observer?.disconnect();
      pointerInsideRef.current = false;
      stopHoverScroll();
    };
  }, [reconcileGeometry, stopHoverScroll]);

  // React can replace the words without changing either observed border box.
  React.useLayoutEffect(() => {
    reconcileGeometry();
  }, [children, reconcileGeometry]);

  return (
    <span
      ref={containerRef}
      className={cn("block min-w-0", className)}
      data-leika-hover-scroll
      onPointerEnter={(event) => {
        onPointerEnter?.(event);
        pointerInsideRef.current = true;
        stopHoverScroll();

        const container = containerRef.current;
        const content = contentRef.current;
        if (container === null || content === null) return;
        cycleRef.current = startHoverScrollCycle({
          maximum: reconcileGeometry(),
          setPosition: (position) => {
            content.style.transform = `translateX(${-position}px)`;
          },
          onStart: () =>
            container.setAttribute("data-leika-hover-scroll-active", ""),
          onStop: () => {
            container.removeAttribute("data-leika-hover-scroll-active");
            content.style.removeProperty("transform");
          },
        });
      }}
      onPointerLeave={(event) => {
        pointerInsideRef.current = false;
        stopHoverScroll();
        onPointerLeave?.(event);
      }}
      {...props}
    >
      <span
        ref={contentRef}
        className="block min-w-0 truncate"
        data-leika-hover-scroll-content
      >
        {children}
      </span>
    </span>
  );
}
