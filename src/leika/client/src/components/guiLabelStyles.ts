/** Type styling every GUI label shares, whether it sits in a row's label
 * column or stacked above what it names. Stock `Label` is a medium-weight
 * foreground heading; a panel full of those competes with the values, so
 * labels are muted and normal-weight instead. Layout is left to the caller.
 *
 * Also worn by the settings rows and by a media preview's title, which are
 * not GUI labels but are doing the same job: naming a thing without drowning
 * it out. Changing this changes all three.
 *
 * Its own module rather than `common.tsx` so that file keeps exporting only
 * components, which is what fast refresh needs to swap them in place. */
export const guiLabelClassName =
  "text-muted-foreground font-normal leading-tight";

/** The row geometry that goes with it: a fixed label column beside the
 * controls, both vertically centered against the panel's 24px row. Shared so
 * the settings rows and the GUI rows cannot drift apart. */
export const guiRowGridClassName =
  "grid min-h-6 grid-cols-[6rem_minmax(0,1fr)] items-center";
