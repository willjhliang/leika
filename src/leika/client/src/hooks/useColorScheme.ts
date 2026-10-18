import { useViewer } from "../ViewerContext";
import { usePrefersDarkMode } from "./useMediaQuery";

export type ColorScheme = "light" | "dark";

/** The scheme in force: the Settings choice, or the browser's under Auto.
 * Python selects the same setting, so this is the one source of dark mode. */
export function useColorScheme(): ColorScheme {
  const chosen = useViewer().useSettings((state) => state.darkMode);
  const prefersDark = usePrefersDarkMode();
  return (chosen ?? prefersDark) ? "dark" : "light";
}
