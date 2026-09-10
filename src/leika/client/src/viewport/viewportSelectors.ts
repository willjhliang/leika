import type { ViewportPageState, ViewportState } from "./ViewportState";

/** The only page snapshot safe to display for this stream generation.
 * A retained transition page may stay visible while its replacement loads;
 * an incomplete live stream must never leak partial content into that view. */
export function displayedViewportPage(
  state: ViewportState,
  pageId: string | null = state.displayPageId,
): ViewportPageState | undefined {
  if (pageId === null) return undefined;
  if (state.transitionPage?.pageId === pageId) return state.transitionPage;
  const stream = state.pageStream;
  if (
    state.activePageId !== pageId ||
    state.displayPageId !== pageId ||
    stream === null ||
    stream.pageId !== pageId ||
    !stream.ready
  )
    return undefined;
  return state.pages[pageId];
}
