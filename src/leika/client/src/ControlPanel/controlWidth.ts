/** The control panel's width, in the panel's own 16px font size.
 *
 * One source of truth for the two representations the layouts need: a CSS
 * length for the sidebar and bottom-sheet layouts, and a pixel count for the
 * dock layout, which computes its geometry in numbers. */
const CONTROL_WIDTH_EM = 20;

export const CONTROL_WIDTH_CSS = `${CONTROL_WIDTH_EM}em`;

export const CONTROL_WIDTH_PX = CONTROL_WIDTH_EM * 16;

/** The width above, as the Tailwind classes the layouts consume. Tailwind only
 * compiles classes it can read literally, so the `20rem`/`80` here restate
 * CONTROL_WIDTH_EM rather than deriving from it. */
export const CONTROL_MAX_WIDTH_CLASS = "max-w-80";

/** A popout sized like the panel, giving way only to a narrower viewport. */
export const POPOUT_WIDTH_CLASS = "w-[min(20rem,calc(100vw-1rem))]";
