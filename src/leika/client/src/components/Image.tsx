import React, { useEffect, useState } from "react";

import { Field, FieldLabel } from "@/components/ui/field";
import { GuiImageMessage } from "../WebsocketMessages";
import { MediaDialog, MediaSurface } from "./MediaExpand";

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
      {label === null ? null : <FieldLabel>{label}</FieldLabel>}
      <MediaSurface subject="image" onExpand={onExpand}>
        {/* `w-full` rather than `max-w-full`: a GUI image spans the panel,
            upscaling a narrow one instead of stranding it against the left
            edge of a row that is wider than it. */}
        <img src={imageUrl} className="block h-auto w-full rounded-lg" />
      </MediaSurface>
    </Field>
  );
});

const XL_SIZE_PX = 880;

function ImageComponent({ props }: GuiImageMessage) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageWidth, setImageWidth] = useState<number | null>(null);
  const [opened, setOpened] = useState(false);

  useEffect(() => {
    const nextUrl = URL.createObjectURL(
      new Blob([props._data], { type: `image/${props._format}` }),
    );
    setImageUrl(nextUrl);
    const image = new Image();
    image.onload = () => setImageWidth(image.naturalWidth);
    image.src = nextUrl;
    return () => URL.revokeObjectURL(nextUrl);
  }, [props._data, props._format]);

  if (imageUrl === null) return null;
  const dialogWidth =
    imageWidth === null
      ? `${XL_SIZE_PX}px`
      : `min(90vw, max(${XL_SIZE_PX}px, ${imageWidth}px))`;

  return (
    <>
      <ImageWithExpand
        imageUrl={imageUrl}
        label={props.label}
        onExpand={() => setOpened(true)}
      />
      <MediaDialog
        open={opened}
        onOpenChange={setOpened}
        title={props.label ?? "Image"}
        showTitle
        width={dialogWidth}
      >
        <img
          src={imageUrl}
          className="mx-auto block h-auto w-full rounded-lg"
        />
      </MediaDialog>
    </>
  );
}

export default ImageComponent;
