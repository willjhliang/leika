import React from "react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useViewer, ViewerContextContents } from "../ViewerContext";
import { GuiUploadButtonMessage } from "../WebsocketMessages";
import { captureSendSession } from "../connectionSender";
import { sendFileUpload } from "../fileUpload";
import { FileUploadError } from "../fileUploadAckBroker";
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
  const { error, isUploading, progress, upload } = useFileUpload({
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
      {error === null ? null : (
        <p
          role="alert"
          className="mt-1 text-xs text-destructive"
          data-leika-upload-error
        >
          {error}
        </p>
      )}
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
  const [error, setError] = React.useState<string | null>(null);
  const abortRef = React.useRef<AbortController | null>(null);
  const progress =
    uploadState === undefined || uploadState.totalBytes === 0
      ? 1
      : uploadState.uploadedBytes / uploadState.totalBytes;
  // ACK completion and local cleanup are separate turns. Keep the control
  // disabled until the sender has actually released the transfer, including
  // for an empty file whose progress is 100% from the start.
  const isUploading = uploadState !== undefined;

  React.useEffect(
    () => () => {
      abortRef.current?.abort();
      abortRef.current = null;
    },
    [],
  );

  async function upload(file: File) {
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;
    const sendSession = captureSendSession(viewer.mutable.current);
    const transferUuid = randomUuid();
    setError(null);
    updateUploadState({
      componentId: componentUuid,
      transferUuid,
      uploadedBytes: 0,
      totalBytes: file.size,
      filename: file.name,
    });
    try {
      await sendFileUpload(
        file,
        componentUuid,
        transferUuid,
        sendSession,
        viewer.mutable.current.uploads,
        { signal: abort.signal },
      );
    } catch (cause) {
      const uploadError =
        cause instanceof FileUploadError
          ? cause
          : new FileUploadError("The file could not be uploaded.", false);
      if (uploadError.visible && !abort.signal.aborted) {
        setError(uploadError.message);
      }
    } finally {
      if (abortRef.current === abort) abortRef.current = null;
      viewer.guiActions.clearUploadState(componentUuid, transferUuid);
    }
  }

  return { error, isUploading, progress, upload };
}
