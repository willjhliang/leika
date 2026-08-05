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
    return type === "image/svg+xml" ? "text" : "image";
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

/** One file the server asked this client to look at. */
export interface FilePreview {
  /** The transfer's uuid, which keys the dialog. */
  id: string;
  filename: string;
  mimeType: string;
  sizeBytes: number;
  /** Object URL for the assembled blob. Revoked when the dialog closes. */
  url: string;
  blob: Blob;
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

function announce(): void {
  for (const listener of listeners) listener();
}

/** Show a file, closing whatever was being shown. */
export function openFilePreview(preview: FilePreview): void {
  if (current !== null) URL.revokeObjectURL(current.url);
  current = preview;
  announce();
}

/** Close a preview, if it is still the one on screen. */
export function closeFilePreview(id: string): void {
  if (current === null || current.id !== id) return;
  URL.revokeObjectURL(current.url);
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
