import React, { useEffect, useState } from "react";

import { Field, FieldLabel } from "@/components/ui/field";
import {
  createOwnedImageObjectUrl,
  inspectEncodedImage,
  matchingImageObjectUrl,
  matchingImagePreparationFailure,
  type OwnedImageObjectUrl,
  type OwnedImagePreparationFailure,
} from "../imageSafety";
import { GuiImageMessage } from "../WebsocketMessages";
import {
  IMAGE_DECODE_FAILURE_MESSAGE,
  releaseFailedObjectUrl,
  useImageDecodeError,
} from "../imageDecodeError";
import { MediaPreview, MediaSurface } from "./MediaPreview";
import { mediaPreviewWidth } from "./mediaPreviewSize";
import {
  previewMediaClassName,
  usePreviewFullscreen,
} from "./previewFullscreen";
import { guiLabelClassName } from "./guiLabelStyles";
import { RejectedImageStatus } from "./SafeImage";
import {
  RASTER_PIXEL_BUDGET_MESSAGE,
  useRasterPixelLease,
} from "../useRasterPixelLease";

const ImageWithExpand = React.memo(function ImageWithExpand({
  imageUrl,
  label,
  onDecodeError,
  onExpand,
}: {
  imageUrl: string;
  label: string | null;
  onDecodeError: () => void;
  onExpand?: () => void;
}) {
  return (
    <Field>
      {label === null ? null : (
        <FieldLabel className={guiLabelClassName}>{label}</FieldLabel>
      )}
      <MediaSurface subject="image" onExpand={onExpand}>
        {/* `w-full` rather than `max-w-full`: a GUI image spans the panel,
            upscaling a narrow one instead of stranding it against the left
            edge of a row that is wider than it. */}
        <img
          src={imageUrl}
          alt={label ?? ""}
          className="block h-auto w-full rounded-lg"
          onError={onDecodeError}
        />
      </MediaSurface>
    </Field>
  );
});

function ImageComponent({ uuid, props }: GuiImageMessage) {
  const mimeType = `image/${props._format}`;
  const admission = React.useMemo(
    () => inspectEncodedImage(props._data, mimeType),
    [mimeType, props._data],
  );
  const [ownedUrl, setOwnedUrl] = useState<OwnedImageObjectUrl | null>(null);
  const [urlFailure, setUrlFailure] =
    useState<OwnedImagePreparationFailure | null>(null);
  const [opened, setOpened] = useState(false);
  const [lastExpandedOwner, setLastExpandedOwner] =
    useState<OwnedImageObjectUrl | null>(null);
  // Stable, so the memo above can actually skip re-renders of the inline copy.
  const expand = React.useCallback(() => setOpened(true), []);
  const [fullscreen] = usePreviewFullscreen(uuid);
  const ownedObjectUrl = ownedUrl?.url ?? null;
  const targetObjectUrl = matchingImageObjectUrl(
    ownedUrl,
    props._data,
    mimeType,
  );
  const currentUrlFailure = matchingImagePreparationFailure(
    urlFailure,
    props._data,
    mimeType,
  );
  const decodeError = useImageDecodeError(ownedObjectUrl);
  const targetDecodeFailed = targetObjectUrl !== null && decodeError.failed;
  const displayObjectUrl = decodeError.failed ? null : ownedObjectUrl;
  const inlinePixels = useRasterPixelLease(
    props._data,
    admission.ok ? admission.size : null,
    currentUrlFailure === null && !targetDecodeFailed,
  );
  const expandedPixels = useRasterPixelLease(
    props._data,
    admission.ok ? admission.size : null,
    opened && currentUrlFailure === null && !targetDecodeFailed,
  );
  const expandedTargetObjectUrl =
    opened && expandedPixels.admitted ? targetObjectUrl : null;
  const expandedDisplayObjectUrl =
    expandedTargetObjectUrl ??
    (opened && (expandedPixels.pending || expandedPixels.admitted)
      ? (lastExpandedOwner?.url ?? null)
      : null);

  // The expanded copy owns a second decoder and therefore a second lease.
  // Remember only a generation that reached both ownership boundaries. On a
  // replacement render the target lease is still pending, so this keeps the
  // already-mounted copy in place; on first open there is no prior owner and
  // no raster is mounted before its reservation succeeds.
  React.useLayoutEffect(() => {
    if (expandedTargetObjectUrl !== null && ownedUrl !== null) {
      setLastExpandedOwner(ownedUrl);
    } else if (
      !opened ||
      (!expandedPixels.pending && !expandedPixels.admitted)
    ) {
      setLastExpandedOwner(null);
    }
  }, [
    expandedPixels.admitted,
    expandedPixels.pending,
    expandedTargetObjectUrl,
    opened,
    ownedUrl,
  ]);

  useEffect(() => {
    setUrlFailure(null);
    if (!admission.ok) {
      setOwnedUrl(null);
      return;
    }
    const result = createOwnedImageObjectUrl(props._data, mimeType);
    if ("ok" in result) {
      setOwnedUrl(null);
      setUrlFailure({ data: props._data, mimeType, failure: result });
      return;
    }
    setOwnedUrl(result);
    return () => URL.revokeObjectURL(result.url);
  }, [admission.ok, mimeType, props._data]);

  useEffect(
    () => releaseFailedObjectUrl(ownedObjectUrl, decodeError.failed),
    [decodeError.failed, ownedObjectUrl],
  );
  // Header admission already measured the exact source. Re-decoding it with
  // `new Image()` here would create a third, hidden decoder owner in addition
  // to the inline and expanded copies that the pixel ledger tracks.
  const imageSize = admission.ok ? admission.size : null;

  const rejection = admission.ok
    ? targetDecodeFailed
      ? { ok: false as const, reason: IMAGE_DECODE_FAILURE_MESSAGE }
      : (currentUrlFailure ??
        (!inlinePixels.pending && !inlinePixels.admitted
          ? { ok: false as const, reason: RASTER_PIXEL_BUDGET_MESSAGE }
          : null))
    : admission;
  if (rejection !== null) {
    return (
      <Field>
        {props.label === null ? null : (
          <FieldLabel className={guiLabelClassName}>{props.label}</FieldLabel>
        )}
        <RejectedImageStatus
          data={props._data}
          filename={`leika-image.${props._format}`}
          mimeType={mimeType}
          reason={rejection.reason}
        />
      </Field>
    );
  }

  if (displayObjectUrl === null) return null;

  return (
    <>
      <ImageWithExpand
        imageUrl={displayObjectUrl}
        label={props.label}
        onDecodeError={decodeError.onError}
        onExpand={expand}
      />
      <MediaPreview
        open={opened}
        onOpenChange={setOpened}
        title={props.label ?? "Image"}
        // The pane's own uuid: this image is what the answer belongs to, and
        // its label is optional and need not be unique.
        rememberAs={uuid}
        width={mediaPreviewWidth(imageSize)}
      >
        {!expandedPixels.pending && !expandedPixels.admitted ? (
          <RejectedImageStatus reason={RASTER_PIXEL_BUDGET_MESSAGE} />
        ) : expandedDisplayObjectUrl !== null ? (
          <img
            src={expandedDisplayObjectUrl}
            alt={props.label ?? ""}
            className={previewMediaClassName(fullscreen)}
            onError={decodeError.onError}
          />
        ) : null}
      </MediaPreview>
    </>
  );
}

export default ImageComponent;
