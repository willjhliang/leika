import React from "react";

import { toast } from "./components/ui/toast";
import { DeferredObjectUrlReleaser } from "./deferredObjectUrlReleaser";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import { handleFileDownloadMessage } from "./fileDownloadHandler";
import {
  cancelPendingFilePreview,
  receiveFilePreviewTextPart,
  receiveFilePreviewReady,
  receiveFilePreviewImage,
} from "./filePreview";
import {
  dismissNotification,
  showNotification,
  updateNotification,
} from "./notifications";
import { plotlyBootstrap } from "./plotlyBootstrap";
import { makeMessageQueueScheduler } from "./messageQueueScheduler";
import { processMessageQueueSlice } from "./messageQueueProcessor";
import {
  isGuiStateMessage,
  type GuiStateMessage,
} from "./ControlPanel/GuiState";
import { useViewer } from "./ViewerContext";
import { filterPageStreamMessages } from "./pageStreamProjection";
import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
  Message,
} from "./WebsocketMessages";

/** Apply one run of server messages. GUI messages commit as one transaction,
 * in order among themselves; no other message reads GUI state. */
function useMessageHandler(): (messages: readonly Message[]) => void {
  const viewer = useViewer();
  const sendFileTransferMessage = React.useCallback(
    (message: FileTransferAbort) => viewer.mutable.current.sendMessage(message),
    [viewer],
  );
  const fileDownloadHandler = useFileDownloadHandler(
    viewer.mutable.current.downloads,
    sendFileTransferMessage,
  );

  const handleMessage = React.useCallback(
    (message: Message) => {
      switch (message.type) {
        case "WorkspaceConfigurationMessage":
          viewer.useGui.set({ workspaceId: message.workspace_id });
          viewer.viewportActions.setPersistenceWorkspace(message.workspace_id);
          return;
        case "PageCreateMessage":
          viewer.viewportActions.addPage(
            message.page_id,
            message.name,
            message.is_default,
          );
          return;
        case "PageUpdateMessage":
          viewer.viewportActions.updatePage(message.page_id, message.name);
          return;
        case "PageCatalogMessage":
          viewer.viewportActions.finishPageCatalog(message.page_ids);
          return;
        case "PageStreamBeginMessage":
          viewer.viewportActions.beginPageStream(
            message.page_id,
            message.generation,
          );
          return;
        case "PageStreamReadyMessage":
          viewer.viewportActions.finishPageStream(
            message.page_id,
            message.generation,
          );
          return;
        case "ThemeConfigurationMessage":
          viewer.guiActions.setTheme(message);
          // Python selects the same preference as Settings. It is a setter,
          // so a later GUI selection (including Auto) takes effect normally.
          viewer.settingsActions.setDarkMode(
            message.theme === "auto" ? null : message.theme === "dark",
          );
          return;
        case "RunJavascriptMessage":
          // Executed once before this frame dispatches, after pure preflight.
          return;
        case "NotificationShowMessage":
          showNotification(message.uuid, message.props);
          return;
        case "NotificationUpdateMessage":
          updateNotification(message.uuid, message.props);
          return;
        case "RemoveNotificationMessage":
          dismissNotification(message.uuid);
          return;
        case "GuiPreviewReadyMessage":
          receiveFilePreviewReady(message);
          return;
        case "GuiPreviewImageMessage":
          receiveFilePreviewImage(message);
          return;
        case "GuiPreviewTextMessage":
          receiveFilePreviewTextPart(
            message.uuid,
            {
              filename: message.filename,
              mimeType: message.mime_type,
              sizeBytes: message.size_bytes,
              textLead: message.text,
            },
            {
              streamId: message.stream_uuid,
              sourceVersion: message.source_version,
              index: message.part_index,
              done: message.done,
            },
          );
          return;
        case "GuiPreviewCancelMessage":
          cancelPendingFilePreview(message.uuid);
          return;
        case "ViewportPaneMessage":
        case "ViewportEmptyMessage":
          viewer.viewportActions.addEmptyPane(message);
          return;
        case "ViewportImageMessage":
          viewer.viewportActions.addImagePane(message);
          return;
        case "ViewportMatplotlibMessage":
          viewer.viewportActions.addMatplotlibPane(message);
          return;
        case "ViewportPlotlyMessage":
          viewer.viewportActions.addPlotlyPane(message);
          return;
        case "ViewportVideoMessage":
          viewer.viewportActions.addVideoPane(message);
          return;
        case "ViewportViserMessage":
          viewer.viewportActions.addViserPane(message);
          return;
        case "ViewportPaneUpdateMessage":
          viewer.viewportActions.updatePane(
            message.page_id,
            message.pane_id,
            message.updates,
          );
          return;
        case "ViewportPaneRemoveMessage":
          viewer.viewportActions.removePane(message.page_id, message.pane_id);
          return;
        case "ViewportPaneSnapshotMessage":
          viewer.viewportActions.setPaneSnapshot(
            message.page_id,
            message.pane_ids,
          );
          return;
        case "FileTransferStartDownload":
        case "FileTransferPart":
          fileDownloadHandler(message);
          return;
        case "FileTransferAbort":
          // Abort is bidirectional. An active upload gets first claim on its
          // client-generated transfer ID; otherwise this belongs to a download.
          if (viewer.mutable.current.uploads.acceptAbort(message).matched)
            return;
          fileDownloadHandler(message);
          return;
        case "FileTransferPartAck": {
          const acceptance = viewer.mutable.current.uploads.acceptAck(message);
          if (acceptance.matched && acceptance.accepted) {
            viewer.guiActions.updateUploadState({
              componentId: acceptance.componentUuid,
              transferUuid: message.transfer_uuid,
              uploadedBytes: message.transferred_bytes,
              totalBytes: message.total_bytes,
            });
          }
          return;
        }
        default:
          console.warn("Ignored unsupported Leika message:", message);
          return;
      }
    },
    [fileDownloadHandler, viewer],
  );

  return React.useCallback(
    (messages: readonly Message[]) => {
      const guiMessages: GuiStateMessage[] = [];
      for (const message of messages) {
        if (isGuiStateMessage(message)) {
          guiMessages.push(message);
          continue;
        }
        try {
          handleMessage(message);
        } catch (error) {
          console.error(
            `Failed to process Leika message '${message.type}':`,
            error,
          );
        }
      }
      viewer.guiActions.applyMessages(guiMessages);
    },
    [handleMessage, viewer],
  );
}

/** Process queued websocket batches before paint. */
export function MessageHandler() {
  const viewer = useViewer();
  const handleMessages = useMessageHandler();

  React.useEffect(() => {
    const processQueue = () => {
      const queue = viewer.mutable.current.messageQueue;
      if (queue.messageCount === 0) return;
      return processMessageQueueSlice(queue, (rawBatch) => {
        const batch = filterPageStreamMessages(
          rawBatch,
          viewer.useViewport.get(),
        );
        if (batch.length === 0) return true;
        const failure =
          viewer.viewportActions.preflightMessageBatch(batch) ??
          plotlyBootstrap.preflight(batch) ??
          viewer.viewportActions.prepareMessageBatch(batch) ??
          plotlyBootstrap.execute(batch);
        if (failure !== null) {
          viewer.mutable.current.failConnection(failure);
          return false;
        }
        handleMessages(batch);
        return true;
      });
    };

    const scheduler = makeMessageQueueScheduler(processQueue, {
      isHidden: () => document.visibilityState === "hidden",
      requestFrame: (callback) => requestAnimationFrame(callback),
      cancelFrame: (handle) => cancelAnimationFrame(handle),
      setTimer: (callback) => setTimeout(callback, 16),
      clearTimer: (handle) => clearTimeout(handle),
    });
    const handleVisibilityChange = () => scheduler.visibilityChanged();
    document.addEventListener("visibilitychange", handleVisibilityChange);

    const mutable = viewer.mutable.current;
    const previousNotifier = mutable.notifyMessageQueue;
    mutable.notifyMessageQueue = scheduler.schedule;
    if (mutable.messageQueue.messageCount > 0) scheduler.schedule();
    return () => {
      if (mutable.notifyMessageQueue === scheduler.schedule) {
        mutable.notifyMessageQueue = previousNotifier;
      }
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      scheduler.stop();
    };
  }, [handleMessages, viewer]);

  return null;
}

function useFileDownloadHandler(
  downloads: FileDownloadAssembler,
  sendMessage: (message: FileTransferAbort) => void,
): (
  message: FileTransferStartDownload | FileTransferPart | FileTransferAbort,
) => void {
  const savedUrlReleaser = React.useMemo(
    () => new DeferredObjectUrlReleaser(),
    [],
  );
  React.useEffect(() => () => savedUrlReleaser.dispose(), [savedUrlReleaser]);

  return React.useCallback(
    (message) =>
      handleFileDownloadMessage(message, {
        downloads,
        savedUrlReleaser,
        sendMessage,
        createBlob: (parts, mimeType) => new Blob(parts, { type: mimeType }),
        createObjectURL: (blob) => URL.createObjectURL(blob),
        revokeObjectURL: (url) => URL.revokeObjectURL(url),
        addToast: (options) => toast.add(options),
        closeToast: (id) => toast.close(id),
        document,
      }),
    [downloads, savedUrlReleaser, sendMessage],
  );
}
