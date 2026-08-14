import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DeferredObjectUrlReleaser,
  downloadObjectUrl,
  SAVE_URL_REVOKE_DELAY_MS,
} from "./deferredObjectUrlReleaser";

describe("DeferredObjectUrlReleaser", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("keeps a clicked download URL alive until a later task", () => {
    vi.useFakeTimers();
    const events: string[] = [];
    const revoke = vi.fn(() => events.push("revoke"));
    const releaser = new DeferredObjectUrlReleaser(revoke);
    const link = {
      download: "",
      hidden: false,
      href: "",
      click: () => events.push("click"),
      remove: () => events.push("remove"),
    };
    const ownerDocument = {
      body: { append: () => events.push("append") },
      createElement: () => link,
    } as unknown as Document;

    downloadObjectUrl("blob:download", "report.csv", releaser, ownerDocument);
    expect(link.href).toBe("blob:download");
    expect(link.download).toBe("report.csv");
    expect(link.hidden).toBe(true);
    expect(events).toEqual(["append", "click", "remove"]);

    vi.advanceTimersByTime(SAVE_URL_REVOKE_DELAY_MS - 1);
    expect(events).toEqual(["append", "click", "remove"]);
    vi.advanceTimersByTime(1);
    expect(events).toEqual(["append", "click", "remove", "revoke"]);
    expect(revoke).toHaveBeenCalledWith("blob:download");
  });

  it("owns pending timers and releases each URL exactly once on cleanup", () => {
    vi.useFakeTimers();
    const revoke = vi.fn();
    const releaser = new DeferredObjectUrlReleaser(revoke);

    releaser.releaseAfterNavigation("blob:first");
    releaser.releaseAfterNavigation("blob:first");
    releaser.releaseAfterNavigation("blob:second");
    releaser.dispose();

    expect(revoke.mock.calls).toEqual([["blob:first"], ["blob:second"]]);
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledTimes(2);
  });

  it("bounds pending URL owners and releases an over-limit URL", () => {
    let handle = 0;
    const releaseFirst = vi.fn();
    const releaseSecond = vi.fn();
    const releaseOverflow = vi.fn();
    const releaser = new DeferredObjectUrlReleaser(
      vi.fn(),
      () => ++handle as unknown as ReturnType<typeof setTimeout>,
      vi.fn(),
      2,
    );

    releaser.releaseAfterNavigation("blob:first", releaseFirst);
    releaser.releaseAfterNavigation("blob:second", releaseSecond);
    // Reusing an existing owner is idempotent at the exact boundary.
    releaser.releaseAfterNavigation("blob:first", releaseFirst);
    expect(() =>
      releaser.releaseAfterNavigation("blob:overflow", releaseOverflow),
    ).toThrow("Too many browser downloads");
    expect(releaseOverflow).toHaveBeenCalledOnce();

    releaser.dispose();
    expect(releaseFirst).toHaveBeenCalledOnce();
    expect(releaseSecond).toHaveBeenCalledOnce();
  });

  it("removes and immediately cleans up if the synthetic click throws", () => {
    vi.useFakeTimers();
    const revoke = vi.fn();
    const remove = vi.fn();
    const ownerDocument = {
      body: { append: vi.fn() },
      createElement: () => ({
        click: () => {
          throw new Error("click failed");
        },
        remove,
      }),
    } as unknown as Document;
    const releaser = new DeferredObjectUrlReleaser(revoke);

    expect(() =>
      downloadObjectUrl("blob:failed", "file.bin", releaser, ownerDocument),
    ).toThrow("click failed");
    expect(remove).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith("blob:failed");
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledOnce();
  });

  it("releases immediately if appending the anchor fails", () => {
    const release = vi.fn();
    const ownerDocument = {
      body: {
        append: () => {
          throw new Error("append failed");
        },
      },
      createElement: () => ({ click: vi.fn(), remove: vi.fn() }),
    } as unknown as Document;

    expect(() =>
      downloadObjectUrl(
        "blob:append",
        "file.bin",
        new DeferredObjectUrlReleaser(),
        ownerDocument,
        release,
      ),
    ).toThrow("append failed");
    expect(release).toHaveBeenCalledOnce();
  });

  it("releases immediately if creating the anchor fails", () => {
    const release = vi.fn();
    const ownerDocument = {
      createElement: () => {
        throw new Error("create failed");
      },
    } as unknown as Document;

    expect(() =>
      downloadObjectUrl(
        "blob:create",
        "file.bin",
        new DeferredObjectUrlReleaser(),
        ownerDocument,
        release,
      ),
    ).toThrow("create failed");
    expect(release).toHaveBeenCalledOnce();
  });

  it("contains a deferred release callback failure", () => {
    vi.useFakeTimers();
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const releaser = new DeferredObjectUrlReleaser();
    releaser.releaseAfterNavigation("blob:throw", () => {
      throw new Error("release failed");
    });
    expect(() => vi.runAllTimers()).not.toThrow();
    expect(error).toHaveBeenCalledOnce();
  });

  it("releases synchronously if scheduling the grace task fails", () => {
    const release = vi.fn();
    const remove = vi.fn();
    const ownerDocument = {
      body: { append: vi.fn() },
      createElement: () => ({ click: vi.fn(), remove }),
    } as unknown as Document;
    const releaser = new DeferredObjectUrlReleaser(vi.fn(), () => {
      throw new Error("timer failed");
    });

    expect(() =>
      downloadObjectUrl(
        "blob:timer",
        "file.bin",
        releaser,
        ownerDocument,
        release,
      ),
    ).toThrow("timer failed");
    expect(remove).toHaveBeenCalledOnce();
    expect(release).toHaveBeenCalledOnce();
  });

  it("preserves a scheduling failure when synchronous release also fails", () => {
    const release = vi.fn(() => {
      throw new Error("release failed");
    });
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const releaser = new DeferredObjectUrlReleaser(vi.fn(), () => {
      throw new Error("timer failed");
    });

    expect(() =>
      releaser.releaseAfterNavigation("blob:timer", release),
    ).toThrow("timer failed");
    expect(release).toHaveBeenCalledOnce();
    expect(consoleError).toHaveBeenCalledWith(
      "Could not release a file URL:",
      expect.objectContaining({ message: "release failed" }),
    );
  });

  it("disposes all owners even if cancellation and one release throw", () => {
    const first = vi.fn(() => {
      throw new Error("release failed");
    });
    const second = vi.fn();
    let handle = 0;
    const releaser = new DeferredObjectUrlReleaser(
      vi.fn(),
      () => ++handle as unknown as ReturnType<typeof setTimeout>,
      () => {
        throw new Error("cancel failed");
      },
    );
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});

    releaser.releaseAfterNavigation("blob:first", first);
    releaser.releaseAfterNavigation("blob:second", second);
    releaser.dispose();

    expect(first).toHaveBeenCalledOnce();
    expect(second).toHaveBeenCalledOnce();
    expect(consoleError).toHaveBeenCalledTimes(3);
    consoleError.mockRestore();
  });
});
