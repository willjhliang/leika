import React from "react";

export type SectionListener = (opened: boolean) => void;
/** Kept for callers that named the settings listener type directly. */
export type SettingsPanelListener = SectionListener;

/**
 * Imperative open/closed state for the control panel's two body sections.
 *
 * The panel body holds two things that are shown INDEPENDENTLY:
 *
 *   - the app's own controls, toggled by the panel handle;
 *   - the browser's settings, toggled by the gear beside it.
 *
 * Neither implies the other. Hiding the controls with the settings up leaves
 * the settings up, and closing the settings leaves the controls where they
 * were; the panel is folded away only when BOTH are down, which is a reading
 * of these two flags rather than a third piece of state.
 *
 * Imperative because the two toggles and the two sections are four separate
 * nodes as far as the dock is concerned -- header and body are registered
 * separately -- so their shared state cannot come from a React parent. Kept out
 * of `ClientSettings` because it is transient: which section is open is not a
 * preference to restore.
 */
function makeSection(initiallyOpen: boolean) {
  let opened = initiallyOpen;
  const listeners = new Set<SectionListener>();

  const publish = (next: boolean) => {
    if (opened === next) return;
    opened = next;
    for (const listener of listeners) listener(next);
  };

  return {
    open: () => publish(true),
    close: () => publish(false),
    toggle: () => publish(!opened),
    get: () => opened,
    subscribe: (listener: SectionListener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/** The browser's own settings. Closed until the gear asks for it. */
export const settingsPanel = makeSection(false);

/** The app's generated controls. Shown until the handle folds them away. */
export const controlsSection = makeSection(true);

export function getSettingsPanelOpen(): boolean {
  return settingsPanel.get();
}

export function subscribeSettingsPanel(listener: SectionListener): () => void {
  return settingsPanel.subscribe(listener);
}

function useSection(section: ReturnType<typeof makeSection>): boolean {
  const [opened, setOpened] = React.useState(section.get);
  React.useEffect(() => section.subscribe(setOpened), [section]);
  return opened;
}

/** Subscribe a component to the settings section's open state. */
export function useSettingsPanelOpen(): boolean {
  return useSection(settingsPanel);
}

/** Subscribe a component to whether the app's own controls are shown. */
export function useControlsShown(): boolean {
  return useSection(controlsSection);
}
