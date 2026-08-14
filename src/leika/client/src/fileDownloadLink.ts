import {
  RETAINED_DOWNLOAD_PRIORITY,
  type RetainedDownload,
} from "./retainedDownloadBudget";

export interface FileDownloadLinkActions {
  /** Insert the UI owner and call `onRemove` when that owner disappears. */
  insert(onRemove: () => void): void;
  /** Remove an already-inserted UI owner under budget pressure. */
  close(): void;
  /** Revoke the object URL owned by the link. */
  revoke(): void;
  reportCleanupError?(error: unknown): void;
}

/** Atomically install a link UI as the owner of one retained download.
 *
 * UI insertion is an external operation and may throw. This helper guarantees
 * that a failed insertion cannot strand either the object URL or its shared
 * Blob-budget lease, while close/eviction races remain idempotent. */
export function installFileDownloadLink(
  retained: RetainedDownload,
  actions: FileDownloadLinkActions,
): void {
  const report =
    actions.reportCleanupError ??
    ((error: unknown) =>
      console.error("Could not release a file link:", error));
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    try {
      actions.revoke();
    } catch (error) {
      report(error);
    } finally {
      retained.release();
    }
  };

  retained.setOwner(RETAINED_DOWNLOAD_PRIORITY.link, () => {
    release();
    try {
      actions.close();
    } catch (error) {
      report(error);
    }
  });
  try {
    actions.insert(release);
  } catch (error) {
    release();
    throw error;
  }
}
