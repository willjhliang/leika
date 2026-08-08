import { describe, expect, it } from "vitest";

import { FileDownloadAssembler } from "./fileDownloadAssembler";
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
    expect(assembler.accept(part(0, [1, 2]))).toEqual({
      status: "complete",
      metadata: start(),
      parts: [new Uint8Array([1, 2]), new Uint8Array([3])],
    });
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
  ])("rejects invalid metadata: %s", (_label, overrides) => {
    const assembler = new FileDownloadAssembler();
    expect(assembler.accept(start(overrides))).toMatchObject({
      status: "rejected",
    });
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
});
