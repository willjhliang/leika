import * as React from "react";

import type { MediaSize } from "./components/mediaPreviewSize";
import {
  mountedRasterPixels,
  type RasterPixelLease,
} from "./rasterPixelBudget";

export const RASTER_PIXEL_BUDGET_MESSAGE =
  "Image preview is unavailable because the page-wide decoded-pixel limit is full.";

type RasterOwner = {
  identity: unknown;
  width: number;
  height: number;
  lease: RasterPixelLease | null;
};

/** Reserve before rendering one exact-generation raster element. */
export function useRasterPixelLease(
  identity: unknown | null,
  size: MediaSize | null,
  enabled = true,
): { admitted: boolean; pending: boolean } {
  const ownerRef = React.useRef<RasterOwner | null>(null);
  const [owned, setOwned] = React.useState<RasterOwner | null>(null);
  const [retryGeneration, setRetryGeneration] = React.useState(0);
  const width = size?.width ?? null;
  const height = size?.height ?? null;

  React.useEffect(
    () => () => {
      ownerRef.current?.lease?.release();
      ownerRef.current = null;
    },
    [],
  );

  React.useEffect(() => {
    const previous = ownerRef.current;
    if (identity === null || width === null || height === null || !enabled) {
      previous?.lease?.release();
      ownerRef.current = null;
      setOwned(null);
      return;
    }
    if (
      previous !== null &&
      previous.identity === identity &&
      previous.width === width &&
      previous.height === height &&
      previous.lease?.active
    ) {
      setOwned(previous);
      return;
    }

    const lease = mountedRasterPixels.replace(previous?.lease ?? null, {
      width,
      height,
    });
    if (lease === null) previous?.lease?.release();
    const next = { identity, width, height, lease };
    ownerRef.current = next;
    setOwned(next);
    if (lease !== null) return;

    let unsubscribe: () => void = () => undefined;
    unsubscribe = mountedRasterPixels.subscribe(() => {
      unsubscribe();
      setRetryGeneration((value) => value + 1);
    });
    return unsubscribe;
  }, [enabled, height, identity, retryGeneration, width]);

  if (identity === null || size === null || !enabled) {
    return { admitted: false, pending: false };
  }
  const matches =
    owned !== null &&
    owned.identity === identity &&
    owned.width === size.width &&
    owned.height === size.height &&
    owned.lease?.active === true;
  return {
    admitted: matches,
    pending:
      owned === null ||
      owned.identity !== identity ||
      owned.width !== size.width ||
      owned.height !== size.height,
  };
}
