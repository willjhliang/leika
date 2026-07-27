import * as React from "react";

/** Subscribe to a CSS media query. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = React.useState(() =>
    typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );
  React.useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/** Breakpoint below which the control panel becomes a bottom sheet. */
export const MOBILE_MEDIA_QUERY = "(max-width: 36em)";

export function useMobileView(): boolean {
  return useMediaQuery(MOBILE_MEDIA_QUERY);
}

/** The OS-level preference behind the theme's `dark_mode: "auto"`. */
export const DARK_SCHEME_MEDIA_QUERY = "(prefers-color-scheme: dark)";

export function usePrefersDarkMode(): boolean {
  return useMediaQuery(DARK_SCHEME_MEDIA_QUERY);
}
