// Which documents are being read with their contents list up beside them.
//
// One of the flags a preview remembers about how it is being looked at; see
// ./previewFlags for what that means and why it is kept where it is.
//
// Down by default, unlike full-window, which is also down by default but for
// a different reason. A document opens to be read from where it starts, and
// a column of links standing beside it from the first paint is a second
// thing on the screen before there is any question of moving around in the
// file. The list is what a reader asks for once they know the file is long
// enough to want one -- and having asked, they are remembered, because the
// next look at that same file is the same reader with the same question.

import { previewFlag, usePreviewFlag } from "./previewFlags";

export const PREVIEW_CONTENTS_STORAGE_KEY = "leika.preview-contents.v1";

const contents = previewFlag(PREVIEW_CONTENTS_STORAGE_KEY);

export const previewContentsStore = contents.store;

export function setPreviewContents(key: string, next: boolean): void {
  contents.set(key, next);
}

/** Whether THIS document is read with its contents beside it, and the way to
 * say otherwise. */
export function usePreviewContents(
  key: string,
): [boolean, (next: boolean) => void] {
  return usePreviewFlag(contents, key);
}
