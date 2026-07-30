import { createStore } from "../store";

/**
 * Open/closed state for the control panel's two body sections, shown
 * INDEPENDENTLY: the app's own controls (toggled by the panel handle) and the
 * browser's settings (toggled by the gear beside it). Neither implies the
 * other; the panel folds away only when BOTH are down, which is a reading of
 * these two flags rather than a third piece of state.
 *
 * Module singletons because the two toggles and the two sections are four
 * separate nodes as far as the dock is concerned, so their shared state cannot
 * come from a React parent. Kept out of `ClientSettings` because which section
 * is open is transient, not a preference to restore.
 */
function makeSection(initiallyOpen: boolean) {
  const store = createStore({ open: initiallyOpen });
  return {
    store,
    open: () => store.set({ open: true }),
    close: () => store.set({ open: false }),
    toggle: () => store.set((state) => ({ open: !state.open })),
  };
}

/** The browser's own settings. Closed until the gear asks for it. */
export const settingsPanel = makeSection(false);

/** The app's generated controls. Shown until the handle folds them away. */
export const controlsSection = makeSection(true);

/** Subscribe a component to the settings section's open state. */
export function useSettingsPanelOpen(): boolean {
  return settingsPanel.store((state) => state.open);
}

/** Subscribe a component to whether the app's own controls are shown. */
export function useControlsShown(): boolean {
  return controlsSection.store((state) => state.open);
}
