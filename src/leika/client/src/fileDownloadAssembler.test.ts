import { describe, expect, it } from "vitest";

import {
  FILE_DOWNLOAD_AGGREGATE_MAX_RECEIVED_PARTS,
  FILE_DOWNLOAD_AGGREGATE_MAX_BYTES,
  FILE_DOWNLOAD_MAX_ACTIVE,
  FILE_DOWNLOAD_MAX_BYTES,
  FILE_DOWNLOAD_MAX_PARTS,
  FILE_DOWNLOAD_MAX_REJECTED_IDS,
  FileDownloadAssembler,
} from "./fileDownloadAssembler";
import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
} from "./WebsocketMessages";

const start = (
  overrides: Partial<FileTransferStartDownload> = {},
): FileTransferStartDownload => ({
  type: "FileTransferStartDownload",
  disposition: "save",
  transfer_uuid: "transfer",
  filename: "file.bin",
  mime_type: "application/octet-stream",
  part_count: 2,
  size_bytes: 3,
  source_uuid: null,
  source_version: null,
  ...overrides,
});

const part = (index: number, bytes: number[]): FileTransferPart => ({
  type: "FileTransferPart",
  source_component_uuid: null,
  transfer_uuid: "transfer",
  part_index: index,
  content: new Uint8Array(bytes),
});

const abort = (reason = "source changed"): FileTransferAbort => ({
  type: "FileTransferAbort",
  transfer_uuid: "transfer",
  reason,
});

describe("FileDownloadAssembler", () => {
  it("assembles validated parts by index", () => {
    const assembler = new FileDownloadAssembler();
    expect(assembler.accept(start())).toEqual({ status: "pending" });
    expect(assembler.accept(part(1, [3]))).toEqual({ status: "pending" });
    const result = assembler.accept(part(0, [1, 2]));
    expect(result).toMatchObject({
      status: "complete",
      metadata: start(),
      parts: [new Uint8Array([1, 2]), new Uint8Array([3])],
    });
    if (result.status === "complete") result.reservation.release();
  });

  it("copies each part out of its potentially much larger frame buffer", () => {
    const assembler = new FileDownloadAssembler();
    const backing = new ArrayBuffer(1024 * 1024);
    const incoming = new Uint8Array(backing, 100, 2);
    incoming.set([4, 5]);
    assembler.accept(start({ part_count: 1, size_bytes: 2 }));
    const result = assembler.accept({
      ...part(0, []),
      content: incoming,
    });

    expect(result).toMatchObject({ status: "complete" });
    if (result.status !== "complete")
      throw new Error("transfer did not finish");
    expect(result.parts[0]).toEqual(new Uint8Array([4, 5]));
    expect(result.parts[0].buffer).not.toBe(backing);
    expect(result.parts[0].buffer.byteLength).toBe(2);
    incoming[0] = 9;
    expect(result.parts[0][0]).toBe(4);
  });

  it("completes a valid empty transfer from its start message", () => {
    const assembler = new FileDownloadAssembler();
    expect(
      assembler.accept(start({ part_count: 0, size_bytes: 0 })),
    ).toMatchObject({ status: "complete", parts: [] });
  });

  it.each([
    ["negative count", { part_count: -1 }],
    ["fractional count", { part_count: 1.5 }],
    ["negative size", { size_bytes: -1 }],
    ["bytes without parts", { part_count: 0, size_bytes: 1 }],
    ["parts without bytes", { part_count: 1, size_bytes: 0 }],
    ["more parts than bytes", { part_count: 4, size_bytes: 3 }],
    ["unknown disposition", { disposition: "open" }],
    ["invalid MIME type", { mime_type: 3 }],
  ])("rejects invalid metadata: %s", (_label, overrides) => {
    const assembler = new FileDownloadAssembler();
    expect(
      assembler.accept(start(overrides as Partial<FileTransferStartDownload>)),
    ).toMatchObject({
      status: "rejected",
    });
  });

  it.each([
    ["empty transfer ID", { transfer_uuid: "" }],
    ["non-string filename", { filename: 3 }],
    ["empty filename", { filename: "" }],
    ["blank filename", { filename: " \t" }],
    ["dot filename", { filename: ".." }],
    ["slash in filename", { filename: "../secret.txt" }],
    ["backslash in filename", { filename: "folder\\file.txt" }],
    ["control in filename", { filename: "bad\nname.txt" }],
    ["format character in filename", { filename: "bad\u200bname.txt" }],
    ["too many filename characters", { filename: "x".repeat(256) }],
    ["too many UTF-8 filename bytes", { filename: "😀".repeat(255) + "x" }],
    ["non-string source ID", { source_uuid: 3 }],
    ["non-string source version", { source_version: 3 }],
  ])("rejects malformed runtime metadata: %s", (_label, overrides) => {
    const assembler = new FileDownloadAssembler();
    expect(
      assembler.accept(
        start(overrides as unknown as Partial<FileTransferStartDownload>),
      ),
    ).toMatchObject({ status: "rejected" });
  });

  it("accepts a Unicode display basename at both documented limits", () => {
    const assembler = new FileDownloadAssembler();
    // 255 characters and 1020 UTF-8 bytes.
    const filename = "😀".repeat(255);
    expect(
      assembler.accept(start({ filename, part_count: 0, size_bytes: 0 })),
    ).toMatchObject({ status: "complete", metadata: { filename } });
  });

  it("returns displaced metadata when a known transfer is rejected", () => {
    const duplicateStart = new FileDownloadAssembler();
    const metadata = start({ disposition: "reload", source_uuid: "button" });
    duplicateStart.accept(metadata);
    expect(duplicateStart.accept(metadata)).toMatchObject({
      status: "rejected",
      metadata,
    });

    const duplicate = new FileDownloadAssembler();
    duplicate.accept(start());
    duplicate.accept(part(0, [1, 2]));
    expect(duplicate.accept(part(0, [1, 2]))).toMatchObject({
      status: "rejected",
    });

    const outOfRange = new FileDownloadAssembler();
    outOfRange.accept(start());
    expect(outOfRange.accept(part(2, [3]))).toMatchObject({
      status: "rejected",
    });
  });

  it("rejects transfers whose chunks disagree with the declared size", () => {
    const tooLarge = new FileDownloadAssembler();
    tooLarge.accept(start({ part_count: 1, size_bytes: 1 }));
    expect(tooLarge.accept(part(0, [1, 2]))).toMatchObject({
      status: "rejected",
    });

    const tooSmall = new FileDownloadAssembler();
    tooSmall.accept(start({ part_count: 1, size_bytes: 3 }));
    expect(tooSmall.accept(part(0, [1, 2]))).toMatchObject({
      status: "rejected",
    });
  });

  it.each([
    ["non-byte content", { content: "not bytes" }],
    ["empty content", { content: new Uint8Array() }],
    ["upload source ID", { source_component_uuid: "button" }],
    ["fractional index", { part_index: 0.5 }],
  ])("rejects and forgets malformed parts: %s", (_label, overrides) => {
    const assembler = new FileDownloadAssembler();
    const metadata = start({ part_count: 1, size_bytes: 1 });
    assembler.accept(metadata);
    const malformed = {
      ...part(0, [1]),
      ...overrides,
    } as unknown as FileTransferPart;
    expect(assembler.accept(malformed)).toMatchObject({
      status: "rejected",
      metadata,
    });
    expect(assembler.accept(part(0, [1]))).toEqual({ status: "ignored" });
  });

  it("checks declared byte bounds before retaining a part", () => {
    const assembler = new FileDownloadAssembler();
    assembler.accept(start({ part_count: 1, size_bytes: 1 }));
    expect(assembler.accept(part(0, [1, 2]))).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("exceed the declared byte size"),
    });
    expect(assembler.accept(part(0, [1]))).toEqual({ status: "ignored" });
  });

  it("validates abort fields and still discards known state", () => {
    const assembler = new FileDownloadAssembler();
    const metadata = start();
    assembler.accept(metadata);
    expect(
      assembler.accept({
        ...abort(),
        reason: 5,
      } as unknown as FileTransferAbort),
    ).toMatchObject({ status: "rejected", metadata });
    expect(assembler.accept(part(0, [1, 2]))).toMatchObject({
      status: "rejected",
      metadata: null,
    });
  });

  it("forgets partial transfers on connection reset", () => {
    const assembler = new FileDownloadAssembler();
    assembler.accept(start());
    assembler.reset();
    expect(assembler.accept(part(0, [1, 2]))).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("without a transfer start"),
    });
  });

  it("returns known metadata and discards state when the server aborts", () => {
    const assembler = new FileDownloadAssembler();
    const metadata = start({ disposition: "reload", source_uuid: "button" });
    assembler.accept(metadata);
    expect(assembler.accept(abort())).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("source changed"),
      metadata,
    });
    expect(assembler.accept(part(0, [1, 2]))).toMatchObject({
      status: "rejected",
      metadata: null,
    });
  });

  it("accepts the exact per-download limit and rejects one byte more", () => {
    const assembler = new FileDownloadAssembler();
    expect(
      assembler.accept(
        start({
          transfer_uuid: "too-large",
          part_count: 1,
          size_bytes: FILE_DOWNLOAD_MAX_BYTES + 1,
        }),
      ),
    ).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("256 MiB"),
    });
    expect(
      assembler.accept(
        start({
          transfer_uuid: "at-limit",
          part_count: 1,
          size_bytes: FILE_DOWNLOAD_MAX_BYTES,
        }),
      ),
    ).toEqual({ status: "pending" });
  });

  it("enforces the exact part-count limit before reservation", () => {
    const assembler = new FileDownloadAssembler();
    expect(
      assembler.accept(
        start({
          transfer_uuid: "at-part-limit",
          part_count: FILE_DOWNLOAD_MAX_PARTS,
          size_bytes: FILE_DOWNLOAD_MAX_PARTS,
        }),
      ),
    ).toEqual({ status: "pending" });
    assembler.accept({ ...abort(), transfer_uuid: "at-part-limit" });

    expect(
      assembler.accept(
        start({
          transfer_uuid: "over-part-limit",
          part_count: FILE_DOWNLOAD_MAX_PARTS + 1,
          size_bytes: FILE_DOWNLOAD_MAX_PARTS + 1,
        }),
      ),
    ).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("65,536"),
    });
    // Neither the terminal boundary transfer nor the rejected start keeps a
    // byte reservation or active slot.
    expect(
      assembler.accept(
        start({
          transfer_uuid: "after-part-limit",
          part_count: 1,
          size_bytes: 1,
        }),
      ),
    ).toEqual({ status: "pending" });
  });

  it("bounds received part objects across simultaneous transfers", () => {
    const assembler = new FileDownloadAssembler();
    const heldPerTransfer = FILE_DOWNLOAD_AGGREGATE_MAX_RECEIVED_PARTS / 2;
    for (const transferUuid of ["aggregate-a", "aggregate-b"]) {
      expect(
        assembler.accept(
          start({
            transfer_uuid: transferUuid,
            part_count: heldPerTransfer + 1,
            size_bytes: heldPerTransfer + 1,
          }),
        ),
      ).toEqual({ status: "pending" });
    }
    for (let index = 0; index < heldPerTransfer; index += 1) {
      for (const transferUuid of ["aggregate-a", "aggregate-b"]) {
        expect(
          assembler.accept({
            ...part(index, [1]),
            transfer_uuid: transferUuid,
          }),
        ).toEqual({ status: "pending" });
      }
    }
    expect(assembler.receivedPartCount).toBe(
      FILE_DOWNLOAD_AGGREGATE_MAX_RECEIVED_PARTS,
    );

    // The next object would exceed the page budget, so its whole transfer is
    // rejected and all of that transfer's prior part tokens are released.
    expect(
      assembler.accept({
        ...part(heldPerTransfer, [1]),
        transfer_uuid: "aggregate-a",
      }),
    ).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("aggregate 65,536"),
    });
    expect(assembler.receivedPartCount).toBe(heldPerTransfer);

    // Once those tokens are gone, the other transfer can finish normally and
    // completion releases every remaining token.
    const completed = assembler.accept({
      ...part(heldPerTransfer, [1]),
      transfer_uuid: "aggregate-b",
    });
    expect(completed).toMatchObject({ status: "complete" });
    expect(assembler.receivedPartCount).toBe(0);
    if (completed.status === "complete") completed.reservation.release();
  });

  it("releases received-part tokens on every state-removal path", () => {
    const assembler = new FileDownloadAssembler();
    const beginPartial = (transferUuid: string) => {
      assembler.accept(
        start({ transfer_uuid: transferUuid, part_count: 2, size_bytes: 2 }),
      );
      assembler.accept({ ...part(0, [1]), transfer_uuid: transferUuid });
      expect(assembler.receivedPartCount).toBe(1);
    };

    beginPartial("aborted");
    assembler.accept({ ...abort(), transfer_uuid: "aborted" });
    expect(assembler.receivedPartCount).toBe(0);

    beginPartial("duplicated-start");
    assembler.accept(
      start({
        transfer_uuid: "duplicated-start",
        part_count: 2,
        size_bytes: 2,
      }),
    );
    expect(assembler.receivedPartCount).toBe(0);

    beginPartial("malformed");
    assembler.accept({ ...part(0, [1]), transfer_uuid: "malformed" });
    expect(assembler.receivedPartCount).toBe(0);

    beginPartial("reset");
    assembler.reset();
    expect(assembler.receivedPartCount).toBe(0);

    assembler.accept(
      start({ transfer_uuid: "complete", part_count: 1, size_bytes: 1 }),
    );
    const complete = assembler.accept({
      ...part(0, [1]),
      transfer_uuid: "complete",
    });
    expect(complete).toMatchObject({ status: "complete" });
    expect(assembler.receivedPartCount).toBe(0);
    if (complete.status === "complete") complete.reservation.release();
  });

  it("accounts for aggregate reservations across every terminal path", () => {
    const assembler = new FileDownloadAssembler();
    expect(FILE_DOWNLOAD_AGGREGATE_MAX_BYTES).toBe(FILE_DOWNLOAD_MAX_BYTES * 2);
    const maximum = (transfer_uuid: string) =>
      start({
        transfer_uuid,
        part_count: 1,
        size_bytes: FILE_DOWNLOAD_MAX_BYTES,
      });

    expect(assembler.accept(maximum("first"))).toEqual({ status: "pending" });
    expect(assembler.accept(maximum("second"))).toEqual({ status: "pending" });
    expect(
      assembler.accept(
        start({ transfer_uuid: "over", part_count: 1, size_bytes: 1 }),
      ),
    ).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("512 MiB"),
    });

    // Abort releases its reservation.
    expect(
      assembler.accept({ ...abort(), transfer_uuid: "first" }),
    ).toMatchObject({ status: "rejected", metadata: maximum("first") });
    expect(
      assembler.accept(
        start({ transfer_uuid: "completed", part_count: 1, size_bytes: 1 }),
      ),
    ).toEqual({ status: "pending" });
    // Completion transfers the reservation; its eventual owner releases it.
    const completed = assembler.accept({
      ...part(0, [1]),
      transfer_uuid: "completed",
    });
    expect(completed).toMatchObject({ status: "complete" });
    if (completed.status === "complete") completed.reservation.release();
    expect(assembler.accept(maximum("third"))).toEqual({ status: "pending" });

    // A duplicate start rejects and releases the displaced reservation.
    expect(assembler.accept(maximum("third"))).toMatchObject({
      status: "rejected",
      metadata: maximum("third"),
    });
    expect(assembler.accept(maximum("fourth"))).toEqual({ status: "pending" });

    // A malformed part also releases its transfer's reservation.
    expect(
      assembler.accept({
        ...part(0, []),
        transfer_uuid: "fourth",
      }),
    ).toMatchObject({ status: "rejected", metadata: maximum("fourth") });
    expect(assembler.accept(maximum("fifth"))).toEqual({ status: "pending" });

    // Reset releases all remaining reservations.
    assembler.reset();
    expect(assembler.accept(maximum("after-reset-1"))).toEqual({
      status: "pending",
    });
    expect(assembler.accept(maximum("after-reset-2"))).toEqual({
      status: "pending",
    });
  });

  it("enforces the active-state limit and releases an aborted slot", () => {
    const assembler = new FileDownloadAssembler();
    for (let index = 0; index < FILE_DOWNLOAD_MAX_ACTIVE; index += 1) {
      expect(
        assembler.accept(
          start({
            transfer_uuid: "active-" + index,
            part_count: 1,
            size_bytes: 1,
          }),
        ),
      ).toEqual({ status: "pending" });
    }
    expect(
      assembler.accept(
        start({ transfer_uuid: "one-too-many", part_count: 1, size_bytes: 1 }),
      ),
    ).toMatchObject({
      status: "rejected",
      reason: expect.stringContaining("too many browser downloads"),
    });
    assembler.accept({ ...abort(), transfer_uuid: "active-0" });
    expect(
      assembler.accept(
        start({ transfer_uuid: "replacement", part_count: 1, size_bytes: 1 }),
      ),
    ).toEqual({ status: "pending" });
  });

  it("requests one peer abort and silently drops rejected trailing parts", () => {
    const assembler = new FileDownloadAssembler();
    const rejected = assembler.accept(
      start({
        transfer_uuid: "too-large",
        part_count: 1,
        size_bytes: FILE_DOWNLOAD_MAX_BYTES + 1,
      }),
    );
    expect(rejected).toMatchObject({
      status: "rejected",
      peerAbort: {
        type: "FileTransferAbort",
        transfer_uuid: "too-large",
        reason: "Browser rejected the file transfer.",
      },
    });

    const trailing = {
      ...part(0, [1]),
      transfer_uuid: "too-large",
    };
    expect(assembler.accept(trailing)).toEqual({ status: "ignored" });
    expect(assembler.accept(trailing)).toEqual({ status: "ignored" });
    // A peer Abort acknowledges cancellation and is never echoed.
    expect(
      assembler.accept({ ...abort(), transfer_uuid: "too-large" }),
    ).toEqual({ status: "ignored" });
  });

  it("bounds and resets rejected-ID tombstones", () => {
    const assembler = new FileDownloadAssembler();
    for (let index = 0; index <= FILE_DOWNLOAD_MAX_REJECTED_IDS; index += 1) {
      expect(
        assembler.accept({
          ...part(0, [1]),
          transfer_uuid: "missing-" + index,
        }),
      ).toMatchObject({ status: "rejected", peerAbort: expect.any(Object) });
    }
    // The oldest tombstone was evicted at the exact bound and can report once
    // more; the newest remains silent.
    expect(
      assembler.accept({ ...part(0, [1]), transfer_uuid: "missing-0" }),
    ).toMatchObject({ status: "rejected", peerAbort: expect.any(Object) });
    expect(
      assembler.accept({
        ...part(0, [1]),
        transfer_uuid: "missing-" + FILE_DOWNLOAD_MAX_REJECTED_IDS,
      }),
    ).toEqual({ status: "ignored" });

    assembler.reset();
    expect(
      assembler.accept({
        ...part(0, [1]),
        transfer_uuid: "missing-" + FILE_DOWNLOAD_MAX_REJECTED_IDS,
      }),
    ).toMatchObject({ status: "rejected", peerAbort: expect.any(Object) });
  });

  it("allows a fresh Start to reuse a previously rejected ID", () => {
    const assembler = new FileDownloadAssembler();
    assembler.accept({ ...part(0, [1]), transfer_uuid: "reused" });
    expect(
      assembler.accept(
        start({ transfer_uuid: "reused", part_count: 1, size_bytes: 1 }),
      ),
    ).toEqual({ status: "pending" });
  });
});
