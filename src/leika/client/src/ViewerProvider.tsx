import React from "react";
import { VideoPlaybackRegistry } from "./viewport/videoPlayback";

import { useClientSettings } from "./ClientSettings";
import { useGuiState } from "./ControlPanel/GuiState";
import { useViewportState } from "./viewport/ViewportState";
import { FileDownloadAssembler } from "./fileDownloadAssembler";
import { FileUploadAckBroker } from "./fileUploadAckBroker";
import { retainedDownloads } from "./retainedDownloadBudget";
import {
  ViewerContext,
  type ViewerContextContents,
  type ViewerMutable,
  warnDisconnectedSend,
} from "./ViewerContext";

/** A viewer owns one set of transport resources. Construct these lazily so
 * rendering never allocates a second download assembler or upload broker. */
function createViewerTransport(): ViewerMutable {
  return {
    sendMessage: warnDisconnectedSend,
    downloads: new FileDownloadAssembler(retainedDownloads),
    uploads: new FileUploadAckBroker(),
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
  const [videoPlayback] = React.useState(() => new VideoPlaybackRegistry());
  React.useEffect(() => {
    const sync = () => videoPlayback.reconcile(viewportState.store.get());
    sync();
    const unsubscribe = viewportState.store.subscribe(sync);
    document.addEventListener("visibilitychange", sync);
    return () => {
      unsubscribe();
      document.removeEventListener("visibilitychange", sync);
      videoPlayback.dispose();
    };
  }, [viewportState, videoPlayback]);
  const { store: settingsStore, actions: settingsActions } =
    useClientSettings();
  // Memoized: a rebuilt context value would re-render every consumer in the
  // app whenever its provider re-renders.
  const viewer: ViewerContextContents = React.useMemo(
    () => ({
      videoPlayback,
      useGui: guiState.store,
      useGuiConfig: guiState.configStore,
      guiActions: guiState.actions,
      useViewport: viewportState.store,
      viewportActions: viewportState.actions,
      useSettings: settingsStore,
      settingsActions: settingsActions,
      mutable,
    }),
    [guiState, viewportState, settingsStore, settingsActions, videoPlayback],
  );

  return (
    <ViewerContext.Provider value={viewer}>{children}</ViewerContext.Provider>
  );
}
