import React from "react";
import { IMAGE_FIT_OBJECT_FIT } from "../ClientSettings";
import { RejectedImageStatus } from "../components/SafeImage";
import {
  createOwnedImageObjectUrl,
  inspectEncodedImage,
  matchingImageObjectUrl,
  matchingImagePreparationFailure,
  type OwnedImageObjectUrl,
  type OwnedImagePreparationFailure,
} from "../imageSafety";
import {
  IMAGE_DECODE_FAILURE_MESSAGE,
  releaseFailedObjectUrl,
  useImageDecodeError,
} from "../imageDecodeError";
import { useViewer } from "../ViewerContext";
import {
  RASTER_PIXEL_BUDGET_MESSAGE,
  useRasterPixelLease,
} from "../useRasterPixelLease";
import type { ViewportImagePane } from "./ViewportState";

export function ViewportImageRenderer({ pane }: { pane: ViewportImagePane }) {
  const viewer = useViewer();
  // An app that named a fit meant it; one that did not leaves the choice to
  // whoever is looking at the image.
  const preferredFit = viewer.useSettings((state) => state.imageFit);
  const fit = IMAGE_FIT_OBJECT_FIT[pane.props.fit ?? preferredFit];
  const mimeType = `image/${pane.props._format}`;
  const admission = React.useMemo(
    () =>
      pane.props._data === null
        ? null
        : inspectEncodedImage(pane.props._data, mimeType),
    [mimeType, pane.props._data],
  );
  const [ownedUrl, setOwnedUrl] = React.useState<OwnedImageObjectUrl | null>(
    null,
  );
  const [urlFailure, setUrlFailure] =
    React.useState<OwnedImagePreparationFailure | null>(null);

  // Display ownership may lag the target while its replacement is prepared.
  // Exact target matching attributes failures; it does not discard good pixels.
  const ownedObjectUrl = ownedUrl?.url ?? null;
  const targetObjectUrl = matchingImageObjectUrl(
    ownedUrl,
    pane.props._data,
    mimeType,
  );
  const currentUrlFailure = matchingImagePreparationFailure(
    urlFailure,
    pane.props._data,
    mimeType,
  );
  const decodeError = useImageDecodeError(ownedObjectUrl);
  const targetDecodeFailed = targetObjectUrl !== null && decodeError.failed;
  const displayObjectUrl = decodeError.failed ? null : ownedObjectUrl;
  const pixels = useRasterPixelLease(
    pane.props._data,
    admission?.ok === true ? admission.size : null,
    currentUrlFailure === null && !targetDecodeFailed,
  );

  // A valid update changes the source of one persistent image. Retain the
  // displayed URL until its successor is prepared, so replacement never
  // introduces an empty generation.
  React.useEffect(() => {
    setUrlFailure(null);
    if (pane.props._data === null || admission?.ok !== true) {
      setOwnedUrl(null);
      return;
    }
    const result = createOwnedImageObjectUrl(pane.props._data, mimeType);
    if ("ok" in result) {
      setOwnedUrl(null);
      setUrlFailure({ data: pane.props._data, mimeType, failure: result });
      return;
    }
    setOwnedUrl(result);
    return () => URL.revokeObjectURL(result.url);
  }, [admission?.ok, mimeType, pane.props._data]);

  React.useEffect(
    () => releaseFailedObjectUrl(ownedObjectUrl, decodeError.failed),
    [decodeError.failed, ownedObjectUrl],
  );

  const rejection =
    admission?.ok === false
      ? admission
      : targetDecodeFailed
        ? { ok: false as const, reason: IMAGE_DECODE_FAILURE_MESSAGE }
        : (currentUrlFailure ??
          (!pixels.pending && !pixels.admitted
            ? { ok: false as const, reason: RASTER_PIXEL_BUDGET_MESSAGE }
            : null));
  if (rejection !== null && pane.props._data !== null) {
    return (
      <RejectedImageStatus
        data={pane.props._data}
        filename={`leika-image.${pane.props._format}`}
        mimeType={mimeType}
        reason={rejection.reason}
      />
    );
  }

  if (pane.props._data === null || displayObjectUrl === null) {
    return (
      <span
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          alignItems: "center",
          justifyContent: "center",
          background: "#000",
          color: "#888",
          fontSize: "var(--text-sm)",
        }}
      >
        No image
      </span>
    );
  }

  return (
    <img
      src={displayObjectUrl}
      alt={pane.props.title}
      draggable={false}
      onError={decodeError.onError}
      style={{
        display: "block",
        width: "100%",
        height: "100%",
        objectFit: fit,
        userSelect: "none",
        background: "#000",
      }}
    />
  );
}
