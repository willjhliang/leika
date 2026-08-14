/** Track ownership of Plotly's imperative work for one host.
 *
 * A `react()` promise is third-party code and is allowed to remain pending.
 * New generations therefore start immediately; the renderer isolates a
 * superseded pending task on a detached node, while this queue makes its late
 * completion clean only that stale node. */
interface PendingOwner<Owner extends object> {
  owner: Owner | null;
  cleanStale: (() => void) | null;
  failCurrent: ((error: unknown) => void) | null;
}

interface TaskFailure {
  error: unknown;
}

function finishAfterQueueCollection<Owner extends object>(
  pending: PendingOwner<Owner>,
): void {
  pending.owner = null;
  pending.failCurrent = null;
  const cleanStale = pending.cleanStale;
  pending.cleanStale = null;
  cleanStale?.();
}

export class PlotlyRenderQueue<Owner extends object> {
  private generation = 0;
  private pendingOwners = new Map<Owner, PendingOwner<Owner>>();

  begin(): number {
    this.generation += 1;
    return this.generation;
  }

  isCurrent(generation: number): boolean {
    return generation === this.generation;
  }

  invalidate(generation: number): void {
    if (this.isCurrent(generation)) this.generation += 1;
  }

  isPending(owner: Owner): boolean {
    return this.pendingOwners.has(owner);
  }

  /** Stop retaining an owner as soon as its host is detached and purged.
   * A late task settlement still runs its weak node-specific cleanup, but a
   * third-party promise that never settles cannot retain the owner or its
   * request-specific error callback. */
  release(owner: Owner): void {
    const pending = this.pendingOwners.get(owner);
    if (pending === undefined) return;
    this.pendingOwners.delete(owner);
    pending.owner = null;
    pending.failCurrent = null;
  }

  get pendingOwnerCount(): number {
    return this.pendingOwners.size;
  }

  run(
    generation: number,
    owner: Owner,
    task: () => unknown,
    cleanStale: () => void,
    failCurrent: (error: unknown) => void,
  ): Promise<void> {
    if (!this.isCurrent(generation)) return Promise.resolve();
    const previous = this.pendingOwners.get(owner);
    if (previous !== undefined) {
      this.pendingOwners.delete(owner);
      previous.owner = null;
      previous.failCurrent = null;
    }
    const pending: PendingOwner<Owner> = {
      owner,
      cleanStale,
      failCurrent,
    };
    this.pendingOwners.set(owner, pending);
    const queueRef = new WeakRef(this);
    const settle = (failure: TaskFailure | null) => {
      const queue = queueRef.deref();
      if (queue === undefined) {
        finishAfterQueueCollection(pending);
        return;
      }
      queue.finish(pending, generation, failure);
    };
    let result: unknown;
    try {
      result = task();
    } catch (error) {
      return Promise.resolve().then(() => settle({ error }));
    }
    return Promise.resolve(result).then(
      () => settle(null),
      (error: unknown) => settle({ error }),
    );
  }

  private finish(
    pending: PendingOwner<Owner>,
    generation: number,
    failure: TaskFailure | null,
  ): void {
    const owner = pending.owner;
    const ownsCurrent =
      owner !== null && this.pendingOwners.get(owner) === pending;
    if (ownsCurrent) this.pendingOwners.delete(owner);
    pending.owner = null;
    const cleanStale = pending.cleanStale;
    pending.cleanStale = null;
    const failCurrent = pending.failCurrent;
    pending.failCurrent = null;

    if (!this.isCurrent(generation) || !ownsCurrent) {
      cleanStale?.();
    } else if (failure !== null) {
      failCurrent?.(failure.error);
    }
  }

  /** Revoke every outstanding owner and clean visible state immediately.
   * Each pending task also invokes its weak node-specific stale cleanup if it
   * ever settles. */
  dispose(clean: () => void): void {
    this.generation += 1;
    for (const pending of this.pendingOwners.values()) {
      pending.owner = null;
      pending.failCurrent = null;
    }
    this.pendingOwners.clear();
    clean();
  }
}
