/** Type styling every GUI label shares, whether it sits in a row's label
 * column or stacked above what it names. Stock `Label` is a medium-weight
 * foreground heading; a panel full of those competes with the values, so
 * labels are muted and normal-weight instead. Layout is left to the caller.
 *
 * Its own module rather than `common.tsx` so that file keeps exporting only
 * components, which is what fast refresh needs to swap them in place. */
export const guiLabelClassName =
  "text-muted-foreground font-normal leading-tight";
