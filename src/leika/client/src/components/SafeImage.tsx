import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  DeferredObjectUrlReleaser,
  downloadObjectUrl,
} from "../deferredObjectUrlReleaser";

const rejectedImageDownloads = new DeferredObjectUrlReleaser();

type RejectedImageDownload = {
  data: Uint8Array;
  filename: string;
  mimeType: string;
  url: string;
};

type RejectedImageDownloadOwnerOptions = {
  releaser?: DeferredObjectUrlReleaser;
  createObjectUrl?: (blob: Blob) => string;
  revokeObjectUrl?: (url: string) => void;
  ownerDocument?: Document;
};

function blobBytes(data: Uint8Array): Uint8Array<ArrayBuffer> {
  if (data.buffer instanceof ArrayBuffer) {
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }
  // SharedArrayBuffer is not a BlobPart in TypeScript's DOM contract. Copy
  // only that unusual input; state-owned websocket bytes use ArrayBuffer.
  return new Uint8Array(data);
}

/** One rejected raster can be clicked repeatedly while its first navigation
 * still owns the Blob URL. Reuse that exact owner instead of cloning the
 * image on every click, and make replacement/unmount cleanup deterministic. */
export class RejectedImageDownloadOwner {
  private owned: RejectedImageDownload | null = null;
  private readonly releaser: DeferredObjectUrlReleaser;

  constructor(
    private readonly options: RejectedImageDownloadOwnerOptions = {},
  ) {
    this.releaser = options.releaser ?? rejectedImageDownloads;
  }

  retainOnly(
    data: Uint8Array | undefined,
    filename: string | undefined,
    mimeType: string | undefined,
  ): void {
    const owned = this.owned;
    if (
      owned === null ||
      (owned.data === data &&
        owned.filename === filename &&
        owned.mimeType === mimeType)
    ) {
      return;
    }
    this.release(owned);
  }

  download(data: Uint8Array, filename: string, mimeType: string): void {
    this.retainOnly(data, filename, mimeType);
    let owned = this.owned;
    if (owned === null) {
      const createObjectUrl =
        this.options.createObjectUrl ?? ((blob) => URL.createObjectURL(blob));
      const url = createObjectUrl(
        new Blob([blobBytes(data)], { type: mimeType }),
      );
      owned = { data, filename, mimeType, url };
      this.owned = owned;
    }

    const exactOwner = owned;
    const release = () => {
      if (this.owned === exactOwner) this.owned = null;
      const revokeObjectUrl =
        this.options.revokeObjectUrl ?? ((url) => URL.revokeObjectURL(url));
      revokeObjectUrl(exactOwner.url);
    };
    try {
      downloadObjectUrl(
        exactOwner.url,
        filename,
        this.releaser,
        this.options.ownerDocument,
        release,
      );
    } catch (error) {
      if (this.owned === exactOwner) {
        try {
          this.releaser.releaseNow(exactOwner.url, release);
        } catch {
          // Preserve the navigation error after best-effort cleanup.
        }
      }
      throw error;
    }
  }

  dispose(): void {
    const owned = this.owned;
    if (owned !== null) this.release(owned);
  }

  private release(owned: RejectedImageDownload): void {
    if (this.owned === owned) this.owned = null;
    const revokeObjectUrl =
      this.options.revokeObjectUrl ?? ((url) => URL.revokeObjectURL(url));
    this.releaser.releaseNow(owned.url, () => revokeObjectUrl(owned.url));
  }
}

export function RejectedImageStatus({
  data,
  filename,
  mimeType,
  reason,
}: {
  data?: Uint8Array;
  filename?: string;
  mimeType?: string;
  reason: string;
}) {
  const [downloadFailed, setDownloadFailed] = React.useState(false);
  const ownerRef = React.useRef<RejectedImageDownloadOwner | null>(null);
  if (ownerRef.current === null) {
    ownerRef.current = new RejectedImageDownloadOwner();
  }
  const owner = ownerRef.current;

  React.useEffect(() => {
    owner.retainOnly(data, filename, mimeType);
    return () => owner.dispose();
  }, [data, filename, mimeType, owner]);

  const download = React.useCallback(() => {
    if (data === undefined || filename === undefined || mimeType === undefined)
      return;
    try {
      owner.download(data, filename, mimeType);
      setDownloadFailed(false);
    } catch (error) {
      console.error("Could not download rejected image:", error);
      setDownloadFailed(true);
    }
  }, [data, filename, mimeType, owner]);

  return (
    <div
      role="status"
      className="flex h-full min-h-24 flex-col items-center justify-center gap-3 p-4 text-center text-sm text-muted-foreground"
    >
      <p>
        {downloadFailed ? "The image download could not be started." : reason}
      </p>
      {data === undefined ? null : (
        <Button type="button" variant="outline" size="sm" onClick={download}>
          Download image
        </Button>
      )}
    </div>
  );
}
