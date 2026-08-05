/** The control panel's width, in the panel's own 16px font size.
 *
 * A pixel count, because the dock computes its geometry in numbers. */
const CONTROL_WIDTH_EM = 20;

export const CONTROL_WIDTH_PX = CONTROL_WIDTH_EM * 16;

/** The width above, as the Tailwind classes the layouts consume. Tailwind only
 * compiles classes it can read literally, so the `20rem`/`80` here restate
 * CONTROL_WIDTH_EM rather than deriving from it. */
export const CONTROL_MAX_WIDTH_CLASS = "max-w-80";

/** A popout sized like the panel, giving way only to a narrower viewport. */
export const POPOUT_WIDTH_CLASS = "w-[min(20rem,calc(100vw-1rem))]";
