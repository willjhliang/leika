/** How far below the top of the frame a heading still counts as reached.
 *
 * A heading is the section you are in from the moment it reaches the top of
 * what you can see. The slack is there because the two ways of arriving at
 * one land it in slightly different places: a carried link stops it flush
 * against the top edge, and the jump a reader who asked for less motion gets
 * leaves the `scroll-margin` typeset gives it. Both have to read as arrived.
 */
const SECTION_LINE_PX = 24;

/** A heading's stable position in the scroll frame's document coordinates. */
export interface MeasuredSection {
  fragment: string;
  top: number;
}

/** Everything section selection needs until the document next lays out. */
export interface SectionLayout {
  first: string | null;
  sections: readonly MeasuredSection[];
  ordered: boolean;
  viewportHeight: number;
  clientHeight: number;
  scrollHeight: number;
}

/** Select a section from cached layout, without asking the DOM to lay out. */
export function sectionAtScroll(
  layout: SectionLayout,
  scrollTop: number,
): string | null {
  const line = scrollTop + SECTION_LINE_PX;
  const bottom = scrollTop + layout.viewportHeight;
  const atEnd =
    layout.scrollHeight > layout.clientHeight &&
    scrollTop + layout.clientHeight >= layout.scrollHeight - 1;

  let reached = layout.first;
  let reachedTop = -Infinity;
  let topmostOnScreen: string | null = null;

  if (layout.ordered) {
    // Find the final heading at or above the section line. Heading positions
    // follow document order in normal typeset flow, so selection is
    // logarithmic no matter how long the file is.
    let low = 0;
    let high = layout.sections.length;
    while (low < high) {
      const middle = low + Math.floor((high - low) / 2);
      if (layout.sections[middle].top <= line) low = middle + 1;
      else high = middle;
    }
    const reachedIndex = low - 1;
    if (reachedIndex >= 0) {
      const section = layout.sections[reachedIndex];
      reached = section.fragment;
      reachedTop = section.top;
    }
    const next = layout.sections[reachedIndex + 1];
    if (next !== undefined && next.top < bottom) {
      topmostOnScreen = next.fragment;
    }
  } else {
    // Typeset headings are ordered, but preserving source-order selection for
    // an unexpectedly positioned custom heading costs little on this rare
    // path and keeps this an optimisation rather than a semantic change.
    for (const section of layout.sections) {
      if (section.top <= line) {
        reached = section.fragment;
        reachedTop = section.top;
      } else if (topmostOnScreen === null && section.top < bottom) {
        topmostOnScreen = section.fragment;
      }
    }
  }

  // Only when the answer would otherwise be a section that is no longer on
  // the screen. A heading sitting just above the line at the bottom of the
  // scroll is still the one at the top of the view, and keeps the mark it
  // earned the ordinary way.
  if (atEnd && topmostOnScreen !== null && reachedTop < scrollTop) {
    return topmostOnScreen;
  }
  return reached;
}
