import { describe, expect, it } from "vitest";

import { Message } from "./WebsocketMessages";
import {
  captureSendSession,
  installConnectionBoundSender,
} from "./connectionSender";
import { FILE_UPLOAD_CHUNK_SIZE_BYTES, sendFileUpload } from "./fileUpload";

describe("sendFileUpload", () => {
  it("stops reading when its connection is replaced", async () => {
    const firstConnection: Message[] = [];
    const replacementConnection: Message[] = [];
    const slot = { sendMessage: () => undefined };
    installConnectionBoundSender(slot, (message) =>
      firstConnection.push(message),
    );
    const uploadSession = captureSendSession(slot);
    let readCount = 0;
    const file = {
      name: "two-parts.bin",
      type: "application/octet-stream",
      size: FILE_UPLOAD_CHUNK_SIZE_BYTES + 1,
      slice(start: number, end: number) {
        return {
          arrayBuffer: async () => {
            readCount += 1;
            if (readCount === 1) {
              installConnectionBoundSender(slot, (message) =>
                replacementConnection.push(message),
              );
            }
            return new ArrayBuffer(
              Math.min(end, FILE_UPLOAD_CHUNK_SIZE_BYTES + 1) - start,
            );
          },
        } as Blob;
      },
    } as File;

    await sendFileUpload(file, "upload-button", "transfer", uploadSession);

    expect(firstConnection.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
    ]);
    expect(replacementConnection).toEqual([]);
    expect(readCount).toBe(1);
  });
});
