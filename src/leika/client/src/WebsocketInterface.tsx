import React, { useContext } from "react";

import { connectionStats } from "./ConnectionStatsController";
import { ViewerContext } from "./ViewerContext";
import WebsocketClientWorker from "./WebsocketClientWorker?worker&inline";
import { WsWorkerIncoming, WsWorkerOutgoing } from "./WebsocketClientWorker";
import { syncSearchParamServer } from "./SearchParamsUtils";

/** Live binary websocket producer with focus-aware reconnect behavior. */
export function WebsocketMessageProducer() {
  const viewer = useContext(ViewerContext)!;
  const server = viewer.useGui((state) => state.server);

  // An effect, not a render side effect: `replaceState` mutates shared
  // browser state, which render must not.
  React.useEffect(() => syncSearchParamServer(server), [server]);

  React.useEffect(() => {
    viewer.viewportActions.setPersistenceServer(server);
    const worker = new WebsocketClientWorker();
    let isConnected = false;
    let retryIntervalId: ReturnType<typeof setInterval> | null = null;
    const postToWorker = (data: WsWorkerIncoming) => worker.postMessage(data);

    const updateRetryInterval = () => {
      const shouldRetry = !isConnected && document.hasFocus();
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
      const data = event.data;
      if (data.type === "stats") {
        connectionStats.record(data.counters);
        return;
      }
      if (data.type === "connected") {
        isConnected = true;
        viewer.guiActions.resetGui();
        viewer.viewportActions.resetPanes();
        viewer.mutable.current.messageQueue.length = 0;
        viewer.useGui.set({
          websocketState: "connected",
          connectionError: null,
        });
        updateRetryInterval();
        viewer.mutable.current.sendMessage = (message) =>
          postToWorker({ type: "send", message });
        return;
      }
      if (data.type === "closed") {
        isConnected = false;
        viewer.guiActions.resetGui();
        // Anything still queued belongs to the dead connection.
        viewer.mutable.current.messageQueue.length = 0;
        updateRetryInterval();
        viewer.mutable.current.sendMessage = (message) =>
          console.log(
            `Tried to send ${message.type} but websocket is not connected!`,
          );
        if (data.versionMismatch) {
          // Retrying cannot fix a version mismatch, so this is reported as a
          // standing error on the connection status rather than a transient
          // "reconnecting" state.
          viewer.useGui.set({
            connectionError: `Connection rejected: ${data.closeReason}`,
          });
        }
        return;
      }
      // The worker's rate smoothing can deliver a batch after the close; a
      // batch from a dead connection must not replay over the reset GUI.
      if (isConnected)
        viewer.mutable.current.messageQueue.push(...data.messages);
    };

    postToWorker({ type: "set_server", server });
    updateWatching();
    return () => {
      unsubscribeWatchers();
      // The counters belong to the worker that is about to be replaced, so
      // they say nothing about the connection that follows.
      connectionStats.forget();
      window.removeEventListener("focus", updateRetryInterval);
      window.removeEventListener("blur", updateRetryInterval);
      if (retryIntervalId !== null) clearInterval(retryIntervalId);
      postToWorker({ type: "close" });
      viewer.mutable.current.sendMessage = (message) =>
        console.log(
          `Tried to send ${message.type} but websocket is not connected!`,
        );
      viewer.useGui.set({ websocketState: "inactive" });
    };
  }, [server, viewer]);

  return null;
}
