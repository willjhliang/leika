import React from "react";

import { toast } from "./components/ui/toast";
import { DeferredObjectUrlReleaser } from "./deferredObjectUrlReleaser";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import { handleFileDownloadMessage } from "./fileDownloadHandler";
import {
  dismissNotification,
  preflightNotificationBatch,
  showNotification,
  updateNotification,
} from "./notifications";
import { plotlyBootstrap } from "./plotlyBootstrap";
import { makeMessageQueueScheduler } from "./messageQueueScheduler";
import {
  dispatchMessageBatch,
  processPreflightedMessageBatches,
  type GuiUpdate,
} from "./messageBatch";
import { useViewer } from "./ViewerContext";
import { dispatchGuiLifecycleMessage } from "./guiLifecycleDispatch";
import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
  Message,
  isGuiComponentMessage,
} from "./WebsocketMessages";

function useMessageHandler(): (message: Message) => GuiUpdate | undefined {
  const viewer = useViewer();
  const sendFileTransferMessage = React.useCallback(
    (message: FileTransferAbort) => viewer.mutable.current.sendMessage(message),
    [viewer],
  );
  const fileDownloadHandler = useFileDownloadHandler(
    viewer.mutable.current.downloads,
    sendFileTransferMessage,
  );

  return React.useCallback(
    (message: Message) => {
      if (isGuiComponentMessage(message)) {
        viewer.guiActions.addGui(message);
        return;
      }

      if (dispatchGuiLifecycleMessage(message, viewer.guiActions)) return;

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
        case "ThemeConfigurationMessage":
          viewer.guiActions.setTheme(message);
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
        case "GuiModalMessage":
          viewer.guiActions.addModal(message);
          return;
        case "GuiUpdateMessage":
          return { uuid: message.uuid, updates: message.updates };
        case "GuiFormSubmitMessage":
          viewer.guiActions.noteFormSubmit(message.uuid);
          return;
        case "RegisterCommandMessage":
          viewer.guiActions.addCommand(message);
          return;
        case "CommandUpdateMessage":
          viewer.guiActions.updateCommand(message.uuid, message.updates);
          return;
        case "RemoveCommandMessage":
          viewer.guiActions.removeCommand(message.uuid);
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
}

/** Process queued websocket batches before paint. */
export function MessageHandler() {
  const viewer = useViewer();
  const handleMessage = useMessageHandler();

  React.useEffect(() => {
    const processQueue = () => {
      const queue = viewer.mutable.current.messageQueue;
      if (queue.messageCount === 0) return;
      const batches = queue.drainBatches();
      processPreflightedMessageBatches(
        batches,
        (batch) =>
          viewer.guiActions.preflightMessageBatch(batch) ??
          viewer.viewportActions.preflightMessageBatch(batch) ??
          preflightNotificationBatch(batch) ??
          plotlyBootstrap.preflight(batch),
        (batch) => {
          const bootstrapFailure = plotlyBootstrap.execute(batch);
          if (bootstrapFailure !== null) return bootstrapFailure;
          dispatchMessageBatch(batch, handleMessage, undefined, {
            guiComponents: viewer.guiActions.addGuiBatch,
            modals: viewer.guiActions.addModalBatch,
            commands: viewer.guiActions.addCommandBatch,
            tabs: viewer.guiActions.applyTabLifecycleBatch,
            guiUpdates: viewer.guiActions.updateGuiPropsBatch,
          });
          return null;
        },
        viewer.mutable.current.failConnection,
      );
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
  }, [handleMessage, viewer]);

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
