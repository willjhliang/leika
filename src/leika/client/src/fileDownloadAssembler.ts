import type {
  FileTransferPart,
  FileTransferStartDownload,
} from "./WebsocketMessages";

/** A download whose every part has arrived. */
export interface CompletedFileDownload {
  metadata: FileTransferStartDownload;
  blob: Blob;
}

type PartialDownload = {
  metadata: FileTransferStartDownload;
  parts: Uint8Array<ArrayBuffer>[];
};

/** Assemble one connection's chunked file downloads.
 *
 * The server sends a transfer's parts in order, after its start, on the one
 * socket; the last part joins them into the file. */
export class FileDownloadAssembler {
  private readonly downloads = new Map<string, PartialDownload>();

  /** Take one message, answering with the file once it is complete. */
  accept(
    message: FileTransferStartDownload | FileTransferPart,
  ): CompletedFileDownload | null {
    let download: PartialDownload | undefined;
    if (message.type === "FileTransferStartDownload") {
      download = { metadata: message, parts: [] };
      this.downloads.set(message.transfer_uuid, download);
    } else {
      download = this.downloads.get(message.transfer_uuid);
      if (download === undefined) return null;
      download.parts.push(message.content);
    }
    const { metadata, parts } = download;
    if (parts.length < metadata.part_count) return null;
    this.downloads.delete(metadata.transfer_uuid);
    return { metadata, blob: new Blob(parts, { type: metadata.mime_type }) };
  }

  /** Forget a transfer the server aborted, answering with what it was. */
  abort(transferUuid: string): FileTransferStartDownload | null {
    const download = this.downloads.get(transferUuid);
    this.downloads.delete(transferUuid);
    return download?.metadata ?? null;
  }

  /** Forget every partial transfer when its connection ends. */
  reset(): void {
    this.downloads.clear();
  }
}
