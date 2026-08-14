import { MAX_HYBRID_FRAME_BYTES } from "./hybridMessageDecode";

/** A single legitimate frame may reach the full decoder boundary. */
export const MAX_PENDING_RAW_FRAME_BYTES = MAX_HYBRID_FRAME_BYTES;
/** Bound closure/ArrayBuffer objects independently of their byte size. */
export const MAX_PENDING_RAW_FRAMES = 64;

export class PendingRawFrameLease {
  private active = true;

  constructor(
    private readonly budget: PendingRawFrameBudget,
    readonly sizeBytes: number,
  ) {}

  get isActive(): boolean {
    return this.active;
  }

  release(): void {
    if (!this.active) return;
    this.active = false;
    this.budget.release(this);
  }

  /** The owning socket generation disappeared; its aggregate was reset. */
  invalidate(): void {
    this.active = false;
  }
}

/** Raw WebSocket buffers admitted to one connection generation but not yet
 * transferred to the main thread. Decoding happens only after ordering is
 * acquired, so this budget covers both queued raw buffers and the one being
 * decoded/paced. */
export class PendingRawFrameBudget {
  private readonly leases = new Set<PendingRawFrameLease>();
  private bytesValue = 0;

  get count(): number {
    return this.leases.size;
  }

  get bytes(): number {
    return this.bytesValue;
  }

  admit(sizeBytes: number): PendingRawFrameLease | null {
    if (
      !Number.isSafeInteger(sizeBytes) ||
      sizeBytes < 0 ||
      sizeBytes > MAX_PENDING_RAW_FRAME_BYTES ||
      this.count >= MAX_PENDING_RAW_FRAMES ||
      sizeBytes > MAX_PENDING_RAW_FRAME_BYTES - this.bytesValue
    ) {
      return null;
    }
    const lease = new PendingRawFrameLease(this, sizeBytes);
    this.leases.add(lease);
    this.bytesValue += sizeBytes;
    return lease;
  }

  reset(): void {
    for (const lease of this.leases) lease.invalidate();
    this.leases.clear();
    this.bytesValue = 0;
  }

  release(lease: PendingRawFrameLease): void {
    if (!this.leases.delete(lease)) return;
    this.bytesValue -= lease.sizeBytes;
  }
}
