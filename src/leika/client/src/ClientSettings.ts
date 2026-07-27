import React from "react";

import { parseToRgb } from "./components/colorUtils";
import { Store, createStore } from "./store";

/** Display preferences owned by the browser rather than by the Python app.
 *
 * These are the viewer's own choices, so they outrank what the server asked
 * for: an app that sets `dark_mode=False` still yields to a reader who turns
 * dark mode on. */
export interface ClientSettings {
  /** `null` follows the server's `dark_mode`, which may itself be "auto". */
  darkMode: boolean | null;
  /** Pin every pane's corner title open instead of revealing it on hover. */
  showPaneTitles: boolean;
  /** CSS color replacing the theme's near-black accent, or `null` for stock. */
  accentColor: string | null;
}

export interface ClientSettingsActions {
  setDarkMode: (darkMode: boolean) => void;
  setShowPaneTitles: (showPaneTitles: boolean) => void;
  setAccentColor: (accentColor: string | null) => void;
}

export interface ClientSettingsStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** Unlike a dock layout, these say nothing about one app, so the key carries
 * neither the server URL nor the workspace: one browser, one set of
 * preferences. */
export const CLIENT_SETTINGS_STORAGE_KEY = "leika.settings.v1";

export function defaultClientSettings(): ClientSettings {
  return { darkMode: null, showPaneTitles: false, accentColor: null };
}

function browserStorage(): ClientSettingsStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Read stored preferences, falling back to the default for any field the
 * payload does not carry as the right type. Validating field by field means a
 * partial write, a payload from a future version, or a hand-edited entry costs
 * only the fields it actually broke. */
export function readClientSettings(
  storage: ClientSettingsStorage | null,
): ClientSettings {
  const defaults = defaultClientSettings();
  if (storage === null) return defaults;

  let parsed: unknown;
  try {
    const raw = storage.getItem(CLIENT_SETTINGS_STORAGE_KEY);
    if (raw === null) return defaults;
    parsed = JSON.parse(raw);
  } catch {
    return defaults;
  }
  if (typeof parsed !== "object" || parsed === null) return defaults;

  const stored = parsed as Record<string, unknown>;
  return {
    darkMode:
      typeof stored.darkMode === "boolean"
        ? stored.darkMode
        : defaults.darkMode,
    showPaneTitles:
      typeof stored.showPaneTitles === "boolean"
        ? stored.showPaneTitles
        : defaults.showPaneTitles,
    // An accent that no longer parses would be written into `--primary` as-is
    // and blank out every control that uses it, so it is dropped here.
    accentColor:
      typeof stored.accentColor === "string" &&
      parseToRgb(stored.accentColor) !== null
        ? stored.accentColor
        : defaults.accentColor,
  };
}

/** Browser-owned display preferences, restored from storage on mount. */
export function useClientSettings(
  storage: ClientSettingsStorage | null = browserStorage(),
): {
  store: Store<ClientSettings>;
  actions: ClientSettingsActions;
} {
  const store = React.useMemo(
    () => createStore(readClientSettings(storage)),
    [storage],
  );

  const actions = React.useMemo<ClientSettingsActions>(() => {
    const update = (settings: Partial<ClientSettings>): void => {
      store.set(settings);
      if (storage === null) return;
      try {
        storage.setItem(
          CLIENT_SETTINGS_STORAGE_KEY,
          JSON.stringify(store.get()),
        );
      } catch {
        // Storage can be unavailable or full. Preferences remain usable for
        // the rest of the session.
      }
    };
    return {
      setDarkMode: (darkMode) => update({ darkMode }),
      setShowPaneTitles: (showPaneTitles) => update({ showPaneTitles }),
      setAccentColor: (accentColor) => update({ accentColor }),
    };
  }, [storage, store]);

  return { store, actions };
}
