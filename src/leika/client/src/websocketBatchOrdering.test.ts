import { afterEach, describe, expect, it, vi } from "vitest";

import {
  acquireConnectionMessageOrder,
  acquireMessageOrder,
  ConnectionBatchTasks,
  runWithDeferredRelease,
} from "./websocketBatchOrdering";

afterEach(() => vi.restoreAllMocks());

describe("acquireMessageOrder", () => {
  it("acquires with the configured deadline", async () => {
    const acquireAsync = vi.fn(() => Promise.resolve());
    await acquireMessageOrder({ acquireAsync, release: vi.fn() }, 123);
    expect(acquireAsync).toHaveBeenCalledWith({ timeout: 123 });
  });

  it("turns a stalled predecessor into a connection error", async () => {
    const timeout = new Error("lock timeout");
    await expect(
      acquireMessageOrder(
        { acquireAsync: () => Promise.reject(timeout), release: vi.fn() },
        1,
      ),
    ).rejects.toMatchObject({
      message: "Message ordering timed out",
      cause: timeout,
    });
  });
});

describe("ConnectionBatchTasks", () => {
  it("releases an ordered wait promptly when its socket generation closes", async () => {
    let resolveLock!: () => void;
    const lock = {
      acquireAsync: () =>
        new Promise<void>((resolve) => {
          resolveLock = resolve;
        }),
      release: vi.fn(),
    };
    const tasks = new ConnectionBatchTasks();
    const acquired = acquireConnectionMessageOrder(lock, tasks);
    tasks.cancelAll();

    await expect(acquired).resolves.toBe(false);
    // A late resolution belongs only to the abandoned lock and cannot change
    // the already-completed old-generation result.
    resolveLock();
    await expect(acquired).resolves.toBe(false);
    await vi.waitFor(() => expect(lock.release).toHaveBeenCalledOnce());
  });

  it("cancels every task once when its socket is replaced", async () => {
    const tasks = new ConnectionBatchTasks();
    const first = vi.fn();
    const second = vi.fn();
    const unregisterFirst = tasks.add(first);
    tasks.add(second);
    unregisterFirst();

    tasks.cancelAll();
    tasks.cancelAll();
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
    expect(tasks.size).toBe(0);
    await expect(tasks.whenClosed).resolves.toBeUndefined();
    expect(tasks.isClosed).toBe(true);
  });

  it("immediately cancels work registered against a closed generation", () => {
    const tasks = new ConnectionBatchTasks();
    tasks.cancelAll();
    const stale = vi.fn();
    tasks.add(stale);
    expect(stale).toHaveBeenCalledOnce();
  });

  it("contains one cleanup failure and continues cancelling", () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const tasks = new ConnectionBatchTasks();
    const later = vi.fn();
    tasks.add(() => {
      throw new Error("cleanup failed");
    });
    tasks.add(later);

    tasks.cancelAll();
    expect(later).toHaveBeenCalledOnce();
    expect(consoleError).toHaveBeenCalledOnce();
  });
});

describe("runWithDeferredRelease", () => {
  it("releases an admitted frame when ordering rejects", async () => {
    const release = vi.fn();
    const failure = new Error("ordering failed");
    await expect(
      runWithDeferredRelease(release, async () => {
        throw failure;
      }),
    ).rejects.toBe(failure);
    expect(release).toHaveBeenCalledOnce();
  });

  it("transfers release ownership only when work explicitly defers it", async () => {
    const release = vi.fn();
    await runWithDeferredRelease(release, async (deferRelease) => {
      deferRelease();
    });
    expect(release).not.toHaveBeenCalled();
  });
});
