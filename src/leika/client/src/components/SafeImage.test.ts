import { afterEach, describe, expect, it, vi } from "vitest";

import { DeferredObjectUrlReleaser } from "../deferredObjectUrlReleaser";
import { RejectedImageDownloadOwner } from "./SafeImage";

function fakeDocument(click: () => void = () => undefined): Document {
  return {
    body: { append: vi.fn() },
    createElement: () => ({
      click,
      remove: vi.fn(),
    }),
  } as unknown as Document;
}

describe("RejectedImageDownloadOwner", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("reuses one Blob URL for rapid clicks and releases it on unmount", () => {
    vi.useFakeTimers();
    const click = vi.fn();
    const createObjectUrl = vi.fn((blob: Blob) => {
      expect(blob.size).toBe(3);
      return "blob:rejected";
    });
    const revokeObjectUrl = vi.fn();
    const owner = new RejectedImageDownloadOwner({
      releaser: new DeferredObjectUrlReleaser(revokeObjectUrl),
      createObjectUrl,
      revokeObjectUrl,
      ownerDocument: fakeDocument(click),
    });
    const data = new Uint8Array([1, 2, 3]);

    owner.download(data, "image.png", "image/png");
    owner.download(data, "image.png", "image/png");
    expect(createObjectUrl).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledTimes(2);

    // Component-effect cleanup uses dispose(): the timer cannot retain the
    // Blob or revoke the exact owner a second time after unmount.
    owner.dispose();
    expect(revokeObjectUrl).toHaveBeenCalledExactlyOnceWith("blob:rejected");
    vi.runAllTimers();
    expect(revokeObjectUrl).toHaveBeenCalledOnce();
  });

  it("releases a prior generation before creating a replacement URL", () => {
    vi.useFakeTimers();
    const createObjectUrl = vi
      .fn<(blob: Blob) => string>()
      .mockReturnValueOnce("blob:first")
      .mockReturnValueOnce("blob:second");
    const revokeObjectUrl = vi.fn();
    const owner = new RejectedImageDownloadOwner({
      releaser: new DeferredObjectUrlReleaser(revokeObjectUrl),
      createObjectUrl,
      revokeObjectUrl,
      ownerDocument: fakeDocument(),
    });

    owner.download(new Uint8Array([1]), "first.png", "image/png");
    owner.download(new Uint8Array([2]), "second.png", "image/png");
    expect(revokeObjectUrl).toHaveBeenCalledExactlyOnceWith("blob:first");
    expect(createObjectUrl).toHaveBeenCalledTimes(2);

    vi.runAllTimers();
    expect(revokeObjectUrl.mock.calls).toEqual([
      ["blob:first"],
      ["blob:second"],
    ]);
  });

  it("releases a newly-created owner when navigation setup fails", () => {
    const revokeObjectUrl = vi.fn();
    const owner = new RejectedImageDownloadOwner({
      releaser: new DeferredObjectUrlReleaser(revokeObjectUrl),
      createObjectUrl: () => "blob:failed",
      revokeObjectUrl,
      ownerDocument: fakeDocument(() => {
        throw new Error("click failed");
      }),
    });

    expect(() =>
      owner.download(new Uint8Array([1]), "failed.png", "image/png"),
    ).toThrow("click failed");
    expect(revokeObjectUrl).toHaveBeenCalledExactlyOnceWith("blob:failed");
    owner.dispose();
    expect(revokeObjectUrl).toHaveBeenCalledOnce();
  });
});
