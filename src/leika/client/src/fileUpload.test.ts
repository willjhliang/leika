import { afterEach, describe, expect, it, vi } from "vitest";

import { Message } from "./WebsocketMessages";
import {
  captureSendSession,
  installConnectionBoundSender,
} from "./connectionSender";
import {
  FILE_UPLOAD_CHUNK_SIZE_BYTES,
  FILE_UPLOAD_MAX_BYTES,
  sendFileUpload,
} from "./fileUpload";
import {
  FILE_UPLOAD_MAX_ACTIVE,
  FileUploadAckBroker,
  FileUploadError,
} from "./fileUploadAckBroker";

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

function harness(file: File) {
  const sent: Message[] = [];
  const slot = { sendMessage: () => undefined };
  const broker = new FileUploadAckBroker();
  installConnectionBoundSender(slot, (message) => sent.push(message));
  const session = captureSendSession(slot);
  const upload = sendFileUpload(
    file,
    "upload-button",
    "transfer",
    session,
    broker,
    { ackTimeoutMs: 100 },
  );
  return { broker, sent, session, slot, upload };
}

function ack(
  broker: FileUploadAckBroker,
  transferredBytes: number,
  totalBytes: number,
  overrides: Partial<{
    source_component_uuid: string | null;
    transfer_uuid: string;
  }> = {},
) {
  return broker.acceptAck({
    type: "FileTransferPartAck",
    source_component_uuid: "upload-button",
    transfer_uuid: "transfer",
    transferred_bytes: transferredBytes,
    total_bytes: totalBytes,
    ...overrides,
  });
}

async function nextTurn() {
  await Promise.resolve();
  await Promise.resolve();
}

describe("sendFileUpload", () => {
  afterEach(() => vi.useRealTimers());

  it("waits for authorization and every cumulative ACK before reading again", async () => {
    const size = FILE_UPLOAD_CHUNK_SIZE_BYTES + 1;
    const file = testFile(size);
    const { broker, sent, upload } = harness(file);

    expect(sent.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
    ]);
    expect(file.reads).toBe(0);

    expect(ack(broker, 0, size)).toMatchObject({
      matched: true,
      accepted: true,
    });
    await nextTurn();
    expect(file.reads).toBe(1);
    expect(sent.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
      "FileTransferPart",
    ]);

    ack(broker, FILE_UPLOAD_CHUNK_SIZE_BYTES, size);
    await nextTurn();
    expect(file.reads).toBe(2);
    expect(
      sent.filter((message) => message.type === "FileTransferPart"),
    ).toHaveLength(2);

    ack(broker, size, size);
    await expect(upload).resolves.toBeUndefined();
  });

  it("rejects out-of-order ACKs and reads no more chunks", async () => {
    const size = FILE_UPLOAD_CHUNK_SIZE_BYTES + 1;
    const file = testFile(size);
    const { broker, sent, upload } = harness(file);

    ack(broker, 0, size);
    await nextTurn();
    expect(file.reads).toBe(1);
    expect(ack(broker, size, size)).toMatchObject({
      matched: true,
      accepted: false,
    });

    await expect(upload).rejects.toThrow("invalid upload acknowledgement");
    expect(file.reads).toBe(1);
    expect(sent.at(-1)).toMatchObject({ type: "FileTransferAbort" });
  });

  it("rejects an invalid duplicate delivered with the final ACK", async () => {
    const file = testFile(1);
    const { broker, sent, upload } = harness(file);
    ack(broker, 0, 1);
    await nextTurn();
    expect(ack(broker, 1, 1)).toMatchObject({ accepted: true });
    // Message batches dispatch synchronously before the resolved ACK promise
    // resumes its sender. The broker must retain this terminal protocol error.
    expect(ack(broker, 1, 1)).toMatchObject({ accepted: false });

    await expect(upload).rejects.toThrow("invalid upload acknowledgement");
    expect(sent.at(-1)).toMatchObject({ type: "FileTransferAbort" });
  });

  it("surfaces server aborts and reads no more chunks", async () => {
    const size = FILE_UPLOAD_CHUNK_SIZE_BYTES + 1;
    const file = testFile(size);
    const { broker, upload } = harness(file);

    ack(broker, 0, size);
    await nextTurn();
    expect(file.reads).toBe(1);
    expect(
      broker.acceptAbort({
        type: "FileTransferAbort",
        transfer_uuid: "transfer",
        reason: "File is too large.",
      }),
    ).toEqual({ matched: true, componentUuid: "upload-button" });

    await expect(upload).rejects.toThrow("File is too large.");
    expect(file.reads).toBe(1);
  });

  it("times out authorization, sends an abort, and never reads the Blob", async () => {
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

  it("stops reading and does not send stale parts after connection replacement", async () => {
    const file = testFile(FILE_UPLOAD_CHUNK_SIZE_BYTES + 1);
    const replacementConnection: Message[] = [];
    const { broker, sent, slot, upload } = harness(file);
    ack(broker, 0, file.size);
    installConnectionBoundSender(slot, (message) =>
      replacementConnection.push(message),
    );
    broker.reset();

    await expect(upload).rejects.toThrow("connection changed");
    expect(file.reads).toBe(0);
    expect(sent.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
    ]);
    expect(replacementConnection).toEqual([]);
  });

  it("handles an abort that arrives during a Blob read without sending that part", async () => {
    let finishRead: ((buffer: ArrayBuffer) => void) | undefined;
    let reads = 0;
    const file = {
      name: "slow.bin",
      type: "application/octet-stream",
      size: 1,
      get reads() {
        return reads;
      },
      slice() {
        return {
          arrayBuffer: () => {
            reads += 1;
            return new Promise<ArrayBuffer>((resolve) => {
              finishRead = resolve;
            });
          },
        } as Blob;
      },
    } as TestFile;
    const { broker, sent, upload } = harness(file);
    ack(broker, 0, 1);
    await nextTurn();
    expect(file.reads).toBe(1);
    broker.acceptAbort({
      type: "FileTransferAbort",
      transfer_uuid: "transfer",
      reason: "Upload stopped.",
    });
    finishRead?.(new ArrayBuffer(1));

    await expect(upload).rejects.toThrow("Upload stopped.");
    expect(
      sent.filter((message) => message.type === "FileTransferPart"),
    ).toHaveLength(0);
  });

  it("rejects an oversized selection before advertising or reading it", async () => {
    const file = testFile(FILE_UPLOAD_MAX_BYTES + 1);
    const { sent, upload } = harness(file);

    await expect(upload).rejects.toThrow("64 MiB upload limit");
    expect(file.reads).toBe(0);
    expect(sent).toEqual([]);
  });

  it.each([
    ["path separator", "../secret.txt"],
    ["control character", "bad\nname.txt"],
    ["format character", "bad\u200bname.txt"],
    ["overlong", "x".repeat(256)],
  ])(
    "rejects an invalid filename before advertising or reading: %s",
    async (_label, name) => {
      const file = testFile(1);
      Object.defineProperty(file, "name", { value: name });
      const { sent, upload } = harness(file);

      await expect(upload).rejects.toThrow("invalid name");
      expect(file.reads).toBe(0);
      expect(sent).toEqual([]);
    },
  );

  it.each(["text/plain\n", "text/plain\u007f", "x".repeat(256)])(
    "rejects invalid MIME metadata before advertising: %#",
    async (type) => {
      const file = testFile(1);
      Object.defineProperty(file, "type", { value: type });
      const { sent, upload } = harness(file);

      await expect(upload).rejects.toThrow("invalid MIME type");
      expect(file.reads).toBe(0);
      expect(sent).toEqual([]);
    },
  );

  it("allows an empty browser File.type", async () => {
    const file = testFile(1);
    Object.defineProperty(file, "type", { value: "" });
    const { broker, sent, upload } = harness(file);
    expect(sent[0]).toMatchObject({
      type: "FileTransferStartUpload",
      mime_type: "",
    });
    broker.acceptAbort({
      type: "FileTransferAbort",
      transfer_uuid: "transfer",
      reason: "Test cleanup.",
    });
    await expect(upload).rejects.toThrow("Test cleanup");
  });

  it.each([
    ["component", "bad\ncomponent", "transfer"],
    ["transfer", "upload-button", ""],
    ["overlong transfer", "upload-button", "x".repeat(129)],
  ])(
    "rejects an invalid %s ID before advertising",
    async (_label, component, transfer) => {
      const file = testFile(1);
      const sent: Message[] = [];
      const slot = { sendMessage: () => undefined };
      installConnectionBoundSender(slot, (message) => sent.push(message));
      const upload = sendFileUpload(
        file,
        component,
        transfer,
        captureSendSession(slot),
        new FileUploadAckBroker(),
      );

      await expect(upload).rejects.toThrow(/invalid ID|valid transfer ID/);
      expect(file.reads).toBe(0);
      expect(sent).toEqual([]);
    },
  );

  it.each([
    ["non-string", 5],
    ["overlong", "x".repeat(161)],
    ["control character", "bad\nreason"],
    ["format character", "bad\u200breason"],
  ])("handles a malformed server abort reason: %s", async (_label, reason) => {
    const file = testFile(1);
    const { broker, upload } = harness(file);
    broker.acceptAbort({
      type: "FileTransferAbort",
      transfer_uuid: "transfer",
      reason,
    } as unknown as Parameters<FileUploadAckBroker["acceptAbort"]>[0]);
    await expect(upload).rejects.toThrow("invalid upload rejection");
  });

  it("best-effort aborts if sending the upload start throws", async () => {
    const sent: Message[] = [];
    const slot = { sendMessage: () => undefined };
    const broker = new FileUploadAckBroker();
    installConnectionBoundSender(slot, (message) => {
      sent.push(message);
      if (message.type === "FileTransferStartUpload") {
        throw new Error("start transport failure");
      }
    });
    const file = testFile(1);
    const upload = sendFileUpload(
      file,
      "upload-button",
      "transfer",
      captureSendSession(slot),
      broker,
      { ackTimeoutMs: 100 },
    );

    await expect(upload).rejects.toThrow("could not be uploaded");
    expect(file.reads).toBe(0);
    expect(sent.map((message) => message.type)).toEqual([
      "FileTransferStartUpload",
      "FileTransferAbort",
    ]);
  });

  it("preserves the original failure when best-effort abort sending throws", async () => {
    const sent: Message[] = [];
    const slot = { sendMessage: () => undefined };
    const broker = new FileUploadAckBroker();
    installConnectionBoundSender(slot, (message) => {
      sent.push(message);
      if (message.type === "FileTransferAbort") {
        throw new Error("transport failed");
      }
    });
    const errorLog = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const file = testFile(FILE_UPLOAD_CHUNK_SIZE_BYTES + 1);
    const upload = sendFileUpload(
      file,
      "upload-button",
      "transfer",
      captureSendSession(slot),
      broker,
      { ackTimeoutMs: 100 },
    );
    ack(broker, 0, file.size);
    await nextTurn();
    broker.acceptAck({
      type: "FileTransferPartAck",
      source_component_uuid: "upload-button",
      transfer_uuid: "transfer",
      transferred_bytes: file.size,
      total_bytes: file.size,
    });

    await expect(upload).rejects.toThrow("invalid upload acknowledgement");
    expect(sent.at(-1)).toMatchObject({ type: "FileTransferAbort" });
    expect(errorLog).toHaveBeenCalledWith(
      "Could not abort failed upload:",
      expect.objectContaining({ message: "transport failed" }),
    );
    errorLog.mockRestore();
  });
});

describe("FileUploadAckBroker active-owner bound", () => {
  it("admits the exact boundary and releases capacity on finish", () => {
    const broker = new FileUploadAckBroker();
    const uploads = Array.from({ length: FILE_UPLOAD_MAX_ACTIVE }, (_, index) =>
      broker.begin(`transfer-${index}`, `control-${index}`, 1),
    );

    expect(() => broker.begin("one-too-many", "extra-control", 1)).toThrow(
      "Too many uploads",
    );

    uploads[0].finish();
    expect(() =>
      broker.begin("replacement", "replacement-control", 1),
    ).not.toThrow();
  });

  it("releases every active owner on connection reset", () => {
    const broker = new FileUploadAckBroker();
    for (let index = 0; index < FILE_UPLOAD_MAX_ACTIVE; index += 1) {
      broker.begin(`transfer-${index}`, `control-${index}`, 0);
    }

    broker.reset();

    for (let index = 0; index < FILE_UPLOAD_MAX_ACTIVE; index += 1) {
      expect(() =>
        broker.begin(`new-transfer-${index}`, `new-control-${index}`, 0),
      ).not.toThrow();
    }
  });
});
