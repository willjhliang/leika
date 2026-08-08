import React from "react";

import { connectionStats } from "./ConnectionStatsController";
import { useViewer, warnDisconnectedSend } from "./ViewerContext";
import WebsocketClientWorker from "./WebsocketClientWorker?worker&inline";
import { WsWorkerIncoming, WsWorkerOutgoing } from "./WebsocketClientWorker";
import { syncSearchParamServer } from "./SearchParamsUtils";
import { installConnectionBoundSender } from "./connectionSender";
import { resetFilePreviewState } from "./filePreview";
import { WorkerEventGate } from "./workerFailure";

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
      resetFilePreviewState();
      viewer.mutable.current.messageQueue.length = 0;
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
      viewer.guiActions.resetGui();
      resetConnectionResources();
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
        viewer.guiActions.resetGui();
        viewer.viewportActions.resetPanes();
        resetConnectionResources();
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
        viewer.mutable.current.messageQueue.push(...data.messages);
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
      workerEvents.close();
      worker.onmessage = null;
      worker.onerror = null;
      worker.onmessageerror = null;
      terminateWorker();
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
