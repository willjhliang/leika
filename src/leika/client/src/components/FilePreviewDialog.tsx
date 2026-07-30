import { DownloadIcon, FileIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  closeFilePreview,
  filePreviewStore,
  formatBytes,
  previewKindFor,
  type FilePreview,
  type PreviewKind,
} from "../filePreview";
import { HintTooltip } from "./common";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { MediaDialog } from "./MediaExpand";

/** The file's text, once it has been read out of the blob.
 *
 * Reading is asynchronous where every other viewer just takes the URL, so the
 * text arrives a frame or two after the dialog opens. `null` is "not yet",
 * which draws nothing rather than an empty document that then jumps.
 */
function useBlobText(blob: Blob, enabled: boolean): string | null {
  const [text, setText] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!enabled) return;
    let current = true;
    blob.text().then(
      (value) => {
        if (current) setText(value);
      },
      () => {
        if (current) setText("");
      },
    );
    return () => {
      current = false;
    };
  }, [blob, enabled]);
  return text;
}

/** A file with no viewer of its own: what it is, and where to go instead.
 *
 * Also where a preview lands when the browser cannot play the codec inside a
 * container it otherwise understands. It carries no download of its own: that
 * control is in the corner for every file, and a second copy of it here would
 * put the same action in two places depending on the type.
 */
function UnsupportedPreview({
  filename,
  mimeType,
  sizeBytes,
}: {
  filename: string;
  mimeType: string;
  sizeBytes: number;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <FileIcon className="text-muted-foreground size-10" />
      <div>
        <p className="text-sm font-medium break-all">{filename}</p>
        <p className="text-muted-foreground text-xs">
          {mimeType} &middot; {formatBytes(sizeBytes)}
        </p>
      </div>
      <p className="text-muted-foreground max-w-sm text-xs">
        There is no viewer for this kind of file. Download it, with the button
        above, to open it in something that knows how.
      </p>
    </div>
  );
}

/** The download control, pinned beside the dialog's close button.
 *
 * Drawn as the close button is -- a ghost icon in the top corner -- because it
 * is the same kind of thing: chrome for the dialog rather than part of the
 * file being shown. Sitting to the left of the X puts it in the one place it
 * can be found whatever the file turns out to be.
 */
function DownloadCorner({ filename, url }: { filename: string; url: string }) {
  return (
    <HintTooltip hint="Download">
      <Button
        variant="ghost"
        size="icon-sm"
        // The close button is `top-2 right-2` and 1.75rem wide, so this clears
        // it by the 0.25rem step the rest of the app is spaced on.
        className="absolute top-2 right-10"
        render={<a href={url} download={filename} />}
      >
        <DownloadIcon />
        <span className="sr-only">Download {filename}</span>
      </Button>
    </HintTooltip>
  );
}

/** What goes inside the frame: whichever viewer the file's kind calls for.
 *
 * Nothing here sets its own size. The frame is one fixed rectangle for every
 * kind -- see {@link FilePreviewDialog} -- so these fill it, fit inside it, or
 * sit at the top of it and scroll.
 */
function PreviewBody({
  kind,
  preview,
}: {
  kind: PreviewKind;
  preview: FilePreview;
}) {
  const { filename, mimeType, sizeBytes, url, blob } = preview;
  const isTextual = kind === "text" || kind === "prose" || kind === "markdown";
  const text = useBlobText(blob, isTextual);

  switch (kind) {
    case "image":
      // Fits the frame rather than filling it: an icon stays an icon instead
      // of being blown up to the width of the dialog.
      return (
        <div className="flex h-full items-center justify-center">
          <img
            src={url}
            alt={filename}
            className="max-h-full max-w-full rounded-lg object-contain"
          />
        </div>
      );
    case "video":
      return (
        <div className="flex h-full items-center justify-center">
          <video src={url} controls className="max-h-full w-full rounded-lg" />
        </div>
      );
    case "audio":
      return (
        <div className="flex h-full items-center justify-center">
          <audio src={url} controls className="w-full max-w-prose" />
        </div>
      );
    case "pdf":
      // An object, not an iframe: a browser with no PDF viewer falls through
      // to the children instead of drawing an empty white rectangle.
      return (
        <object
          data={url}
          type="application/pdf"
          className="h-full w-full rounded-lg"
        >
          <UnsupportedPreview
            filename={filename}
            mimeType={mimeType}
            sizeBytes={sizeBytes}
          />
        </object>
      );
    // Prose is read line after line, and a line run to the width this dialog
    // wants for images is hard to carry your eye back along. Markdown and
    // plain text take a measure -- 65ch, which is what `prose` is -- with the
    // margins a page would give them.
    case "markdown":
      return (
        <div className="mx-auto w-full max-w-prose px-2">
          {text === null ? null : <MarkdownRenderer>{text}</MarkdownRenderer>}
        </div>
      );
    case "prose":
      return (
        // Wrapped to the measure rather than scrolling past it: a paragraph
        // of plain text is often one long line, and the column is the point.
        <pre className="mx-auto w-full max-w-prose px-2 font-mono text-xs whitespace-pre-wrap">
          {text ?? ""}
        </pre>
      );
    case "text":
      return (
        // Source and data, where a row is a record rather than a sentence:
        // the width is there to be used, and a long line scrolls rather than
        // being read in pieces.
        <pre className="bg-muted/40 min-h-full w-full overflow-x-auto rounded-lg p-4 font-mono text-xs whitespace-pre">
          {text ?? ""}
        </pre>
      );
    case "unsupported":
      return (
        <UnsupportedPreview
          filename={filename}
          mimeType={mimeType}
          sizeBytes={sizeBytes}
        />
      );
  }
}

/** Mount point for previews, one per app. */
export function FilePreviewHost() {
  const preview = React.useSyncExternalStore(
    filePreviewStore.subscribe,
    filePreviewStore.snapshot,
    filePreviewStore.snapshot,
  );
  if (preview === null) return null;
  return (
    <FilePreviewDialog
      // Keyed by transfer so switching files rebuilds the viewers rather than
      // handing a new URL to a <video> that is already playing another.
      key={preview.id}
      preview={preview}
      onClose={() => closeFilePreview(preview.id)}
    />
  );
}

/** The dialog a previewed file opens in.
 *
 * Built on the same {@link MediaDialog} an expanded image or plot uses, so a
 * preview is the size and shape of every other large thing in the app. The
 * title is shown here where an expanded pane's is not: a file has a name, and
 * the name is half of what a preview is telling you.
 *
 * One rectangle, the same for every file: a fixed width and a fixed height,
 * with the viewer filling, fitting or scrolling inside it. Sized to its
 * contents instead, a one-line file would open a sliver of a dialog and the
 * next a tall one, moving the close button every time -- and the type of the
 * file would be deciding the shape of the window, which is not something the
 * reader asked about.
 */
export function FilePreviewDialog({
  preview,
  onClose,
}: {
  preview: FilePreview;
  onClose: () => void;
}) {
  const kind = previewKindFor(preview.mimeType, preview.filename);
  return (
    <MediaDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={preview.filename}
      showTitle
      width="min(72rem, calc(100vw - 2rem))"
    >
      <DownloadCorner filename={preview.filename} url={preview.url} />
      <div className="h-[70dvh] overflow-auto">
        <PreviewBody kind={kind} preview={preview} />
      </div>
    </MediaDialog>
  );
}
