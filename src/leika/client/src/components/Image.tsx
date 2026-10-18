import React, { useState } from "react";

import { Field, FieldLabel } from "@/components/ui/field";
import { GuiImageMessage } from "../WebsocketMessages";
import { MediaImage } from "./MediaImage";
import { MediaPreview, MediaSurface } from "./MediaPreview";
import { mediaPreviewWidth, type MediaSize } from "./mediaPreviewSize";
import {
  previewMediaClassName,
  usePreviewFullscreen,
} from "./previewFullscreen";
import { guiLabelClassName } from "./guiLabelStyles";
import { useObjectUrl } from "./useObjectUrl";

const ImageWithExpand = React.memo(function ImageWithExpand({
  imageUrl,
  label,
  onSize,
  onExpand,
}: {
  imageUrl: string;
  label: string | null;
  onSize: (size: MediaSize) => void;
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
        <MediaImage
          src={imageUrl}
          alt={label ?? ""}
          className="block h-auto w-full rounded-lg"
          onSize={onSize}
        />
      </MediaSurface>
    </Field>
  );
});

function ImageComponent({ uuid, props }: GuiImageMessage) {
  const imageUrl = useObjectUrl(props._data, `image/${props._format}`);
  // What the preview opens at, measured by the inline copy as it loads.
  const [imageSize, setImageSize] = useState<MediaSize | null>(null);
  const [opened, setOpened] = useState(false);
  // Stable, so the memo above can actually skip re-renders of the inline copy.
  const expand = React.useCallback(() => setOpened(true), []);
  const [fullscreen] = usePreviewFullscreen(uuid);

  if (imageUrl === null) return null;

  return (
    <>
      <ImageWithExpand
        imageUrl={imageUrl}
        label={props.label}
        onSize={setImageSize}
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
        <MediaImage
          src={imageUrl}
          alt={props.label ?? ""}
          className={previewMediaClassName(fullscreen)}
        />
      </MediaPreview>
    </>
  );
}

export default ImageComponent;
