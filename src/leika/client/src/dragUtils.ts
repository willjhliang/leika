/** Canonical modifier-key combo shared by commands and pointer gestures. */
export type KeyModifier =
  | "cmd/ctrl"
  | "alt"
  | "shift"
  | "cmd/ctrl+alt"
  | "cmd/ctrl+shift"
  | "alt+shift"
  | "cmd/ctrl+alt+shift";

export function keyModifierFromEvent(event: {
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): KeyModifier | null {
  const parts: string[] = [];
  if (event.ctrlKey || event.metaKey) parts.push("cmd/ctrl");
  if (event.altKey) parts.push("alt");
  if (event.shiftKey) parts.push("shift");
  return parts.length === 0 ? null : (parts.join("+") as KeyModifier);
}

/** Pointer travel (px, per axis) before a press counts as a drag. Shared by
 * every drag gesture -- the dock's panel/tab drags and the viewport's pane
 * drags -- so "moved enough to be a drag" means the same thing everywhere. */
export const MOTION_THRESHOLD_PX = 4;

export function motionExceedsThreshold(
  start: [number, number],
  end: [number, number],
): boolean {
  return (
    Math.abs(end[0] - start[0]) > MOTION_THRESHOLD_PX ||
    Math.abs(end[1] - start[1]) > MOTION_THRESHOLD_PX
  );
}
