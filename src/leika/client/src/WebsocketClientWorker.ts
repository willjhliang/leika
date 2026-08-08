import * as msgpack from "@msgpack/msgpack";
import AwaitLock from "await-lock";
import { ZSTDDecoder } from "zstddec";

import {
  computeBinaryOffsets,
  replaceBinaryPlaceholders,
} from "./BinaryMessageDecode";
import { ConnectionCounters, emptyCounters } from "./connectionStats";
import { newPacingState, paceBatch } from "./pacing";
import { shouldRetryWebsocket } from "./utils/shouldRetryWebsocket";
import { LEIKA_PROTOCOL, LEIKA_VERSION } from "./VersionInfo";
import { Message } from "./WebsocketMessages";
import { FatalWorkerEvent, WorkerFailureController } from "./workerFailure";

export type WsWorkerIncoming =
  | { type: "send"; message: Message }
  | { type: "set_server"; server: string }
  | { type: "retry" }
  | { type: "watch_stats"; watching: boolean };

export type WsWorkerOutgoing =
  | { type: "connected" }
  | {
      type: "closed";
      versionMismatch: boolean;
      closeReason: string;
    }
  | { type: "message_batch"; messages: Message[] }
  | { type: "stats"; counters: ConnectionCounters }
  | FatalWorkerEvent;

type WorkerScope = {
  postMessage(data: WsWorkerOutgoing, transferable?: Transferable[]): void;
  onmessage: ((event: MessageEvent<WsWorkerIncoming>) => void) | null;
};

const workerScope = self as unknown as WorkerScope;

type SerializedStruct = {
  messages: Message[];
  timestampSec: number;
  binaryBufferLengths?: number[];
};

/**
 * Decode a hybrid wire format message: zstd-compressed msgpack metadata,
 * followed by raw (uncompressed) aligned binary buffers.
 *
 * Wire format:
 *   [8 bytes] decompressed size of msgpack (little-endian uint64)
 *   [8 bytes] compressed size of msgpack (little-endian uint64)
 *   [N bytes] zstd-compressed msgpack payload
 *   [P bytes] padding to 8-byte alignment
 *   [M bytes] concatenated binary buffers (each 8-byte aligned)
 *
 * Binary arrays in the msgpack are replaced with tagged placeholder objects.
 * These are reconstructed as typed array views directly into the WebSocket's
 * ArrayBuffer -- zero-copy for the binary array data.
 */
function decodeHybridMessage(
  buffer: ArrayBuffer,
  zstdDecoder: { decode: (data: Uint8Array, size: number) => Uint8Array },
): SerializedStruct & { buffer: ArrayBuffer } {
  const headerView = new DataView(buffer);
  const decompressedSize = Number(headerView.getBigUint64(0, true));
  const compressedSize = Number(headerView.getBigUint64(8, true));

  // Decompress msgpack portion only. Binary data is raw/uncompressed.
  const compressedData = new Uint8Array(buffer, 16, compressedSize);
  const decompressed = zstdDecoder.decode(compressedData, decompressedSize);
  const data = msgpack.decode(decompressed) as SerializedStruct;

  // Attach the raw buffer for postMessage transfer semantics.
  // Mutate instead of spreading ({ ...data, buffer }) to avoid an extra
  // object allocation on every incoming message.
  const result = data as SerializedStruct & { buffer: ArrayBuffer };
  result.buffer = buffer;

  // If no binary buffers, return as-is. Message had no arrays.
  const bufferLengths = data.binaryBufferLengths;
  if (!bufferLengths || bufferLengths.length === 0) {
    return result;
  }

  // Compute binary section offsets and replace placeholders with typed array views.
  const binaryOffsets = computeBinaryOffsets(
    bufferLengths,
    16 + compressedSize,
  );
  for (const message of data.messages) {
    replaceBinaryPlaceholders(message, buffer, binaryOffsets, bufferLengths);
  }

  return result;
}

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
  const cancelPendingOrderedSends = new Set<() => void>();

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
      for (const cancel of [...cancelPendingOrderedSends]) cancel();

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
      ws.send(encoded);
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
        versionMismatch: false,
        closeReason:
          error instanceof Error ? error.message : "Invalid WebSocket URL",
      });
      return;
    }
    const orderLock = new AwaitLock();
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
      // Code 1002 is the server's protocol/version rejection.
      const versionMismatch = event.code === 1002;

      counters.connectedSinceMs = null;

      postOutgoing({
        type: "closed",
        versionMismatch,
        closeReason: event.reason || "Connection closed",
      });

      if (versionMismatch) {
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

      // Weighed here, before the buffer is handed to the main thread: posting
      // it transfers ownership away and leaves `byteLength` at zero.
      const buffer = event.data;
      counters.bytesReceived += buffer.byteLength;
      const dataPromise = (async () => {
        if (zstdReady === null || zstdDecoder === null) {
          throw new Error("decoder is unavailable");
        }
        await zstdReady;
        return decodeHybridMessage(buffer, zstdDecoder);
      })().then(
        (data) => ({ ok: true as const, data }),
        (error: unknown) => {
          // Attach this rejection handler immediately. Otherwise a decode that
          // fails while waiting for the ordering lock becomes an unhandled
          // rejection until that wait completes.
          failure.fail("Connection worker could not decode a message", error);
          return { ok: false as const };
        },
      );

      // Preserve arrival order unless an earlier batch stalls for ten seconds.
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

      try {
        await orderLock.acquireAsync({ timeout: 10000 });
        acquiredLock = true;
      } catch {
        if (failure.hasFailed) return;
        // Timed out waiting for the in-order slot. Proceed without the lock
        // (out of order) rather than calling release() on a lock we never
        // acquired -- that would release another waiter's hold and corrupt the
        // ordering state.
        counters.outOfOrderBatches += 1;
        console.warn("Order lock timed out; processing message out of order.");
      }

      let releaseDeferred = false;
      try {
        const decoded = await dataPromise;
        if (!decoded.ok || failure.hasFailed || ws !== socket) return;
        const data = decoded.data;

        counters.messagesReceived += data.messages.length;
        const messages = takePongs(data.messages, jsReceivedMs);
        // All typed array views point into the original WebSocket ArrayBuffer.
        // Transfer just that buffer instead of walking the entire message tree.
        const sendBatch = () => {
          try {
            if (!failure.hasFailed && ws === socket) {
              postOutgoing({ type: "message_batch", messages }, [data.buffer]);
            }
          } finally {
            releaseOrderLock();
          }
        };

        const delayMs = paceBatch(
          pacing,
          jsReceivedMs,
          performance.now(),
          data.timestampSec * 1000,
        );
        if (delayMs > 0) {
          const cancel = () => {
            cancelPendingOrderedSends.delete(cancel);
            clearTimeout(timer);
            releaseOrderLock();
          };
          const timer = setTimeout(() => {
            cancelPendingOrderedSends.delete(cancel);
            sendBatch();
          }, delayMs);
          cancelPendingOrderedSends.add(cancel);
          releaseDeferred = true;
        } else {
          sendBatch();
        }
      } catch (error) {
        failure.fail("Connection worker could not process a message", error);
      } finally {
        if (!releaseDeferred) releaseOrderLock();
      }
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
    }
  };
}
