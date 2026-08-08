import React from "react";

import { applyGuiConfigUpdate } from "./ControlPanel/GuiState";
import { toast } from "./components/ui/toast";
import {
  abortFilePreviewTransfer,
  noteReloadStarted,
  openFilePreview,
  previewKindFor,
  reloadFilePreview,
  resolveFilePreview,
  warmedContents,
  warmFilePreview,
} from "./filePreview";
import { warmMarkdownDocument } from "./components/markdownDocument";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import {
  dismissNotification,
  fileDownloadToastOptions,
  showNotification,
  updateNotification,
} from "./notifications";
import { notePlotlyMaybeLoaded } from "./plotlyReady";
import { makeMessageQueueScheduler } from "./messageQueueScheduler";
import { dispatchMessageBatch, type GuiUpdate } from "./messageBatch";
import { useViewer } from "./ViewerContext";
import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
  GuiComponentMessage,
  Message,
  isGuiComponentMessage,
} from "./WebsocketMessages";

function useMessageHandler(): (message: Message) => GuiUpdate | undefined {
  const viewer = useViewer();
  const fileDownloadHandler = useFileDownloadHandler(
    viewer.mutable.current.downloads,
  );

  return (message) => {
    if (isGuiComponentMessage(message)) {
      viewer.guiActions.addGui(message);
      return;
    }

    switch (message.type) {
      case "WorkspaceConfigurationMessage":
        viewer.viewportActions.setPersistenceWorkspace(message.workspace_id);
        return;
      case "SetGuiPanelLabelMessage":
        viewer.useGui.set({ label: message.label ?? "" });
        return;
      case "ThemeConfigurationMessage":
        viewer.guiActions.setTheme(message);
        return;
      case "RunJavascriptMessage":
        new Function(message.source)();
        notePlotlyMaybeLoaded();
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
      case "GuiCloseModalMessage":
        viewer.guiActions.removeModal(message.uuid);
        return;
      case "GuiUpdateMessage":
        return { uuid: message.uuid, updates: message.updates };
      case "GuiRemoveMessage":
        viewer.guiActions.removeGui(message.uuid);
        return;
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
        viewer.viewportActions.updatePane(message.pane_id, message.updates);
        return;
      case "ViewportPaneRemoveMessage":
        viewer.viewportActions.removePane(message.pane_id);
        return;
      case "ViewportPaneSnapshotMessage":
        viewer.viewportActions.setPaneSnapshot(message.pane_ids);
        return;
      case "FileTransferStartDownload":
      case "FileTransferPart":
      case "FileTransferAbort":
        fileDownloadHandler(message);
        return;
      case "FileTransferPartAck":
        if (message.source_component_uuid !== null) {
          viewer.guiActions.updateUploadState({
            componentId: message.source_component_uuid,
            uploadedBytes: message.transferred_bytes,
            totalBytes: message.total_bytes,
          });
        }
        return;
      default:
        console.warn("Ignored unsupported Leika message:", message);
        return;
    }
  };
}

/** Process queued websocket batches before paint. */
export function MessageHandler() {
  const viewer = useViewer();
  const handleMessage = useMessageHandler();

  React.useEffect(() => {
    const processQueue = () => {
      const queue = viewer.mutable.current.messageQueue;
      if (queue.length === 0) return;
      const batch = queue.splice(0, queue.length);
      const guiUpdates = dispatchMessageBatch(batch, handleMessage);

      if (guiUpdates.size === 0) return;
      const configUpdates: Record<string, GuiComponentMessage | undefined> = {};
      const orderUpdates: Record<string, number> = {};
      for (const [uuid, updates] of guiUpdates) {
        const current = viewer.useGuiConfig.get(uuid);
        if (current === undefined) {
          console.error(`Tried to update non-existent component '${uuid}'`);
          continue;
        }
        const updated = applyGuiConfigUpdate(current, updates);
        if (updated !== current) configUpdates[uuid] = updated;
        // Where the element sits among its siblings is the container's to
        // know, not the element's -- see reorderGui.
        if (typeof updates.order === "number") {
          orderUpdates[uuid] = updates.order;
        }
      }
      if (Object.keys(configUpdates).length > 0) {
        viewer.useGuiConfig.set(configUpdates);
      }
      if (Object.keys(orderUpdates).length > 0) {
        viewer.guiActions.reorderGui(orderUpdates);
      }
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
    if (mutable.messageQueue.length > 0) scheduler.schedule();
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
): (
  message: FileTransferStartDownload | FileTransferPart | FileTransferAbort,
) => void {
  return (message) => {
    const result = downloads.accept(message);
    if (result.status === "rejected") {
      console.error(result.reason);
      if (result.metadata !== null) {
        abortFilePreviewTransfer(
          result.metadata.transfer_uuid,
          result.metadata.disposition === "reload"
            ? result.metadata.source_uuid
            : null,
        );
      }
      return;
    }

    if (message.type === "FileTransferStartDownload") {
      if (message.disposition === "preview") {
        // The dialog opens on the first message rather than the last: its
        // name, viewer and size are all here, so the click is answered now
        // and only the contents wait on the rest of the transfer -- or not
        // even that, when a warm transfer already brought them.
        openFilePreview({
          id: message.transfer_uuid,
          filename: message.filename,
          mimeType: message.mime_type,
          sizeBytes: message.size_bytes,
          contents: warmedContents(
            message.source_uuid,
            message.filename,
            message.source_version,
          ),
          sourceUuid: message.source_uuid,
          sourceVersion: message.source_version,
        });
      } else if (
        message.disposition === "reload" &&
        message.source_uuid !== null
      ) {
        noteReloadStarted(message.source_uuid);
      }
    }

    if (result.status !== "complete") return;

    const { metadata, parts } = result;
    const blob = new Blob(parts, { type: metadata.mime_type });
    const url = URL.createObjectURL(blob);
    const { filename, disposition, transfer_uuid: transferUuid } = metadata;

    if (disposition === "warm") {
      // Arrived ahead of its press, so nothing is shown: the file is held
      // for the preview that a press would open, and a markdown document is
      // readied the rest of the way while the reader is elsewhere.
      URL.revokeObjectURL(url);
      if (metadata.source_uuid !== null) {
        warmFilePreview(
          metadata.source_uuid,
          filename,
          metadata.source_version,
          blob,
        );
      }
      if (
        metadata.source_uuid !== null &&
        previewKindFor(metadata.mime_type, filename) === "markdown"
      ) {
        void blob.text().then(warmMarkdownDocument, () => undefined);
      }
      return;
    }

    if (disposition === "save") {
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return;
    }

    if (disposition === "reload") {
      const { source_uuid: sourceUuid, source_version: version } = metadata;
      if (sourceUuid === null) URL.revokeObjectURL(url);
      else
        reloadFilePreview({
          sourceUuid,
          filename,
          mimeType: metadata.mime_type,
          sizeBytes: metadata.size_bytes,
          contents: { url, blob },
          sourceVersion: version,
        });
      return;
    }

    if (disposition === "preview") {
      // The dialog owns the URL until it closes. If it closed while bytes
      // were in flight, resolveFilePreview releases the late URL instead.
      resolveFilePreview(transferUuid, { url, blob });
      return;
    }

    // Otherwise offer the file as a link. Its object URL lives exactly as
    // long as the toast that exposes it.
    const options = fileDownloadToastOptions(filename, url);
    toast.add({
      id: transferUuid,
      title: options.title,
      description: (
        <a
          {...options.link}
          className="font-medium underline underline-offset-4"
        >
          Save file
        </a>
      ),
      timeout: options.timeout,
      data: options.data,
      onRemove: () => URL.revokeObjectURL(url),
    });
  };
}
