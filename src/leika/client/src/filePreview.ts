import {
  RETAINED_DOWNLOAD_PRIORITY,
  type RetainedDownload,
  retainedDownloads,
} from "./retainedDownloadBudget";
import { normalizedSafeRasterMimeType } from "./imageSafety";

// Which viewer a previewed file gets, and the reading of its size.
//
// Kept apart from the dialog that draws it: picking a viewer is a decision
// about a name and a MIME type with no DOM in it, and it is the part with
// edge cases worth pinning.

/** The viewers a preview dialog can put a file in.
 *
 * `markdown` and `prose` are the two that hold writing, and are set in a
 * column a person can read down. `text` is everything else textual -- source,
 * data, logs -- where a line is a record rather than a sentence.
 */
export type PreviewKind =
  | "markdown"
  | "prose"
  | "text"
  | "image"
  | "video"
  | "audio"
  | "pdf"
  | "unsupported";

/** Decoding larger files to JS strings can multiply retained memory. The Blob
 * remains available through the preview's download control. */
export const FILE_TEXT_PREVIEW_MAX_BYTES = 16 * 1024 * 1024;

export function fileTextPreviewAllowed(sizeBytes: number): boolean {
  return sizeBytes <= FILE_TEXT_PREVIEW_MAX_BYTES;
}

/** Whether a viewer holds writing to be read down, rather than something to
 * be looked at or scanned.
 *
 * The distinction is what the dialog sizes itself from: reading is done by
 * scrolling through a column, so a document wants a short measure and as much
 * height as the window will give it, while a picture or a player is fitted
 * into its frame and gains nothing from a taller one.
 */
export function isReadingKind(kind: PreviewKind): boolean {
  return kind === "markdown" || kind === "prose";
}

/** Whether a viewer holds something that arrives with a size of its own.
 *
 * The distinction the popup takes its own size from. A picture was made at a
 * width and a player is as tall as it is; the popup is that, and the media
 * fills it. Everything else -- a document, a table of records, a card saying
 * there is no viewer -- has no size until something decides one for it, so it
 * gets a frame instead, and the frame is fixed so that a one-line log and a
 * thousand-line one open the same window.
 *
 * A PDF is a document by this reckoning even though it is drawn by a viewer:
 * it is pages, read by scrolling, and its page size is not the size to show
 * it at.
 */
export function isMediaKind(kind: PreviewKind): boolean {
  return kind === "image" || kind === "video" || kind === "audio";
}

/** Extensions whose files are text that no MIME type admits to.
 *
 * `mimetypes.guess_type` on the server answers "application/octet-stream" for
 * plenty of things that are plainly text -- lockfiles, dotfiles, .log -- and a
 * download of unknown type is better shown than refused. Only extensions whose
 * contents are text by definition belong here; guessing wrong renders a binary
 * as mojibake.
 */
const TEXT_EXTENSIONS = new Set([
  "cfg",
  "conf",
  "csv",
  "diff",
  "ini",
  "log",
  "lock",
  "patch",
  "properties",
  "rst",
  "tex",
  "toml",
  "tsv",
  "txt",
  "yaml",
  "yml",
]);

/** MIME types outside `text/*` whose payload is text.
 *
 * `application/json` and friends are structured, but they are structured
 * *text*: showing the source is a real preview of them, where an "unsupported"
 * card would not be.
 */
const TEXT_MIME_SUFFIXES = ["+json", "+xml", "+yaml"];
const TEXT_MIME_TYPES = new Set([
  "application/javascript",
  "application/json",
  "application/x-ndjson",
  "application/x-sh",
  "application/xml",
  "application/yaml",
]);

function extensionOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  // A leading dot names the file (".gitignore"), it does not extend it.
  if (dot <= 0) return "";
  return filename.slice(dot + 1).toLowerCase();
}

/** The viewer a file's name and type call for.
 *
 * The name is consulted first for markdown and last for text, so an .md file
 * renders whether or not the server's MIME table knows the extension, while a
 * declared `text/*` type is trusted over any guess from the name.
 */
export function previewKindFor(
  mimeType: string,
  filename: string,
): PreviewKind {
  const extension = extensionOf(filename);
  const type = mimeType.split(";")[0].trim().toLowerCase();

  if (extension === "md" || extension === "markdown") return "markdown";
  if (type === "text/markdown") return "markdown";

  if (type.startsWith("image/")) {
    // SVG is an image the browser will happily render, and also a document
    // that can carry script. It is shown as its source instead, which is a
    // truthful preview and not a way to run anything.
    if (type === "image/svg+xml") return "text";
    return normalizedSafeRasterMimeType(type) === null
      ? "unsupported"
      : "image";
  }
  if (type.startsWith("video/")) return "video";
  if (type.startsWith("audio/")) return "audio";
  if (type === "application/pdf") return "pdf";

  // Writing rather than records: `text/plain` is what a .txt is, and it is
  // the only textual type that claims nothing about its structure. A .csv, a
  // .json, a .log all say what they are, and what they are is data.
  if (type === "text/plain" || extension === "txt") return "prose";

  if (type.startsWith("text/")) return "text";
  if (TEXT_MIME_TYPES.has(type)) return "text";
  if (TEXT_MIME_SUFFIXES.some((suffix) => type.endsWith(suffix))) return "text";
  if (TEXT_EXTENSIONS.has(extension)) return "text";

  return "unsupported";
}

/** A previewed file's bytes, once every part of the transfer has arrived. */
export interface FileContents {
  /** Object URL for the assembled blob. Revoked when the dialog closes. */
  url: string;
  blob: Blob;
  /** Page-wide completed-file byte reservation owned with this URL. */
  retained?: RetainedDownload;
}

function ensureRetained(contents: FileContents): RetainedDownload | null {
  if (contents.retained !== undefined) {
    return contents.retained.isActive ? contents.retained : null;
  }
  const retained = retainedDownloads.retain(contents.blob, {
    priority: RETAINED_DOWNLOAD_PRIORITY.preview,
  });
  if (retained !== null) contents.retained = retained;
  return retained;
}

/** One file the server asked this client to look at.
 *
 * Everything but the bytes is known from the transfer's first message, and
 * that is deliberately enough to open the dialog with: the name, the viewer
 * its type calls for, and so the frame's size are all settled while the file
 * is still arriving. The dialog answers a click at the speed of the metadata,
 * and only the contents wait on the transfer.
 */
export interface FilePreview {
  /** The transfer's uuid, which keys the dialog. */
  id: string;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  /** The file itself, or null while its parts are still arriving. */
  contents: FileContents | null;
  /** The component this file came out of -- the preview button that was
   * pressed -- or null for a file a script sent, which has nothing to ask
   * again. What the reload and the watch are addressed to. */
  sourceUuid: string | null;
  /** What the source was when these contents were sent, as the server stamps
   * it. Handed back with every watch, and null for a source that cannot
   * change under the reader, which is the same as saying: do not watch. */
  sourceVersion: string | null;
}

export interface FilePreviewReload {
  sourceUuid: string;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  contents: FileContents;
  sourceVersion: string | null;
}

/** A preview whose transfer has finished and whose URL has one owner. */
type CompleteFilePreview = Omit<FilePreview, "contents"> & {
  contents: FileContents;
};

/** A stable key for display state remembered across preview mounts. */
export function previewMemoryKey(
  preview: Pick<FilePreview, "sourceUuid" | "filename">,
): string {
  return preview.sourceUuid === null
    ? "file-name:" + preview.filename
    : "file-source:" + preview.sourceUuid;
}

// The file currently being previewed, held outside React so that the message
// handler -- which is not a component and must not re-render one to do its
// job -- can open a dialog the same way it raises a toast.
//
// One at a time: a second file arriving replaces the first, whose object URL
// is revoked with it. Stacking previews would leave a pile of dialogs and no
// obvious way back to the one underneath.
let current: FilePreview | null = null;
const listeners = new Set<() => void>();

/** The revision the watcher should compare against.
 *
 * Usually this is the revision on screen. While a reader is scrolling, a
 * freshly arrived reload is held until the active scroll gesture ends,
 * rather than replacing a long document underneath the compositor. The
 * watcher must still move on: asking again with the displayed revision would
 * download the same new file once per tick while the old copy remains visible.
 */
type FilePreviewWatchTarget = Pick<FilePreview, "sourceUuid" | "sourceVersion">;
let watchTarget: FilePreviewWatchTarget | null = null;

/** A completed replacement waiting for the reader to stop scrolling. */
let deferredReplacement: CompleteFilePreview | null = null;

let scrollingPreviewId: string | null = null;

function releaseFileContents(contents: FileContents): void {
  try {
    URL.revokeObjectURL(contents.url);
  } finally {
    contents.retained?.release();
  }
}

function announce(): void {
  for (const listener of listeners) listener();
}

function setWatchTarget(
  sourceUuid: string | null,
  sourceVersion: string | null,
): void {
  if (
    watchTarget?.sourceUuid === sourceUuid &&
    watchTarget.sourceVersion === sourceVersion
  ) {
    return;
  }
  watchTarget = { sourceUuid, sourceVersion };
}

function cancelFilePreviewScroll(): void {
  scrollingPreviewId = null;
}

function revokeDeferredReplacement(): void {
  if (deferredReplacement !== null) {
    releaseFileContents(deferredReplacement.contents);
    deferredReplacement = null;
  }
}

function restoreVisibleWatchTarget(): void {
  if (current === null) {
    watchTarget = null;
    return;
  }
  setWatchTarget(current.sourceUuid, current.sourceVersion);
}

function discardDeferredReplacement(): void {
  cancelFilePreviewScroll();
  revokeDeferredReplacement();
}

function ownCurrentContents(preview: CompleteFilePreview): boolean {
  const contents = preview.contents;
  const retained = ensureRetained(contents);
  if (retained === null) {
    releaseFileContents(contents);
    return false;
  }
  retained.setOwner(RETAINED_DOWNLOAD_PRIORITY.preview, () => {
    if (current?.contents !== contents) return;
    try {
      URL.revokeObjectURL(contents.url);
    } finally {
      current = null;
      watchTarget = null;
      arriving.clear();
      discardDeferredReplacement();
      announce();
    }
  });
  return true;
}

function ownDeferredContents(replacement: CompleteFilePreview): void {
  const contents = replacement.contents;
  const retained = ensureRetained(contents);
  if (retained === null) {
    releaseFileContents(contents);
    if (deferredReplacement?.contents === contents) {
      deferredReplacement = null;
      restoreVisibleWatchTarget();
    }
    return;
  }
  retained.setOwner(RETAINED_DOWNLOAD_PRIORITY.deferredPreview, () => {
    if (deferredReplacement?.contents !== contents) return;
    try {
      URL.revokeObjectURL(contents.url);
    } finally {
      deferredReplacement = null;
      // This copy never became visible. Resume watching from the version the
      // reader can still see so the server does not suppress a needed resend.
      restoreVisibleWatchTarget();
      announce();
    }
  });
}

function applyReplacement(replacement: CompleteFilePreview): void {
  if (current === null || current.id !== replacement.id) {
    releaseFileContents(replacement.contents);
    return;
  }
  if (current.contents !== null) {
    releaseFileContents(current.contents);
  }
  current = replacement;
  if (!ownCurrentContents(replacement)) {
    current = null;
    watchTarget = null;
    arriving.clear();
    discardDeferredReplacement();
  }
  announce();
}

/** Show a file, closing whatever was being shown. */
export function openFilePreview(preview: FilePreview): void {
  if (current?.contents != null) releaseFileContents(current.contents);
  discardDeferredReplacement();
  // Whatever was on its way was for what is being replaced, and a transfer
  // that dies mid-flight is forgotten here rather than blocking that file's
  // watch for the rest of the session.
  arriving.clear();
  current = preview;
  if (preview.contents !== null) {
    if (!ownCurrentContents(preview as CompleteFilePreview)) {
      current = null;
      watchTarget = null;
      announce();
      return;
    }
  }
  setWatchTarget(preview.sourceUuid, preview.sourceVersion);
  announce();
}

/** Fill in the contents of the preview `id`, once they have all arrived.
 *
 * If that preview is no longer on screen -- the reader closed the dialog
 * while the file was still in flight -- the contents are let go rather than
 * shown: a dialog that was dismissed reappearing seconds later would be
 * answering a question the reader has withdrawn.
 *
 * A dialog opened from warmed contents already has something on screen. The
 * arrived transfer replaces it, since the press is always answered with what
 * the file holds *now*, but waits for an active scroll gesture to end before it
 * reparses a long document underneath the reader.
 */
export function resolveFilePreview(id: string, contents: FileContents): void {
  if (current === null || current.id !== id) {
    releaseFileContents(contents);
    return;
  }
  const next: CompleteFilePreview = { ...current, contents };
  if (current.contents !== null && scrollingPreviewId === id) {
    revokeDeferredReplacement();
    deferredReplacement = next;
    ownDeferredContents(next);
    return;
  }

  revokeDeferredReplacement();
  applyReplacement(next);
}

// Sources whose next copy is on the wire. A watch is answered only when the
// file has changed, so silence cannot be told apart from an answer that has
// not finished arriving -- and a file being appended to while it is being
// read is exactly the case where the ask comes round again before the last
// one has landed. Without this, following a large file would pull it once per
// tick instead of once per change.
const arriving = new Set<string>();

/** A reload for this source has started and not yet landed. */
export function reloadIsOnItsWay(sourceUuid: string): boolean {
  return arriving.has(sourceUuid);
}

/** Note a reload transfer's first message, which arrives ahead of its bytes. */
export function noteReloadStarted(sourceUuid: string): void {
  arriving.add(sourceUuid);
}

/** Unwind preview state owned by a transfer that cannot finish.
 *
 * A failed reload leaves the existing contents in place and merely allows the
 * watcher to ask again. A failed initial preview closes only an empty dialog;
 * warmed contents remain useful even if their fresh replacement was corrupt.
 */
export function abortFilePreviewTransfer(
  transferUuid: string,
  sourceUuid: string | null,
): void {
  if (sourceUuid !== null) arriving.delete(sourceUuid);
  if (
    current === null ||
    current.id !== transferUuid ||
    current.contents !== null
  ) {
    return;
  }
  current = null;
  watchTarget = null;
  announce();
}

/** Put a fresher copy of the file into the preview already showing it.
 *
 * The other way contents arrive. `resolveFilePreview` fills in a dialog that
 * was opened empty and is waiting for its file; this replaces the file in a
 * dialog that has one -- because the reader pressed reload, or because the
 * file on disk moved while they were reading it.
 *
 * Addressed to the source rather than to a transfer: the transfer is new
 * every time, and what is being answered is "this button's file", which is
 * what the open preview can be recognised by. A reload for anything else --
 * the reader closed the dialog, or opened a different file, while the bytes
 * were in flight -- is dropped, since a preview that was dismissed reappearing
 * is worse than one that missed an edit.
 *
 * The dialog is not remounted: same `id`, so the document keeps the place the
 * reader had scrolled to and only its contents change underneath.
 */
export function reloadFilePreview({
  sourceUuid,
  filename,
  mimeType,
  sizeBytes,
  contents,
  sourceVersion,
}: FilePreviewReload): void {
  arriving.delete(sourceUuid);
  if (current === null || current.sourceUuid !== sourceUuid) {
    releaseFileContents(contents);
    return;
  }
  const next: CompleteFilePreview = {
    ...current,
    filename,
    mimeType,
    sizeBytes,
    contents,
    sourceVersion,
  };
  setWatchTarget(sourceUuid, sourceVersion);

  if (scrollingPreviewId === current.id) {
    // Only the newest completed copy matters. Keeping the displayed URL alive
    // until the swap also leaves the download control and embedded viewers
    // valid throughout the short hold.
    revokeDeferredReplacement();
    deferredReplacement = next;
    ownDeferredContents(next);
    // The visible snapshot is unchanged, but the watch snapshot moved on.
    announce();
    return;
  }

  revokeDeferredReplacement();
  applyReplacement(next);
}

/** Mark the preview as moving until its scroll frame reports `scrollend`. */
export function beginFilePreviewScroll(id: string): void {
  if (current === null || current.id !== id) return;
  scrollingPreviewId = id;
}

/** Apply the newest replacement held during one completed scroll gesture. */
export function finishFilePreviewScroll(id: string): void {
  if (scrollingPreviewId !== id) return;
  cancelFilePreviewScroll();

  const next = deferredReplacement;
  deferredReplacement = null;
  if (next !== null) applyReplacement(next);
}

/** Files that arrived ahead of their press, newest last.
 *
 * Held as blobs rather than object URLs so there is nothing here to revoke:
 * a dialog that uses one is handed a URL of its own to own. Source identity
 * and version keep same-named or newly changed files from borrowing stale
 * bytes. A handful is a session's worth of preview buttons; past that the
 * oldest is dropped, and its press waits for its own transfer.
 */
const WARMED_LIMIT = 8;
type WarmedFile = {
  filename: string;
  version: string | null;
  retained: RetainedDownload;
};
const warmed = new Map<string, WarmedFile>();

/** Hold a file whose press has not come yet. */
export function warmFilePreview(
  sourceUuid: string,
  filename: string,
  version: string | null,
  retainedOrBlob: RetainedDownload | Blob,
): void {
  const retained =
    retainedOrBlob instanceof Blob
      ? retainedDownloads.retain(retainedOrBlob, {
          priority: RETAINED_DOWNLOAD_PRIORITY.warm,
        })
      : retainedOrBlob;
  if (retained === null || !retained.isActive) return;
  const replaced = warmed.get(sourceUuid);
  if (replaced !== undefined) replaced.retained.release();
  const entry = { filename, version, retained };
  warmed.delete(sourceUuid);
  warmed.set(sourceUuid, entry);
  retained.setOwner(RETAINED_DOWNLOAD_PRIORITY.warm, () => {
    if (warmed.get(sourceUuid) === entry) warmed.delete(sourceUuid);
  });
  if (warmed.size > WARMED_LIMIT) {
    const oldestId = warmed.keys().next().value!;
    const oldest = warmed.get(oldestId)!;
    warmed.delete(oldestId);
    oldest.retained.release();
  }
}

/** Return only the exact source revision the upcoming press announced. */
export function warmedContents(
  sourceUuid: string | null,
  filename: string,
  version: string | null,
): FileContents | null {
  if (sourceUuid === null) return null;
  const entry = warmed.get(sourceUuid);
  if (
    entry === undefined ||
    entry.filename !== filename ||
    entry.version !== version
  ) {
    return null;
  }
  warmed.delete(sourceUuid);
  let url: string;
  try {
    url = URL.createObjectURL(entry.retained.blob);
  } catch {
    entry.retained.release();
    return null;
  }
  const contents = { blob: entry.retained.blob, url, retained: entry.retained };
  // `openFilePreview` immediately takes ownership in production. Until then,
  // the transferred value at least knows how to release its URL if higher
  // priority budget pressure arrives synchronously.
  entry.retained.setOwner(RETAINED_DOWNLOAD_PRIORITY.preview, () =>
    URL.revokeObjectURL(url),
  );
  return contents;
}

/** Clear every resource owned by the current server connection. */
export function resetFilePreviewState(): void {
  arriving.clear();
  for (const entry of warmed.values()) entry.retained.release();
  warmed.clear();
  discardDeferredReplacement();
  watchTarget = null;
  if (current === null) return;
  if (current.contents !== null) releaseFileContents(current.contents);
  current = null;
  announce();
}

/** Close a preview, if it is still the one on screen. */
export function closeFilePreview(id: string): void {
  if (current === null || current.id !== id) return;
  arriving.clear();
  discardDeferredReplacement();
  watchTarget = null;
  if (current.contents !== null) releaseFileContents(current.contents);
  current = null;
  announce();
}

/** The `useSyncExternalStore` half of the above. */
export const filePreviewStore = {
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  snapshot(): FilePreview | null {
    return current;
  },
};

/** The latest source revision, including a reload held off screen. */
export const filePreviewWatchStore = {
  subscribe: filePreviewStore.subscribe,
  snapshot(): FilePreviewWatchTarget | null {
    return watchTarget;
  },
};

/** A byte count as a person would say it. */
export function formatBytes(count: number): string {
  if (count < 1024) return `${count} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let size = count / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(1)} ${units[unit]}`;
}
