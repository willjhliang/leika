import {
  inspectImageDataUrl,
  MAX_IMAGE_DIMENSION,
  MAX_IMAGE_PIXELS,
  MALFORMED_IMAGE_MESSAGE,
  type RejectedImage,
} from "../imageSafety";
import type { MediaSize } from "./mediaPreviewSize";

export const MARKDOWN_RESERVED_MAX_DIMENSION = MAX_IMAGE_DIMENSION;
export const MARKDOWN_RESERVED_MAX_PIXELS = MAX_IMAGE_PIXELS;

/** Safe image registrations bind the measured size into their content-hash
 * route name. A generic `/leika-assets/<hash>` plus forged query dimensions
 * does not match and therefore cannot opt arbitrary bytes into `<img>` decode. */
const MEASURED_ASSET =
  /^\/leika-assets\/[0-9a-f]{64}-([1-9][0-9]*)x([1-9][0-9]*)(?:\.[a-z0-9]{1,16})?\?w=([1-9][0-9]*)&h=([1-9][0-9]*)$/;

function safeSize(widthText: string, heightText: string): MediaSize | null {
  const width = Number(widthText);
  const height = Number(heightText);
  if (
    !Number.isSafeInteger(width) ||
    !Number.isSafeInteger(height) ||
    String(width) !== widthText ||
    String(height) !== heightText ||
    width <= 0 ||
    height <= 0 ||
    width > MAX_IMAGE_DIMENSION ||
    height > MAX_IMAGE_DIMENSION ||
    width > Math.floor(MAX_IMAGE_PIXELS / height)
  )
    return null;
  return { width, height };
}

/** The server-authenticated size for a same-origin image asset, if exact. */
export function reservedMarkdownAssetSize(
  src: string | undefined,
): Partial<MediaSize> {
  const measured = MEASURED_ASSET.exec(src ?? "");
  if (
    measured === null ||
    measured[1] !== measured[3] ||
    measured[2] !== measured[4]
  )
    return {};
  return safeSize(measured[1], measured[2]) ?? {};
}

export interface MarkdownImageAdmission {
  admission: { ok: true; size: MediaSize } | RejectedImage;
  sourceKind: "asset" | "data" | "blocked";
}

/** Decide without fetching: measured same-origin assets and bounded data
 * rasters are previewable; external/relative/forged sources remain links. */
export function inspectMarkdownImageSource(
  src: string | undefined,
): MarkdownImageAdmission {
  if (src === undefined)
    return {
      admission: { ok: false, reason: MALFORMED_IMAGE_MESSAGE },
      sourceKind: "blocked",
    };
  const assetSize = reservedMarkdownAssetSize(src);
  if (assetSize.width !== undefined && assetSize.height !== undefined) {
    return {
      admission: {
        ok: true,
        size: { width: assetSize.width, height: assetSize.height },
      },
      sourceKind: "asset",
    };
  }
  if (src.startsWith("data:")) {
    return { admission: inspectImageDataUrl(src), sourceKind: "data" };
  }
  return {
    admission: {
      ok: false,
      reason:
        "Remote or unverified images are not loaded automatically. Open the image link to fetch it.",
    },
    sourceKind: "blocked",
  };
}
