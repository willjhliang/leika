// The card's own vertical inset, moved onto whatever sits against that edge.
//
// A card pads its contents away from its edges, which leaves a band above the
// topmost handle -- and below it, once the panel is collapsed to nothing else
// -- that LOOKS like part of the title bar and drags nothing: the padding
// belongs to the card, so a press there never reaches the handle. Nor can the
// handle reach out and take it, since every wrapper in between clips to its own
// box. So whatever sits at an edge of the card takes that inset over as its own
// padding, and the card drops the matching `py` in return (see TabGroupFrame's
// `insetTop` / `insetBottom` props, and their callers). Same geometry, one more
// band of it grabbable.

/** The inset as padding, for a handle that is a plain header. */
export const CARD_INSET_TOP = "pt-(--card-spacing)";
export const CARD_INSET_BOTTOM = "pb-(--card-spacing)";

/** The top inset on a handle BAR, which needs two things a header does not:
 * `box-content`, because padding sits inside the border box and the bar's
 * min-height would otherwise swallow the inset rather than grow by it; and the
 * variable, which keeps the bar's anchored icon button off the inset band (see
 * HandleIconButton). */
export const CARD_INSET_TOP_BAR = `box-content ${CARD_INSET_TOP} [--handle-inset-top:var(--card-spacing)]`;

/** A handle that is the LAST thing in its card covers the bottom inset without
 * adding to it: the (zero-height) body still follows it in the flow. */
export const CARD_INSET_BOTTOM_OVERLAP = `${CARD_INSET_BOTTOM} -mb-(--card-spacing)`;
