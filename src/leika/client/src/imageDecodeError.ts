import * as React from "react";

export const IMAGE_DECODE_FAILURE_MESSAGE =
  "Image preview is unavailable because the browser could not decode the raster. The encoded image is still available to download.";

export const MATPLOTLIB_DECODE_FAILURE_MESSAGE =
  "Matplotlib figure is unavailable because the browser could not decode its SVG image.";

export function isCurrentImageDecodeFailure(
  failedSource: string | null,
  currentSource: string | null,
): boolean {
  return currentSource !== null && failedSource === currentSource;
}

/** Decode failures belong to an exact URL generation. A late error from an
 * old `<img>` can update this tiny state, but can never hide its replacement. */
export function useImageDecodeError(source: string | null) {
  const [failedSource, setFailedSource] = React.useState<string | null>(null);
  const onError = React.useCallback(() => {
    if (source !== null) setFailedSource(source);
  }, [source]);
  return {
    failed: isCurrentImageDecodeFailure(failedSource, source),
    onError,
  };
}

export function releaseFailedObjectUrl(
  source: string | null,
  failed: boolean,
  revoke: (source: string) => void = (value) => URL.revokeObjectURL(value),
): void {
  if (!failed || source === null) return;
  try {
    revoke(source);
  } catch (error) {
    console.error("Could not release a failed image object URL:", error);
  }
}

export interface SourceObjectUrlOwner {
  source: string;
  objectUrl: string | null;
  renderError: string | null;
}

export function matchingSourceObjectUrlOwner(
  owner: SourceObjectUrlOwner | null,
  source: unknown,
): SourceObjectUrlOwner | null {
  return typeof source === "string" && owner?.source === source ? owner : null;
}
