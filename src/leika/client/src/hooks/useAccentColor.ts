import React from "react";

import { accentForeground } from "../components/colorUtils";

/** Paint a chosen accent over the theme's `--primary` pair, or clear it.
 *
 * The properties are written inline on `<html>`, which outranks both the
 * `:root` and `.dark` blocks in `index.css`, so one write serves either scheme
 * and clearing it restores whichever stock accent is in force. Every control
 * that reads `bg-primary` -- checkboxes, slider ranges, default buttons,
 * progress bars, badges -- follows without knowing an accent exists. */
export function useAccentColor(accentColor: string | null): void {
  React.useEffect(() => {
    const root = document.documentElement;
    if (accentColor === null) {
      root.style.removeProperty("--primary");
      root.style.removeProperty("--primary-foreground");
      return;
    }
    root.style.setProperty("--primary", accentColor);
    root.style.setProperty(
      "--primary-foreground",
      accentForeground(accentColor),
    );
  }, [accentColor]);
}
