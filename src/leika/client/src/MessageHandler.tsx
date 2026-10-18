import { toast } from "./components/ui/toast";
import { DeferredObjectUrlReleaser } from "./deferredObjectUrlReleaser";
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
import { runPlotlyBootstrap } from "./plotlyReady";
import {
  isGuiStateMessage,
  type GuiStateMessage,
} from "./ControlPanel/GuiState";
import type { ViewerContextContents } from "./ViewerContext";
import {
  FileTransferAbort,
  FileTransferPart,
  FileTransferStartDownload,
  Message,
} from "./WebsocketMessages";

/** Apply server messages in order. GUI messages commit as one transaction,
 * in order among themselves; no other message reads GUI state. */
export function handleMessages(
  viewer: ViewerContextContents,
  messages: readonly Message[],
): void {
  const guiMessages: GuiStateMessage[] = [];
  for (const message of messages) {
    if (isGuiStateMessage(message)) {
      guiMessages.push(message);
      continue;
    }
    try {
      handleMessage(viewer, message);
    } catch (error) {
      console.error(
        `Failed to process Leika message '${message.type}':`,
        error,
      );
    }
  }
  viewer.guiActions.applyMessages(guiMessages);
}

function handleMessage(viewer: ViewerContextContents, message: Message): void {
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
      runPlotlyBootstrap(message.source);
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
    case "ViewportImageMessage":
    case "ViewportMatplotlibMessage":
    case "ViewportPlotlyMessage":
    case "ViewportVideoMessage":
    case "ViewportViserMessage":
      viewer.viewportActions.addPane(message);
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
      viewer.viewportActions.setPaneSnapshot(message.page_id, message.pane_ids);
      return;
    case "FileTransferStartDownload":
    case "FileTransferPart":
      handleDownload(viewer, message);
      return;
    case "FileTransferAbort":
      // Abort is bidirectional. An active upload gets first claim on its
      // client-generated transfer ID; otherwise this belongs to a download.
      if (viewer.mutable.current.uploads.acceptAbort(message).matched) return;
      handleDownload(viewer, message);
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
}

const savedUrlReleaser = new DeferredObjectUrlReleaser();

function handleDownload(
  viewer: ViewerContextContents,
  message: FileTransferStartDownload | FileTransferPart | FileTransferAbort,
): void {
  handleFileDownloadMessage(message, {
    downloads: viewer.mutable.current.downloads,
    savedUrlReleaser,
    sendMessage: (abort) => viewer.mutable.current.sendMessage(abort),
    createBlob: (parts, mimeType) => new Blob(parts, { type: mimeType }),
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    addToast: (options) => toast.add(options),
    closeToast: (id) => toast.close(id),
    document,
  });
}
