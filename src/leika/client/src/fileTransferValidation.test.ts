import { describe, expect, it } from "vitest";

import {
  FILE_TRANSFER_FILENAME_MAX_CHARACTERS,
  FILE_TRANSFER_FILENAME_MAX_UTF8_BYTES,
  FILE_TRANSFER_IDENTIFIER_MAX_CHARACTERS,
  FILE_TRANSFER_MIME_TYPE_MAX_CHARACTERS,
  validFileTransferFilename,
  validFileTransferIdentifier,
  validFileTransferMimeType,
} from "./fileTransferValidation";

describe("validFileTransferFilename", () => {
  it("accepts the exact character and UTF-8 boundaries", () => {
    expect(
      validFileTransferFilename(
        "x".repeat(FILE_TRANSFER_FILENAME_MAX_CHARACTERS),
      ),
    ).toBe(true);
    expect(
      validFileTransferFilename(
        "é".repeat(FILE_TRANSFER_FILENAME_MAX_UTF8_BYTES / 2),
      ),
    ).toBe(false); // 512 characters exceeds the independent 255-char limit.
    expect(validFileTransferFilename("🙂".repeat(255))).toBe(true);
    expect(validFileTransferFilename("🙂".repeat(256))).toBe(false);
  });

  it.each([
    ["empty", ""],
    ["blank", " \t"],
    ["dot", "."],
    ["parent", ".."],
    ["slash", "dir/file"],
    ["backslash", "dir\\file"],
    ["control", "bad\nname"],
    ["format", "bad\u200bname"],
    ["surrogate", "bad\ud800name"],
  ])("rejects a %s display name", (_label, value) => {
    expect(validFileTransferFilename(value)).toBe(false);
  });
});

describe("validFileTransferIdentifier", () => {
  it("accepts printable ASCII through the exact boundary", () => {
    expect(
      validFileTransferIdentifier(
        "x".repeat(FILE_TRANSFER_IDENTIFIER_MAX_CHARACTERS),
      ),
    ).toBe(true);
    expect(validFileTransferIdentifier("component id:1")).toBe(true);
  });

  it.each(["", "x".repeat(129), "bad\n", "bad\u007f", "é"])(
    "rejects an invalid identifier %#",
    (value) => expect(validFileTransferIdentifier(value)).toBe(false),
  );
});

describe("validFileTransferMimeType", () => {
  it("allows an empty File.type and the exact character boundary", () => {
    expect(validFileTransferMimeType("")).toBe(true);
    expect(
      validFileTransferMimeType(
        "x".repeat(FILE_TRANSFER_MIME_TYPE_MAX_CHARACTERS),
      ),
    ).toBe(true);
  });

  it.each(["x".repeat(256), "text/plain\n", "text/plain\u007f"])(
    "rejects invalid MIME metadata %#",
    (value) => expect(validFileTransferMimeType(value)).toBe(false),
  );
});
