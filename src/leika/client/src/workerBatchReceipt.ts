/** A posted batch stays charged to the worker's raw-frame budget until the
 * main thread has admitted it to its own bounded queue. Keeping at most one
 * receipt outstanding also prevents the worker-to-main event queue from
 * becoming an unobservable third buffer. */
export const WORKER_BATCH_RECEIPT_TIMEOUT_MS = 10_000;

interface PendingReceipt {
  batchId: number;
  release: () => void;
  timer: ReturnType<typeof setTimeout>;
}

export class WorkerBatchReceiptGate {
  private pending: PendingReceipt | null = null;

  constructor(
    readonly connectionId: number,
    private readonly onTimeout: () => void,
    private readonly timeoutMs = WORKER_BATCH_RECEIPT_TIMEOUT_MS,
  ) {}

  get hasPendingReceipt(): boolean {
    return this.pending !== null;
  }

  /** Install ownership before posting: a synchronously failing post therefore
   * follows the same exact release path as a close or timeout. */
  post(batchId: number, release: () => void, post: () => boolean): boolean {
    if (
      this.pending !== null ||
      !Number.isSafeInteger(batchId) ||
      batchId < 0
    ) {
      return false;
    }
    const receipt: PendingReceipt = {
      batchId,
      release,
      timer: setTimeout(() => {
        if (this.pending !== receipt) return;
        this.pending = null;
        try {
          release();
        } finally {
          this.onTimeout();
        }
      }, this.timeoutMs),
    };
    this.pending = receipt;
    if (post()) return true;
    this.finish(receipt);
    return false;
  }

  acknowledge(connectionId: number, batchId: number): boolean {
    const receipt = this.pending;
    if (
      receipt === null ||
      connectionId !== this.connectionId ||
      batchId !== receipt.batchId
    ) {
      return false;
    }
    this.finish(receipt);
    return true;
  }

  reset(): void {
    const receipt = this.pending;
    if (receipt !== null) this.finish(receipt);
  }

  private finish(receipt: PendingReceipt): void {
    if (this.pending !== receipt) return;
    this.pending = null;
    clearTimeout(receipt.timer);
    receipt.release();
  }
}
