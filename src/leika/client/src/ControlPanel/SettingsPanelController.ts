import { createStore } from "../store";

/** Transient panel UI state shared by controls rendered in separate dock nodes. */
function makeSection(initiallyOpen: boolean) {
  const store = createStore({ open: initiallyOpen });
  return {
    store,
    open: () => store.set({ open: true }),
    close: () => store.set({ open: false }),
    toggle: () => store.set((state) => ({ open: !state.open })),
  };
}

/** Whether the settings popover is open. */
export const settingsPanel = makeSection(false);

/** Whether the app's generated controls are shown. */
export const controlsSection = makeSection(true);

/** Subscribe a component to the settings section's open state. */
export function useSettingsPanelOpen(): boolean {
  return settingsPanel.store((state) => state.open);
}

/** Subscribe a component to whether the app's own controls are shown. */
export function useControlsShown(): boolean {
  return controlsSection.store((state) => state.open);
}
