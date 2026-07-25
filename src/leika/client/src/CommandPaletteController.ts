export type CommandPaletteListener = (opened: boolean) => void;

let requestedOpen = false;
const openListeners = new Set<CommandPaletteListener>();

function publishOpenState(opened: boolean) {
  requestedOpen = opened;
  for (const listener of openListeners) listener(opened);
}

/**
 * Imperative command-palette entry point used by application chrome.
 */
export const commandPalette = {
  open: () => publishOpenState(true),
  close: () => publishOpenState(false),
  toggle: () => publishOpenState(!requestedOpen),
};

export function getCommandPaletteOpen(): boolean {
  return requestedOpen;
}

export function subscribeCommandPalette(
  listener: CommandPaletteListener,
): () => void {
  openListeners.add(listener);
  return () => {
    openListeners.delete(listener);
  };
}
