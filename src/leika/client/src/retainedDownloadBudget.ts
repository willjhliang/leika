const MEBIBYTE = 1024 * 1024;

/** Active assemblies, links, previews, warm caches, and the short
 * cross-browser save-navigation grace period share this page-wide budget. */
export const FILE_DOWNLOAD_MEMORY_MAX_BYTES = 512 * MEBIBYTE;
/** Empty files still consume bookkeeping, a toast, or an object URL. */
export const FILE_DOWNLOAD_MEMORY_MAX_OWNERS = 512;

/** Lower-priority caches are discarded before user-visible file owners. */
export const RETAINED_DOWNLOAD_PRIORITY = {
  warm: 0,
  link: 1,
  deferredPreview: 2,
  preview: 3,
  save: 4,
} as const;

export type RetainedDownloadPriority =
  (typeof RETAINED_DOWNLOAD_PRIORITY)[keyof typeof RETAINED_DOWNLOAD_PRIORITY];

export interface RetainDownloadOptions {
  priority: RetainedDownloadPriority;
  /** Save navigation cannot safely lose its URL until Firefox/WebKit have
   * consumed the click. Protected entries make later admissions fail instead
   * of cancelling a download already under way. */
  protected?: boolean;
}
export interface ReserveDownloadOptions {
  priority: RetainedDownloadPriority;
}

/** Declared bytes reserved while file parts are still being assembled. The
 * token is transferred atomically to a completed Blob owner, never released
 * and re-admitted across that boundary. */
export class DownloadMemoryReservation {
  private active = true;

  constructor(
    private readonly budget: RetainedDownloadBudget,
    readonly sizeBytes: number,
  ) {}

  get isActive(): boolean {
    return this.active;
  }

  retain(blob: Blob, options: RetainDownloadOptions): RetainedDownload | null {
    if (!this.active || blob.size !== this.sizeBytes) {
      this.release();
      return null;
    }
    this.active = false;
    return this.budget.adopt(this, blob, options);
  }

  release(): void {
    if (!this.active) return;
    this.active = false;
    this.budget.releaseReservation(this);
  }
}

/** One completed Blob counted exactly once while a browser owner retains it. */
export class RetainedDownload {
  private active = true;
  private evictionHandler: () => void = () => undefined;

  constructor(
    private readonly budget: RetainedDownloadBudget,
    readonly blob: Blob,
    private priorityValue: RetainedDownloadPriority,
    readonly protectedFromEviction: boolean,
  ) {}

  get priority(): RetainedDownloadPriority {
    return this.priorityValue;
  }

  get isActive(): boolean {
    return this.active;
  }

  /** Transfer the Blob to a new owner and define how budget pressure can
   * remove that owner's references and object URLs. */
  setOwner(priority: RetainedDownloadPriority, evict: () => void): void {
    if (!this.active) return;
    this.priorityValue = priority;
    this.evictionHandler = evict;
  }

  /** Release an owner normally. Idempotence keeps close/replace callbacks
   * safe when a toast animation and budget eviction finish together. */
  release(): void {
    if (!this.active) return;
    this.active = false;
    this.budget.release(this);
  }

  evict(): void {
    if (!this.active || this.protectedFromEviction) return;
    try {
      this.evictionHandler();
    } catch (error) {
      console.error("Could not evict a retained file:", error);
    } finally {
      // A buggy owner must not make the accounting itself unbounded. Every
      // production handler drops its references before this forced release.
      this.release();
    }
  }
}

/** Aggregate accounting for active assemblies and completed file owners. */
export class RetainedDownloadBudget {
  private readonly entries = new Set<RetainedDownload>();
  private readonly reservations = new Set<DownloadMemoryReservation>();
  private usedBytes = 0;

  get sizeBytes(): number {
    return this.usedBytes;
  }

  get ownerCount(): number {
    return this.entries.size + this.reservations.size;
  }

  get size(): number {
    return this.entries.size;
  }

  reserve(
    size: number,
    { priority }: ReserveDownloadOptions,
  ): DownloadMemoryReservation | null {
    if (
      !Number.isSafeInteger(size) ||
      size < 0 ||
      size > FILE_DOWNLOAD_MEMORY_MAX_BYTES
    ) {
      return null;
    }
    while (
      this.ownerCount >= FILE_DOWNLOAD_MEMORY_MAX_OWNERS ||
      size > FILE_DOWNLOAD_MEMORY_MAX_BYTES - this.usedBytes
    ) {
      const candidate = this.evictionCandidate(priority);
      if (candidate === null) return null;
      candidate.evict();
    }
    const reservation = new DownloadMemoryReservation(this, size);
    this.reservations.add(reservation);
    this.usedBytes += size;
    return reservation;
  }

  retain(blob: Blob, options: RetainDownloadOptions): RetainedDownload | null {
    const reservation = this.reserve(blob.size, options);
    return reservation?.retain(blob, options) ?? null;
  }

  /** Atomically replace an active reservation with its completed Blob owner;
   * aggregate bytes are unchanged across the transfer. */
  adopt(
    reservation: DownloadMemoryReservation,
    blob: Blob,
    {
      priority,
      protected: protectedFromEviction = false,
    }: RetainDownloadOptions,
  ): RetainedDownload | null {
    if (!this.reservations.delete(reservation)) return null;
    const retained = new RetainedDownload(
      this,
      blob,
      priority,
      protectedFromEviction,
    );
    this.entries.add(retained);
    return retained;
  }

  /** Primarily connection/test cleanup. Protected save navigations remain
   * until their short owned timer fires; revoking those early is unsafe. */
  evictAll(): void {
    for (const entry of [...this.entries]) entry.evict();
  }

  release(entry: RetainedDownload): void {
    if (!this.entries.delete(entry)) return;
    this.usedBytes -= entry.blob.size;
  }

  releaseReservation(reservation: DownloadMemoryReservation): void {
    if (!this.reservations.delete(reservation)) return;
    this.usedBytes -= reservation.sizeBytes;
  }

  private evictionCandidate(
    incomingPriority: RetainedDownloadPriority,
  ): RetainedDownload | null {
    let candidate: RetainedDownload | null = null;
    for (const entry of this.entries) {
      if (
        entry.protectedFromEviction ||
        entry.priority > incomingPriority ||
        (incomingPriority === RETAINED_DOWNLOAD_PRIORITY.preview &&
          entry.priority === RETAINED_DOWNLOAD_PRIORITY.preview) ||
        (candidate !== null && entry.priority >= candidate.priority)
      ) {
        continue;
      }
      candidate = entry;
    }
    return candidate;
  }
}

/** The page-wide budget: every server connection and every completed-file
 * disposition ultimately retains bytes in the same browser process. */
export const retainedDownloads = new RetainedDownloadBudget();
