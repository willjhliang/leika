import { createElement } from "react";

import { warmMarkdownBlob } from "./components/markdownDocument";
import { toast } from "./components/ui/toast";
import type { FileDownloadAssembler } from "./fileDownloadAssembler";
import {
  abortFilePreviewTransfer,
  acceptFilePreview,
  noteReloadStarted,
  previewKindFor,
  receiveFilePreviewPart,
  reloadFilePreview,
  resolveFilePreview,
  warmedContents,
  warmFilePreview,
} from "./filePreview";
import { fileDownloadToastOptions } from "./notifications";
import type {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
} from "./WebsocketMessages";

/** How long a saved file's URL outlives the click that saves it: Firefox and
 * Safari read the file after the click has returned. */
const SAVE_URL_REVOKE_DELAY_MS = 1_000;

/** Process one download message: assemble the file, then hand it to whoever
 * asked for it -- a preview, the warm cache, a save, or a link. */
export function handleFileDownloadMessage(
  message: FileTransferStartDownload | FileTransferPart | FileTransferAbort,
  downloads: FileDownloadAssembler,
): void {
  if (message.type === "FileTransferAbort") {
    const metadata = downloads.abort(message.transfer_uuid);
    console.error(
      `File transfer ${message.transfer_uuid} was aborted: ${message.reason}`,
    );
    if (metadata !== null) {
      abortFilePreviewTransfer(
        metadata.transfer_uuid,
        metadata.disposition === "reload" ? metadata.source_uuid : null,
      );
    }
    return;
  }

  if (message.type === "FileTransferStartDownload") {
    if (message.disposition === "preview") {
      // Button previews are already open locally. Metadata fills in that
      // popup after server preparation; it cannot reopen a dismissed click.
      acceptFilePreview({
        id: message.transfer_uuid,
        filename: message.filename,
        mimeType: message.mime_type,
        sizeBytes: message.size_bytes,
        contents: warmedContents(
          message.source_uuid,
          message.filename,
          message.source_version,
        ),
        sourceUuid: message.source_uuid,
        sourceVersion: message.source_version,
      });
    } else if (message.disposition === "reload") {
      noteReloadStarted(message.source_uuid!);
    }
  } else if (message.part_index === 0) {
    receiveFilePreviewPart(message.transfer_uuid, message.content);
  }

  const file = downloads.accept(message);
  if (file === null) return;
  const { metadata, blob } = file;
  const { filename, disposition, transfer_uuid: transferUuid } = metadata;
  // A warm file or a reload always names the preview button it answers.
  const sourceUuid = metadata.source_uuid;

  if (disposition === "warm") {
    // Arrived ahead of its press, so nothing is shown: the file is held for
    // the preview that a press would open, and a markdown document is readied
    // the rest of the way while the reader is elsewhere.
    warmFilePreview(sourceUuid!, filename, metadata.source_version, blob);
    if (previewKindFor(metadata.mime_type, filename) === "markdown") {
      warmMarkdownBlob(blob);
    }
    return;
  }

  const url = URL.createObjectURL(blob);
  switch (disposition) {
    case "save": {
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), SAVE_URL_REVOKE_DELAY_MS);
      return;
    }
    case "reload":
      reloadFilePreview({
        sourceUuid: sourceUuid!,
        filename,
        mimeType: metadata.mime_type,
        sizeBytes: metadata.size_bytes,
        contents: { url, blob },
        sourceVersion: metadata.source_version,
      });
      return;
    case "preview":
      // The dialog owns the URL until it closes. If it closed while bytes
      // were in flight, resolveFilePreview releases the late URL instead.
      resolveFilePreview(transferUuid, { url, blob });
      return;
    case "link": {
      // The link's URL lives exactly as long as the toast that offers it.
      const options = fileDownloadToastOptions(filename, url);
      toast.add({
        id: transferUuid,
        title: options.title,
        description: createElement(
          "a",
          {
            ...options.link,
            className: "font-medium underline underline-offset-4",
          },
          "Save file",
        ),
        timeout: options.timeout,
        data: options.data,
        onRemove: () => URL.revokeObjectURL(url),
      });
      return;
    }
  }
}
