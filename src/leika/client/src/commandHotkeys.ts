export type HotkeyBinding = [definition: string, handler: () => void];

type HotkeyEvent = Pick<
  KeyboardEvent,
  "key" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey"
>;

/** Compose built-in palette bindings with the server-registered commands. */
export function commandPaletteHotkeys(
  hasCommands: boolean,
  openPalette: () => void,
  commandHotkeys: HotkeyBinding[],
): HotkeyBinding[] {
  if (!hasCommands) return [];
  return [
    ["mod+k", openPalette],
    ["mod+shift+p", openPalette],
    ...commandHotkeys,
  ];
}

/** Match a normalized hotkey definition against one keyboard event. */
export function hotkeyMatches(event: HotkeyEvent, definition: string): boolean {
  const parts = definition.toLowerCase().split("+");
  const key = parts.at(-1);
  const mod = parts.includes("mod");
  return (
    event.key.toLowerCase() === key &&
    (mod
      ? event.ctrlKey || event.metaKey
      : event.ctrlKey === parts.includes("ctrl")) &&
    (mod || event.metaKey === parts.includes("meta")) &&
    event.shiftKey === parts.includes("shift") &&
    event.altKey === parts.includes("alt")
  );
}
