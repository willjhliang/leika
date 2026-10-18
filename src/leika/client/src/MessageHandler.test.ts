import { afterEach, describe, expect, it, vi } from "vitest";

import { handleFileDownloadMessage } from "./fileDownloadHandler";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import {
  filePreviewStore,
  openFilePreview,
  reloadIsOnItsWay,
  requestFilePreview,
  resetFilePreviewState,
} from "./filePreview";
import {
  FileTransferPart,
  FileTransferStartDownload,
} from "./WebsocketMessages";

const start = (
  overrides: Partial<FileTransferStartDownload> = {},
): FileTransferStartDownload => ({
  type: "FileTransferStartDownload",
  disposition: "preview",
  transfer_uuid: "transfer",
  filename: "notes.md",
  mime_type: "text/markdown",
  part_count: 1,
  size_bytes: 1,
  source_uuid: "button",
  source_version: "1",
  ...overrides,
});

const part = (
  transferUuid = "transfer",
  index = 0,
  content = [1],
): FileTransferPart => ({
  type: "FileTransferPart",
  source_component_uuid: null,
  transfer_uuid: transferUuid,
  part_index: index,
  content: new Uint8Array(content),
});

afterEach(() => {
  resetFilePreviewState();
  vi.restoreAllMocks();
});

describe("handleFileDownloadMessage", () => {
  it("fills the preview its click opened once the last part arrives", async () => {
    const downloads = new FileDownloadAssembler();
    requestFilePreview("button", "Notes");
    handleFileDownloadMessage(
      start({ part_count: 2, size_bytes: 2 }),
      downloads,
    );
    handleFileDownloadMessage(part(), downloads);
    expect(filePreviewStore.snapshot()?.contents).toBeNull();

    handleFileDownloadMessage(part("transfer", 1, [2]), downloads);
    const contents = filePreviewStore.snapshot()?.contents;
    expect(contents?.blob.type).toBe("text/markdown");
    expect([...new Uint8Array(await contents!.blob.arrayBuffer())]).toEqual([
      1, 2,
    ]);
  });

  it("unwinds an empty preview and a pending reload when the server aborts", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const downloads = new FileDownloadAssembler();
    requestFilePreview("button", "Notes");
    handleFileDownloadMessage(start(), downloads);
    handleFileDownloadMessage(
      { type: "FileTransferAbort", transfer_uuid: "transfer", reason: "gone" },
      downloads,
    );
    expect(filePreviewStore.snapshot()).toBeNull();
    // The aborted transfer's late part has nothing left to join.
    handleFileDownloadMessage(part(), downloads);
    expect(filePreviewStore.snapshot()).toBeNull();

    openFilePreview({
      id: "visible",
      filename: "notes.md",
      mimeType: "text/markdown",
      sizeBytes: 1,
      contents: null,
      sourceUuid: "button",
      sourceVersion: "1",
    });
    handleFileDownloadMessage(
      start({ disposition: "reload", transfer_uuid: "reload" }),
      downloads,
    );
    expect(reloadIsOnItsWay("button")).toBe(true);
    handleFileDownloadMessage(
      { type: "FileTransferAbort", transfer_uuid: "reload", reason: "gone" },
      downloads,
    );
    expect(reloadIsOnItsWay("button")).toBe(false);
  });
});
