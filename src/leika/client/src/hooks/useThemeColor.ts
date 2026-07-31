import React from "react";

import { useColorScheme } from "./useColorScheme";

/** Tint the browser's own chrome with the surface the dock is painted in.
 *
 * `theme-color` is what colors the address bar on Android and the area around
 * the page on iOS, so leaving it at a fixed value framed a light workspace in
 * black. Matching it to `--leika-panel-surface` lets the window's edges carry
 * on from the panels instead of boxing them in.
 *
 * Driven off the resolved scheme rather than a `prefers-color-scheme` media
 * query on the tag itself: a reader who picks Light or Dark in the settings
 * outranks the OS, and a media query would go on answering to the OS. The
 * token is read rather than restated here, so this cannot drift from whatever
 * the dock is actually painting.
 */
export function useThemeColor(): void {
  const scheme = useColorScheme();
  React.useEffect(() => {
    const meta = document.querySelector<HTMLMetaElement>(
      'meta[name="theme-color"]',
    );
    if (meta === null) return;
    // Read after the class lands: `scheme` changes because `<html>` did, so by
    // now the cascade already answers with the incoming scheme's surface.
    meta.content = getComputedStyle(document.documentElement)
      .getPropertyValue("--leika-panel-surface")
      .trim();
  }, [scheme]);
}
