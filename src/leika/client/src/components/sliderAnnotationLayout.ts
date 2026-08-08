/** Stable, unambiguous effect key for slider label geometry. */
export function sliderAnnotationLayoutKey(
  marks: { label?: string | null }[],
  positions: number[],
): string {
  // JSON tuples preserve boundaries even when labels contain punctuation; an
  // ad-hoc delimiter can make distinct layouts collide and retain stale refs.
  return JSON.stringify(
    marks.map((mark, index) => [positions[index], mark.label ?? null]),
  );
}
