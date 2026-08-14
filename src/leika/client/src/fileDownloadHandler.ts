import React from "react";

import { warmMarkdownBlob } from "./components/markdownDocument";
import { toast } from "./components/ui/toast";
import {
  DeferredObjectUrlReleaser,
  downloadObjectUrl,
} from "./deferredObjectUrlReleaser";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import { installFileDownloadLink } from "./fileDownloadLink";
import {
  abortFilePreviewTransfer,
  noteReloadStarted,
  openFilePreview,
  previewKindFor,
  reloadFilePreview,
  resolveFilePreview,
  warmedContents,
  warmFilePreview,
} from "./filePreview";
import { fileDownloadToastOptions } from "./notifications";
import { RETAINED_DOWNLOAD_PRIORITY } from "./retainedDownloadBudget";
import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
} from "./WebsocketMessages";

type FileDownloadMessage =
  FileTransferStartDownload | FileTransferPart | FileTransferAbort;

export interface FileDownloadHandlerRuntime {
  downloads: FileDownloadAssembler;
  savedUrlReleaser: DeferredObjectUrlReleaser;
  sendMessage: (message: FileTransferAbort) => void;
  createBlob: (parts: Uint8Array<ArrayBuffer>[], mimeType: string) => Blob;
  createObjectURL: (blob: Blob) => string;
  revokeObjectURL: (url: string) => void;
  addToast: typeof toast.add;
  closeToast: (id: string) => void;
  document: Document;
}

/** One connection-scoped slot: repeated bad transfers upsert instead of
 * accumulating a toast per attacker-controlled transfer UUID. */
export const FILE_TRANSFER_FAILURE_TOAST_ID = "leika-file-transfer-failure";

export function resetFileTransferFailureToast(): void {
  try {
    toast.close(FILE_TRANSFER_FAILURE_TOAST_ID);
  } catch (error) {
    console.error("Could not close stale file-transfer error:", error);
  }
}

function failCompletedFile(
  metadata: FileTransferStartDownload,
  runtime: FileDownloadHandlerRuntime,
  reason: string,
  error?: unknown,
): void {
  if (error === undefined) console.error(reason);
  else console.error(reason, error);
  abortFilePreviewTransfer(
    metadata.transfer_uuid,
    metadata.disposition === "reload" ? metadata.source_uuid : null,
  );
  try {
    runtime.addToast({
      id: FILE_TRANSFER_FAILURE_TOAST_ID,
      title: "File could not be prepared",
      description: reason,
      type: "error",
      timeout: 8_000,
      data: { closeButton: true },
    });
  } catch (toastError) {
    console.error("Could not show the file-transfer error:", toastError);
  }
}

/** Process one download message with explicit browser side-effect boundaries.
 * Kept outside React lifecycle code so allocation, URL, cancellation, and
 * cleanup failures can be verified without mounting the whole viewer. */
export function handleFileDownloadMessage(
  message: FileDownloadMessage,
  runtime: FileDownloadHandlerRuntime,
): void {
  const result = runtime.downloads.accept(message);
  if (result.status === "ignored") return;
  if (result.status === "rejected") {
    console.error(result.reason);
    if (result.peerAbort !== null) {
      try {
        runtime.sendMessage(result.peerAbort);
      } catch (error) {
        // Cancellation is best effort. A broken transport must not replace the
        // controlled local rejection or stop the rest of this batch.
        console.error("Could not cancel the rejected file transfer:", error);
      }
    }
    if (result.metadata !== null) {
      abortFilePreviewTransfer(
        result.metadata.transfer_uuid,
        result.metadata.disposition === "reload"
          ? result.metadata.source_uuid
          : null,
      );
    }
    return;
  }

  if (message.type === "FileTransferStartDownload") {
    if (message.disposition === "preview") {
      // The dialog opens on the first message rather than the last: its
      // name, viewer and size are all here, so the click is answered now
      // and only the contents wait on the rest of the transfer -- or not
      // even that, when a warm transfer already brought them.
      openFilePreview({
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
    } else if (
      message.disposition === "reload" &&
      message.source_uuid !== null
    ) {
      noteReloadStarted(message.source_uuid);
    }
  }

  if (result.status !== "complete") return;

  const { metadata, parts, reservation } = result;
  let blob: Blob;
  try {
    blob = runtime.createBlob(parts, metadata.mime_type);
  } catch (error) {
    reservation.release();
    failCompletedFile(
      metadata,
      runtime,
      "The browser could not assemble the received file.",
      error,
    );
    return;
  }
  const { filename, disposition, transfer_uuid: transferUuid } = metadata;
  const retained = reservation.retain(blob, {
    priority:
      disposition === "warm"
        ? RETAINED_DOWNLOAD_PRIORITY.warm
        : disposition === "link"
          ? RETAINED_DOWNLOAD_PRIORITY.link
          : disposition === "save"
            ? RETAINED_DOWNLOAD_PRIORITY.save
            : RETAINED_DOWNLOAD_PRIORITY.preview,
    protected: disposition === "save",
  });
  if (retained === null) {
    failCompletedFile(
      metadata,
      runtime,
      "The completed file did not match its reserved byte size.",
    );
    return;
  }

  if (disposition === "warm") {
    // Arrived ahead of its press, so nothing is shown: the file is held
    // for the preview that a press would open, and a markdown document is
    // readied the rest of the way while the reader is elsewhere.
    if (metadata.source_uuid !== null) {
      warmFilePreview(
        metadata.source_uuid,
        filename,
        metadata.source_version,
        retained,
      );
    } else {
      retained.release();
    }
    if (
      metadata.source_uuid !== null &&
      previewKindFor(metadata.mime_type, filename) === "markdown"
    ) {
      warmMarkdownBlob(blob, () => retained.isActive);
    }
    return;
  }

  let url: string;
  try {
    url = runtime.createObjectURL(blob);
  } catch (error) {
    retained.release();
    failCompletedFile(
      metadata,
      runtime,
      "The browser could not create a URL for the received file.",
      error,
    );
    return;
  }
  if (disposition === "save") {
    try {
      downloadObjectUrl(
        url,
        filename,
        runtime.savedUrlReleaser,
        runtime.document,
        () => {
          try {
            runtime.revokeObjectURL(url);
          } finally {
            retained.release();
          }
        },
      );
    } catch (error) {
      console.error("Could not start the file download:", error);
      try {
        runtime.addToast({
          id: FILE_TRANSFER_FAILURE_TOAST_ID,
          title: "Download could not start",
          description: "The browser could not open the file download.",
          type: "error",
          timeout: 8_000,
          data: { closeButton: true },
        });
      } catch (toastError) {
        // A secondary notification failure must not stop the rest of the
        // server's message batch after the URL/Blob owner was already freed.
        console.error("Could not show the download error:", toastError);
      }
    }
    return;
  }

  if (disposition === "reload") {
    const { source_uuid: sourceUuid, source_version: version } = metadata;
    if (sourceUuid === null) {
      runtime.revokeObjectURL(url);
      retained.release();
    } else {
      reloadFilePreview({
        sourceUuid,
        filename,
        mimeType: metadata.mime_type,
        sizeBytes: metadata.size_bytes,
        contents: { url, blob, retained },
        sourceVersion: version,
      });
    }
    return;
  }

  if (disposition === "preview") {
    // The dialog owns the URL until it closes. If it closed while bytes
    // were in flight, resolveFilePreview releases the late URL instead.
    resolveFilePreview(transferUuid, { url, blob, retained });
    return;
  }

  // Otherwise offer the file as a link. Its object URL lives exactly as long
  // as the toast that exposes it.
  const options = fileDownloadToastOptions(filename, url);
  try {
    installFileDownloadLink(retained, {
      revoke: () => runtime.revokeObjectURL(url),
      close: () => runtime.closeToast(transferUuid),
      insert: (releaseLink) =>
        runtime.addToast({
          id: transferUuid,
          title: options.title,
          description: React.createElement(
            "a",
            {
              ...options.link,
              className: "font-medium underline underline-offset-4",
            },
            "Save file",
          ),
          timeout: options.timeout,
          data: options.data,
          onRemove: releaseLink,
        }),
    });
  } catch (error) {
    // The helper has already released the URL and Blob lease. Contain a broken
    // toast manager so the rest of this websocket batch still runs.
    console.error("Could not offer the file download link:", error);
  }
}
