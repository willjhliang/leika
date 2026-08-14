import type { SendSession } from "./connectionSender";
import {
  validFileTransferFilename,
  validFileTransferIdentifier,
  validFileTransferMimeType,
} from "./fileTransferValidation";
import {
  FileUploadAckBroker,
  FileUploadError,
  FILE_UPLOAD_ACK_TIMEOUT_MS,
} from "./fileUploadAckBroker";

export const FILE_UPLOAD_CHUNK_SIZE_BYTES = 512 * 1024;
/** Matches the server's per-transfer reservation limit. Reject locally before
 * asking the browser to read any bytes or advertising an upload the server
 * cannot accept. */
export const FILE_UPLOAD_MAX_BYTES = 64 * 1024 * 1024;

export interface FileUploadOptions {
  signal?: AbortSignal;
  ackTimeoutMs?: number;
}

function connectionChanged(): FileUploadError {
  return new FileUploadError(
    "The connection changed during the upload.",
    false,
  );
}

/** Send one file through the connection captured when the upload starts.
 *
 * The server first authorizes the advertised size with ACK 0. Thereafter one
 * part is read and sent per exact cumulative ACK, bounding queued copies in
 * the browser worker, WebSocket implementation, and server. */
export async function sendFileUpload(
  file: File,
  componentUuid: string,
  transferUuid: string,
  session: SendSession,
  acknowledgements: FileUploadAckBroker,
  { signal, ackTimeoutMs = FILE_UPLOAD_ACK_TIMEOUT_MS }: FileUploadOptions = {},
): Promise<void> {
  if (!session.isCurrent()) throw connectionChanged();
  if (!Number.isSafeInteger(file.size) || file.size < 0) {
    throw new FileUploadError("The selected file has an invalid size.", false);
  }
  if (file.size > FILE_UPLOAD_MAX_BYTES) {
    throw new FileUploadError(
      "The selected file is larger than the 64 MiB upload limit.",
      false,
    );
  }
  if (!validFileTransferFilename(file.name)) {
    throw new FileUploadError("The selected file has an invalid name.", false);
  }
  if (!validFileTransferMimeType(file.type)) {
    throw new FileUploadError(
      "The selected file has an invalid MIME type.",
      false,
    );
  }
  if (!validFileTransferIdentifier(componentUuid)) {
    throw new FileUploadError("The upload control has an invalid ID.", false);
  }
  if (!validFileTransferIdentifier(transferUuid)) {
    throw new FileUploadError(
      "The upload could not create a valid transfer ID.",
      false,
    );
  }
  const numChunks = Math.ceil(file.size / FILE_UPLOAD_CHUNK_SIZE_BYTES);
  const upload = acknowledgements.begin(transferUuid, componentUuid, file.size);
  const cancelled = new FileUploadError("Upload cancelled.", true, false);
  const cancel = () => upload.cancel(cancelled);
  signal?.addEventListener("abort", cancel, { once: true });
  let started = false;

  try {
    if (signal?.aborted) throw cancelled;
    // Install the waiter before sending so even an immediate server response
    // cannot race ahead of its owner.
    const authorization = upload.waitForAck(0, ackTimeoutMs);
    // `sendMessage` is synchronous by contract, but a hostile transport stub
    // can throw before the awaited line. Attach rejection ownership now so
    // cancelling the waiter in that path cannot become unhandled.
    void authorization.catch(() => undefined);
    started = true;
    session.sendMessage({
      type: "FileTransferStartUpload",
      transfer_uuid: transferUuid,
      source_component_uuid: componentUuid,
      filename: file.name,
      mime_type: file.type,
      size_bytes: file.size,
      part_count: numChunks,
    });
    await authorization;

    let transferredBytes = 0;
    for (let index = 0; index < numChunks; index += 1) {
      if (!session.isCurrent()) throw connectionChanged();
      if (signal?.aborted) throw cancelled;
      const start = index * FILE_UPLOAD_CHUNK_SIZE_BYTES;
      const end = Math.min(
        (index + 1) * FILE_UPLOAD_CHUNK_SIZE_BYTES,
        file.size,
      );
      let buffer: ArrayBuffer;
      try {
        buffer = await file.slice(start, end).arrayBuffer();
      } catch (cause) {
        console.error("Could not read upload chunk:", cause);
        throw new FileUploadError("The selected file could not be read.", true);
      }
      if (!session.isCurrent()) throw connectionChanged();
      if (signal?.aborted) throw cancelled;
      if (buffer.byteLength !== end - start) {
        throw new FileUploadError(
          "The selected file changed while it was being read.",
          true,
        );
      }

      transferredBytes += buffer.byteLength;
      const partAck = upload.waitForAck(transferredBytes, ackTimeoutMs);
      void partAck.catch(() => undefined);
      session.sendMessage({
        type: "FileTransferPart",
        source_component_uuid: componentUuid,
        transfer_uuid: transferUuid,
        part_index: index,
        content: new Uint8Array(buffer),
      });
      await partAck;
    }
    upload.complete();
  } catch (cause) {
    const error =
      cause instanceof FileUploadError
        ? cause
        : new FileUploadError("The file could not be uploaded.", true);
    upload.cancel(error);
    if (started && error.notifyServer && session.isCurrent()) {
      try {
        session.sendMessage({
          type: "FileTransferAbort",
          transfer_uuid: transferUuid,
          reason: error.message,
        });
      } catch (abortError) {
        // Releasing the server reservation is best effort. A failing transport
        // must not replace the controlled read/timeout/protocol error.
        console.error("Could not abort failed upload:", abortError);
      }
    }
    throw error;
  } finally {
    signal?.removeEventListener("abort", cancel);
    upload.finish();
  }
}
