import React from "react";

import { useClientSettings } from "./ClientSettings";
import { UseGui } from "./ControlPanel/GuiState";
import { Message } from "./WebsocketMessages";
import type { MessageSender } from "./connectionSender";
import type { BoundedMessageQueue } from "./boundedMessageQueue";
import type { FileDownloadAssembler } from "./fileDownloadAssembler";
import type { FileUploadAckBroker } from "./fileUploadAckBroker";
import { useViewportState } from "./viewport/ViewportState";

/** Mutable transport state for the live websocket producer. */
export type ViewerMutable = {
  sendMessage: MessageSender;
  messageQueue: BoundedMessageQueue;
  notifyMessageQueue: () => void;
  downloads: FileDownloadAssembler;
  uploads: FileUploadAckBroker;
  /** Terminate/reset the current transport on a semantic trust-boundary
   * violation discovered before a wire frame applies side effects. */
  failConnection: (reason: string) => void;
};

export function warnDisconnectedSend(message: Message): void {
  console.warn(`Cannot send ${message.type}: WebSocket is not connected.`);
}

/** Application context for Leika's GUI and 2D pane workspace. */
export type ViewerContextContents = {
  useGui: UseGui["store"];
  useGuiConfig: UseGui["configStore"];
  guiActions: UseGui["actions"];
  useViewport: ReturnType<typeof useViewportState>["store"];
  viewportActions: ReturnType<typeof useViewportState>["actions"];
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
