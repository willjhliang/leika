import * as React from "react";

import { persisted, type PersistedStorage } from "../utils/persisted";

export type ColorFormat = "hex" | "rgb" | "css" | "hsl";

const COLOR_FORMATS: readonly unknown[] = ["hex", "rgb", "css", "hsl"];

export const COLOR_FORMAT_STORAGE_KEY = "leika.color-format.v1";

/** The output format every colour picker shows, remembered per browser. */
export function colorFormatPreference(storage?: PersistedStorage | null) {
  return persisted(
    COLOR_FORMAT_STORAGE_KEY,
    (stored): ColorFormat =>
      COLOR_FORMATS.includes(stored) ? (stored as ColorFormat) : "hex",
    storage,
  );
}

const preference = colorFormatPreference();

export function useColorFormatPreference(): [
  ColorFormat,
  (format: ColorFormat) => void,
] {
  const format = React.useSyncExternalStore(
    preference.subscribe,
    preference.get,
    preference.get,
  );
  return [format, preference.set];
}
