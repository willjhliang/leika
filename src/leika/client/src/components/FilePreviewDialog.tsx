import { DownloadIcon, FileIcon } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  closeFilePreview,
  filePreviewStore,
  formatBytes,
  isReadingKind,
  previewKindFor,
  type FilePreview,
  type PreviewKind,
} from "../filePreview";
import { HintTooltip } from "./common";
import { MarkdownRenderer } from "./MarkdownRenderer";
import { MediaDialog } from "./MediaExpand";

/** Read a textual blob without briefly rendering an empty document. */
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
        className="absolute top-2 right-10"
        render={<a href={url} download={filename} />}
      >
        <DownloadIcon />
        <span className="sr-only">Download {filename}</span>
      </Button>
    </HintTooltip>
  );
}

/** The column a document is read in.
 *
 * Two things make writing readable, and neither is about the file: a measure
 * short enough that the eye finds the start of the next line -- `max-w-prose`,
 * around 65 characters -- and type set for reading rather than for fitting.
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
    <div className="mx-auto w-full max-w-prose px-2 text-[0.9375rem]">
      {children}
    </div>
  );
}

/** Render content within the dialog's fixed preview frame. */
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
      return (
        <ReadingColumn>
          {text === null ? null : <MarkdownRenderer>{text}</MarkdownRenderer>}
        </ReadingColumn>
      );
    case "prose":
      return (
        <ReadingColumn>
          {/* Unrendered writing, so the lines are the author's: monospace,
              a touch smaller than prose that has been typeset, and wrapped
              rather than scrolled because a paragraph is not a record. */}
          <pre className="font-mono text-[0.85em] leading-[1.5] whitespace-pre-wrap">
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

/** How tall the frame holding the file is.
 *
 * Fixed either way, so a preview opens the same size whatever the file turns
 * out to hold -- a one-line log and a thousand-line one are the same window,
 * and nothing jumps as the contents arrive.
 *
 * A document gets everything the window has left: the 6rem taken off is the
 * dialog's margin, its padding and its title bar, so `reading` is the tallest
 * frame that still fits without the dialog itself scrolling. More page per
 * screen is the whole of what a preview is for. Media stops short of that,
 * because a picture or a player is fitted into its frame rather than scrolled
 * through, and the extra height would only be empty space around it.
 */
const FRAME_HEIGHT = {
  reading: "h-[calc(100dvh-6rem)]",
  fitted: "h-[70dvh]",
} as const;

/** Fixed-size dialog shared by every preview type. */
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
      <div
        className={cn(
          "overflow-auto",
          FRAME_HEIGHT[isReadingKind(kind) ? "reading" : "fitted"],
        )}
      >
        <PreviewBody kind={kind} preview={preview} />
      </div>
    </MediaDialog>
  );
}
