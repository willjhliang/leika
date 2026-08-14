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
  // Stable, so the memo above can actually skip re-renders of the inline copy.
  const expand = React.useCallback(() => setOpened(true), []);
  const [fullscreen] = usePreviewFullscreen(uuid);
  const inlinePixels = useRasterPixelLease(
    props._data,
    admission.ok ? admission.size : null,
  );
  const expandedPixels = useRasterPixelLease(
    props._data,
    admission.ok ? admission.size : null,
    opened,
  );

  useEffect(() => {
    setOwnedUrl(null);
    setUrlFailure(null);
    if (!admission.ok) return;
    const result = createOwnedImageObjectUrl(props._data, mimeType);
    if ("ok" in result) {
      setUrlFailure({ data: props._data, mimeType, failure: result });
      return;
    }
    setOwnedUrl(result);
    return () => URL.revokeObjectURL(result.url);
  }, [admission.ok, mimeType, props._data]);

  const imageUrl = matchingImageObjectUrl(ownedUrl, props._data, mimeType);
  const currentUrlFailure = matchingImagePreparationFailure(
    urlFailure,
    props._data,
    mimeType,
  );
  const decodeError = useImageDecodeError(imageUrl);
  useEffect(
    () => releaseFailedObjectUrl(imageUrl, decodeError.failed),
    [decodeError.failed, imageUrl],
  );
  // Header admission already measured the exact source. Re-decoding it with
  // `new Image()` here would create a third, hidden decoder owner in addition
  // to the inline and expanded copies that the pixel ledger tracks.
  const imageSize = admission.ok ? admission.size : null;

  const rejection = admission.ok
    ? !inlinePixels.pending && !inlinePixels.admitted
      ? { ok: false as const, reason: RASTER_PIXEL_BUDGET_MESSAGE }
      : decodeError.failed
        ? { ok: false as const, reason: IMAGE_DECODE_FAILURE_MESSAGE }
        : currentUrlFailure
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

  if (imageUrl === null || !inlinePixels.admitted) return null;

  return (
    <>
      <ImageWithExpand
        imageUrl={imageUrl}
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
        ) : expandedPixels.admitted ? (
          <img
            src={imageUrl}
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
