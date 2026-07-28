import React, { useContext } from "react";
import { v4 as uuid } from "uuid";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { ViewerContext, ViewerContextContents } from "../ViewerContext";
import { GuiUploadButtonMessage } from "../WebsocketMessages";
import { HintTooltip } from "./common";

export default function UploadButtonComponent({
  uuid,
  props: {
    disabled,
    hint,
    color,
    mime_type: mimeType,
    _icon_html: iconHtml,
    label,
  },
}: GuiUploadButtonMessage) {
  const viewer = useContext(ViewerContext)!;
  const fileUploadRef = React.useRef<HTMLInputElement>(null);
  const { isUploading, progress, upload } = useFileUpload({
    viewer,
    componentUuid: uuid,
  });

  const button = (
    <Button
      id={uuid}
      // The same two roles the plain button takes, resolved the same way.
      variant={color === "secondary" ? "outline" : "default"}
      className="w-full"
      data-leika-button-color={color}
      onClick={() => {
        if (fileUploadRef.current === null) return;
        fileUploadRef.current.value = "";
        fileUploadRef.current.click();
      }}
      disabled={disabled || isUploading}
    >
      {iconHtml === null ? null : (
        <span
          data-icon="inline-start"
          className="size-3.5 [&_svg]:size-full"
          dangerouslySetInnerHTML={{ __html: iconHtml }}
        />
      )}
      {label}
    </Button>
  );

  return (
    <>
      <input
        type="file"
        hidden
        id={`file_upload_${uuid}`}
        name="file"
        accept={mimeType}
        ref={fileUploadRef}
        onChange={(event) => {
          const file = event.currentTarget.files?.[0];
          if (file !== undefined) upload(file);
        }}
      />
      {hint === null ? (
        button
      ) : (
        <HintTooltip hint={hint}>
          <span className="block w-full">{button}</span>
        </HintTooltip>
      )}
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
    const viewerMutable = viewer.mutable.current;
    const chunkSize = 512 * 1024;
    const numChunks = Math.ceil(file.size / chunkSize);
    const transferUuid = uuid();

    updateUploadState({
      componentId: componentUuid,
      uploadedBytes: 0,
      totalBytes: file.size,
      filename: file.name,
    });
    viewerMutable.sendMessage({
      type: "FileTransferStartUpload",
      source_component_uuid: componentUuid,
      transfer_uuid: transferUuid,
      filename: file.name,
      mime_type: file.type,
      size_bytes: file.size,
      part_count: numChunks,
    });

    for (let index = 0; index < numChunks; index++) {
      const chunk = file.slice(index * chunkSize, (index + 1) * chunkSize);
      const buffer = await chunk.arrayBuffer();
      viewerMutable.sendMessage({
        type: "FileTransferPart",
        source_component_uuid: componentUuid,
        transfer_uuid: transferUuid,
        part_index: index,
        content: new Uint8Array(buffer),
      });
    }
  }

  return { isUploading, progress, upload };
}
