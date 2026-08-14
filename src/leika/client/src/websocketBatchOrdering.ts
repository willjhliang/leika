export const MESSAGE_ORDER_TIMEOUT_MS = 10_000;

interface TimedAsyncLock {
  acquireAsync(options: { timeout: number }): Promise<void>;
  release(): void;
}

/** A later lifecycle message may never overtake an earlier one. */
export async function acquireMessageOrder(
  lock: TimedAsyncLock,
  timeoutMs = MESSAGE_ORDER_TIMEOUT_MS,
): Promise<void> {
  try {
    await lock.acquireAsync({ timeout: timeoutMs });
  } catch (cause) {
    throw new Error("Message ordering timed out", { cause });
  }
}

/** Wait for order only while this socket generation is live. Closing an old
 * generation promptly lets its handler drop the raw frame instead of waiting
 * out the ordering timeout. */
export function acquireConnectionMessageOrder(
  lock: TimedAsyncLock,
  tasks: ConnectionBatchTasks,
  timeoutMs = MESSAGE_ORDER_TIMEOUT_MS,
): Promise<boolean> {
  const acquiring = acquireMessageOrder(lock, timeoutMs).then(
    () => {
      if (!tasks.isClosed) return true;
      // Closing won the race, but AwaitLock has no cancellation API. The
      // queued acquisition still resolves when its predecessor releases; hand
      // it straight on so this abandoned waiter cannot strand the old lock.
      lock.release();
      return false;
    },
    (error: unknown) => {
      // AwaitLock removes a timed-out resolver. Once this generation is closed
      // there is no failure left to report, and consuming it avoids a late
      // rejected loser after the close branch already resolved the race.
      if (tasks.isClosed) return false;
      throw error;
    },
  );
  return Promise.race([acquiring, tasks.whenClosed.then(() => false)]);
}

/** Release one admitted frame on every synchronous/async exit unless delayed
 * delivery has explicitly transferred that responsibility to its timer. */
export async function runWithDeferredRelease(
  release: () => void,
  work: (deferRelease: () => void) => Promise<void>,
): Promise<void> {
  let deferred = false;
  try {
    await work(() => {
      deferred = true;
    });
  } finally {
    if (!deferred) release();
  }
}

/** Timers holding ordered batches belong to exactly one WebSocket. Replacing
 * or closing that socket cancels all of them before a new generation starts. */
export class ConnectionBatchTasks {
  private readonly cancellations = new Set<() => void>();
  private closed = false;
  private resolveClosed!: () => void;
  readonly whenClosed = new Promise<void>((resolve) => {
    this.resolveClosed = resolve;
  });

  add(cancel: () => void): () => void {
    if (this.closed) {
      cancel();
      return () => undefined;
    }
    this.cancellations.add(cancel);
    return () => this.cancellations.delete(cancel);
  }

  cancelAll(): void {
    if (this.closed) return;
    this.closed = true;
    this.resolveClosed();
    const cancellations = [...this.cancellations];
    this.cancellations.clear();
    for (const cancel of cancellations) {
      try {
        cancel();
      } catch (error) {
        console.error("Could not cancel an ordered connection task:", error);
      }
    }
  }

  get size(): number {
    return this.cancellations.size;
  }

  get isClosed(): boolean {
    return this.closed;
  }
}
