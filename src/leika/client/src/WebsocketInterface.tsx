import React from "react";

import { connectionStats } from "./ConnectionStatsController";
import { resetMarkdownDocumentCache } from "./components/markdownDocument";
import { resetNotifications } from "./notifications";
import { useViewer, warnDisconnectedSend } from "./ViewerContext";
import WebsocketClientWorker from "./WebsocketClientWorker?worker&inline";
import { WsWorkerIncoming, WsWorkerOutgoing } from "./WebsocketClientWorker";
import { syncSearchParamServer } from "./SearchParamsUtils";
import { installConnectionBoundSender } from "./connectionSender";
import { resetConnectionOwners } from "./connectionLifecycle";
import { resetFilePreviewState } from "./filePreview";
import { resetFileTransferFailureToast } from "./fileDownloadHandler";
import { retainedDownloads } from "./retainedDownloadBudget";
import { WorkerEventGate } from "./workerFailure";
import { plotlyBootstrap } from "./plotlyBootstrap";
import { resetMountedRasterPixels } from "./rasterPixelBudget";
import type { PageSubscribeMessage } from "./WebsocketMessages";

/** Live binary websocket producer with focus-aware reconnect behavior. */
export function WebsocketMessageProducer() {
  const viewer = useViewer();
  const server = viewer.useGui((state) => state.server);

  // An effect, not a render side effect: `replaceState` mutates shared
  // browser state, which render must not.
  React.useEffect(() => syncSearchParamServer(server), [server]);

  React.useEffect(() => {
    viewer.viewportActions.setPersistenceServer(server);
    const worker = new WebsocketClientWorker();
    const terminateWorker = () => {
      try {
        worker.terminate();
      } catch (error) {
        console.error("Could not terminate connection worker:", error);
      }
    };
    let active = true;
    const workerEvents = new WorkerEventGate();
    let isConnected = false;
    let retryAllowed = true;
    let requestedPageId: string | null = null;
    let pageSubscriptionGeneration = 0;
    let retryIntervalId: ReturnType<typeof setInterval> | null = null;
    const postToWorker = (data: WsWorkerIncoming) => {
      if (!workerEvents.acceptsEvents) return;
      try {
        worker.postMessage(data);
      } catch (error) {
        failWorker(
          error instanceof Error && error.message.length > 0
            ? "Connection worker could not receive a command: " + error.message
            : "Connection worker could not receive a command.",
        );
      }
    };

    const updateRetryInterval = () => {
      const shouldRetry = retryAllowed && !isConnected && document.hasFocus();
      if (!isConnected) {
        viewer.useGui.set({
          websocketState: shouldRetry ? "reconnecting" : "inactive",
        });
      }
      if (shouldRetry && retryIntervalId === null) {
        postToWorker({ type: "retry" });
        retryIntervalId = setInterval(
          () => postToWorker({ type: "retry" }),
          1000,
        );
      } else if (!shouldRetry && retryIntervalId !== null) {
        clearInterval(retryIntervalId);
        retryIntervalId = null;
      }
    };

    const resetConnectionResources = () => {
      viewer.mutable.current.downloads.reset();
      viewer.mutable.current.uploads.reset(
        "The connection changed during the upload.",
      );
      resetFilePreviewState();
      // Preview/warm owners release themselves above. This also closes file
      // link toasts from the old server; protected save navigations alone stay
      // alive until their one-second cross-browser grace timer completes.
      retainedDownloads.evictAll();
      resetMarkdownDocumentCache();
      resetNotifications();
      resetFileTransferFailureToast();
      plotlyBootstrap.reset();
      resetMountedRasterPixels();
      viewer.mutable.current.messageQueue.reset();
    };

    const resetConnectionState = () => {
      requestedPageId = null;
      resetConnectionOwners({
        resetGui: viewer.guiActions.resetGui,
        resetPanes: viewer.viewportActions.resetPanes,
        resetResources: resetConnectionResources,
      });
    };

    const markDisconnected = ({
      retry,
      error,
    }: {
      retry: boolean;
      error: string | null;
    }) => {
      isConnected = false;
      retryAllowed = retry;
      resetConnectionState();
      viewer.mutable.current.sendMessage = warnDisconnectedSend;
      viewer.useGui.set({ connectionError: error });
      updateRetryInterval();
    };

    const failWorker = (reason: string) => {
      if (!active || !workerEvents.close()) return;
      terminateWorker();
      connectionStats.forget();
      markDisconnected({
        retry: false,
        error: reason.endsWith(".")
          ? reason + " Reload the page to reconnect."
          : reason + ". Reload the page to reconnect.",
      });
    };
    viewer.mutable.current.failConnection = failWorker;

    const syncPageSubscription = () => {
      const state = viewer.useViewport.get();
      const pageId = state.activePageId;
      if (
        !isConnected ||
        !state.catalogReady ||
        pageId === null ||
        requestedPageId === pageId
      )
        return;
      requestedPageId = pageId;
      pageSubscriptionGeneration =
        pageSubscriptionGeneration >= Number.MAX_SAFE_INTEGER
          ? 1
          : pageSubscriptionGeneration + 1;
      viewer.viewportActions.beginPageSubscription(
        pageId,
        pageSubscriptionGeneration,
      );
      const message: PageSubscribeMessage = {
        type: "PageSubscribeMessage",
        page_id: pageId,
        generation: pageSubscriptionGeneration,
      };
      viewer.mutable.current.sendMessage(message);
    };
    const unsubscribePageSubscription =
      viewer.useViewport.subscribe(syncPageSubscription);

    // The worker measures only while something is watching, so it is told when
    // that changes -- and only then, since the counters it reports arrive
    // through this same store once a second.
    let watching = false;
    const updateWatching = () => {
      const wanted = connectionStats.store.get().watchers > 0;
      if (wanted === watching) return;
      watching = wanted;
      postToWorker({ type: "watch_stats", watching });
    };
    const unsubscribeWatchers = connectionStats.store.subscribe(updateWatching);

    window.addEventListener("focus", updateRetryInterval);
    window.addEventListener("blur", updateRetryInterval);
    worker.onmessage = (event: MessageEvent<WsWorkerOutgoing>) => {
      if (!active || !workerEvents.acceptsEvents) return;
      const data = event.data;
      if (data.type === "fatal") {
        failWorker(data.reason);
        return;
      }
      if (data.type === "stats") {
        connectionStats.record(data.counters);
        return;
      }
      if (data.type === "connected") {
        isConnected = true;
        retryAllowed = true;
        resetConnectionState();
        viewer.useGui.set({
          websocketState: "connected",
          connectionError: null,
        });
        updateRetryInterval();
        installConnectionBoundSender(viewer.mutable.current, (message) =>
          postToWorker({ type: "send", message }),
        );
        return;
      }
      if (data.type === "closed") {
        markDisconnected({
          retry: !data.versionMismatch,
          error: data.versionMismatch
            ? "Connection rejected: " + data.closeReason
            : null,
        });
        return;
      }
      // The worker's rate smoothing can deliver a batch after the close; a
      // batch from a dead connection must not replay over the reset GUI.
      if (isConnected) {
        if (
          !viewer.mutable.current.messageQueue.enqueue(
            data.messages,
            data.frameBytes,
            data.metadataBytes,
          )
        ) {
          failWorker(
            "Connection message queue exceeded its browser safety limit",
          );
          return;
        }
        // Only now does the worker release this transferred frame from its
        // connection-generation budget and permit the next ordered batch.
        postToWorker({
          type: "batch_received",
          connectionId: data.connectionId,
          batchId: data.batchId,
        });
        viewer.mutable.current.notifyMessageQueue();
      }
    };
    worker.onerror = (event) => {
      event.preventDefault();
      failWorker(
        event.message.length > 0
          ? "Connection worker failed: " + event.message
          : "Connection worker failed.",
      );
    };
    worker.onmessageerror = () => {
      failWorker("Connection worker could not decode a message.");
    };

    postToWorker({ type: "set_server", server });
    updateWatching();
    return () => {
      active = false;
      if (viewer.mutable.current.failConnection === failWorker) {
        viewer.mutable.current.failConnection = (reason) =>
          console.error("Cannot fail an inactive connection:", reason);
      }
      workerEvents.close();
      worker.onmessage = null;
      worker.onerror = null;
      worker.onmessageerror = null;
      terminateWorker();
      unsubscribePageSubscription();
      unsubscribeWatchers();
      // The counters belong to the worker that is about to be replaced, so
      // they say nothing about the connection that follows.
      connectionStats.forget();
      window.removeEventListener("focus", updateRetryInterval);
      window.removeEventListener("blur", updateRetryInterval);
      markDisconnected({ retry: false, error: null });
    };
  }, [server, viewer]);

  return null;
}
