import type { Message } from "./WebsocketMessages";
import {
  FileUploadAckBroker,
  FileUploadError,
  FILE_UPLOAD_ACK_TIMEOUT_MS,
} from "./fileUploadAckBroker";

export const FILE_UPLOAD_CHUNK_SIZE_BYTES = 512 * 1024;

export interface FileUploadOptions {
  signal?: AbortSignal;
  ackTimeoutMs?: number;
}

/** Send one file through the connection whose sender is passed in.
 *
 * The server first authorizes the advertised size with ACK 0. Thereafter one
 * part is read and sent per acknowledgement, so at most one part is ever
 * queued between the browser and the server. */
export async function sendFileUpload(
  file: File,
  componentUuid: string,
  transferUuid: string,
  sendMessage: (message: Message) => void,
  acknowledgements: FileUploadAckBroker,
  { signal, ackTimeoutMs = FILE_UPLOAD_ACK_TIMEOUT_MS }: FileUploadOptions = {},
): Promise<void> {
  const partCount = Math.ceil(file.size / FILE_UPLOAD_CHUNK_SIZE_BYTES);
  const upload = acknowledgements.begin(transferUuid, componentUuid);
  const cancel = () =>
    upload.fail(new FileUploadError("Upload cancelled.", true, false));
  signal?.addEventListener("abort", cancel, { once: true });

  try {
    sendMessage({
      type: "FileTransferStartUpload",
      transfer_uuid: transferUuid,
      source_component_uuid: componentUuid,
      filename: file.name,
      mime_type: file.type,
      size_bytes: file.size,
      part_count: partCount,
    });
    await upload.acknowledged(ackTimeoutMs);

    for (let index = 0; index < partCount; index += 1) {
      const start = index * FILE_UPLOAD_CHUNK_SIZE_BYTES;
      const end = Math.min(start + FILE_UPLOAD_CHUNK_SIZE_BYTES, file.size);
      const content = new Uint8Array(
        await file.slice(start, end).arrayBuffer(),
      );
      sendMessage({
        type: "FileTransferPart",
        source_component_uuid: componentUuid,
        transfer_uuid: transferUuid,
        part_index: index,
        content,
      });
      await upload.acknowledged(ackTimeoutMs);
    }
  } catch (cause) {
    const error =
      cause instanceof FileUploadError
        ? cause
        : new FileUploadError("The file could not be uploaded.", true);
    if (error.notifyServer) {
      sendMessage({
        type: "FileTransferAbort",
        transfer_uuid: transferUuid,
        reason: error.message,
      });
    }
    throw error;
  } finally {
    signal?.removeEventListener("abort", cancel);
    upload.finish();
  }
}
