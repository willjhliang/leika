import { describe, expect, it, vi } from "vitest";

import { installFileDownloadLink } from "./fileDownloadLink";
import {
  RETAINED_DOWNLOAD_PRIORITY,
  RetainedDownloadBudget,
} from "./retainedDownloadBudget";

function retainedFile() {
  return new RetainedDownloadBudget().retain(new Blob(["file"]), {
    priority: RETAINED_DOWNLOAD_PRIORITY.link,
  })!;
}

describe("installFileDownloadLink", () => {
  it("releases the URL and lease when inserting the toast throws", () => {
    const retained = retainedFile();
    const revoke = vi.fn();
    const failure = new Error("toast insertion failed");

    expect(() =>
      installFileDownloadLink(retained, {
        insert: () => {
          throw failure;
        },
        close: vi.fn(),
        revoke,
      }),
    ).toThrow(failure);
    expect(revoke).toHaveBeenCalledOnce();
    expect(retained.isActive).toBe(false);
  });

  it("makes repeated toast-removal callbacks idempotent", () => {
    const retained = retainedFile();
    const revoke = vi.fn();
    let onRemove: () => void = () => undefined;
    installFileDownloadLink(retained, {
      insert: (release) => {
        onRemove = release;
      },
      close: vi.fn(),
      revoke,
    });

    onRemove();
    onRemove();
    expect(revoke).toHaveBeenCalledOnce();
    expect(retained.isActive).toBe(false);
  });

  it("closes the toast and releases ownership when budget pressure evicts it", () => {
    const budget = new RetainedDownloadBudget();
    const retained = budget.retain(new Blob(["file"]), {
      priority: RETAINED_DOWNLOAD_PRIORITY.link,
    })!;
    const revoke = vi.fn();
    const close = vi.fn();
    installFileDownloadLink(retained, {
      insert: vi.fn(),
      close,
      revoke,
    });

    budget.evictAll();
    expect(revoke).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect(retained.isActive).toBe(false);
  });

  it("contains cleanup API failures and always releases the lease", () => {
    const retained = retainedFile();
    const report = vi.fn();
    let onRemove: () => void = () => undefined;
    installFileDownloadLink(retained, {
      insert: (release) => {
        onRemove = release;
      },
      close: vi.fn(),
      revoke: () => {
        throw new Error("revoke failed");
      },
      reportCleanupError: report,
    });

    expect(onRemove).not.toThrow();
    expect(report).toHaveBeenCalledOnce();
    expect(retained.isActive).toBe(false);
  });
});
