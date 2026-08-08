import type { SendSession } from "./connectionSender";

export const FILE_UPLOAD_CHUNK_SIZE_BYTES = 512 * 1024;

/** Send one file through the connection captured when the upload starts. */
export async function sendFileUpload(
  file: File,
  componentUuid: string,
  transferUuid: string,
  session: SendSession,
): Promise<void> {
  if (!session.isCurrent()) return;
  const numChunks = Math.ceil(file.size / FILE_UPLOAD_CHUNK_SIZE_BYTES);
  session.sendMessage({
    type: "FileTransferStartUpload",
    source_component_uuid: componentUuid,
    transfer_uuid: transferUuid,
    filename: file.name,
    mime_type: file.type,
    size_bytes: file.size,
    part_count: numChunks,
  });

  for (let index = 0; index < numChunks; index++) {
    if (!session.isCurrent()) return;
    const chunk = file.slice(
      index * FILE_UPLOAD_CHUNK_SIZE_BYTES,
      (index + 1) * FILE_UPLOAD_CHUNK_SIZE_BYTES,
    );
    const buffer = await chunk.arrayBuffer();
    if (!session.isCurrent()) return;
    session.sendMessage({
      type: "FileTransferPart",
      source_component_uuid: componentUuid,
      transfer_uuid: transferUuid,
      part_index: index,
      content: new Uint8Array(buffer),
    });
  }
}
