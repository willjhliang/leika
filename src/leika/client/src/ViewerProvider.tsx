import React from "react";

import { useClientSettings } from "./ClientSettings";
import { useGuiState } from "./ControlPanel/GuiState";
import { useViewportState } from "./viewport/ViewportState";
import { BoundedMessageQueue } from "./boundedMessageQueue";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import { FileUploadAckBroker } from "./fileUploadAckBroker";
import { retainedDownloads } from "./retainedDownloadBudget";
import {
  ViewerContext,
  type ViewerContextContents,
  type ViewerMutable,
  warnDisconnectedSend,
} from "./ViewerContext";

/** A viewer owns one set of transport resources, shared by its producer and
 * message handler. Construct these lazily so rendering never replaces or
 * allocates a second queue, download assembler, or upload broker. */
function createViewerTransport(): ViewerMutable {
  return {
    sendMessage: warnDisconnectedSend,
    messageQueue: new BoundedMessageQueue(),
    notifyMessageQueue: () => undefined,
    downloads: new FileDownloadAssembler(retainedDownloads),
    uploads: new FileUploadAckBroker(),
    failConnection: (reason) =>
      console.error("Cannot fail an inactive connection:", reason),
  };
}

/** Composition boundary for browser state and mutable transport resources. */
export function ViewerProvider({
  initialServer,
  children,
}: {
  initialServer: string;
  children: React.ReactNode;
}) {
  const [transport] = React.useState(createViewerTransport);
  const mutable = React.useRef(transport);
  const guiState = useGuiState(initialServer);
  const viewportState = useViewportState();
  const { store: settingsStore, actions: settingsActions } =
    useClientSettings();
  // Memoized: a rebuilt context value would re-render every consumer in the
  // app whenever its provider re-renders.
  const viewer: ViewerContextContents = React.useMemo(
    () => ({
      useGui: guiState.store,
      useGuiConfig: guiState.configStore,
      guiActions: guiState.actions,
      useViewport: viewportState.store,
      viewportActions: viewportState.actions,
      useSettings: settingsStore,
      settingsActions: settingsActions,
      mutable,
    }),
    [guiState, viewportState, settingsStore, settingsActions],
  );

  return (
    <ViewerContext.Provider value={viewer}>{children}</ViewerContext.Provider>
  );
}
