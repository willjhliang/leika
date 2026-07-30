import { describe, expect, it } from "vitest";

import { TOGGLE_CLASSES } from "./toggleStyles";
import { buttonVariants } from "./ui/button";

/** The pair the button itself rests and hovers at, when the icon is all of it. */
const WHOLE_RESTING = "text-muted-foreground";
const WHOLE_HOVER = "hover:text-foreground";

/** The same step, applied to an icon that sits beside a label. */
const ICON_RESTING = "[&_[data-icon]]:text-muted-foreground";
const ICON_HOVER = "hover:[&_[data-icon]]:text-foreground";

const ICON_SIZES = ["icon", "icon-xs", "icon-sm", "icon-lg"] as const;
const TEXT_SIZES = ["default", "xs", "sm", "lg"] as const;
const BARE = ["ghost", "outline"] as const;
const FILLED = ["default", "secondary", "destructive"] as const;

/** The classes as a set, so a check for one cannot match inside another --
 * `text-muted-foreground` is a substring of the arbitrary variant that applies
 * it to a child. */
function classes(value: string): Set<string> {
  return new Set(value.split(/\s+/).filter(Boolean));
}

describe("an icon that is the whole button", () => {
  it("rests a step back, in every icon size", () => {
    // Close, collapse, expand, send: all the same button, so all the same
    // color. Pinned here because the alternative -- each call site pasting
    // the pair -- is what let the dialog's close button drift darker than
    // the notification's.
    for (const variant of BARE) {
      for (const size of ICON_SIZES) {
        const found = classes(buttonVariants({ variant, size }));
        expect(found, `${variant}/${size}`).toContain(WHOLE_RESTING);
        expect(found, `${variant}/${size}`).toContain(WHOLE_HOVER);
      }
    }
  });

  it("keeps its own foreground over a fill", () => {
    // A secondary icon chip reads against its fill; muting it would take it
    // a step back from a background that already moved.
    for (const variant of FILLED) {
      for (const size of ICON_SIZES) {
        expect(
          classes(buttonVariants({ variant, size })),
          `${variant}/${size}`,
        ).not.toContain(WHOLE_RESTING);
      }
    }
  });

  it("lets a call site override it, for an icon on a fill of its own", () => {
    // The combobox chip's remove button dims by opacity against the chip.
    // Tailwind-merge keeps the last color class, which is the caller's.
    const value = buttonVariants({
      variant: "ghost",
      size: "icon-xs",
      className: "text-current",
    });
    expect(value.lastIndexOf("text-current")).toBeGreaterThan(
      value.indexOf(WHOLE_RESTING),
    );
  });
});

describe("an icon beside a label", () => {
  it("steps back on its own, leaving the label where it was", () => {
    // The label is what the button is called and is read; the icon is
    // glanced at. Every size, since a button carrying an icon is usually a
    // text-sized one.
    for (const variant of BARE) {
      for (const size of [...TEXT_SIZES, ...ICON_SIZES]) {
        const found = classes(buttonVariants({ variant, size }));
        expect(found, `${variant}/${size}`).toContain(ICON_RESTING);
        expect(found, `${variant}/${size}`).toContain(ICON_HOVER);
        // The button's own color is untouched at text sizes: only the icon
        // moved.
        if ((TEXT_SIZES as readonly string[]).includes(size)) {
          expect(found, `${variant}/${size}`).not.toContain(WHOLE_RESTING);
        }
      }
    }
  });

  it("stays on the label's own color over a fill", () => {
    // The muted foreground is a step back from the panel's text. Over the
    // accent it is not a softer color but a different one at worse contrast,
    // so a filled button's icon reads as its label does.
    for (const variant of FILLED) {
      for (const size of TEXT_SIZES) {
        const found = classes(buttonVariants({ variant, size }));
        expect(found, `${variant}/${size}`).not.toContain(ICON_RESTING);
        expect(found, `${variant}/${size}`).not.toContain(ICON_HOVER);
      }
    }
  });
});

describe("a toggle, which is a button that stays pressed", () => {
  it("treats its icon the way the button it borrows from does", () => {
    const outlined = classes(TOGGLE_CLASSES.secondary);
    expect(outlined).toContain(ICON_RESTING);
    expect(outlined).toContain(ICON_HOVER);

    // Filled, so the icon reads as the label does -- as in the filled button.
    expect(classes(TOGGLE_CLASSES.primary)).not.toContain(ICON_RESTING);
  });

  it("brings the outlined toggle's icon forward while it is on", () => {
    // Pressed fills an outlined toggle with `muted` itself, so an icon left
    // at the muted foreground would be a step back onto its own color.
    expect(classes(TOGGLE_CLASSES.secondary)).toContain(
      "aria-pressed:[&_[data-icon]]:text-foreground",
    );
  });
});
