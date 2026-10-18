import { describe, expect, it } from "vitest";

import { FileDownloadAssembler } from "./fileDownloadAssembler";
import {
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

async function bytesOf(blob: Blob | undefined): Promise<number[]> {
  return [...new Uint8Array(await blob!.arrayBuffer())];
}

describe("FileDownloadAssembler", () => {
  it("joins a transfer's parts into one Blob when the last arrives", async () => {
    const assembler = new FileDownloadAssembler();
    expect(assembler.accept(start())).toBeNull();
    expect(assembler.accept(part(0, [1, 2]))).toBeNull();
    const file = assembler.accept(part(1, [3]));

    expect(file?.metadata).toEqual(start());
    expect(file?.blob.type).toBe("application/octet-stream");
    expect(await bytesOf(file?.blob)).toEqual([1, 2, 3]);
    // Completed transfers are forgotten.
    expect(assembler.accept(part(2, [4]))).toBeNull();
  });

  it("completes an empty transfer from its start message", async () => {
    const assembler = new FileDownloadAssembler();
    const file = assembler.accept(start({ part_count: 0, size_bytes: 0 }));
    expect(await bytesOf(file?.blob)).toEqual([]);
  });

  it("answers a server abort with the transfer it ends", () => {
    const assembler = new FileDownloadAssembler();
    const metadata = start({ disposition: "reload", source_uuid: "button" });
    assembler.accept(metadata);
    expect(assembler.abort("transfer")).toEqual(metadata);
    expect(assembler.abort("transfer")).toBeNull();
    expect(assembler.accept(part(0, [1, 2]))).toBeNull();
  });

  it("forgets partial transfers on connection reset", () => {
    const assembler = new FileDownloadAssembler();
    assembler.accept(start({ part_count: 1 }));
    assembler.reset();
    expect(assembler.accept(part(0, [1, 2, 3]))).toBeNull();
  });
});
