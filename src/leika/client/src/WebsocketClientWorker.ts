import * as msgpack from "@msgpack/msgpack";
import AwaitLock from "await-lock";
import { ZSTDDecoder } from "zstddec";

import { ConnectionCounters, emptyCounters } from "./connectionStats";
import { decodeHybridMessage } from "./hybridMessageDecode";
import { newPacingState, paceBatch } from "./pacing";
import { PendingRawFrameBudget } from "./pendingFrameBudget";
import { shouldRetryWebsocket } from "./utils/shouldRetryWebsocket";
import { LEIKA_VERSION } from "./VersionInfo";
import { LEIKA_PROTOCOL, Message } from "./WebsocketMessages";
import {
  acquireConnectionMessageOrder,
  ConnectionBatchTasks,
  runWithDeferredRelease,
} from "./websocketBatchOrdering";
import { FatalWorkerEvent, WorkerFailureController } from "./workerFailure";
import { WorkerBatchReceiptGate } from "./workerBatchReceipt";
import {
  classifySocketClose,
  closeRejectedConnection,
  type WebsocketCloseKind,
} from "./websocketClose";
import { sendWithWebsocketBudget } from "./websocketSendBudget";

export type WsWorkerIncoming =
  | { type: "send"; message: Message }
  | { type: "set_server"; server: string }
  | { type: "retry" }
  | { type: "batch_received"; connectionId: number; batchId: number }
  | { type: "watch_stats"; watching: boolean };

export type WsWorkerOutgoing =
  | { type: "connected" }
  | {
      type: "closed";
      closeKind: WebsocketCloseKind;
      closeReason: string;
    }
  | {
      type: "message_batch";
      messages: Message[];
      connectionId: number;
      batchId: number;
      frameBytes: number;
      metadataBytes: number;
    }
  | { type: "stats"; counters: ConnectionCounters }
  | FatalWorkerEvent;

type WorkerScope = {
  postMessage(data: WsWorkerOutgoing, transferable?: Transferable[]): void;
  onmessage: ((event: MessageEvent<WsWorkerIncoming>) => void) | null;
};

const workerScope = self as unknown as WorkerScope;

{
  let server: string | null = null;
  let ws: WebSocket | null = null;

  // -- What the connection is doing ----------------------------------------
  //
  // Counted here rather than on the main thread because this is where the
  // socket is: bytes are weighed as frames arrive, and a round trip is timed
  // from the moment the frame lands, before decoding, pacing and React have
  // had their turn. Totals run for the life of the page, across reconnects.

  /** How often a watched connection is pinged and reported on. */
  const STATS_INTERVAL_MS = 1000;
  /** Round trips kept for the median: half a minute of them at that rate. */
  const ROUND_TRIP_WINDOW = 30;

  const counters = emptyCounters(performance.now());
  let connectionsOpened = 0;
  let statsTimer: ReturnType<typeof setInterval> | null = null;
  let connectionBatchTasks: ConnectionBatchTasks | null = null;
  let connectionFrameBudget: PendingRawFrameBudget | null = null;
  let connectionReceiptGate: WorkerBatchReceiptGate | null = null;
  let rejectCurrentSendQueue: ((reason: string) => void) | null = null;
  let nextConnectionId = 0;

  const surfaceWorkerError = (error: unknown) => {
    const surfaced =
      error instanceof Error ? error : new Error("Worker failure: " + error);
    setTimeout(() => {
      throw surfaced;
    }, 0);
  };

  const failure = new WorkerFailureController(
    () => {
      server = null;
      if (statsTimer !== null) clearInterval(statsTimer);
      statsTimer = null;
      connectionBatchTasks?.cancelAll();
      connectionBatchTasks = null;
      connectionReceiptGate?.reset();
      connectionReceiptGate = null;
      rejectCurrentSendQueue = null;
      connectionFrameBudget?.reset();
      connectionFrameBudget = null;

      const failedSocket = ws;
      ws = null;
      counters.connectedSinceMs = null;
      failedSocket?.close();
    },
    (event) => workerScope.postMessage(event),
    surfaceWorkerError,
  );

  const postOutgoing = (
    data: WsWorkerOutgoing,
    transferable?: Transferable[],
  ): boolean =>
    failure.post("Connection worker could not post a message", () =>
      workerScope.postMessage(data, transferable),
    );

  // Decoder initialization is owned by this worker lifecycle. A rejected
  // initialization must not linger as an unhandled promise while the socket
  // continues to claim it is connected.
  let zstdDecoder: ZSTDDecoder | null = null;
  let zstdReady: Promise<void> | null = null;
  try {
    zstdDecoder = new ZSTDDecoder();
    zstdReady = zstdDecoder.init();
    void zstdReady.catch((error: unknown) => {
      failure.fail("Connection worker could not initialize its decoder", error);
    });
  } catch (error) {
    failure.fail("Connection worker could not initialize its decoder", error);
  }

  const recordRoundTrip = (ms: number) => {
    counters.roundTripsMs.push(ms);
    if (counters.roundTripsMs.length > ROUND_TRIP_WINDOW)
      counters.roundTripsMs.shift();
  };

  /** Send one message, counting what it weighed. Nothing goes out on a socket
   * that is not open; those are counted too, since a page quietly dropping the
   * clicks it is given is exactly the kind of trouble this panel is for. */
  const sendToServer = (message: Message) => {
    if (failure.hasFailed) return;
    if (ws === null || ws.readyState !== WebSocket.OPEN) {
      counters.droppedSends += 1;
      return;
    }
    try {
      const encoded = msgpack.encode(message);
      const rejection = sendWithWebsocketBudget(ws, encoded);
      if (rejection !== null) {
        counters.droppedSends += 1;
        const reject = rejectCurrentSendQueue;
        if (reject === null) {
          failure.fail(
            "Connection worker lost its send-queue owner",
            new Error(rejection),
          );
        } else reject(rejection);
        return;
      }
      counters.bytesSent += encoded.byteLength;
      counters.messagesSent += 1;
    } catch (error) {
      failure.fail("Connection worker could not send a message", error);
    }
  };

  /** Pull the answers to our own pings out of a batch, timing each one. They
   * are the worker's business, not the app's, so they go no further. */
  const takePongs = (messages: Message[], receivedMs: number): Message[] => {
    if (!messages.some((message) => message.type === "ServerPongMessage"))
      return messages;
    const rest: Message[] = [];
    for (const message of messages) {
      if (message.type === "ServerPongMessage")
        recordRoundTrip(receivedMs - message.sent_ms);
      else rest.push(message);
    }
    return rest;
  };

  const reportStats = () => {
    if (failure.hasFailed) return;
    // Ping first: the reply lands between now and the next tick, so what is
    // posted here is the round trip the last tick asked for.
    if (ws?.readyState === WebSocket.OPEN) {
      sendToServer({ type: "ClientPingMessage", sent_ms: performance.now() });
    }
    if (failure.hasFailed) return;
    counters.atMs = performance.now();
    postOutgoing({ type: "stats", counters });
  };

  const setWatching = (watching: boolean) => {
    if (failure.hasFailed || watching === (statsTimer !== null)) return;
    if (watching) {
      reportStats();
      if (!failure.hasFailed) {
        statsTimer = setInterval(reportStats, STATS_INTERVAL_MS);
      }
      return;
    }
    if (statsTimer !== null) clearInterval(statsTimer);
    statsTimer = null;
    // Round trips are only measured while someone is looking, so the ones from
    // the last look say nothing about the link now. The totals stay.
    counters.roundTripsMs.length = 0;
  };

  const tryConnect = () => {
    const targetServer = server;
    if (failure.hasFailed || targetServer === null) return;
    connectionBatchTasks?.cancelAll();
    connectionBatchTasks = null;
    connectionReceiptGate?.reset();
    connectionReceiptGate = null;
    rejectCurrentSendQueue = null;
    connectionFrameBudget?.reset();
    connectionFrameBudget = null;
    const previousSocket = ws;
    ws = null;
    try {
      previousSocket?.close();
    } catch (error) {
      failure.fail(
        "Connection worker could not close its previous socket",
        error,
      );
      return;
    }

    // One subprotocol string carries the client identification, the version,
    // and the schema this bundle was built against. The server turns away
    // anything it does not match, which is what keeps a page from connecting
    // to a server whose messages it cannot read.
    const protocol = `leika-v${LEIKA_VERSION}+p${LEIKA_PROTOCOL}`;
    let socket: WebSocket;
    try {
      socket = new WebSocket(targetServer, [protocol]);
    } catch (error) {
      postOutgoing({
        type: "closed",
        closeKind: "socket",
        closeReason:
          error instanceof Error ? error.message : "Invalid WebSocket URL",
      });
      return;
    }
    const orderLock = new AwaitLock();
    const batchTasks = new ConnectionBatchTasks();
    const frameBudget = new PendingRawFrameBudget();
    const connectionId = nextConnectionId;
    nextConnectionId += 1;
    let nextBatchId = 0;
    connectionBatchTasks = batchTasks;
    connectionFrameBudget = frameBudget;
    ws = socket;
    socket.binaryType = "arraybuffer";

    // Timeout is necessary when we're connecting to an SSH/tunneled port.
    const retryTimeout = setTimeout(() => {
      if (failure.hasFailed || ws !== socket) return;
      try {
        socket.close();
      } catch (error) {
        failure.fail(
          "Connection worker could not close a timed-out socket",
          error,
        );
      }
    }, 5000);

    function closeCurrentConnection(reason: string) {
      if (failure.hasFailed || ws !== socket) return;
      clearTimeout(retryTimeout);
      ws = null;
      if (rejectCurrentSendQueue === closeCurrentConnection) {
        rejectCurrentSendQueue = null;
      }
      counters.connectedSinceMs = null;
      batchTasks.cancelAll();
      receiptGate.reset();
      frameBudget.reset();
      if (connectionBatchTasks === batchTasks) connectionBatchTasks = null;
      if (connectionReceiptGate === receiptGate) connectionReceiptGate = null;
      if (connectionFrameBudget === frameBudget) connectionFrameBudget = null;
      try {
        closeRejectedConnection(socket, reason);
      } catch (error) {
        failure.fail(
          `Connection worker could not close a rejected connection after: ${reason}`,
          error,
        );
        return;
      }
      postOutgoing({
        type: "closed",
        closeKind: "worker_rejection",
        closeReason: reason,
      });
    }
    rejectCurrentSendQueue = closeCurrentConnection;
    const receiptGate = new WorkerBatchReceiptGate(connectionId, () => {
      closeCurrentConnection(
        "Main thread did not admit a connection batch in time",
      );
    });
    connectionReceiptGate = receiptGate;

    socket.onopen = () => {
      clearTimeout(retryTimeout);
      if (failure.hasFailed || ws !== socket) return;

      connectionsOpened += 1;
      counters.connectedSinceMs = performance.now();
      // Every connection after the first is one the page lost and got back.
      counters.reconnects = connectionsOpened - 1;

      postOutgoing({ type: "connected" });
    };

    socket.onclose = (event) => {
      clearTimeout(retryTimeout);
      if (failure.hasFailed || ws !== socket) return;
      ws = null;
      if (rejectCurrentSendQueue === closeCurrentConnection) {
        rejectCurrentSendQueue = null;
      }
      batchTasks.cancelAll();
      receiptGate.reset();
      frameBudget.reset();
      if (connectionBatchTasks === batchTasks) connectionBatchTasks = null;
      if (connectionReceiptGate === receiptGate) connectionReceiptGate = null;
      if (connectionFrameBudget === frameBudget) connectionFrameBudget = null;
      const closeKind = classifySocketClose(event.code);

      counters.connectedSinceMs = null;

      postOutgoing({
        type: "closed",
        closeKind,
        closeReason: event.reason || "Connection closed",
      });

      if (closeKind === "version_mismatch") {
        console.warn(
          `Connection rejected: ${event.reason}. Client version: ${LEIKA_VERSION},` +
            ` protocol: ${LEIKA_PROTOCOL}`,
        );
      }
    };

    // State for tracking message timing.
    const pacing = newPacingState();
    socket.onmessage = async (event) => {
      if (failure.hasFailed || ws !== socket) return;
      if (!(event.data instanceof ArrayBuffer)) {
        failure.fail("Connection worker received a non-binary message");
        return;
      }

      const buffer = event.data;
      // Admit the raw ArrayBuffer synchronously, before an await or zstd
      // allocation. A paced predecessor can make WebSocket events burst; both
      // bytes and frame objects are bounded for the whole socket generation.
      const frameLease = frameBudget.admit(buffer.byteLength);
      if (frameLease === null) {
        closeCurrentConnection(
          "Connection receive queue exceeded its browser safety limit",
        );
        return;
      }
      counters.bytesReceived += frameLease.sizeBytes;

      // Lifecycle and component messages are order-sensitive. A stalled
      // predecessor invalidates this connection; later batches never overtake
      // and are not decoded ahead of it.
      const jsReceivedMs = performance.now();
      let acquiredLock = false;
      const releaseOrderLock = () => {
        if (!acquiredLock) return;
        acquiredLock = false;
        try {
          orderLock.release();
        } catch (error) {
          failure.fail(
            "Connection worker could not release its ordering lock",
            error,
          );
        }
      };
      const releaseFrame = () => {
        frameLease.release();
        releaseOrderLock();
      };

      await runWithDeferredRelease(releaseFrame, async (deferRelease) => {
        try {
          const acquired = await acquireConnectionMessageOrder(
            orderLock,
            batchTasks,
          );
          if (!acquired) return;
          acquiredLock = true;
        } catch (error) {
          if (failure.hasFailed || ws !== socket || batchTasks.isClosed) return;
          console.error("Connection message ordering failed:", error);
          closeCurrentConnection("Message ordering timed out");
          return;
        }

        try {
          if (failure.hasFailed || ws !== socket || batchTasks.isClosed) return;
          if (zstdReady === null || zstdDecoder === null) {
            throw new Error("decoder is unavailable");
          }
          await zstdReady;
          if (failure.hasFailed || ws !== socket || batchTasks.isClosed) return;
          const data = decodeHybridMessage(buffer, zstdDecoder);

          counters.messagesReceived += data.messages.length;
          const messages = takePongs(data.messages, jsReceivedMs);
          // All typed array views point into the original WebSocket
          // ArrayBuffer. Transfer just that buffer instead of walking the
          // entire message tree.
          const handOffBatch = () => {
            if (failure.hasFailed || ws !== socket) return false;
            const batchId = nextBatchId;
            nextBatchId += 1;
            return receiptGate.post(batchId, releaseFrame, () =>
              postOutgoing(
                {
                  type: "message_batch",
                  messages,
                  connectionId,
                  batchId,
                  frameBytes: frameLease.sizeBytes,
                  metadataBytes: data.metadataBytes,
                },
                [data.buffer],
              ),
            );
          };

          const delayMs = paceBatch(
            pacing,
            jsReceivedMs,
            performance.now(),
            data.timestampSec * 1000,
          );
          if (delayMs > 0) {
            let unregister: () => void = () => undefined;
            const cancel = () => {
              unregister();
              clearTimeout(timer);
              releaseFrame();
            };
            const timer = setTimeout(() => {
              unregister();
              // A successful handoff transfers release ownership to the
              // receipt gate. Failed/stale sends still release locally.
              if (!handOffBatch()) releaseFrame();
            }, delayMs);
            unregister = batchTasks.add(cancel);
            // The timer/cancellation callback now owns both the raw frame and
            // ordering lock. Mark this only after task registration, since a
            // closed generation can synchronously run `cancel` from `add`.
            deferRelease();
          } else {
            if (handOffBatch()) deferRelease();
          }
        } catch (error) {
          if (!failure.hasFailed && ws === socket && !batchTasks.isClosed) {
            failure.fail("Connection worker could not decode a message", error);
          }
        }
      });
    };
  };

  workerScope.onmessage = (event) => {
    if (failure.hasFailed) return;
    const data = event.data;

    if (data.type === "send") {
      // The socket can be null (not yet connected) or closing/closed by the
      // time a send arrives; only send when it's actually open, otherwise drop
      // it rather than throwing in the worker.
      sendToServer(data.message);
    } else if (data.type === "watch_stats") {
      setWatching(data.watching);
    } else if (data.type === "set_server") {
      server = data.server;
      tryConnect();
    } else if (data.type === "retry") {
      // Leave live sockets alone. The timeout in `tryConnect` owns slow
      // attempts, so retry ticks cannot starve a slow link.
      if (server !== null && shouldRetryWebsocket(ws?.readyState ?? null)) {
        tryConnect();
      }
    } else if (data.type === "batch_received") {
      connectionReceiptGate?.acknowledge(data.connectionId, data.batchId);
    }
  };
}
