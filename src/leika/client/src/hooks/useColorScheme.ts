import { useSyncExternalStore } from "react";

/** The resolved color scheme, read from the `dark` class that the theme
 * provider puts on the document root. That class is the single source of
 * truth: it already folds together the server-configured theme, the OS
 * preference that theme defers to under `"auto"`, and embedded-workspace
 * configuration. */
function getColorScheme(): "light" | "dark" {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function subscribeColorScheme(onChange: () => void): () => void {
  if (typeof document === "undefined") return () => undefined;
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  return () => observer.disconnect();
}

export function useColorScheme(): "light" | "dark" {
  return useSyncExternalStore(
    subscribeColorScheme,
    getColorScheme,
    () => "light" as const,
  );
}
