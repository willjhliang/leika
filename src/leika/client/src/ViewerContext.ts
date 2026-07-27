import React from "react";

import { useClientSettings } from "./ClientSettings";
import { UseGui } from "./ControlPanel/GuiState";
import { Message } from "./WebsocketMessages";
import { useViewportState } from "./viewport/ViewportState";

/** Mutable transport state for the live websocket producer. */
export type ViewerMutable = {
  sendMessage: (message: Message) => void;
  messageQueue: Message[];
};

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
