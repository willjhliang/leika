import { afterEach, describe, expect, it, vi } from "vitest";

import { PlotlyRenderQueue } from "./plotlyRenderQueue";

function deferred(): {
  promise: Promise<void>;
  resolve: () => void;
  reject: (error: unknown) => void;
} {
  let resolve!: () => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<void>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

describe("PlotlyRenderQueue", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("starts newer work without waiting for a stale third-party promise", async () => {
    const queue = new PlotlyRenderQueue<object>();
    const first = deferred();
    const events: string[] = [];
    const firstOwner = {};
    const firstGeneration = queue.begin();
    const firstRun = queue.run(
      firstGeneration,
      firstOwner,
      async () => {
        events.push("first started");
        await first.promise;
        events.push("first mutated");
      },
      () => events.push("stale purge"),
      vi.fn(),
    );

    queue.invalidate(firstGeneration);
    queue.release(firstOwner);
    const secondGeneration = queue.begin();
    const secondRun = queue.run(
      secondGeneration,
      {},
      () => events.push("second started"),
      vi.fn(),
      vi.fn(),
    );
    expect(events).toEqual(["first started", "second started"]);

    first.resolve();
    await firstRun;
    await secondRun;
    expect(events).toEqual([
      "first started",
      "second started",
      "first mutated",
      "stale purge",
    ]);
  });

  it("contains a stale rejection and still runs the newer generation", async () => {
    const queue = new PlotlyRenderQueue<object>();
    const first = deferred();
    const firstFailure = vi.fn();
    const firstOwner = {};
    const firstGeneration = queue.begin();
    const firstRun = queue.run(
      firstGeneration,
      firstOwner,
      () => first.promise,
      vi.fn(),
      firstFailure,
    );

    queue.invalidate(firstGeneration);
    queue.release(firstOwner);
    const secondGeneration = queue.begin();
    const secondTask = vi.fn();
    const secondRun = queue.run(
      secondGeneration,
      {},
      secondTask,
      vi.fn(),
      vi.fn(),
    );
    first.reject(new Error("stale failure"));
    await firstRun;
    await secondRun;

    expect(firstFailure).not.toHaveBeenCalled();
    expect(secondTask).toHaveBeenCalledOnce();
  });

  it("reports a failure only while that generation still owns the host", async () => {
    const queue = new PlotlyRenderQueue<object>();
    const render = deferred();
    const owner = {};
    const failure = new Error("current failure");
    const failCurrent = vi.fn();
    const cleanStale = vi.fn();
    const generation = queue.begin();
    const result = queue.run(
      generation,
      owner,
      () => render.promise,
      cleanStale,
      failCurrent,
    );

    render.reject(failure);
    await result;

    expect(failCurrent).toHaveBeenCalledExactlyOnceWith(failure);
    expect(cleanStale).not.toHaveBeenCalled();
    expect(queue.pendingOwnerCount).toBe(0);
  });

  it("purges immediately and through a task's stale cleanup after dispose", async () => {
    const queue = new PlotlyRenderQueue<object>();
    const render = deferred();
    const events: string[] = [];
    const owner = {};
    const generation = queue.begin();
    const renderResult = queue.run(
      generation,
      owner,
      async () => {
        events.push("started");
        await render.promise;
        events.push("late mutation");
      },
      () => events.push("stale purge"),
      vi.fn(),
    );

    queue.dispose(() => events.push("dispose purge"));
    expect(events).toEqual(["started", "dispose purge"]);
    expect(queue.isPending(owner)).toBe(false);
    expect(queue.pendingOwnerCount).toBe(0);
    render.resolve();
    await renderResult;
    expect(events).toEqual([
      "started",
      "dispose purge",
      "late mutation",
      "stale purge",
    ]);
    expect(queue.pendingOwnerCount).toBe(0);
  });

  it.each(["resolve", "reject"] as const)(
    "cleans a late %s once after its owner queue is collected",
    async (outcome) => {
      class CollectedWeakRef<T extends object> {
        deref(): T | undefined {
          return undefined;
        }
      }
      vi.stubGlobal("WeakRef", CollectedWeakRef);

      const queue = new PlotlyRenderQueue<object>();
      const render = deferred();
      const staleCleanup = vi.fn();
      const failCurrent = vi.fn();
      const generation = queue.begin();
      const result = queue.run(
        generation,
        {},
        () => render.promise,
        staleCleanup,
        failCurrent,
      );
      queue.dispose(vi.fn());

      if (outcome === "resolve") render.resolve();
      else render.reject(new Error("late rejection"));
      await result;

      expect(staleCleanup).toHaveBeenCalledOnce();
      expect(failCurrent).not.toHaveBeenCalled();
    },
  );

  it("releases old error closures across pending supersessions and unmount", async () => {
    const queue = new PlotlyRenderQueue<object>();
    const renders = Array.from({ length: 5 }, () => deferred());
    const owners = renders.map(() => ({}));
    const staleCleanups = owners.map(() => vi.fn());
    const failures = owners.map(() => vi.fn());
    const runs: Promise<void>[] = [];
    let generation: number | null = null;

    for (let index = 0; index < renders.length; index += 1) {
      if (generation !== null) {
        queue.invalidate(generation);
        queue.release(owners[index - 1]);
      }
      generation = queue.begin();
      runs.push(
        queue.run(
          generation,
          owners[index],
          () => renders[index].promise,
          staleCleanups[index],
          failures[index],
        ),
      );

      expect(queue.pendingOwnerCount).toBe(1);
      expect(queue.isPending(owners[index])).toBe(true);
      for (const staleOwner of owners.slice(0, index)) {
        expect(queue.isPending(staleOwner)).toBe(false);
      }
    }

    for (let index = 0; index < renders.length - 1; index += 1) {
      renders[index].reject(new Error("late failure " + index));
    }
    await Promise.all(runs.slice(0, -1));
    expect(queue.pendingOwnerCount).toBe(1);
    expect(queue.isPending(owners.at(-1)!)).toBe(true);
    for (const cleanup of staleCleanups.slice(0, -1)) {
      expect(cleanup).toHaveBeenCalledOnce();
    }
    for (const failure of failures) expect(failure).not.toHaveBeenCalled();

    queue.dispose(vi.fn());
    expect(queue.pendingOwnerCount).toBe(0);
    renders.at(-1)!.reject(new Error("late failure after unmount"));
    await runs.at(-1);
    expect(staleCleanups.at(-1)).toHaveBeenCalledOnce();
    for (const failure of failures) expect(failure).not.toHaveBeenCalled();
    expect(queue.pendingOwnerCount).toBe(0);
  });
});
