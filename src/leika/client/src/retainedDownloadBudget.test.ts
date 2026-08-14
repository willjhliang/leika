import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FILE_DOWNLOAD_MEMORY_MAX_BYTES,
  FILE_DOWNLOAD_MEMORY_MAX_OWNERS,
  RETAINED_DOWNLOAD_PRIORITY,
  RetainedDownloadBudget,
} from "./retainedDownloadBudget";

function sizedBlob(size: number): Blob {
  // Accounting depends only on the immutable Blob.size contract. Avoid
  // allocating hundreds of MiB merely to test exact integer boundaries.
  return { size } as Blob;
}

describe("RetainedDownloadBudget", () => {
  afterEach(() => vi.restoreAllMocks());

  it("accepts exactly 512 MiB and rejects one byte more", () => {
    const budget = new RetainedDownloadBudget();
    const exact = budget.retain(sizedBlob(FILE_DOWNLOAD_MEMORY_MAX_BYTES), {
      priority: RETAINED_DOWNLOAD_PRIORITY.preview,
    });
    expect(exact).not.toBeNull();
    expect(budget.sizeBytes).toBe(FILE_DOWNLOAD_MEMORY_MAX_BYTES);

    expect(
      budget.retain(sizedBlob(1), {
        priority: RETAINED_DOWNLOAD_PRIORITY.warm,
      }),
    ).toBeNull();
    exact!.release();
    expect(budget.sizeBytes).toBe(0);
    expect(
      budget.retain(sizedBlob(FILE_DOWNLOAD_MEMORY_MAX_BYTES + 1), {
        priority: RETAINED_DOWNLOAD_PRIORITY.save,
      }),
    ).toBeNull();
  });

  it("shares the exact limit between active assemblies and completed owners", () => {
    const budget = new RetainedDownloadBudget();
    const half = FILE_DOWNLOAD_MEMORY_MAX_BYTES / 2;
    const assembling = budget.reserve(half, {
      priority: RETAINED_DOWNLOAD_PRIORITY.preview,
    })!;
    const completed = budget.retain(sizedBlob(half), {
      priority: RETAINED_DOWNLOAD_PRIORITY.preview,
    })!;

    expect(budget.sizeBytes).toBe(FILE_DOWNLOAD_MEMORY_MAX_BYTES);
    expect(
      budget.reserve(1, { priority: RETAINED_DOWNLOAD_PRIORITY.preview }),
    ).toBeNull();

    assembling.release();
    completed.release();
    expect(budget.sizeBytes).toBe(0);
  });

  it("transfers a reservation to its Blob atomically", () => {
    const budget = new RetainedDownloadBudget();
    const events: number[] = [];
    const reservation = budget.reserve(17, {
      priority: RETAINED_DOWNLOAD_PRIORITY.link,
    })!;
    events.push(budget.sizeBytes);
    const retained = reservation.retain(sizedBlob(17), {
      priority: RETAINED_DOWNLOAD_PRIORITY.link,
    })!;
    events.push(budget.sizeBytes);

    expect(events).toEqual([17, 17]);
    expect(reservation.isActive).toBe(false);
    expect(retained.isActive).toBe(true);
    expect(budget.size).toBe(1);

    retained.release();
    expect(budget.sizeBytes).toBe(0);
  });

  it("bounds empty completed owners and evicts the oldest eligible one", () => {
    const budget = new RetainedDownloadBudget();
    const evicted = vi.fn();
    for (let index = 0; index < FILE_DOWNLOAD_MEMORY_MAX_OWNERS; index += 1) {
      const retained = budget.retain(sizedBlob(0), {
        priority: RETAINED_DOWNLOAD_PRIORITY.link,
      })!;
      if (index === 0) {
        retained.setOwner(RETAINED_DOWNLOAD_PRIORITY.link, evicted);
      }
    }

    expect(budget.ownerCount).toBe(FILE_DOWNLOAD_MEMORY_MAX_OWNERS);
    expect(budget.sizeBytes).toBe(0);
    expect(
      budget.retain(sizedBlob(0), {
        priority: RETAINED_DOWNLOAD_PRIORITY.link,
      }),
    ).not.toBeNull();
    expect(evicted).toHaveBeenCalledOnce();
    expect(budget.ownerCount).toBe(FILE_DOWNLOAD_MEMORY_MAX_OWNERS);
  });

  it("rejects when protected empty owners saturate the token budget", () => {
    const budget = new RetainedDownloadBudget();
    const owners = Array.from({ length: FILE_DOWNLOAD_MEMORY_MAX_OWNERS }, () =>
      budget.retain(sizedBlob(0), {
        priority: RETAINED_DOWNLOAD_PRIORITY.save,
        protected: true,
      })!,
    );

    expect(budget.ownerCount).toBe(FILE_DOWNLOAD_MEMORY_MAX_OWNERS);
    expect(
      budget.reserve(0, { priority: RETAINED_DOWNLOAD_PRIORITY.save }),
    ).toBeNull();
    for (const owner of owners) owner.release();
    expect(budget.ownerCount).toBe(0);
  });

  it("evicts oldest lower-priority owners until the admission fits", () => {
    const budget = new RetainedDownloadBudget();
    const half = FILE_DOWNLOAD_MEMORY_MAX_BYTES / 2;
    const events: string[] = [];
    const firstWarm = budget.retain(sizedBlob(half), {
      priority: RETAINED_DOWNLOAD_PRIORITY.warm,
    })!;
    firstWarm.setOwner(RETAINED_DOWNLOAD_PRIORITY.warm, () =>
      events.push("first warm"),
    );
    const preview = budget.retain(sizedBlob(half), {
      priority: RETAINED_DOWNLOAD_PRIORITY.preview,
    })!;
    preview.setOwner(RETAINED_DOWNLOAD_PRIORITY.preview, () =>
      events.push("preview"),
    );

    const link = budget.retain(sizedBlob(1), {
      priority: RETAINED_DOWNLOAD_PRIORITY.link,
    });
    expect(link).not.toBeNull();
    expect(events).toEqual(["first warm"]);
    expect(firstWarm.isActive).toBe(false);
    expect(preview.isActive).toBe(true);
    expect(budget.sizeBytes).toBe(half + 1);
  });

  it("drops a low-priority incoming cache instead of a visible preview", () => {
    const budget = new RetainedDownloadBudget();
    const preview = budget.retain(sizedBlob(FILE_DOWNLOAD_MEMORY_MAX_BYTES), {
      priority: RETAINED_DOWNLOAD_PRIORITY.preview,
    })!;
    const evict = vi.fn();
    preview.setOwner(RETAINED_DOWNLOAD_PRIORITY.preview, evict);

    expect(
      budget.retain(sizedBlob(1), {
        priority: RETAINED_DOWNLOAD_PRIORITY.warm,
      }),
    ).toBeNull();
    expect(evict).not.toHaveBeenCalled();
    expect(preview.isActive).toBe(true);
  });

  it("evicts connection-owned links but preserves a navigating save", () => {
    const budget = new RetainedDownloadBudget();
    const half = FILE_DOWNLOAD_MEMORY_MAX_BYTES / 2;
    const closeLink = vi.fn();
    const link = budget.retain(sizedBlob(half), {
      priority: RETAINED_DOWNLOAD_PRIORITY.link,
    })!;
    link.setOwner(RETAINED_DOWNLOAD_PRIORITY.link, closeLink);
    const save = budget.retain(sizedBlob(half), {
      priority: RETAINED_DOWNLOAD_PRIORITY.save,
      protected: true,
    })!;
    const cancelSave = vi.fn();
    save.setOwner(RETAINED_DOWNLOAD_PRIORITY.save, cancelSave);

    budget.evictAll();

    expect(closeLink).toHaveBeenCalledOnce();
    expect(link.isActive).toBe(false);
    expect(cancelSave).not.toHaveBeenCalled();
    expect(save.isActive).toBe(true);
    expect(budget.sizeBytes).toBe(half);
    save.release();
    expect(budget.sizeBytes).toBe(0);
  });

  it("never evicts an in-flight save navigation", () => {
    const budget = new RetainedDownloadBudget();
    const protectedSave = budget.retain(
      sizedBlob(FILE_DOWNLOAD_MEMORY_MAX_BYTES),
      {
        priority: RETAINED_DOWNLOAD_PRIORITY.save,
        protected: true,
      },
    )!;
    const evict = vi.fn();
    protectedSave.setOwner(RETAINED_DOWNLOAD_PRIORITY.save, evict);

    expect(
      budget.retain(sizedBlob(1), {
        priority: RETAINED_DOWNLOAD_PRIORITY.save,
        protected: true,
      }),
    ).toBeNull();
    budget.evictAll();
    expect(evict).not.toHaveBeenCalled();
    expect(budget.sizeBytes).toBe(FILE_DOWNLOAD_MEMORY_MAX_BYTES);
    protectedSave.release();
    expect(budget.sizeBytes).toBe(0);
  });

  it("contains owner cleanup failures and still releases accounting", () => {
    const budget = new RetainedDownloadBudget();
    const errorLog = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const retained = budget.retain(sizedBlob(FILE_DOWNLOAD_MEMORY_MAX_BYTES), {
      priority: RETAINED_DOWNLOAD_PRIORITY.warm,
    })!;
    retained.setOwner(RETAINED_DOWNLOAD_PRIORITY.warm, () => {
      throw new Error("cleanup failed");
    });

    expect(
      budget.retain(sizedBlob(1), {
        priority: RETAINED_DOWNLOAD_PRIORITY.warm,
      }),
    ).not.toBeNull();
    expect(retained.isActive).toBe(false);
    expect(errorLog).toHaveBeenCalledWith(
      "Could not evict a retained file:",
      expect.objectContaining({ message: "cleanup failed" }),
    );
  });
});
