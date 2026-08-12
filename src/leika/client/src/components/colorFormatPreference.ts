import * as React from "react";

export type ColorFormat = "hex" | "rgb" | "css" | "hsl";

const COLOR_FORMATS: readonly ColorFormat[] = ["hex", "rgb", "css", "hsl"];

export interface ColorFormatStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const COLOR_FORMAT_STORAGE_KEY = "leika.color-format.v1";

function browserStorage(): ColorFormatStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readColorFormat(storage: ColorFormatStorage | null): ColorFormat {
  if (storage === null) return "hex";
  try {
    const stored = storage.getItem(COLOR_FORMAT_STORAGE_KEY);
    return COLOR_FORMATS.includes(stored as ColorFormat)
      ? (stored as ColorFormat)
      : "hex";
  } catch {
    return "hex";
  }
}

export interface ColorFormatPreference {
  store: {
    subscribe: (listener: () => void) => () => void;
    snapshot: () => ColorFormat;
  };
  set: (format: ColorFormat) => void;
}

export function createColorFormatPreference(
  storage: ColorFormatStorage | null = browserStorage(),
): ColorFormatPreference {
  let current = readColorFormat(storage);
  const listeners = new Set<() => void>();
  return {
    store: {
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      snapshot() {
        return current;
      },
    },
    set(format) {
      if (format === current) return;
      current = format;
      if (storage !== null) {
        try {
          storage.setItem(COLOR_FORMAT_STORAGE_KEY, format);
        } catch {
          // The picker remains usable for this page when storage is blocked.
        }
      }
      listeners.forEach((listener) => listener());
    },
  };
}

const preference = createColorFormatPreference();

export function useColorFormatPreference(): [
  ColorFormat,
  (format: ColorFormat) => void,
] {
  const format = React.useSyncExternalStore(
    preference.store.subscribe,
    preference.store.snapshot,
    preference.store.snapshot,
  );
  return [format, preference.set];
}
