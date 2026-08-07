import { afterEach, describe, expect, it, vi } from "vitest";

import {
  closeFilePreview,
  filePreviewStore,
  formatBytes,
  isMediaKind,
  isReadingKind,
  openFilePreview,
  noteReloadStarted,
  previewKindFor,
  reloadFilePreview,
  reloadIsOnItsWay,
  resolveFilePreview,
  warmedContents,
  warmFilePreview,
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
  const contents = () => ({
    url: `blob:${crypto.randomUUID()}`,
    blob: new Blob(["# hi"]),
  });

  afterEach(() => {
    const open = filePreviewStore.snapshot();
    if (open !== null) closeFilePreview(open.id);
    vi.restoreAllMocks();
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
    warmFilePreview("notes.md", new Blob(["# early"]));

    const early = warmedContents("notes.md");
    expect(early).not.toBeNull();
    openFilePreview({ ...metadata("a"), contents: early });

    const fresh = contents();
    resolveFilePreview("a", fresh);
    expect(revoke).toHaveBeenCalledWith(early!.url);
    expect(filePreviewStore.snapshot()?.contents).toBe(fresh);
    // The warmed blob itself is still held for the next press.
    expect(warmedContents("notes.md")).not.toBeNull();
  });

  it("has nothing warmed for a file nobody warmed", () => {
    expect(warmedContents("never.md")).toBeNull();
  });

  it("swaps a fresher copy into the dialog without reopening it", () => {
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
    reloadFilePreview("button", "notes.md", second, "2:9");
    expect(revoke).toHaveBeenCalledWith(first.url);
    expect(filePreviewStore.snapshot()).toMatchObject({
      id: "a",
      contents: second,
      sourceVersion: "2:9",
    });
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

    reloadFilePreview("button", "notes.md", contents(), "2:9");
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
    reloadFilePreview("button", "notes.md", late, "2:9");
    expect(revoke).toHaveBeenCalledWith(late.url);
    expect(filePreviewStore.snapshot()?.contents).toBe(showing);
  });

  it("lets go of a reload for a preview nobody is reading", () => {
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const late = contents();
    reloadFilePreview("button", "notes.md", late, "2:9");
    expect(revoke).toHaveBeenCalledWith(late.url);
    expect(filePreviewStore.snapshot()).toBeNull();
  });

  it("takes the name from the reload, which is the one that is current", () => {
    // A button whose contents are computed can hand back a different name
    // than it did last time; the title says what is on screen now.
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    openFilePreview(metadata("a"));
    resolveFilePreview("a", contents());
    reloadFilePreview("button", "notes-v2.md", contents(), "2:9");
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
