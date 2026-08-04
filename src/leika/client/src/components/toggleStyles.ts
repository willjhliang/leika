/** How a toggle looks in each colorway, off and on.
 *
 * A toggle is a button that stays pressed, so it borrows the button's own two
 * roles: off, it is that button at rest; on, it wears the appearance that
 * button takes under the pointer at the moment of a click. What it does NOT
 * borrow is the 1px nudge a press applies -- that is the motion of pressing,
 * and a toggle that stayed nudged would sit a pixel below its neighbours for
 * as long as it was on.
 *
 * Written against the stock Toggle rather than the Button so the pressed state
 * and its keyboard semantics come from the component built for it. The base
 * variant hovers and presses everything to `muted`, which is right for the
 * outlined role and has to be overridden for the filled one.
 *
 * EVERY colorway needs a pressed value per theme, and the pressed rules are
 * marked important. The outlined role is why: it carries a dark-mode resting
 * colour of its own, and `dark:bg-input/30` and `aria-pressed:bg-muted` are
 * the same specificity, so the resting one won on order alone and an ON toggle
 * in dark mode was indistinguishable from an OFF one.
 */
export const TOGGLE_CLASSES: Record<"default" | "inverse", string> = {
  // Filled, like a shadcn `default` button -- which is the opposite of what
  // leika's own "default" role means, hence the name below. On, it takes the
  // same step that button takes under the pointer: the same value in either
  // theme, since the accent it steps from is itself theme-dependent.
  inverse: [
    "border border-transparent bg-primary text-primary-foreground",
    "hover:bg-primary/80 hover:text-primary-foreground",
    "aria-pressed:bg-primary/80! aria-pressed:text-primary-foreground",
    "data-[state=on]:bg-primary/80!",
    // No icon treatment, as in the filled button this borrows from: over the
    // accent, the muted foreground is a different color at worse contrast
    // rather than a softer one, so the icon stays on the label's own.
  ].join(" "),
  // Outlined, like an outline button: transparent at rest, filling under a
  // press with `muted` in light and the same `input/50` that button hovers to
  // in dark.
  default: [
    "border border-border bg-background text-foreground",
    "hover:bg-muted hover:text-foreground",
    "aria-pressed:bg-muted! aria-pressed:text-foreground",
    "dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
    "dark:aria-pressed:bg-input/50!",
    // Muted at rest, as in the outline button. It comes forward when pressed
    // as well as on hover: pressed fills the toggle with `muted` itself, and
    // a muted icon on it would be a step back onto its own color.
    "[&_[data-icon]]:text-muted-foreground hover:[&_[data-icon]]:text-foreground",
    "aria-pressed:[&_[data-icon]]:text-foreground",
  ].join(" "),
};
