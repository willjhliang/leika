import * as React from "react";
import { Input as InputPrimitive } from "@base-ui/react/input";

import {
  type HoverScrollCycle,
  startHoverScrollCycle,
} from "@/components/hoverScroll";
import { cn } from "@/lib/utils";

function inputHoverMaximum(input: HTMLInputElement): number {
  return Math.max(0, input.scrollWidth - input.clientWidth);
}

/** Move a blurred input's native text viewport with the shared text cycle. */
function startInputHoverScroll(
  input: HTMLInputElement,
  maximum: number,
): HoverScrollCycle {
  return startHoverScrollCycle({
    maximum,
    setPosition: (position) => {
      input.scrollLeft = position;
    },
    onStart: () => input.setAttribute("data-leika-hover-scroll-active", ""),
    onStop: () => input.removeAttribute("data-leika-hover-scroll-active"),
    shouldStop: () => document.activeElement === input,
  });
}

const Input = React.forwardRef<
  HTMLInputElement,
  React.ComponentPropsWithoutRef<"input">
>(function Input(
  {
    className,
    type,
    onPointerEnter,
    onPointerLeave,
    onPointerDown,
    onFocus,
    onBlur,
    ...props
  },
  forwardedRef,
) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const cycleRef = React.useRef<HoverScrollCycle | null>(null);
  const pointerInsideRef = React.useRef(false);
  const blurFrameRef = React.useRef<number | null>(null);
  const focusFrameRef = React.useRef<number | null>(null);

  const setInputRef = React.useCallback(
    (input: HTMLInputElement | null) => {
      inputRef.current = input;
      if (typeof forwardedRef === "function") {
        forwardedRef(input);
      } else if (forwardedRef !== null) {
        forwardedRef.current = input;
      }
    },
    [forwardedRef],
  );

  const cancelFocusReset = React.useCallback(() => {
    if (focusFrameRef.current !== null) {
      cancelAnimationFrame(focusFrameRef.current);
      focusFrameRef.current = null;
    }
  }, []);

  /**
   * Release hover ownership. Only an active cycle may restore the prefix:
   * native focus, selection, and manual scrolling otherwise own scrollLeft.
   */
  const stopHoverScroll = React.useCallback((resetOwnedViewport: boolean) => {
    const input = inputRef.current;
    const ownedViewport =
      input?.hasAttribute("data-leika-hover-scroll-active") ?? false;
    cycleRef.current?.stop();
    cycleRef.current = null;
    if (resetOwnedViewport && ownedViewport && input !== null) {
      input.scrollLeft = 0;
    }
    return ownedViewport;
  }, []);

  const reconcileGeometry = React.useCallback(() => {
    const input = inputRef.current;
    if (input === null || !pointerInsideRef.current) return;
    cycleRef.current?.reconcileMaximum(inputHoverMaximum(input));
  }, []);

  const beginHoverScroll = React.useCallback(
    (input: HTMLInputElement) => {
      stopHoverScroll(false);
      cycleRef.current = startInputHoverScroll(input, inputHoverMaximum(input));
    },
    [stopHoverScroll],
  );

  React.useLayoutEffect(() => {
    const input = inputRef.current;
    if (input === null) return;

    let mounted = true;
    const reconcileMountedGeometry = () => {
      if (mounted) reconcileGeometry();
    };
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(reconcileMountedGeometry);
    observer?.observe(input);
    void document.fonts?.ready.then(reconcileMountedGeometry);

    return () => {
      mounted = false;
      observer?.disconnect();
    };
  }, [reconcileGeometry]);

  // Input contents do not change their border box, so controlled value and
  // presentation changes explicitly refresh the cached text extent.
  React.useLayoutEffect(() => {
    reconcileGeometry();
  }, [className, props.placeholder, props.value, reconcileGeometry, type]);

  React.useEffect(
    () => () => {
      pointerInsideRef.current = false;
      if (blurFrameRef.current !== null) {
        cancelAnimationFrame(blurFrameRef.current);
        blurFrameRef.current = null;
      }
      cancelFocusReset();
      stopHoverScroll(false);
    },
    [cancelFocusReset, stopHoverScroll],
  );

  return (
    <InputPrimitive
      ref={setInputRef}
      type={type}
      data-slot="input"
      data-leika-hover-scroll-input=""
      className={cn(
        // One size at every window width: the stock `text-base md:text-sm`
        // exists to stop iOS Safari zooming when a sub-16px field is focused,
        // but it keys off viewport width, so a narrow desktop window made the
        // text jump. This GUI is desktop-first.
        "h-8 w-full min-w-0 rounded-lg border border-input bg-transparent px-2.5 py-1 text-sm transition-colors outline-none file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:border-ring disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-input/50 disabled:opacity-50 aria-invalid:border-destructive dark:bg-input/30 dark:disabled:bg-input/80 dark:aria-invalid:border-destructive/50",
        className,
      )}
      onPointerEnter={(event) => {
        onPointerEnter?.(event);
        pointerInsideRef.current = true;
        stopHoverScroll(true);
        if (document.activeElement !== event.currentTarget) {
          beginHoverScroll(event.currentTarget);
        }
      }}
      onPointerLeave={(event) => {
        pointerInsideRef.current = false;
        stopHoverScroll(true);
        onPointerLeave?.(event);
      }}
      onPointerDown={(event) => {
        // A blurred hover cycle is only paint for reading. Restore its prefix
        // before native caret hit-testing, but never disturb a focused field's
        // own selection or manually scrolled viewport.
        cancelFocusReset();
        if (stopHoverScroll(false)) {
          event.currentTarget.scrollLeft = 0;
        }
        onPointerDown?.(event);
      }}
      onFocus={(event) => {
        // Focus gives the native field complete ownership of its viewport.
        cancelFocusReset();
        if (stopHoverScroll(false)) {
          const input = event.currentTarget;
          input.scrollLeft = 0;
          // Firefox and WebKit reveal the caret after dispatching `focus`,
          // which can undo the synchronous reset above. Complete the handoff
          // after that native work. Pointer focus already released hover on
          // pointer-down, so this never overrides click caret placement.
          focusFrameRef.current = requestAnimationFrame(() => {
            focusFrameRef.current = null;
            if (
              inputRef.current === input &&
              document.activeElement === input
            ) {
              input.scrollLeft = 0;
            }
          });
        }
        onFocus?.(event);
      }}
      onBlur={(event) => {
        const input = event.currentTarget;
        cancelFocusReset();
        onBlur?.(event);
        if (blurFrameRef.current !== null) {
          cancelAnimationFrame(blurFrameRef.current);
        }
        blurFrameRef.current = requestAnimationFrame(() => {
          blurFrameRef.current = null;
          if (
            inputRef.current === input &&
            pointerInsideRef.current &&
            document.activeElement !== input
          ) {
            beginHoverScroll(input);
          }
        });
      }}
      {...props}
    />
  );
});

export { Input };
