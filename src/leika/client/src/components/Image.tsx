import { Maximize2Icon } from "lucide-react";
import React, { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { GuiImageMessage } from "../WebsocketMessages";
import { HintTooltip } from "./common";

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
      <div className="relative">
        <img src={imageUrl} className="block h-auto max-w-full" />
        {onExpand === undefined ? null : (
          <HintTooltip hint="Expand image">
            <Button
              type="button"
              variant="secondary"
              size="icon-sm"
              className="absolute right-2 bottom-2"
              onClick={onExpand}
              aria-label="Expand image"
            >
              <Maximize2Icon />
            </Button>
          </HintTooltip>
        )}
      </div>
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
      <Dialog open={opened} onOpenChange={setOpened}>
        <DialogContent
          className="max-h-[calc(100dvh-2rem)] overflow-auto sm:max-w-none"
          style={{ width: dialogWidth }}
        >
          <DialogHeader>
            <DialogTitle>{props.label ?? "Image"}</DialogTitle>
          </DialogHeader>
          <img src={imageUrl} className="mx-auto block h-auto max-w-full" />
        </DialogContent>
      </Dialog>
    </>
  );
}

export default ImageComponent;
