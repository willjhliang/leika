import { useSyncExternalStore } from "react";

import {
  getColorScheme,
  subscribeColorScheme,
  type ColorScheme,
} from "./colorSchemeStore";

/** The resolved color scheme from the theme provider's document-root class. */
export function useColorScheme(): ColorScheme {
  return useSyncExternalStore(
    subscribeColorScheme,
    getColorScheme,
    () => "light" as const,
  );
}
