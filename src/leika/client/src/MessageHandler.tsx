import React, { useContext } from "react";

import { applyGuiConfigUpdate } from "./ControlPanel/GuiState";
import { toast } from "./components/ui/toast";
import {
  openFilePreview,
  previewKindFor,
  resolveFilePreview,
  warmedContents,
  warmFilePreview,
} from "./filePreview";
import { warmMarkdownDocument } from "./components/markdownDocument";
import {
  dismissNotification,
  fileDownloadToastOptions,
  showNotification,
  updateNotification,
} from "./notifications";
import { notePlotlyMaybeLoaded } from "./plotlyReady";
import { makeMessageQueueScheduler } from "./messageQueueScheduler";
import { ViewerContext } from "./ViewerContext";
import {
  FileTransferPart,
  FileTransferStartDownload,
  GuiComponentMessage,
  Message,
  isGuiComponentMessage,
} from "./WebsocketMessages";

type GuiUpdate = {
  uuid: string;
  updates: Record<string, unknown>;
};

function useMessageHandler(): (message: Message) => GuiUpdate | undefined {
  const viewer = useContext(ViewerContext)!;
  const fileDownloadHandler = useFileDownloadHandler();

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
  const viewer = useContext(ViewerContext)!;
  const handleMessage = useMessageHandler();

  React.useEffect(() => {
    const processQueue = () => {
      const queue = viewer.mutable.current.messageQueue;
      if (queue.length === 0) return;
      const batch = queue.splice(0, queue.length);
      const guiUpdates = new Map<string, Record<string, unknown>>();

      for (const message of batch) {
        // Updates are deferred to the end of the batch while removes apply
        // immediately, so an update whose component was removed later in the
        // same batch is legitimate leftover, not an error.
        if (message.type === "GuiRemoveMessage")
          guiUpdates.delete(message.uuid);
        const result = handleMessage(message);
        if (result === undefined) continue;
        guiUpdates.set(result.uuid, {
          ...(guiUpdates.get(result.uuid) ?? {}),
          ...result.updates,
        });
      }

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

function useFileDownloadHandler(): (
  message: FileTransferStartDownload | FileTransferPart,
) => void {
  const downloadStatesRef = React.useRef<
    Record<
      string,
      {
        metadata: FileTransferStartDownload;
        parts: FileTransferPart[];
        bytesDownloaded: number;
      }
    >
  >({});

  return (message) => {
    if (message.type === "FileTransferStartDownload") {
      downloadStatesRef.current[message.transfer_uuid] = {
        metadata: message,
        parts: [],
        bytesDownloaded: 0,
      };
      if (message.disposition === "preview") {
        // The dialog opens on the first message rather than the last: its
        // name, viewer and size are all here, so the click is answered now
        // and only the contents wait on the rest of the transfer -- or not
        // even that, when a warm transfer already brought them: the document
        // shows at once, and the arriving copy replaces it on landing.
        openFilePreview({
          id: message.transfer_uuid,
          filename: message.filename,
          mimeType: message.mime_type,
          sizeBytes: message.size_bytes,
          contents: warmedContents(message.filename),
        });
      }
    } else {
      const state = downloadStatesRef.current[message.transfer_uuid];
      if (state === undefined) {
        console.error(
          "Received FileTransferPart for unknown transfer",
          message.transfer_uuid,
        );
        return;
      }
      if (message.part_index !== state.parts.length) {
        console.error("A file download message was received out of order!");
      }
      state.parts.push(message);
      state.bytesDownloaded += message.content.length;
    }

    const state = downloadStatesRef.current[message.transfer_uuid];
    if (state.bytesDownloaded < state.metadata.size_bytes) return;

    // Every chunk has arrived: assemble the blob.
    const blob = new Blob(
      state.parts
        .sort((left, right) => left.part_index - right.part_index)
        .map((part) => part.content),
      { type: state.metadata.mime_type },
    );
    const url = URL.createObjectURL(blob);
    const { filename, disposition } = state.metadata;
    delete downloadStatesRef.current[message.transfer_uuid];

    if (disposition === "warm") {
      // Arrived ahead of its press, so nothing is shown: the file is held
      // for the preview that a press would open, and a markdown document is
      // readied the rest of the way -- parsed into the render cache, its
      // images fetched into the browser's -- while the reader is elsewhere.
      URL.revokeObjectURL(url);
      warmFilePreview(filename, blob);
      if (previewKindFor(state.metadata.mime_type, filename) === "markdown") {
        void blob.text().then(warmMarkdownDocument, () => undefined);
      }
      return;
    }

    if (disposition === "save") {
      // Hand the blob straight to the browser, which owns the download UI from
      // here (its own progress/downloads list).
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      return;
    }

    if (disposition === "preview") {
      // The dialog owns the URL from here: every viewer in it reads from the
      // URL, so it is revoked when the dialog closes rather than now -- or
      // right away, if the dialog was closed while the file was in flight.
      resolveFilePreview(message.transfer_uuid, { url, blob });
      return;
    }

    // Otherwise offer the file as a link, which the user can also right click
    // to "Save as...". The object URL has to outlive this call, so it is
    // revoked only once the toast is gone.
    const options = fileDownloadToastOptions(filename, url);
    toast.add({
      id: message.transfer_uuid,
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
