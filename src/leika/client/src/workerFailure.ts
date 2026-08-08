export type FatalWorkerEvent = { type: "fatal"; reason: string };

/** A small one-way gate for callbacks already queued by a failed worker. */
export class WorkerEventGate {
  private open = true;

  get acceptsEvents(): boolean {
    return this.open;
  }

  close(): boolean {
    if (!this.open) return false;
    this.open = false;
    return true;
  }
}

function describeError(error: unknown): string | null {
  if (error instanceof Error && error.message.length > 0) return error.message;
  if (typeof error === "string" && error.length > 0) return error;
  return null;
}

/**
 * A worker failure is a one-way transition. The latch is closed before any
 * cleanup runs, so socket callbacks and queued timers cannot revive the
 * worker while it is being torn down.
 */
export class WorkerFailureController {
  private readonly gate = new WorkerEventGate();

  constructor(
    private readonly shutdown: () => void,
    private readonly announce: (event: FatalWorkerEvent) => void,
    private readonly surfaceAnnouncementError: (error: unknown) => void,
  ) {}

  get hasFailed(): boolean {
    return !this.gate.acceptsEvents;
  }

  fail(reason: string, cause?: unknown): void {
    if (!this.gate.close()) return;

    const detail = describeError(cause);
    let fullReason = detail === null ? reason : `${reason}: ${detail}`;
    try {
      this.shutdown();
    } catch (error) {
      const shutdownDetail = describeError(error);
      if (shutdownDetail !== null) {
        fullReason += ` (cleanup also failed: ${shutdownDetail})`;
      }
    }

    try {
      this.announce({ type: "fatal", reason: fullReason });
    } catch (error) {
      // If even the small, cloneable fatal event cannot be posted, the only
      // remaining route to the owner is a real worker error event.
      this.surfaceAnnouncementError(error);
    }
  }

  /** Run a worker-to-owner post and make any synchronous failure fatal. */
  post(reason: string, operation: () => void): boolean {
    if (!this.gate.acceptsEvents) return false;
    try {
      operation();
      return true;
    } catch (error) {
      this.fail(reason, error);
      return false;
    }
  }
}
