import { DownloadIcon, FileIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import {
  closeFilePreview,
  filePreviewStore,
  formatBytes,
  isMediaKind,
  isReadingKind,
  previewKindFor,
  type FileContents,
  type FilePreview,
  type PreviewKind,
} from "../filePreview";
import { HintTooltip } from "./common";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { MediaPreview } from "./MediaPreview";
import { mediaPreviewWidth, useMediaSize } from "./mediaPreviewSize";
import {
  previewMediaClassName,
  usePreviewFullscreen,
} from "./previewFullscreen";

/** Read a textual blob without briefly rendering an empty document.
 *
 * The text lands as a transition: showing a document means parsing it, which
 * for a long file is real work, and work a transition lets React do after the
 * frame around the document has painted rather than before. The dialog is on
 * screen at the click, and the document arrives in it.
 */
function useBlobText(blob: Blob, enabled: boolean): string | null {
  const [text, setText] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!enabled) return;
    let current = true;
    blob.text().then(
      (value) => {
        if (current) React.startTransition(() => setText(value));
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

/** Fallback for file types without an in-browser viewer. */
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

/** Download action beside the dialog's close button. */
function DownloadCorner({ filename, url }: { filename: string; url: string }) {
  return (
    <HintTooltip hint="Download">
      <Button
        variant="ghost"
        size="icon-sm"
        className="absolute top-2 right-18"
        render={<a href={url} download={filename} />}
      >
        <DownloadIcon />
        <span className="sr-only">Download {filename}</span>
      </Button>
    </HintTooltip>
  );
}

/** The measure writing is read at here: short enough that the eye finds the
 * start of the next line, and the width `max-w-prose` is named for. */
const MEASURE = "65ch";

/** The surface a document is read on.
 *
 * Two things make writing readable, and neither is about the file: a measure
 * short enough that the eye finds the start of the next line, and type set for
 * reading rather than for fitting.
 *
 * The measure is named rather than imposed. This is the full width of the
 * popup, and the document lays its own blocks out inside it: prose keeps to a
 * reading column in the middle, and a table, which is not read a line at a
 * time, takes the whole of what the window has. A column clamped here would
 * have taken that choice away from every block at once.
 *
 * The size is the one thing this adds that the panel does not. Body copy in a
 * GUI row is 13px so that it lines up with the inputs around it, which is a
 * size for labels rather than for paragraphs. A preview has no inputs to line
 * up with, so it takes GitHub's 16px less the pixel this UI runs below stock
 * everywhere else. Everything the markdown renderer draws is sized in `em`,
 * so headings, code and tables all follow from this one number.
 */
function ReadingColumn({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="w-full px-2 text-[0.9375rem]"
      style={{ "--measure": MEASURE } as React.CSSProperties}
    >
      {children}
    </div>
  );
}

/** What the popup holds while there is nothing to hold yet: the file still
 * arriving, or a document still being read out of it. One mark for both, so
 * the wait reads as one wait however it is being spent.
 *
 * Fills a document's frame, and carries its own height where there is no
 * frame -- media has none, and a spinner in a box of no height is nothing. */
function PendingBody() {
  return (
    <div className="flex h-full min-h-40 items-center justify-center">
      <Spinner className="text-muted-foreground size-6" />
    </div>
  );
}

/** Render the file, in the frame a document gets and media does not. */
function PreviewBody({
  kind,
  preview,
  contents,
}: {
  kind: PreviewKind;
  preview: FilePreview;
  contents: FileContents;
}) {
  const { filename, mimeType, sizeBytes } = preview;
  const { url, blob } = contents;
  const isTextual = kind === "text" || kind === "prose" || kind === "markdown";
  const text = useBlobText(blob, isTextual);
  const [fullscreen] = usePreviewFullscreen(filename);

  switch (kind) {
    // The three that are shown at their own size. The popup has already been
    // opened at the media's width -- see `mediaPreviewWidth` at the bottom of
    // this file -- so each of these fills it, rather than being centered in
    // something wider with a column of empty dialog down either side.
    case "image":
      return (
        <img
          src={url}
          alt={filename}
          className={previewMediaClassName(fullscreen)}
        />
      );
    case "video":
      return (
        <video
          src={url}
          controls
          className={previewMediaClassName(fullscreen)}
        />
      );
    case "audio":
      // Not sized like the other two: a player is a bar, and stretching it
      // down a full-window popup would only make a taller bar. It keeps the
      // width and stays where a caption would be.
      return <audio src={url} controls className="block w-full" />;
    case "pdf":
      // Let browsers without a PDF viewer render the fallback children.
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
    case "markdown":
      // The spinner from the transfer holds until the document is ready to
      // land whole, in one paint.
      if (text === null) return <PendingBody />;
      return (
        <ReadingColumn>
          <MarkdownRenderer>{text}</MarkdownRenderer>
        </ReadingColumn>
      );
    case "prose":
      return (
        <ReadingColumn>
          {/* Unrendered writing, so the lines are the author's: monospace,
              a touch smaller than prose that has been typeset, and wrapped
              rather than scrolled because a paragraph is not a record. It is
              the whole document, so it holds the measure itself rather than
              leaving blocks to. */}
          <pre className="mx-auto max-w-[var(--measure)] font-mono text-[0.85em] leading-[1.5] whitespace-pre-wrap">
            {text ?? ""}
          </pre>
        </ReadingColumn>
      );
    case "text":
      return (
        // Preserve data and source lines, scrolling horizontally when needed.
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
      // Remount stateful media viewers for each transfer.
      key={preview.id}
      preview={preview}
      onClose={() => closeFilePreview(preview.id)}
    />
  );
}

/** How tall the frame holding a DOCUMENT is.
 *
 * Fixed, so a preview opens the same size whatever the file turns out to hold
 * -- a one-line log and a thousand-line one are the same window, and nothing
 * jumps as the contents arrive. Media has no frame at all; see
 * {@link isMediaKind}.
 *
 * Writing gets everything the window has left: the 6rem taken off is the
 * dialog's margin, its padding and its title bar, so `reading` is the tallest
 * frame that still fits without the dialog itself scrolling. More page per
 * screen is the whole of what a preview is for. The rest stops short of that,
 * because a PDF or a card is looked at rather than read down, and the extra
 * height would only be empty space around it.
 *
 * Full-window, neither guess applies and the frame simply takes the body it
 * is given -- which is the popup less its title bar, measured rather than
 * subtracted.
 */
const FRAME_HEIGHT = {
  reading: "h-[calc(100dvh-6rem)]",
  fitted: "h-[70dvh]",
  fullscreen: "h-full",
} as const;

/** How wide a document opens: as much of the window as it can have, short of
 * the edges. A document has no width of its own to ask for. */
const DOCUMENT_WIDTH = "min(72rem, calc(100vw - 2rem))";

/** A file, in the popup its kind calls for.
 *
 * Media opens at its own size, in the same popup a pane's expand button
 * opens; a document opens in a fixed frame. Which of the two is settled by
 * the name and the MIME type, both of which arrive with the transfer's first
 * message -- so the popup is the right shape from the click, and only the
 * contents wait.
 */
export function FilePreviewDialog({
  preview,
  onClose,
}: {
  preview: FilePreview;
  onClose: () => void;
}) {
  const kind = previewKindFor(preview.mimeType, preview.filename);
  const media = isMediaKind(kind);
  // Only a picture says how big it is. Audio has no size at all, and a
  // video's is not worth a second decode to learn, so both open at the floor.
  const imageSize = useMediaSize(
    kind === "image" ? (preview.contents?.url ?? null) : null,
  );
  // Read rather than passed down: the popup owns the toggle, and the document
  // frame is the one thing inside it that has to know.
  const [fullscreen] = usePreviewFullscreen(preview.filename);

  const body =
    preview.contents === null ? (
      <PendingBody />
    ) : (
      <PreviewBody kind={kind} preview={preview} contents={preview.contents} />
    );

  return (
    <MediaPreview
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={preview.filename}
      // The file's name. A transfer's uuid is new on every press, and the
      // button that sent it is not named on the wire -- but the name is what
      // the transfer announces first, and it is already what a warmed
      // preview is filed under.
      rememberAs={preview.filename}
      width={media ? mediaPreviewWidth(imageSize) : DOCUMENT_WIDTH}
    >
      {preview.contents !== null && (
        <DownloadCorner
          filename={preview.filename}
          url={preview.contents.url}
        />
      )}
      {media ? (
        body
      ) : (
        <div
          className={cn(
            "overflow-auto",
            FRAME_HEIGHT[
              fullscreen
                ? "fullscreen"
                : isReadingKind(kind)
                  ? "reading"
                  : "fitted"
            ],
          )}
        >
          {body}
        </div>
      )}
    </MediaPreview>
  );
}
