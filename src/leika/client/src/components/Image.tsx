import React, { useEffect, useState } from "react";

import { Field, FieldLabel } from "@/components/ui/field";
import { GuiImageMessage } from "../WebsocketMessages";
import { MediaPreview, MediaSurface } from "./MediaPreview";
import { mediaPreviewWidth, useMediaSize } from "./mediaPreviewSize";
import { guiLabelClassName } from "./guiLabelStyles";

const ImageWithExpand = React.memo(function ImageWithExpand({
  imageUrl,
  label,
  onExpand,
}: {
  imageUrl: string;
  label: string | null;
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
        />
      </MediaSurface>
    </Field>
  );
});

function ImageComponent({ props }: GuiImageMessage) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  // Stable, so the memo above can actually skip re-renders of the inline copy.
  const expand = React.useCallback(() => setOpened(true), []);
  // What the preview opens at. Measured off the URL rather than beside it, so
  // the size follows the picture wherever it is being shown from.
  const imageSize = useMediaSize(imageUrl);

  useEffect(() => {
    const nextUrl = URL.createObjectURL(
      new Blob([props._data], { type: `image/${props._format}` }),
    );
    setImageUrl(nextUrl);
    return () => URL.revokeObjectURL(nextUrl);
  }, [props._data, props._format]);

  if (imageUrl === null) return null;

  return (
    <>
      <ImageWithExpand
        imageUrl={imageUrl}
        label={props.label}
        onExpand={expand}
      />
      <MediaPreview
        open={opened}
        onOpenChange={setOpened}
        title={props.label ?? "Image"}
        width={mediaPreviewWidth(imageSize)}
      >
        <img
          src={imageUrl}
          alt={props.label ?? ""}
          className="mx-auto block h-auto w-full rounded-lg"
        />
      </MediaPreview>
    </>
  );
}

export default ImageComponent;
