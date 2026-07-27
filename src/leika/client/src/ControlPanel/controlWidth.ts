/** The control panel's width, in the panel's own 16px font size.
 *
 * One source of truth for the two representations the layouts need: a CSS
 * length for the sidebar and bottom-sheet layouts, and a pixel count for the
 * dock layout, which computes its geometry in numbers. */
const CONTROL_WIDTH_EM = 20;

export const CONTROL_WIDTH_CSS = `${CONTROL_WIDTH_EM}em`;

export const CONTROL_WIDTH_PX = CONTROL_WIDTH_EM * 16;
