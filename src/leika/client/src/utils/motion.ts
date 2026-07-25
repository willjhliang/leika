// Honors the OS-level "reduce motion" accessibility setting. Both layout
// engines (the dock and the viewport workspace) turn their transitions instant
// when it is set, so this lives in a neutral module rather than inside either.
//
// The MediaQueryList is module-scoped so `.matches` reads stay live without
// re-querying; jsdom (unit tests) has no matchMedia, hence the optional call.
const reducedMotionQuery =
  typeof window !== "undefined"
    ? window.matchMedia?.("(prefers-reduced-motion: reduce)")
    : undefined;

export function prefersReducedMotion(): boolean {
  return reducedMotionQuery?.matches ?? false;
}
