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
    // Prose and Markdown use a readable line length.
    case "markdown":
      return (
        <div className="mx-auto w-full max-w-prose px-2">
          {text === null ? null : <MarkdownRenderer>{text}</MarkdownRenderer>}
        </div>
      );
    case "prose":
      return (
        <pre className="mx-auto w-full max-w-prose px-2 font-mono text-xs whitespace-pre-wrap">
          {text ?? ""}
        </pre>
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
      <div className="h-[70dvh] overflow-auto">
        <PreviewBody kind={kind} preview={preview} />
      </div>
    </MediaDialog>
  );
}
