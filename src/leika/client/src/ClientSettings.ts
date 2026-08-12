import React from "react";

import { parseToRgb } from "./components/colorUtils";
import { Store, createStore } from "./store";

/** How an image is sized inside the box it is given, named the way this
 * control usually is. Kept in step with `ImageFit` on the Python side, which
 * is what arrives on a pane's `fit`. */
export type ImageFit = "fit" | "fill" | "stretch";

/** The CSS keyword each one applies. The two vocabularies disagree on "fill":
 * CSS means stretching by it, so filling the box is CSS `cover`. */
export const IMAGE_FIT_OBJECT_FIT: Record<
  ImageFit,
  "contain" | "cover" | "fill"
> = {
  fit: "contain",
  fill: "cover",
  stretch: "fill",
};

const IMAGE_FITS = Object.keys(IMAGE_FIT_OBJECT_FIT) as ImageFit[];

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
  /** How image panes size themselves when Python did not say. */
  imageFit: ImageFit;
  /** Whether the phone's bottom control sheet is unfolded. */
  mobileControlsExpanded: boolean;
}

export interface ClientSettingsActions {
  /** `null` hands the scheme back to the server and the OS. A viewer who has
   * pinned one has to be able to stop, or the first flip of the switch is a
   * one-way door out of `dark_mode="auto"`. */
  setDarkMode: (darkMode: boolean | null) => void;
  setShowPaneTitles: (showPaneTitles: boolean) => void;
  setAccentColor: (accentColor: string | null) => void;
  setImageFit: (imageFit: ImageFit) => void;
  setMobileControlsExpanded: (expanded: boolean) => void;
}

export interface ClientSettingsStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** Unlike a dock layout, these say nothing about one app, so the key carries
 * neither the server URL nor the workspace: one browser, one set of
 * preferences.
 *
 * v2 retires v1's image-fit vocabulary, which was the CSS keywords. Reading a
 * v1 payload under the new names would have silently turned a saved "fill"
 * from filling the pane into stretching it, so the whole key is retired
 * instead -- the other three preferences are cheap to set again. */
export const CLIENT_SETTINGS_STORAGE_KEY = "leika.settings.v2";

export function defaultClientSettings(): ClientSettings {
  // Fitting shows the whole image, which is the safe default for data: it
  // crops nothing and distorts nothing.
  return {
    darkMode: null,
    showPaneTitles: false,
    accentColor: null,
    imageFit: "fit",
    mobileControlsExpanded: true,
  };
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
    imageFit: IMAGE_FITS.includes(stored.imageFit as ImageFit)
      ? (stored.imageFit as ImageFit)
      : defaults.imageFit,
    mobileControlsExpanded:
      typeof stored.mobileControlsExpanded === "boolean"
        ? stored.mobileControlsExpanded
        : defaults.mobileControlsExpanded,
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
      setImageFit: (imageFit) => update({ imageFit }),
      setMobileControlsExpanded: (mobileControlsExpanded) =>
        update({ mobileControlsExpanded }),
    };
  }, [storage, store]);

  return { store, actions };
}
