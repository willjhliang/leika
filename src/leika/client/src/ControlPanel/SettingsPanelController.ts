import React from "react";

export type SettingsPanelListener = (opened: boolean) => void;

let requestedOpen = false;
const openListeners = new Set<SettingsPanelListener>();

function publishOpenState(opened: boolean) {
  requestedOpen = opened;
  for (const listener of openListeners) listener(opened);
}

/**
 * Imperative entry point for the control panel's settings section.
 *
 * The gear lives in the panel header and the section lives in the panel body,
 * which the dock registers as two separate nodes, so their shared open state
 * cannot come from a React parent. Kept out of `ClientSettings` because it is
 * transient: which pane is open is not a preference to restore.
 */
export const settingsPanel = {
  open: () => publishOpenState(true),
  close: () => publishOpenState(false),
  toggle: () => publishOpenState(!requestedOpen),
};

export function getSettingsPanelOpen(): boolean {
  return requestedOpen;
}

export function subscribeSettingsPanel(
  listener: SettingsPanelListener,
): () => void {
  openListeners.add(listener);
  return () => {
    openListeners.delete(listener);
  };
}

/** Subscribe a component to the settings section's open state. */
export function useSettingsPanelOpen(): boolean {
  const [opened, setOpened] = React.useState(getSettingsPanelOpen);
  React.useEffect(() => subscribeSettingsPanel(setOpened), []);
  return opened;
}
