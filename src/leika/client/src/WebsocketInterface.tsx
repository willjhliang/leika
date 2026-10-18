import { encode } from "@msgpack/msgpack";
import React from "react";
import { ZSTDDecoder } from "zstddec";

import { connectionStats } from "./ConnectionStatsController";
import { emptyCounters } from "./connectionStats";
import { resetMarkdownDocumentCache } from "./components/markdownDocument";
import { resetFileTransferFailureToast } from "./fileDownloadHandler";
import { resetFilePreviewState } from "./filePreview";
import { decodeHybridMessage } from "./hybridMessageDecode";
import { handleMessages } from "./MessageHandler";
import { resetNotifications } from "./notifications";
import { resetMountedRasterPixels } from "./rasterPixelBudget";
import { retainedDownloads } from "./retainedDownloadBudget";
import { useViewer, warnDisconnectedSend } from "./ViewerContext";
import { LEIKA_PROTOCOL, type Message } from "./WebsocketMessages";

/** How often a watched connection is pinged and reported on. */
const STATS_INTERVAL_MS = 1000;
/** Round trips kept for the median: half a minute of them at that rate. */
const ROUND_TRIP_WINDOW = 30;

// Ready before the first socket opens, so every frame decodes synchronously
// in arrival order.
const zstd = new ZSTDDecoder();
const zstdReady = zstd.init();

/** Own the websocket: connect, retry while visible, decode frames, apply
 * their messages once per animation frame, and measure the connection. */
export function WebsocketMessageProducer() {
  const viewer = useViewer();
  const { server } = viewer;

  React.useEffect(() => {
    viewer.viewportActions.setPersistenceServer(server);
    let active = true;
    let socket: WebSocket | null = null;
    let connected = false;
    let retryAllowed = true;
    let retryTimer: ReturnType<typeof setInterval> | null = null;
    let requestedPageId: string | null = null;
    let pageGeneration = 0;

    // Counted where the socket is, for the life of the page across
    // reconnects; rates and verdicts are derived from snapshots.
    const counters = emptyCounters(performance.now());
    let connectionsOpened = 0;
    let statsTimer: ReturnType<typeof setInterval> | null = null;

    // A burst of frames applies once, on the next animation frame. Hidden
    // tabs get no animation frames, so a timer drains them as well.
    let queue: Message[] = [];
    let drainFrame: number | null = null;
    let drainTimer: ReturnType<typeof setTimeout> | null = null;
    const cancelDrain = () => {
      if (drainFrame !== null) cancelAnimationFrame(drainFrame);
      if (drainTimer !== null) clearTimeout(drainTimer);
      drainFrame = null;
      drainTimer = null;
    };
    const drain = () => {
      cancelDrain();
      const messages = queue;
      queue = [];
      handleMessages(viewer, messages);
    };
    const scheduleDrain = () => {
      if (drainFrame !== null) return;
      drainFrame = requestAnimationFrame(drain);
      drainTimer = setTimeout(drain, 100);
    };

    /** A sender belongs to one socket, so work still holding it after a
     * reconnect drops its sends instead of reaching the new connection. */
    const senderFor =
      (target: WebSocket) =>
      (message: Message): void => {
        if (target.readyState !== WebSocket.OPEN) {
          counters.droppedSends += 1;
          return;
        }
        const encoded = encode(message);
        target.send(encoded);
        counters.bytesSent += encoded.byteLength;
        counters.messagesSent += 1;
      };

    const resetConnectionState = (retainPanes: boolean) => {
      requestedPageId = null;
      cancelDrain();
      queue = [];
      viewer.guiActions.resetGui();
      if (retainPanes) viewer.viewportActions.reconnect();
      else viewer.viewportActions.resetPanes();
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
      // Retained renderers still own their pixel leases during an ordinary
      // reconnect; their unmount releases them after replay or eviction.
      if (!retainPanes) resetMountedRasterPixels();
    };

    const updateRetryInterval = () => {
      const shouldRetry =
        active &&
        retryAllowed &&
        !connected &&
        document.visibilityState !== "hidden";
      if (!connected) {
        viewer.useGui.set({
          websocketState: shouldRetry ? "reconnecting" : "inactive",
        });
      }
      if (shouldRetry && retryTimer === null) {
        retryTimer = setInterval(connect, 1000);
        connect();
      } else if (!shouldRetry && retryTimer !== null) {
        clearInterval(retryTimer);
        retryTimer = null;
      }
    };

    const markDisconnected = (retry: boolean, error: string | null) => {
      connected = false;
      retryAllowed = retry;
      resetConnectionState(active && retry);
      viewer.mutable.current.sendMessage = warnDisconnectedSend;
      viewer.useGui.set({ connectionError: error });
      updateRetryInterval();
    };

    /** Open a socket unless one is already connecting or open. */
    function connect() {
      if (socket !== null && socket.readyState <= WebSocket.OPEN) return;
      // One subprotocol string identifies the package version and schema this
      // bundle was built against; the server turns away anything else.
      const ws = new WebSocket(server, [`leika-${LEIKA_PROTOCOL}`]);
      ws.binaryType = "arraybuffer";
      socket = ws;
      // A tunnelled port can accept a connection that never opens.
      const timeout = setTimeout(() => ws.close(), 5000);

      ws.onopen = () => {
        clearTimeout(timeout);
        if (ws !== socket) return;
        connectionsOpened += 1;
        counters.connectedSinceMs = performance.now();
        // Every connection after the first is one the page lost and got back.
        counters.reconnects = connectionsOpened - 1;
        connected = true;
        retryAllowed = true;
        resetConnectionState(true);
        viewer.useGui.set({
          websocketState: "connected",
          connectionError: null,
        });
        updateRetryInterval();
        viewer.mutable.current.sendMessage = senderFor(ws);
        sentRendering = null;
        syncRendering();
      };

      ws.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (ws !== socket) return;
        const receivedMs = performance.now();
        counters.bytesReceived += event.data.byteLength;
        const messages = decodeHybridMessage(event.data, zstd);
        counters.messagesReceived += messages.length;
        for (const message of messages) {
          // Answers to the statistics pings stop here.
          if (message.type === "ServerPongMessage") {
            counters.roundTripsMs.push(receivedMs - message.sent_ms);
            if (counters.roundTripsMs.length > ROUND_TRIP_WINDOW)
              counters.roundTripsMs.shift();
          } else queue.push(message);
        }
        scheduleDrain();
      };

      ws.onclose = (event) => {
        clearTimeout(timeout);
        if (ws !== socket) return;
        socket = null;
        counters.connectedSinceMs = null;
        // The server closes with 1002 a page built from other code.
        if (event.code === 1002) {
          console.warn(
            `Connection rejected: ${event.reason}. Client protocol: ${LEIKA_PROTOCOL}`,
          );
          markDisconnected(false, `Connection rejected: ${event.reason}`);
        } else markDisconnected(true, viewer.useGui.get().connectionError);
      };
    }

    const syncPageSubscription = () => {
      const state = viewer.useViewport.get();
      const pageId = state.activePageId;
      if (
        !connected ||
        !state.catalogReady ||
        pageId === null ||
        requestedPageId === pageId
      )
        return;
      requestedPageId = pageId;
      pageGeneration += 1;
      viewer.viewportActions.beginPageSubscription(pageId, pageGeneration);
      viewer.mutable.current.sendMessage({
        type: "PageSubscribeMessage",
        page_id: pageId,
        generation: pageGeneration,
      });
    };
    const unsubscribePageSubscription =
      viewer.useViewport.subscribe(syncPageSubscription);

    let sentRendering: string | null = null;
    const syncRendering = () => {
      if (!connected) return;
      const { rendering, imageFit } = viewer.useSettings.get();
      const key = `${rendering}:${imageFit}`;
      if (key === sentRendering) return;
      sentRendering = key;
      viewer.mutable.current.sendMessage({
        type: "RenderingSettingsMessage",
        rendering,
        image_fit: imageFit,
      });
    };
    const unsubscribeRendering = viewer.useSettings.subscribe(syncRendering);

    // The connection is pinged only while something is watching it.
    const reportStats = () => {
      // Ping first: the reply lands before the next tick, so this reports the
      // round trip the last tick asked for.
      if (connected) {
        viewer.mutable.current.sendMessage({
          type: "ClientPingMessage",
          sent_ms: performance.now(),
        });
      }
      counters.atMs = performance.now();
      connectionStats.record({
        ...counters,
        roundTripsMs: [...counters.roundTripsMs],
      });
    };
    const updateWatching = () => {
      const watching = connectionStats.store.get().watchers > 0;
      if (watching === (statsTimer !== null)) return;
      if (watching) {
        // The timer first: a report notifies this same store.
        statsTimer = setInterval(reportStats, STATS_INTERVAL_MS);
        reportStats();
        return;
      }
      clearInterval(statsTimer!);
      statsTimer = null;
      // Round trips from the last look say nothing about the link now.
      counters.roundTripsMs.length = 0;
    };
    const unsubscribeWatchers = connectionStats.store.subscribe(updateWatching);
    updateWatching();

    void zstdReady.then(() => {
      if (!active) return;
      document.addEventListener("visibilitychange", updateRetryInterval);
      updateRetryInterval();
    });
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", updateRetryInterval);
      if (statsTimer !== null) clearInterval(statsTimer);
      unsubscribePageSubscription();
      unsubscribeRendering();
      unsubscribeWatchers();
      const closing = socket;
      socket = null;
      closing?.close();
      // The counters belong to this connection, not the one that follows.
      connectionStats.forget();
      markDisconnected(false, null);
    };
  }, [server, viewer]);

  return null;
}
