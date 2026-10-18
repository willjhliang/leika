import { afterEach, describe, expect, it, vi } from "vitest";

import { Message } from "./WebsocketMessages";
import { FILE_UPLOAD_CHUNK_SIZE_BYTES, sendFileUpload } from "./fileUpload";
import { FileUploadAckBroker, FileUploadError } from "./fileUploadAckBroker";

type TestFile = File & { reads: number };

function testFile(size: number): TestFile {
  let reads = 0;
  return {
    name: "upload.bin",
    type: "application/octet-stream",
    size,
    get reads() {
      return reads;
    },
    slice(start: number, end: number) {
      return {
        arrayBuffer: async () => {
          reads += 1;
          return new ArrayBuffer(Math.min(end, size) - start);
        },
      } as Blob;
    },
  } as TestFile;
}

function harness(file: File, signal?: AbortSignal) {
  const sent: Message[] = [];
  const broker = new FileUploadAckBroker();
  const upload = sendFileUpload(
    file,
    "upload-button",
    "transfer",
    (message) => sent.push(message),
    broker,
    { ackTimeoutMs: 100, signal },
  );
  return { broker, sent, upload };
}

function ack(broker: FileUploadAckBroker, transferredBytes: number) {
  return broker.acceptAck({
    type: "FileTransferPartAck",
    source_component_uuid: "upload-button",
    transfer_uuid: "transfer",
    transferred_bytes: transferredBytes,
    total_bytes: 0,
  });
}

async function nextTurn() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("sendFileUpload", () => {
  afterEach(() => vi.useRealTimers());

  it("waits for authorization and every acknowledgement before reading again", async () => {
    const size = FILE_UPLOAD_CHUNK_SIZE_BYTES + 1;
    const file = testFile(size);
    const { broker, sent, upload } = harness(file);

    expect(sent.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
    ]);
    expect(file.reads).toBe(0);

    expect(ack(broker, 0)).toBe("upload-button");
    await nextTurn();
    expect(file.reads).toBe(1);
    expect(sent.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
      "FileTransferPart",
    ]);

    ack(broker, FILE_UPLOAD_CHUNK_SIZE_BYTES);
    await nextTurn();
    expect(file.reads).toBe(2);
    const last = sent.at(-1);
    expect(
      last?.type === "FileTransferPart" ? last.content.byteLength : null,
    ).toBe(1);

    ack(broker, size);
    await expect(upload).resolves.toBeUndefined();
    // A finished upload no longer claims the server's replies.
    expect(ack(broker, size)).toBeNull();
  });

  it("surfaces server aborts and reads no more chunks", async () => {
    const file = testFile(FILE_UPLOAD_CHUNK_SIZE_BYTES + 1);
    const { broker, sent, upload } = harness(file);

    ack(broker, 0);
    await nextTurn();
    expect(file.reads).toBe(1);
    expect(
      broker.acceptAbort({
        type: "FileTransferAbort",
        transfer_uuid: "transfer",
        reason: "Upload exceeds the 64 MiB limit.",
      }),
    ).toBe(true);

    await expect(upload).rejects.toThrow("Upload exceeds the 64 MiB limit.");
    expect(file.reads).toBe(1);
    // The server ended it, so there is nothing to abort back.
    expect(sent.at(-1)).toMatchObject({ type: "FileTransferPart" });
  });

  it("times out authorization, sends an abort, and never reads the file", async () => {
    vi.useFakeTimers();
    const file = testFile(1);
    const { sent, upload } = harness(file);
    const result = upload.catch((error: unknown) => error);

    await vi.advanceTimersByTimeAsync(100);
    const error = await result;
    expect(error).toBeInstanceOf(FileUploadError);
    expect((error as Error).message).toContain("did not acknowledge");
    expect(file.reads).toBe(0);
    expect(sent.at(-1)).toMatchObject({ type: "FileTransferAbort" });
  });

  it("fails without an abort when the connection changes", async () => {
    const file = testFile(FILE_UPLOAD_CHUNK_SIZE_BYTES + 1);
    const { broker, sent, upload } = harness(file);
    broker.reset("The connection changed during the upload.");

    await expect(upload).rejects.toThrow("connection changed");
    expect(file.reads).toBe(0);
    expect(sent.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
    ]);
  });

  it("cancels quietly, telling the server to let the transfer go", async () => {
    const file = testFile(1);
    const abort = new AbortController();
    const { sent, upload } = harness(file, abort.signal);
    abort.abort();

    const error = await upload.catch((cause: unknown) => cause);
    expect(error).toMatchObject({ visible: false });
    expect(sent.at(-1)).toMatchObject({ type: "FileTransferAbort" });
  });
});
