import { describe, expect, it, vi } from "vitest";

import {
  isCurrentImageDecodeFailure,
  matchingSourceObjectUrlOwner,
  releaseFailedObjectUrl,
} from "./imageDecodeError";

describe("image decode generation identity", () => {
  it("contains a late decode error to the exact failed URL", () => {
    expect(isCurrentImageDecodeFailure("blob:first", "blob:first")).toBe(true);
    expect(isCurrentImageDecodeFailure("blob:first", "blob:next")).toBe(false);
    expect(isCurrentImageDecodeFailure("blob:first", null)).toBe(false);
  });

  it("releases only the current failed object URL and contains cleanup errors", () => {
    const revoke = vi.fn();
    releaseFailedObjectUrl("blob:first", false, revoke);
    releaseFailedObjectUrl(null, true, revoke);
    expect(revoke).not.toHaveBeenCalled();
    releaseFailedObjectUrl("blob:first", true, revoke);
    expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:first");

    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    const error = new Error("revoke failed");
    releaseFailedObjectUrl("blob:broken", true, () => {
      throw error;
    });
    expect(log).toHaveBeenCalledWith(
      "Could not release a failed image object URL:",
      error,
    );
    log.mockRestore();
  });

  it("never exposes an object URL or setup error under replacement source", () => {
    const owner = {
      source: "<svg>first</svg>",
      objectUrl: "blob:first",
      renderError: null,
    };
    expect(matchingSourceObjectUrlOwner(owner, owner.source)).toBe(owner);
    expect(
      matchingSourceObjectUrlOwner(owner, "<svg>replacement</svg>"),
    ).toBeNull();
    expect(matchingSourceObjectUrlOwner(owner, null)).toBeNull();
  });
});
