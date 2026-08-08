// Which previews fill the window, and the styling that follows from it.
//
// One of the flags a preview remembers about how it is being looked at; see
// ./previewFlags for what that means and why it is kept where it is. Filling
// the window is the reader's answer to "this is too small", and the next
// file is not that file, so the answer is kept against this one alone.

import { previewFlag, usePreviewFlag } from "./previewFlags";

/** Marks the popup as full-window, for anything reading the page from the
 * outside -- a test, mostly. Nothing styles off it: see
 * {@link previewMediaClassName} for why. */
export const PREVIEW_FULLSCREEN_ATTR = "data-preview-fullscreen";

const fullscreen = previewFlag();

export const previewFullscreenStore = fullscreen.store;

export function setPreviewFullscreen(key: string, next: boolean): void {
  fullscreen.set(key, next);
}

/** Whether THIS preview opens full-window, and the way to say otherwise. */
export function usePreviewFullscreen(
  key: string,
): [boolean, (next: boolean) => void] {
  return usePreviewFlag(fullscreen, key);
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
