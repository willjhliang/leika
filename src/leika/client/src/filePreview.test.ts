import { describe, expect, it } from "vitest";

import { formatBytes, previewKindFor } from "./filePreview";

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
