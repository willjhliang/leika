import { afterEach, describe, expect, it, vi } from "vitest";

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
  receiveFilePreviewImage,
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
    // Opening consumes the warmed copy.
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

  it("keeps a confirmed copy for the next press", () => {
    const { request, blob } = complete();
    closeFilePreview(request.requestUuid);

    const reopened = requestFilePreview("source", "Report");
    expect(reopened.cachedKey).toBe("original");
    expect(filePreviewStore.snapshot()!.contents!.blob).toBe(blob);
    expect(filePreviewWatchStore.snapshot()!.sourceVersion).toBeNull();
    ready(reopened.requestUuid, "original", true);
    expect(filePreviewWatchStore.snapshot()!.sourceVersion).toBe("version");
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

  it("falls back to an ordinary open once newer files push it out", () => {
    const { request } = complete();
    closeFilePreview(request.requestUuid);
    for (let index = 0; index < 8; index += 1) {
      warmFilePreview(String(index), "other.md", "1", new Blob(["other"]));
    }
    expect(requestFilePreview("source", "Report").cachedKey).toBeNull();
    expect(filePreviewStore.snapshot()!.contents).toBeNull();
  });
});

describe("progressive preview images", () => {
  afterEach(resetFilePreviewState);
  const url = `/leika-assets/${"a".repeat(64)}-8x6.png?w=8&h=6`;
  const part = (id: string) =>
    receiveFilePreviewTextPart(
      "report",
      {
        filename: "report.md",
        mimeType: "text/markdown",
        sizeBytes: 100,
        textLead: "![Figure](<plot é.png>)",
      },
      { streamId: id, sourceVersion: id, index: 0, done: true },
    );
  const image = (stream: string, source = "plot é.png", asset = url) =>
    receiveFilePreviewImage({
      type: "GuiPreviewImageMessage",
      uuid: "report",
      stream_uuid: stream,
      source,
      url: asset,
    });

  it("retains ready images with the warmed stream and ignores stale streams", () => {
    part("old");
    image("old");
    requestFilePreview("report", "Report");
    expect(
      filePreviewStore
        .snapshot()
        ?.textStream?.imageSources?.get(
          "http://leika.invalid/plot%20%C3%A9.png",
        ),
    ).toBe(url);
    part("new");
    image("old");
    expect(
      filePreviewStore.snapshot()?.textStream?.imageSources,
    ).toBeUndefined();
    image("new");
    expect(filePreviewStore.snapshot()?.textStream?.imageSources?.size).toBe(1);
    closeFilePreview(filePreviewStore.snapshot()!.id);
    image("new", "second.png");
    expect(filePreviewStore.snapshot()).toBeNull();
    resetFilePreviewState();
    image("new");
    requestFilePreview("report", "Report");
    expect(filePreviewStore.snapshot()?.textStream).toBeUndefined();
  });
});
