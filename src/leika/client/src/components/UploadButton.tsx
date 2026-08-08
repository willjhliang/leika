import React from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useViewer, ViewerContextContents } from "../ViewerContext";
import { GuiUploadButtonMessage } from "../WebsocketMessages";
import { captureSendSession } from "../connectionSender";
import { sendFileUpload } from "../fileUpload";
import { randomUuid } from "../utils/randomUuid";
import { ButtonLabel, GuiButtonRow, IconHtml } from "./common";

export default function UploadButtonComponent({
  uuid,
  props: {
    disabled,
    hint,
    color,
    mime_type: mimeType,
    _icon_html: iconHtml,
    label,
    text,
  },
}: GuiUploadButtonMessage) {
  const viewer = useViewer();
  const fileUploadRef = React.useRef<HTMLInputElement>(null);
  const { isUploading, progress, upload } = useFileUpload({
    viewer,
    componentUuid: uuid,
  });

  const button = (
    <Button
      id={uuid}
      // The same two roles the plain button takes, resolved the same way.
      variant={color === "inverse" ? "default" : "outline"}
      className="w-full"
      data-leika-button-color={color}
      onClick={() => {
        if (fileUploadRef.current === null) return;
        fileUploadRef.current.value = "";
        fileUploadRef.current.click();
      }}
      disabled={disabled || isUploading}
    >
      {iconHtml === null ? null : <IconHtml html={iconHtml} />}
      <ButtonLabel>{text}</ButtonLabel>
    </Button>
  );
  return (
    <>
      <input
        type="file"
        hidden
        accept={mimeType}
        ref={fileUploadRef}
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          if (file !== undefined) upload(file);
        }}
      />
      <GuiButtonRow {...{ uuid, label, hint, disabled }}>{button}</GuiButtonRow>
      {/* Upload feedback lives with the button that started it. */}
      {isUploading && <Progress value={100 * progress} className="mt-2" />}
    </>
  );
}

function useFileUpload({
  viewer,
  componentUuid,
}: {
  componentUuid: string;
  viewer: ViewerContextContents;
}) {
  const updateUploadState = viewer.guiActions.updateUploadState;
  const uploadState = viewer.useGui(
    (state) => state.uploadsInProgress[componentUuid],
  );
  const progress =
    uploadState === undefined || uploadState.totalBytes === 0
      ? 1
      : uploadState.uploadedBytes / uploadState.totalBytes;
  const isUploading =
    uploadState !== undefined &&
    uploadState.uploadedBytes < uploadState.totalBytes;

  async function upload(file: File) {
    const sendSession = captureSendSession(viewer.mutable.current);
    const transferUuid = randomUuid();

    updateUploadState({
      componentId: componentUuid,
      uploadedBytes: 0,
      totalBytes: file.size,
      filename: file.name,
    });
    await sendFileUpload(file, componentUuid, transferUuid, sendSession);
  }

  return { isUploading, progress, upload };
}
