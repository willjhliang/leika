export const SAVE_URL_REVOKE_DELAY_MS = 1_000;
export const MAX_DEFERRED_OBJECT_URLS = 512;

type TimerHandle = ReturnType<typeof globalThis.setTimeout>;
type PendingRelease = {
  timer: TimerHandle;
  release: () => void;
};

/** Own object URLs whose anchor navigation has started but may not yet have
 * consumed the underlying Blob. Immediate revocation is racy in Firefox and
 * Safari; a short task delay keeps the URL valid without leaking it. */
export class DeferredObjectUrlReleaser {
  private readonly pending = new Map<string, PendingRelease>();

  constructor(
    private readonly revoke: (url: string) => void = (url) =>
      URL.revokeObjectURL(url),
    private readonly schedule: (
      callback: () => void,
      delayMs: number,
    ) => TimerHandle = (callback, delayMs) =>
      globalThis.setTimeout(callback, delayMs),
    private readonly cancel: (handle: TimerHandle) => void = (handle) =>
      globalThis.clearTimeout(handle),
    private readonly maxPendingUrls: number = MAX_DEFERRED_OBJECT_URLS,
  ) {
    if (!Number.isSafeInteger(maxPendingUrls) || maxPendingUrls < 1) {
      throw new Error("Invalid deferred object-URL limit.");
    }
  }

  /** Release an unconsumed URL immediately, cancelling an existing grace
   * timer when present. The release callback owns both URL and Blob lease. */
  releaseNow(url: string, release: () => void = () => this.revoke(url)): void {
    const pending = this.pending.get(url);
    if (pending !== undefined) {
      this.pending.delete(url);
      try {
        this.cancel(pending.timer);
      } finally {
        pending.release();
      }
      return;
    }
    release();
  }

  releaseAfterNavigation(
    url: string,
    release: () => void = () => this.revoke(url),
  ): void {
    // Object URLs created for completed downloads are unique. Still make a
    // repeated call idempotent so ownership remains clear under error paths.
    if (this.pending.has(url)) return;
    if (this.pending.size >= this.maxPendingUrls) {
      const capacityError = new Error(
        "Too many browser downloads are awaiting URL cleanup.",
      );
      try {
        this.releaseNow(url, release);
      } catch (releaseError) {
        console.error("Could not release a file URL:", releaseError);
      }
      throw capacityError;
    }
    let timer: TimerHandle;
    try {
      timer = this.schedule(() => {
        if (this.pending.get(url)?.timer !== timer) return;
        this.pending.delete(url);
        try {
          release();
        } catch (error) {
          console.error("Could not release a file URL:", error);
        }
      }, SAVE_URL_REVOKE_DELAY_MS);
    } catch (error) {
      try {
        this.releaseNow(url, release);
      } catch (releaseError) {
        // Preserve the scheduling failure while still making the cleanup
        // problem observable. `releaseNow` has already removed pending state.
        console.error("Could not release a file URL:", releaseError);
      }
      throw error;
    }
    this.pending.set(url, { timer, release });
  }

  /** Release everything if the owning message handler leaves before its short
   * timers run. Page teardown no longer needs the URLs, and clearing handles
   * prevents callbacks retaining the handler afterward. */
  dispose(): void {
    const pending = [...this.pending.values()];
    this.pending.clear();
    for (const { timer, release } of pending) {
      try {
        this.cancel(timer);
      } catch (error) {
        console.error("Could not cancel file URL cleanup:", error);
      }
      try {
        release();
      } catch (error) {
        console.error("Could not release a file URL:", error);
      }
    }
  }
}

/** Start a browser download while the anchor is connected, then keep its Blob
 * URL alive long enough for Firefox/WebKit to consume the navigation. */
export function downloadObjectUrl(
  url: string,
  filename: string,
  releaser: DeferredObjectUrlReleaser,
  ownerDocument: Document = document,
  release?: () => void,
): void {
  let link: HTMLAnchorElement | null = null;
  let appended = false;
  try {
    link = ownerDocument.createElement("a");
    link.href = url;
    link.download = filename;
    link.hidden = true;
    ownerDocument.body.append(link);
    appended = true;
    link.click();
  } catch (error) {
    try {
      if (appended) link?.remove();
    } catch {
      // Preserve the append/click failure, but still release ownership below.
    }
    try {
      releaser.releaseNow(url, release);
    } catch {
      // Keep the original DOM failure after best-effort ownership cleanup.
    }
    throw error;
  }
  try {
    link.remove();
  } catch (error) {
    try {
      // Navigation did start, so retain the URL for the browser's grace task.
      releaser.releaseAfterNavigation(url, release);
    } catch {
      // Scheduling failure already released it synchronously.
    }
    throw error;
  }
  releaser.releaseAfterNavigation(url, release);
}
