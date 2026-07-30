import { createStore } from "./store";

const paletteStore = createStore({ open: false });

/** Imperative command-palette entry point used by application chrome. */
export const commandPalette = {
  open: () => paletteStore.set({ open: true }),
  close: () => paletteStore.set({ open: false }),
};

/** Subscribe a component to the palette's open state. */
export function useCommandPaletteOpen(): boolean {
  return paletteStore((state) => state.open);
}
