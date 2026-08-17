import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FILE_TRANSFER_FAILURE_TOAST_ID,
  type FileDownloadHandlerRuntime,
  handleFileDownloadMessage,
} from "./fileDownloadHandler";
import { DeferredObjectUrlReleaser } from "./deferredObjectUrlReleaser";
import {
  FILE_DOWNLOAD_MAX_BYTES,
  FileDownloadAssembler,
} from "./fileDownloadAssembler";
import {
  filePreviewStore,
  openFilePreview,
  reloadIsOnItsWay,
  resetFilePreviewState,
  resolveFilePreview,
} from "./filePreview";
import { retainedDownloads } from "./retainedDownloadBudget";
import { filterPageStreamMessages } from "./pageStreamProjection";
import {
  FileTransferPart,
  FileTransferStartDownload,
  Message,
} from "./WebsocketMessages";
import type { ViewportState } from "./viewport/ViewportState";

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

const part = (transferUuid = "transfer"): FileTransferPart => ({
  type: "FileTransferPart",
  source_component_uuid: null,
  transfer_uuid: transferUuid,
  part_index: 0,
  content: new Uint8Array([1]),
});

const paneUpdate = (pageId: string, title: string): Message => ({
  type: "ViewportPaneUpdateMessage",
  page_id: pageId,
  pane_id: "pane",
  updates: { title },
});

function pageStreamState({
  pageId = "a",
  generation = 3,
  accepting = false,
}: {
  pageId?: string;
  generation?: number;
  accepting?: boolean;
} = {}): ViewportState {
  return {
    pages: Object.create(null) as ViewportState["pages"],
    pageOrder: ["a", "b"],
    activePageId: pageId,
    displayPageId: null,
    warmPage: null,
    transitionPage: null,
    catalogReady: true,
    pageStream: {
      pageId,
      generation,
      accepting,
      ready: false,
    },
    interactionEpoch: 0,
  };
}

function runtime(
  overrides: Partial<FileDownloadHandlerRuntime> = {},
): FileDownloadHandlerRuntime {
  return {
    downloads: new FileDownloadAssembler(retainedDownloads),
    savedUrlReleaser: new DeferredObjectUrlReleaser(() => undefined),
    sendMessage: vi.fn(),
    createBlob: (parts, mimeType) => new Blob(parts, { type: mimeType }),
    createObjectURL: () => "blob:download",
    revokeObjectURL: vi.fn(),
    addToast: vi.fn() as FileDownloadHandlerRuntime["addToast"],
    closeToast: vi.fn(),
    document: {} as Document,
    ...overrides,
  };
}

afterEach(() => {
  resetFilePreviewState();
  retainedDownloads.evictAll();
  vi.restoreAllMocks();
});

describe("filterPageStreamMessages", () => {
  it("drops A-to-B-to-A stale payloads until the matching generation begins", () => {
    const messages: Message[] = [
      { type: "PageStreamBeginMessage", page_id: "a", generation: 1 },
      paneUpdate("a", "stale-a"),
      { type: "PageStreamReadyMessage", page_id: "a", generation: 1 },
      { type: "PageStreamBeginMessage", page_id: "b", generation: 2 },
      paneUpdate("b", "stale-b"),
      { type: "PageStreamReadyMessage", page_id: "b", generation: 2 },
      { type: "PageStreamBeginMessage", page_id: "a", generation: 3 },
      paneUpdate("a", "current-a"),
      paneUpdate("b", "inactive-b"),
      { type: "PageStreamReadyMessage", page_id: "a", generation: 3 },
      {
        type: "PageUpdateMessage",
        page_id: "a",
        name: "Renamed globally",
      },
    ];

    const filtered = filterPageStreamMessages(messages, pageStreamState());
    expect(
      filtered.flatMap((message) =>
        message.type === "ViewportPaneUpdateMessage"
          ? [message.updates.title]
          : [],
      ),
    ).toEqual(["current-a"]);
    expect(filtered.at(-1)?.type).toBe("PageUpdateMessage");
  });

  it("closes batch-local acceptance on wrong-page and stale-generation begins", () => {
    const messages: Message[] = [
      paneUpdate("a", "live-before-marker"),
      { type: "PageStreamBeginMessage", page_id: "b", generation: 2 },
      paneUpdate("a", "after-wrong-page-begin"),
      { type: "PageStreamBeginMessage", page_id: "a", generation: 3 },
      paneUpdate("a", "after-current-begin"),
      { type: "PageStreamBeginMessage", page_id: "a", generation: 1 },
      paneUpdate("a", "after-stale-begin"),
      { type: "PageStreamBeginMessage", page_id: "a", generation: 3 },
      paneUpdate("a", "after-current-reopen"),
    ];

    const filtered = filterPageStreamMessages(
      messages,
      pageStreamState({ accepting: true }),
    );
    expect(
      filtered.flatMap((message) =>
        message.type === "ViewportPaneUpdateMessage"
          ? [message.updates.title]
          : [],
      ),
    ).toEqual([
      "live-before-marker",
      "after-current-begin",
      "after-current-reopen",
    ]);
  });
});

describe("handleFileDownloadMessage", () => {
  it("upserts one bounded error toast during a stream of failed files", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const addToast = vi.fn<FileDownloadHandlerRuntime["addToast"]>();
    const env = runtime({
      addToast,
      createBlob: () => {
        throw new Error("allocation failed");
      },
    });
    for (const transferUuid of ["first", "second", "third"]) {
      handleFileDownloadMessage(start({ transfer_uuid: transferUuid }), env);
      handleFileDownloadMessage(part(transferUuid), env);
    }

    expect(addToast).toHaveBeenCalledTimes(3);
    for (const [options] of addToast.mock.calls) {
      expect(options.id).toBe(FILE_TRANSFER_FAILURE_TOAST_ID);
    }
  });

  it("sends one bounded Abort and silently drops rejected trailing parts", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const sendMessage = vi.fn();
    const env = runtime({ sendMessage });
    handleFileDownloadMessage(
      start({
        transfer_uuid: "too-large",
        size_bytes: FILE_DOWNLOAD_MAX_BYTES + 1,
      }),
      env,
    );
    handleFileDownloadMessage(part("too-large"), env);
    handleFileDownloadMessage(part("too-large"), env);

    expect(sendMessage).toHaveBeenCalledOnce();
    expect(sendMessage).toHaveBeenCalledWith({
      type: "FileTransferAbort",
      transfer_uuid: "too-large",
      reason: "Browser rejected the file transfer.",
    });
  });

  it("contains a transport failure while cancelling a rejected transfer", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const env = runtime({
      sendMessage: () => {
        throw new Error("socket failed");
      },
    });
    expect(() =>
      handleFileDownloadMessage(
        start({ size_bytes: FILE_DOWNLOAD_MAX_BYTES + 1 }),
        env,
      ),
    ).not.toThrow();
    expect(consoleError).toHaveBeenCalledWith(
      "Could not cancel the rejected file transfer:",
      expect.any(Error),
    );
  });

  it("never echoes a server-originated Abort", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const sendMessage = vi.fn();
    const env = runtime({ sendMessage });
    handleFileDownloadMessage(start(), env);
    handleFileDownloadMessage(
      {
        type: "FileTransferAbort",
        transfer_uuid: "transfer",
        reason: "source changed",
      },
      env,
    );
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("closes an initial preview when Blob construction fails", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const addToast = vi.fn() as FileDownloadHandlerRuntime["addToast"];
    const env = runtime({
      addToast,
      createBlob: () => {
        throw new Error("allocation failed");
      },
    });
    handleFileDownloadMessage(start(), env);
    expect(filePreviewStore.snapshot()?.contents).toBeNull();

    handleFileDownloadMessage(part(), env);

    expect(filePreviewStore.snapshot()).toBeNull();
    expect(retainedDownloads.sizeBytes).toBe(0);
    expect(addToast).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "File could not be prepared",
        description: "The browser could not assemble the received file.",
      }),
    );
  });

  it("unblocks reload watching when object-URL construction fails", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    openFilePreview({
      id: "visible",
      filename: "notes.md",
      mimeType: "text/markdown",
      sizeBytes: 1,
      contents: null,
      sourceUuid: "button",
      sourceVersion: "1",
    });
    resolveFilePreview("visible", {
      blob: new Blob(["x"]),
      url: "blob:visible",
    });
    const env = runtime({
      createObjectURL: () => {
        throw new Error("URL allocation failed");
      },
    });
    handleFileDownloadMessage(
      start({
        disposition: "reload",
        transfer_uuid: "reload-transfer",
        source_version: "2",
      }),
      env,
    );
    expect(reloadIsOnItsWay("button")).toBe(true);

    handleFileDownloadMessage(part("reload-transfer"), env);

    expect(reloadIsOnItsWay("button")).toBe(false);
    expect(filePreviewStore.snapshot()?.id).toBe("visible");
    expect(retainedDownloads.ownerCount).toBe(1);
  });

  it("contains save DOM and toast failures after releasing ownership", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const env = runtime({
      addToast: (() => {
        throw new Error("toast failed");
      }) as FileDownloadHandlerRuntime["addToast"],
      // The intentionally incomplete document makes anchor construction fail.
      document: {} as Document,
    });
    handleFileDownloadMessage(start({ disposition: "save" }), env);

    expect(() => handleFileDownloadMessage(part(), env)).not.toThrow();
    expect(retainedDownloads.ownerCount).toBe(0);
    expect(retainedDownloads.sizeBytes).toBe(0);
    expect(consoleError).toHaveBeenCalledWith(
      "Could not start the file download:",
      expect.any(Error),
    );
    expect(consoleError).toHaveBeenCalledWith(
      "Could not show the download error:",
      expect.objectContaining({ message: "toast failed" }),
    );
  });
});
