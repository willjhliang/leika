import { afterEach, describe, expect, it, vi } from "vitest";

import {
  RETAINED_DOWNLOAD_PRIORITY,
  retainedDownloads,
} from "./retainedDownloadBudget";
import {
  abortFilePreviewTransfer,
  acceptFilePreview,
  beginFilePreviewScroll,
  cancelPendingFilePreview,
  closeFilePreview,
  filePreviewStore,
  filePreviewWatchStore,
  FILE_TEXT_PREVIEW_MAX_BYTES,
  fileTextPreviewAllowed,
  finishFilePreviewScroll,
  formatBytes,
  isMediaKind,
  isReadingKind,
  openFilePreview,
  noteReloadStarted,
  previewKindFor,
  previewMemoryKey,
  reloadFilePreview,
  reloadIsOnItsWay,
  requestFilePreview,
  receiveFilePreviewText,
  receiveFilePreviewPart,
  receiveFilePreviewTextPart,
  receiveFilePreviewReady,
  resetFilePreviewState,
  resolveFilePreview,
  warmedContents,
  warmFilePreview,
  type FileContents,
} from "./filePreview";

describe("previewKindFor", () => {
  it("puts the media types in their own players", () => {
    expect(previewKindFor("image/png", "field.png")).toBe("image");
    expect(previewKindFor("image/jpeg", "photo.jpg")).toBe("image");
    expect(previewKindFor("video/mp4", "clip.mp4")).toBe("video");
    expect(previewKindFor("audio/mpeg", "take.mp3")).toBe("audio");
    expect(previewKindFor("application/pdf", "paper.pdf")).toBe("pdf");
  });

  it("tells writing apart from records", () => {
    // `text/plain` is the one textual type that claims nothing about its
    // structure, so it is the one that gets a column to be read down.
    expect(previewKindFor("text/plain", "notes.txt")).toBe("prose");
    expect(previewKindFor("application/octet-stream", "notes.txt")).toBe(
      "prose",
    );
    // These all say what they are, and what they are is data.
    expect(previewKindFor("text/csv", "readings.csv")).toBe("text");
    expect(previewKindFor("application/json", "tsconfig.json")).toBe("text");
    expect(previewKindFor("application/octet-stream", "app.log")).toBe("text");
  });

  it("shows text as text, whether or not the type says so", () => {
    expect(previewKindFor("text/csv", "readings.csv")).toBe("text");
    // The server's MIME table gives up on plenty of plainly textual files.
    expect(previewKindFor("application/octet-stream", "app.log")).toBe("text");
    expect(previewKindFor("application/octet-stream", "pyproject.toml")).toBe(
      "text",
    );
    // Structured, but structured text: the source is a real preview of it.
    expect(previewKindFor("application/json", "tsconfig.json")).toBe("text");
    expect(previewKindFor("application/ld+json", "meta.jsonld")).toBe("text");
  });

  it("renders markdown, going by the name the type does not know", () => {
    expect(previewKindFor("text/markdown", "README.md")).toBe("markdown");
    // Some platforms' MIME tables answer text/plain, or nothing at all, for
    // .md; the extension is what settles it.
    expect(previewKindFor("text/plain", "README.md")).toBe("markdown");
    expect(previewKindFor("application/octet-stream", "notes.markdown")).toBe(
      "markdown",
    );
  });

  it("shows an SVG as its source rather than rendering it", () => {
    // It is an image the browser would draw, and also a document that can
    // carry script. Showing the source previews it without running it.
    expect(previewKindFor("image/svg+xml", "logo.svg")).toBe("text");
  });

  it("reads the type without its parameters, in any case", () => {
    expect(previewKindFor("text/plain; charset=utf-8", "notes.txt")).toBe(
      "prose",
    );
    expect(previewKindFor("IMAGE/PNG", "FIELD.PNG")).toBe("image");
  });

  it("falls through to the download card for anything else", () => {
    expect(previewKindFor("application/zip", "bundle.zip")).toBe("unsupported");
    expect(previewKindFor("application/octet-stream", "weights.bin")).toBe(
      "unsupported",
    );
    // A dot that starts the name is not an extension, so this is not a "gitignore"
    // file that happens to be text -- it is a name with no extension at all.
    expect(previewKindFor("application/octet-stream", ".gitignore")).toBe(
      "unsupported",
    );
  });
});

describe("isMediaKind", () => {
  it("claims the three kinds that arrive with a size of their own", () => {
    expect(isMediaKind("image")).toBe(true);
    expect(isMediaKind("video")).toBe(true);
    expect(isMediaKind("audio")).toBe(true);
  });

  it("leaves the ones a frame has to be picked for", () => {
    // A PDF is drawn by a viewer and is still a document: it is pages, read
    // by scrolling, and its page size is not the size to show it at.
    expect(isMediaKind("pdf")).toBe(false);
    expect(isMediaKind("markdown")).toBe(false);
    expect(isMediaKind("prose")).toBe(false);
    expect(isMediaKind("text")).toBe(false);
    expect(isMediaKind("unsupported")).toBe(false);
  });

  it("takes nothing that a document is read down", () => {
    // The two splits are answering different questions and must not be
    // confused: `isReadingKind` picks a frame's height, this picks whether
    // there is a frame at all.
    expect(isReadingKind("image")).toBe(false);
    expect(isMediaKind("markdown")).toBe(false);
  });
});

describe("formatBytes", () => {
  it("counts bytes exactly and larger sizes to one decimal", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1023)).toBe("1023 B");
    expect(formatBytes(1024)).toBe("1.0 KiB");
    expect(formatBytes(1536)).toBe("1.5 KiB");
    expect(formatBytes(64 * 1024 * 1024)).toBe("64.0 MiB");
  });

  it("stops climbing units at the largest it knows", () => {
    expect(formatBytes(5 * 1024 ** 4)).toBe("5.0 TiB");
    expect(formatBytes(2048 * 1024 ** 4)).toBe("2048.0 TiB");
  });
});

describe("text preview admission", () => {
  it("accepts exactly 16 MiB and declines the next byte", () => {
    expect(fileTextPreviewAllowed(FILE_TEXT_PREVIEW_MAX_BYTES)).toBe(true);
    expect(fileTextPreviewAllowed(FILE_TEXT_PREVIEW_MAX_BYTES + 1)).toBe(false);
  });
});

describe("the preview store", () => {
  const metadata = (id: string, sourceUuid: string | null = "button") => ({
    id,
    filename: "notes.md",
    mimeType: "text/markdown",
    sizeBytes: 4,
    contents: null,
    sourceUuid,
    sourceVersion: "1:4",
  });
  const contents = (): FileContents => ({
    url: `blob:${crypto.randomUUID()}`,
    blob: new Blob(["# hi"]),
  });
  const reload = (
    nextContents: ReturnType<typeof contents>,
    overrides: Partial<Parameters<typeof reloadFilePreview>[0]> = {},
  ) =>
    reloadFilePreview({
      sourceUuid: "button",
      filename: "notes.md",
      mimeType: "text/markdown",
      sizeBytes: nextContents.blob.size,
      contents: nextContents,
      sourceVersion: "2:9",
      ...overrides,
    });

  afterEach(() => {
    resetFilePreviewState();
    vi.restoreAllMocks();
  });

  it("keys remembered display state by source identity", () => {
    expect(previewMemoryKey(metadata("a", "first-button"))).toBe(
      "file-source:first-button",
    );
    expect(previewMemoryKey(metadata("b", "second-button"))).toBe(
      "file-source:second-button",
    );
    expect(previewMemoryKey(metadata("c", null))).toBe("file-name:notes.md");
  });

  it("clears previews, reload markers, and warmed files on disconnect", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const arrived = contents();
    openFilePreview({ ...metadata("a"), contents: arrived });
    noteReloadStarted("button");
    warmFilePreview("button", "warm.md", "1", new Blob(["ready"]));

    resetFilePreviewState();

    expect(filePreviewStore.snapshot()).toBeNull();
    expect(reloadIsOnItsWay("button")).toBe(false);
    expect(warmedContents("button", "warm.md", "1")).toBeNull();
    expect(revoke).toHaveBeenCalledWith(arrived.url);
    expect(retainedDownloads.sizeBytes).toBe(0);
  });

  it("unwinds failed preview and reload transfers without losing good contents", () => {
    openFilePreview(metadata("initial"));
    abortFilePreviewTransfer("initial", null);
    expect(filePreviewStore.snapshot()).toBeNull();

    openFilePreview(metadata("loaded"));
    const arrived = contents();
    resolveFilePreview("loaded", arrived);
    noteReloadStarted("button");
    abortFilePreviewTransfer("reload-transfer", "button");
    expect(filePreviewStore.snapshot()?.contents).toBe(arrived);
    expect(reloadIsOnItsWay("button")).toBe(false);
  });

  it("opens on the click and keeps its identity when metadata and bytes arrive", () => {
    requestFilePreview("button", "Read notes");
    const pending = filePreviewStore.snapshot()!;
    expect(pending).toMatchObject({
      filename: "Read notes",
      contents: null,
      transferId: null,
      sourceVersion: null,
    });
    expect(acceptFilePreview(metadata("transfer"))).toBe(true);
    const arrived = contents();
    resolveFilePreview("transfer", arrived);
    expect(filePreviewStore.snapshot()).toMatchObject({
      id: pending.id,
      transferId: "transfer",
      filename: "notes.md",
      contents: arrived,
    });
  });

  it("uses warm metadata without displaying unverified warm bytes", () => {
    const blob = new Blob(["# cached"], { type: "text/markdown" });
    warmFilePreview("button", "notes.md", "old-version", blob);
    requestFilePreview("button", "Read notes");
    expect(filePreviewStore.snapshot()).toMatchObject({
      filename: "notes.md",
      mimeType: "text/markdown",
      sizeBytes: blob.size,
      contents: null,
      sourceVersion: null,
    });
    const warmed = warmedContents("button", "notes.md", "old-version");
    expect(warmed?.blob).toBe(blob);
    acceptFilePreview({ ...metadata("transfer"), contents: warmed });
  });

  it("does not reopen a click dismissed before its metadata arrived", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    requestFilePreview("button", "Read notes");
    closeFilePreview(filePreviewStore.snapshot()!.id);
    const warm = contents();
    expect(acceptFilePreview({ ...metadata("transfer"), contents: warm })).toBe(
      false,
    );
    expect(filePreviewStore.snapshot()).toBeNull();
    expect(revoke).toHaveBeenCalledWith(warm.url);
  });

  it("cancels only an unfulfilled request for the failed source", () => {
    requestFilePreview("button", "Read notes");
    const pending = filePreviewStore.snapshot();
    cancelPendingFilePreview("other");
    expect(filePreviewStore.snapshot()).toBe(pending);
    cancelPendingFilePreview("button");
    expect(filePreviewStore.snapshot()).toBeNull();

    requestFilePreview("button", "Read notes");
    acceptFilePreview(metadata("started"));
    const started = filePreviewStore.snapshot();
    cancelPendingFilePreview("button");
    expect(filePreviewStore.snapshot()).toBe(started);
  });

  it("drops superseded replies while keeping script previews available", () => {
    requestFilePreview("first", "First");
    requestFilePreview("second", "Second");
    const pending = filePreviewStore.snapshot();
    expect(acceptFilePreview(metadata("late", "first"))).toBe(false);
    expect(filePreviewStore.snapshot()).toBe(pending);
    expect(acceptFilePreview(metadata("current", "second"))).toBe(true);
    expect(acceptFilePreview(metadata("duplicate", "second"))).toBe(false);
    expect(filePreviewStore.snapshot()?.id).toBe(pending?.id);
    expect(acceptFilePreview(metadata("script", null))).toBe(true);
    expect(filePreviewStore.snapshot()?.id).toBe("script");
  });

  it("handles transfer failure and scrolling with a locally allocated dialog ID", () => {
    requestFilePreview("button", "Read notes");
    acceptFilePreview(metadata("failed"));
    abortFilePreviewTransfer("failed", null);
    expect(filePreviewStore.snapshot()).toBeNull();

    requestFilePreview("button", "Read notes");
    const id = filePreviewStore.snapshot()!.id;
    const warm = contents();
    acceptFilePreview({ ...metadata("fresh"), contents: warm });
    beginFilePreviewScroll(id);
    const fresh = contents();
    resolveFilePreview("fresh", fresh);
    expect(filePreviewStore.snapshot()?.contents).toBe(warm);
    finishFilePreviewScroll(id);
    expect(filePreviewStore.snapshot()?.contents).toBe(fresh);
  });

  it("opens on metadata alone, and fills in the contents when they arrive", () => {
    // The dialog answers the click from the transfer's first message; the
    // bytes catch up under the same id, without reopening anything.
    openFilePreview(metadata("a"));
    expect(filePreviewStore.snapshot()?.contents).toBeNull();
    const arrived = contents();
    resolveFilePreview("a", arrived);
    expect(filePreviewStore.snapshot()).toMatchObject({
      id: "a",
      contents: arrived,
    });
  });

  it("lets go of contents whose dialog was closed while they were in flight", () => {
    // A dismissed dialog stays dismissed: the late bytes are released, not
    // shown.
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    closeFilePreview("a");
    const arrived = contents();
    resolveFilePreview("a", arrived);
    expect(filePreviewStore.snapshot()).toBeNull();
    expect(revoke).toHaveBeenCalledWith(arrived.url);
  });

  it("shows warmed contents at the press, then owns the fresh copy", () => {
    // A file that arrived ahead of its press opens the dialog already full;
    // the press's own transfer still lands, and replaces it -- revoking the
    // URL the warmed copy was shown under, since the dialog owned that one.
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    warmFilePreview("button", "notes.md", "1:4", new Blob(["# early"]));

    const early = warmedContents("button", "notes.md", "1:4");
    expect(early).not.toBeNull();
    openFilePreview({ ...metadata("a"), contents: early });

    const fresh = contents();
    resolveFilePreview("a", fresh);
    expect(revoke).toHaveBeenCalledWith(early!.url);
    expect(filePreviewStore.snapshot()?.contents).toBe(fresh);
    // Opening consumes the warmed owner; it cannot duplicate the Blob behind
    // the visible preview outside aggregate retained-byte accounting.
    expect(warmedContents("button", "notes.md", "1:4")).toBeNull();
  });

  it("keeps warmed contents stable until an active scroll gesture ends", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const early = contents();
    openFilePreview({ ...metadata("a"), contents: early });
    beginFilePreviewScroll("a");

    const fresh = contents();
    resolveFilePreview("a", fresh);
    expect(filePreviewStore.snapshot()?.contents).toBe(early);
    expect(revoke).not.toHaveBeenCalledWith(early.url);

    finishFilePreviewScroll("a");
    expect(filePreviewStore.snapshot()?.contents).toBe(fresh);
    expect(revoke).toHaveBeenCalledWith(early.url);
  });

  it("has nothing warmed for a file nobody warmed", () => {
    expect(warmedContents("never", "never.md", "1")).toBeNull();
    expect(warmedContents(null, "never.md", "1")).toBeNull();
  });

  it("never stores a warm entry whose Blob lease is already inactive", () => {
    const retained = retainedDownloads.retain(new Blob(["stale"]), {
      priority: RETAINED_DOWNLOAD_PRIORITY.warm,
    });
    expect(retained).not.toBeNull();
    retained!.release();

    warmFilePreview("button", "stale.md", "1", retained!);
    expect(warmedContents("button", "stale.md", "1")).toBeNull();
    expect(retainedDownloads.sizeBytes).toBe(0);
  });

  it("never shares warmed bytes across sources or revisions", () => {
    warmFilePreview("first", "notes.md", "1", new Blob(["first"]));
    warmFilePreview("second", "notes.md", "1", new Blob(["second"]));

    expect(warmedContents("first", "notes.md", "1")?.blob.size).toBe(5);
    expect(warmedContents("second", "notes.md", "1")?.blob.size).toBe(6);
    expect(warmedContents("first", "notes.md", "2")).toBeNull();
    expect(warmedContents("first", "renamed.md", "1")).toBeNull();
  });

  it("swaps a fresher copy and its metadata without reopening", () => {
    // What a reload is for: same dialog, same id -- so the document is not
    // remounted and the reader keeps their place -- with new bytes in it,
    // and the version they were stamped with, which is what the next watch
    // asks against.
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    const first = contents();
    resolveFilePreview("a", first);

    const second = contents();
    reload(second, {
      filename: "report.pdf",
      mimeType: "application/pdf",
      sizeBytes: 2048,
    });
    expect(revoke).toHaveBeenCalledWith(first.url);
    expect(filePreviewStore.snapshot()).toMatchObject({
      id: "a",
      filename: "report.pdf",
      mimeType: "application/pdf",
      sizeBytes: 2048,
      contents: second,
      sourceVersion: "2:9",
    });
  });

  it("holds a completed reload until the scroll gesture finishes", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    const first = contents();
    resolveFilePreview("a", first);

    beginFilePreviewScroll("a");
    const second = contents();
    reload(second, { sourceVersion: "2:9" });

    // The document and its URL stay untouched during the gesture. The watch
    // revision still advances, so a long scroll never downloads this same
    // completed version once per polling tick.
    expect(filePreviewStore.snapshot()?.contents).toBe(first);
    expect(filePreviewWatchStore.snapshot()).toEqual({
      sourceUuid: "button",
      sourceVersion: "2:9",
    });
    expect(revoke).not.toHaveBeenCalledWith(first.url);

    finishFilePreviewScroll("a");
    expect(filePreviewStore.snapshot()?.contents).toBe(second);
    expect(revoke).toHaveBeenCalledWith(first.url);
  });

  it("watches from the visible version when a held reload is evicted", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    const first = contents();
    resolveFilePreview("a", first);
    beginFilePreviewScroll("a");

    const second = contents();
    reload(second, { sourceVersion: "2:9" });
    expect(filePreviewWatchStore.snapshot()?.sourceVersion).toBe("2:9");
    expect(second.retained).toBeDefined();

    second.retained!.evict();

    expect(filePreviewStore.snapshot()?.contents).toBe(first);
    expect(filePreviewWatchStore.snapshot()).toEqual({
      sourceUuid: "button",
      sourceVersion: "1:4",
    });
    expect(revoke).toHaveBeenCalledWith(second.url);
    finishFilePreviewScroll("a");
    expect(filePreviewStore.snapshot()?.contents).toBe(first);
  });

  it("keeps only the newest reload completed during one scroll gesture", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    const first = contents();
    resolveFilePreview("a", first);
    beginFilePreviewScroll("a");

    const second = contents();
    const third = contents();
    reload(second, { sourceVersion: "2" });
    reload(third, { sourceVersion: "3" });

    expect(revoke).toHaveBeenCalledWith(second.url);
    expect(filePreviewStore.snapshot()?.contents).toBe(first);
    expect(filePreviewWatchStore.snapshot()?.sourceVersion).toBe("3");

    finishFilePreviewScroll("a");
    expect(filePreviewStore.snapshot()?.contents).toBe(third);
    expect(revoke).toHaveBeenCalledWith(first.url);
  });

  it("discards a held reload when its preview closes", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    const first = contents();
    resolveFilePreview("a", first);
    beginFilePreviewScroll("a");

    const second = contents();
    reload(second, { sourceVersion: "2" });
    closeFilePreview("a");

    expect(revoke).toHaveBeenCalledWith(first.url);
    expect(revoke).toHaveBeenCalledWith(second.url);
    expect(filePreviewStore.snapshot()).toBeNull();
    expect(filePreviewWatchStore.snapshot()).toBeNull();

    finishFilePreviewScroll("a");
    expect(filePreviewStore.snapshot()).toBeNull();
  });

  it("knows a copy is on its way, until it lands", () => {
    // What stops a preview asking again for a file it is already receiving.
    // A watch is answered only when something changed, so an unanswered ask
    // and an answer still arriving look identical from here; the transfer's
    // first message is the difference, and it comes ahead of the bytes.
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    expect(reloadIsOnItsWay("button")).toBe(false);

    noteReloadStarted("button");
    expect(reloadIsOnItsWay("button")).toBe(true);
    // Only for the source it was noted against.
    expect(reloadIsOnItsWay("other-button")).toBe(false);

    reload(contents());
    expect(reloadIsOnItsWay("button")).toBe(false);
  });

  it("forgets a copy that never arrived when the reader moves on", () => {
    // A transfer cut off mid-flight would otherwise leave its source marked
    // as busy for the rest of the session, and that file would never be
    // watched again.
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    noteReloadStarted("button");
    closeFilePreview("a");
    expect(reloadIsOnItsWay("button")).toBe(false);

    openFilePreview(metadata("b"));
    noteReloadStarted("button");
    openFilePreview(metadata("c"));
    expect(reloadIsOnItsWay("button")).toBe(false);
  });

  it("lets go of a reload for something else being read", () => {
    // The reader closed this one and opened another while the bytes were in
    // flight. Answering the question they withdrew would replace the file
    // they are actually looking at.
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview({ ...metadata("a"), sourceUuid: "other-button" });
    const showing = contents();
    resolveFilePreview("a", showing);

    const late = contents();
    reload(late);
    expect(revoke).toHaveBeenCalledWith(late.url);
    expect(filePreviewStore.snapshot()?.contents).toBe(showing);
  });

  it("lets go of a reload for a preview nobody is reading", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const late = contents();
    reload(late);
    expect(revoke).toHaveBeenCalledWith(late.url);
    expect(filePreviewStore.snapshot()).toBeNull();
  });

  it("takes the name from the reload, which is the one that is current", () => {
    // A button whose contents are computed can hand back a different name
    // than it did last time; the title says what is on screen now.
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    resolveFilePreview("a", contents());
    reload(contents(), { filename: "notes-v2.md" });
    expect(filePreviewStore.snapshot()?.filename).toBe("notes-v2.md");
  });

  it("revokes what it was showing when a new file replaces it", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    const first = contents();
    resolveFilePreview("a", first);
    openFilePreview(metadata("b"));
    expect(revoke).toHaveBeenCalledWith(first.url);
    expect(filePreviewStore.snapshot()?.id).toBe("b");
  });
});

describe("first-screen previews", () => {
  afterEach(resetFilePreviewState);
  const lead = {
    filename: "report.md",
    mimeType: "text/markdown",
    sizeBytes: 100_000,
    textLead: "# First screen",
  };

  it("opens cached text locally and preserves it when transfer metadata arrives", () => {
    receiveFilePreviewText("source", lead);
    expect(filePreviewStore.snapshot()).toBeNull();
    requestFilePreview("source", "Read report");
    const pending = filePreviewStore.snapshot()!;
    expect(pending.textLead).toBe(lead.textLead);
    acceptFilePreview({
      ...pending,
      id: "transfer",
      transferId: undefined,
      textLead: undefined,
    });
    expect(filePreviewStore.snapshot()).toMatchObject({
      id: pending.id,
      transferId: "transfer",
      textLead: lead.textLead,
    });
  });

  it("does not let late prefixes reopen dismissed or replace unrelated previews", () => {
    requestFilePreview("source", "Read report");
    closeFilePreview(filePreviewStore.snapshot()!.id);
    receiveFilePreviewText("source", lead);
    expect(filePreviewStore.snapshot()).toBeNull();
    requestFilePreview("other", "Other report");
    receiveFilePreviewText("source", lead);
    expect(filePreviewStore.snapshot()!.filename).toBe("Other report");
  });

  it("bounds and clears the first-screen cache", () => {
    for (let index = 0; index < 9; index++)
      receiveFilePreviewText(String(index), {
        ...lead,
        textLead: "x".repeat(20_000),
      });
    requestFilePreview("0", "Evicted");
    expect(filePreviewStore.snapshot()!.textLead).toBeUndefined();
    requestFilePreview("8", "Retained");
    expect(filePreviewStore.snapshot()!.textLead).toHaveLength(8192);
    resetFilePreviewState();
    requestFilePreview("8", "Cleared");
    expect(filePreviewStore.snapshot()!.textLead).toBeUndefined();
  });

  it("uses only the first bounded chunk of the matching transfer", () => {
    openFilePreview({
      id: "transfer",
      ...lead,
      textLead: undefined,
      contents: null,
      sourceUuid: null,
      sourceVersion: null,
    });
    receiveFilePreviewPart("other", new TextEncoder().encode("Wrong"));
    expect(filePreviewStore.snapshot()!.textLead).toBeUndefined();
    receiveFilePreviewPart(
      "transfer",
      new TextEncoder().encode("a".repeat(8191) + "😀"),
    );
    expect(filePreviewStore.snapshot()!.textLead).toBe("a".repeat(8191));
    receiveFilePreviewPart("transfer", new TextEncoder().encode("Replacement"));
    expect(filePreviewStore.snapshot()!.textLead).toHaveLength(8191);
  });
});

describe("continuous preview text", () => {
  afterEach(resetFilePreviewState);
  const metadata = {
    filename: "stream.md",
    mimeType: "text/markdown",
    sizeBytes: 100000,
    textLead: "# First\n\n",
  };
  const part = {
    streamId: "stream",
    sourceVersion: "version",
    index: 0,
    done: false,
  };

  it("extends one stream through metadata and ignores duplicates or out-of-order chunks", () => {
    requestFilePreview("source", "Read stream");
    receiveFilePreviewTextPart("source", metadata, part);
    const pending = filePreviewStore.snapshot()!;
    receiveFilePreviewTextPart(
      "source",
      { ...metadata, textLead: "wrong" },
      { ...part, index: 2 },
    );
    receiveFilePreviewTextPart("source", metadata, part);
    expect(filePreviewStore.snapshot()!.textStream!.text).toBe(
      metadata.textLead,
    );
    acceptFilePreview({
      ...pending,
      textStream: undefined,
      id: "transfer",
      sourceVersion: "version",
    });
    receiveFilePreviewTextPart(
      "source",
      { ...metadata, textLead: "More content" },
      { ...part, index: 1, done: true },
    );
    expect(filePreviewStore.snapshot()!.textStream).toMatchObject({
      text: metadata.textLead + "More content",
      complete: true,
    });
    expect(filePreviewStore.snapshot()!.id).toBe(pending.id);
  });

  it("caches completed text without reopening a dismissed preview or restarting unchanged text", () => {
    receiveFilePreviewTextPart("source", metadata, part);
    receiveFilePreviewTextPart(
      "source",
      { ...metadata, textLead: "More content" },
      { ...part, index: 1, done: true },
    );
    expect(filePreviewStore.snapshot()).toBeNull();
    requestFilePreview("source", "Read stream");
    const stream = filePreviewStore.snapshot()!.textStream;
    receiveFilePreviewTextPart("source", metadata, part);
    expect(filePreviewStore.snapshot()!.textStream).toBe(stream);
    closeFilePreview(filePreviewStore.snapshot()!.id);
    receiveFilePreviewTextPart("source", metadata, {
      ...part,
      streamId: "new-version",
    });
    expect(filePreviewStore.snapshot()).toBeNull();
  });
});

describe("reopening retained Markdown", () => {
  afterEach(resetFilePreviewState);
  const ready = (
    requestUuid: string | null,
    key = "original",
    reused = false,
  ) =>
    receiveFilePreviewReady({
      type: "GuiPreviewReadyMessage",
      uuid: "source",
      request_uuid: requestUuid,
      cache_key: key,
      source_version: "version",
      reused,
    });
  const complete = () => {
    const request = requestFilePreview("source", "Report");
    ready(request.requestUuid);
    acceptFilePreview({
      id: "transfer",
      filename: "report.md",
      mimeType: "text/markdown",
      sizeBytes: 8,
      contents: null,
      sourceUuid: "source",
      sourceVersion: "version",
    });
    const blob = new Blob(["# Report"], { type: "text/markdown" });
    resolveFilePreview("transfer", { blob, url: URL.createObjectURL(blob) });
    return { request, blob };
  };

  it("moves the existing byte reservation between the popup and bounded cache", () => {
    const { request, blob } = complete();
    const lease = filePreviewStore.snapshot()!.contents!.retained!;
    const count = retainedDownloads.ownerCount;
    const bytes = retainedDownloads.sizeBytes;
    closeFilePreview(request.requestUuid);
    expect(lease.priority).toBe(RETAINED_DOWNLOAD_PRIORITY.warm);
    expect(retainedDownloads.ownerCount).toBe(count);
    expect(retainedDownloads.sizeBytes).toBe(bytes);

    const reopened = requestFilePreview("source", "Report");
    expect(reopened.cachedKey).toBe("original");
    expect(filePreviewStore.snapshot()!.contents!.blob).toBe(blob);
    expect(filePreviewWatchStore.snapshot()!.sourceVersion).toBeNull();
    ready(reopened.requestUuid, "original", true);
    expect(filePreviewWatchStore.snapshot()!.sourceVersion).toBe("version");
    expect(lease.priority).toBe(RETAINED_DOWNLOAD_PRIORITY.preview);
    expect(retainedDownloads.ownerCount).toBe(count);
  });

  it("ignores late confirmations and never tags old bytes with an arriving revision", () => {
    const { request, blob } = complete();
    closeFilePreview(request.requestUuid);
    const reopened = requestFilePreview("source", "Report");
    ready(request.requestUuid, "original", true);
    expect(filePreviewStore.snapshot()!.transferId).toBeNull();
    ready(reopened.requestUuid, "changed");
    expect(filePreviewStore.snapshot()!.cacheKey).toBe("original");
    closeFilePreview(reopened.requestUuid);
    const again = requestFilePreview("source", "Report");
    expect(again.cachedKey).toBe("original");
    expect(filePreviewStore.snapshot()!.contents!.blob).toBe(blob);
  });

  it("falls back to an ordinary open after memory-pressure eviction", () => {
    const { request } = complete();
    const lease = filePreviewStore.snapshot()!.contents!.retained!;
    closeFilePreview(request.requestUuid);
    lease.evict();
    expect(requestFilePreview("source", "Report").cachedKey).toBeNull();
    expect(filePreviewStore.snapshot()!.contents).toBeNull();
  });
});
