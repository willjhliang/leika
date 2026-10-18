import React from "react";
import type { VideoPlaybackRegistry } from "./viewport/videoPlayback";

import { useClientSettings } from "./ClientSettings";
import type { GuiSession } from "./ControlPanel/GuiState";
import { Message } from "./WebsocketMessages";
import type { FileDownloadAssembler } from "./fileDownloadAssembler";
import type { FileUploadAckBroker } from "./fileUploadAckBroker";
import type { ViewportSession } from "./viewport/ViewportState";

export type MessageSender = (message: Message) => void;

/** Mutable transport state for the live websocket producer. */
export type ViewerMutable = {
  /** Sends on the current connection; replaced on every connect. */
  sendMessage: MessageSender;
  downloads: FileDownloadAssembler;
  uploads: FileUploadAckBroker;
};

export function warnDisconnectedSend(message: Message): void {
  console.warn(`Cannot send ${message.type}: WebSocket is not connected.`);
}

/** Application context for Leika's GUI and 2D pane workspace. */
export type ViewerContextContents = {
  videoPlayback: VideoPlaybackRegistry;
  useGui: GuiSession["store"];
  useGuiConfig: GuiSession["configStore"];
  guiActions: GuiSession["actions"];
  useViewport: ViewportSession["store"];
  viewportActions: ViewportSession["actions"];
  useSettings: ReturnType<typeof useClientSettings>["store"];
  settingsActions: ReturnType<typeof useClientSettings>["actions"];
  mutable: React.MutableRefObject<ViewerMutable>;
};

export const ViewerContext = React.createContext<ViewerContextContents | null>(
  null,
);

/** Read the current viewer, failing at the component boundary if it is absent. */
export function useViewer(): ViewerContextContents {
  const viewer = React.useContext(ViewerContext);
  if (viewer === null) {
    throw new Error("useViewer must be used within ViewerContext.Provider");
  }
  return viewer;
}
