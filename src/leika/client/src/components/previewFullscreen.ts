// Which previews fill the window, and the styling that follows from it.
//
// Per preview, not per session. Full-window is a decision about one thing
// being too small to read at the size it opens -- a dense figure, a document
// with a wide table in it -- and the next file is a different thing. So the
// flag is keyed by whatever is being previewed, and pressing the toggle on
// one says nothing about any other.
//
// Held outside React because it outlives every component that reads it: the
// preview it belongs to is unmounted the moment it closes, which is exactly
// when the answer has to survive.
//
// A set of the keys that open full-window rather than a map to booleans, so
// what is remembered is only what somebody asked for. Going back to windowed
// forgets the key instead of writing `false` against it, and a session that
// opens a thousand files carries nothing for the ones it never enlarged.
//
// Not written to storage. This is a way of looking at something, not a
// preference somebody set: every preference that outlives the tab is one a
// viewer can find and change in the settings popout. Reloading starts small.

import * as React from "react";

/** Marks the popup as full-window, for anything reading the page from the
 * outside -- a test, mostly. Nothing styles off it: see
 * {@link previewMediaClassName} for why. */
export const PREVIEW_FULLSCREEN_ATTR = "data-preview-fullscreen";

const fullscreenKeys = new Set<string>();
const listeners = new Set<() => void>();

/** The `useSyncExternalStore` half, held apart from the hook so that the flag
 * can be read without a component to read it from. */
export const previewFullscreenStore = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  snapshot(key: string): boolean {
    return fullscreenKeys.has(key);
  },
};

export function setPreviewFullscreen(key: string, next: boolean): void {
  // Previews mount and unmount constantly, and each one asks. Only a real
  // change is worth waking every reader for.
  if (next === fullscreenKeys.has(key)) return;
  if (next) fullscreenKeys.add(key);
  else fullscreenKeys.delete(key);
  for (const listener of listeners) listener();
}

/** Whether THIS preview opens full-window, and the way to say otherwise.
 *
 * `key` names what is being previewed, and is what the answer is remembered
 * against: a file's name, or the uuid of the pane whose media this is. Two
 * previews sharing a key share the answer, which is the right reading of a
 * name -- the same file shown from two buttons is the same file.
 */
export function usePreviewFullscreen(
  key: string,
): [boolean, (next: boolean) => void] {
  const value = React.useSyncExternalStore(
    previewFullscreenStore.subscribe,
    () => previewFullscreenStore.snapshot(key),
    () => previewFullscreenStore.snapshot(key),
  );
  const set = React.useCallback(
    (next: boolean) => setPreviewFullscreen(key, next),
    [key],
  );
  return [value, set];
}

/** What a picture or a video wears inside a preview.
 *
 * Two sizings, because the popup means two different things in the two modes.
 * Windowed, the popup is already the shape of the media -- see
 * `mediaPreviewWidth` -- so the media fills its width and sets the height.
 * Full-window the popup is the shape of the SCREEN, which the media is not,
 * so the element takes the whole area and `object-contain` fits the picture
 * inside it: scaled up to the window in the direction that fits, letterboxed
 * in the other. Squared off at the same time, since a corner radius is a
 * popup's edge and full-window there is no edge left.
 *
 * A branch rather than one string with `in-data-[...]` variants on it. That
 * reads better and does not work: Tailwind wraps an `in-*` ancestor in
 * `:where()`, so the variant lands on the same specificity as the utility it
 * is meant to beat and the winner is whichever the generated sheet happens to
 * print second. `object-contain` came through, having nothing to fight;
 * `h-full` lost to `h-auto` and a portrait ran off the bottom of the screen.
 */
export function previewMediaClassName(fullscreen: boolean): string {
  return fullscreen
    ? "block h-full w-full object-contain"
    : "mx-auto block h-auto w-full rounded-lg";
}
