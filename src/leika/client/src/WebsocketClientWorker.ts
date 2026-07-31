import * as msgpack from "@msgpack/msgpack";
import { Message } from "./WebsocketMessages";
import AwaitLock from "await-lock";
import { LEIKA_PROTOCOL, LEIKA_VERSION } from "./VersionInfo";
import { ZSTDDecoder } from "zstddec";

// Initialize zstd decoder at module load.
const zstdDecoder = new ZSTDDecoder();
const zstdReady = zstdDecoder.init();

export type WsWorkerIncoming =
  | { type: "send"; message: Message }
  | { type: "set_server"; server: string }
  | { type: "retry" }
  | { type: "watch_stats"; watching: boolean }
  | { type: "close" };

export type WsWorkerOutgoing =
  | { type: "connected" }
  | {
      type: "closed";
      versionMismatch?: boolean;
      closeReason?: string;
    }
  | { type: "message_batch"; messages: Message[] }
  | { type: "stats"; counters: ConnectionCounters };

import {
  replaceBinaryPlaceholders,
  computeBinaryOffsets,
} from "./BinaryMessageDecode";
import { newPacingState, paceBatch } from "./pacing";
import { ConnectionCounters, emptyCounters } from "./connectionStats";

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
  const orderLock = new AwaitLock();

  const postOutgoing = (
    data: WsWorkerOutgoing,
    transferable?: Transferable[],
  ) => {
    // @ts-ignore
    self.postMessage(data, transferable);
  };

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

  const recordRoundTrip = (ms: number) => {
    counters.roundTripsMs.push(ms);
    if (counters.roundTripsMs.length > ROUND_TRIP_WINDOW)
      counters.roundTripsMs.shift();
  };

  /** Send one message, counting what it weighed. Nothing goes out on a socket
   * that is not open; those are counted too, since a page quietly dropping the
   * clicks it is given is exactly the kind of trouble this panel is for. */
  const sendToServer = (message: Message) => {
    if (ws === null || ws.readyState !== WebSocket.OPEN) {
      counters.droppedSends += 1;
      return;
    }
    const encoded = msgpack.encode(message);
    ws.send(encoded);
    counters.bytesSent += encoded.byteLength;
    counters.messagesSent += 1;
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
    // Ping first: the reply lands between now and the next tick, so what is
    // posted here is the round trip the last tick asked for.
    sendToServer({ type: "ClientPingMessage", sent_ms: performance.now() });
    counters.atMs = performance.now();
    postOutgoing({ type: "stats", counters });
  };

  const setWatching = (watching: boolean) => {
    if (watching === (statsTimer !== null)) return;
    if (watching) {
      reportStats();
      statsTimer = setInterval(reportStats, STATS_INTERVAL_MS);
      return;
    }
    clearInterval(statsTimer!);
    statsTimer = null;
    // Round trips are only measured while someone is looking, so the ones from
    // the last look say nothing about the link now. The totals stay.
    counters.roundTripsMs.length = 0;
  };

  const tryConnect = () => {
    if (ws !== null) ws.close();

    // One subprotocol string carries the client identification, the version,
    // and the schema this bundle was built against. The server turns away
    // anything it does not match, which is what keeps a page from connecting
    // to a server whose messages it cannot read.
    const protocol = `leika-v${LEIKA_VERSION}+p${LEIKA_PROTOCOL}`;
    console.log(`Connecting to: ${server!} with protocol: ${protocol}`);
    ws = new WebSocket(server!, [protocol]);
    ws.binaryType = "arraybuffer";

    // Timeout is necessary when we're connecting to an SSH/tunneled port.
    const retryTimeout = setTimeout(() => {
      ws?.close();
    }, 5000);

    ws.onopen = () => {
      clearTimeout(retryTimeout);
      console.log(`Connected! ${server}`);

      connectionsOpened += 1;
      counters.connectedSinceMs = performance.now();
      // Every connection after the first is one the page lost and got back.
      counters.reconnects = connectionsOpened - 1;

      // Just indicate that we're connected.
      postOutgoing({
        type: "connected",
      });
    };

    ws.onclose = (event) => {
      // Check for explicit close (code 1002 = protocol error, which we use for version mismatch).
      const versionMismatch = event.code === 1002;

      counters.connectedSinceMs = null;

      // Send close notification.
      postOutgoing({
        type: "closed",
        versionMismatch: versionMismatch,
        closeReason: event.reason || "Connection closed",
      });

      console.log(
        `Disconnected! ${server} code=${event.code}, reason: ${event.reason}`,
      );

      if (versionMismatch) {
        console.warn(
          `Connection rejected: ${event.reason}. Client version: ${LEIKA_VERSION},` +
            ` protocol: ${LEIKA_PROTOCOL}`,
        );
      }

      clearTimeout(retryTimeout);
    };

    // State for tracking message timing.
    const pacing = newPacingState();
    ws.onmessage = async (event) => {
      // Weighed here, before the buffer is handed to the main thread: posting
      // it transfers ownership away and leaves `byteLength` at zero.
      counters.bytesReceived += (event.data as ArrayBuffer).byteLength;
      const dataPromise = (async () => {
        // binaryType="arraybuffer" ensures event.data is an ArrayBuffer directly
        // (skips the default Blob->ArrayBuffer async conversion).
        const buffer = event.data as ArrayBuffer;
        await zstdReady;
        return decodeHybridMessage(buffer, zstdDecoder);
      })();

      // Try our best to handle messages in order. If this takes more than 10 seconds, we give up. :)
      const jsReceivedMs = performance.now();
      let acquiredLock = false;
      try {
        await orderLock.acquireAsync({ timeout: 10000 });
        acquiredLock = true;
      } catch {
        // Timed out waiting for the in-order slot. Proceed without the lock
        // (out of order) rather than calling release() on a lock we never
        // acquired -- that would release another waiter's hold and corrupt the
        // ordering state.
        counters.outOfOrderBatches += 1;
        console.log("Order lock timed out; processing message out of order.");
      }
      // Once the lock is acquired the release happens in `sendFn` (which may
      // be deferred via setTimeout). If anything between here and scheduling
      // `sendFn` throws -- e.g. decode fails -- we must still release, or the
      // lock stays held and every subsequent message times out.
      try {
        const data = await dataPromise;

        // Function to send the message and release the order lock.
        counters.messagesReceived += data.messages.length;
        const messages = takePongs(data.messages, jsReceivedMs);
        // All typed array views point into the original WebSocket ArrayBuffer.
        // Transfer just that buffer instead of walking the entire message tree.
        const sendFn = () => {
          try {
            postOutgoing({ type: "message_batch", messages: messages }, [
              data.buffer,
            ]);
          } catch (e) {
            // `sendFn` can run later from setTimeout, outside the catch below.
            // Log and still release the lock so one bad post cannot wedge all
            // later message ordering.
            console.error("Failed to post incoming message batch:", e);
          } finally {
            // Only release if we actually acquired the lock above.
            if (acquiredLock) {
              orderLock.release();
              acquiredLock = false;
            }
          }
        };

        const delayMs = paceBatch(
          pacing,
          jsReceivedMs,
          performance.now(),
          data.timestampSec * 1000,
        );
        if (delayMs > 0) setTimeout(sendFn, delayMs);
        else sendFn();
      } catch (e) {
        console.error("Failed to process incoming message:", e);
        if (acquiredLock) {
          orderLock.release();
          acquiredLock = false;
        }
      }
    };
  };

  self.onmessage = (e) => {
    const data: WsWorkerIncoming = e.data;

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
      // A retry closes the current socket before opening a fresh one -- so
      // while an attempt is still CONNECTING, leave it alone. The 5-second
      // timeout in `tryConnect` owns slow attempts; killing them here every
      // second would starve a link (e.g. an SSH tunnel) that takes longer
      // than the retry interval to come up.
      if (server !== null && ws?.readyState !== WebSocket.CONNECTING) {
        tryConnect();
      }
    } else if (data.type === "close") {
      server = null;
      ws !== null && ws.close();
      self.close();
    } else {
      console.log(
        `WebSocket worker: got ${data}, not sure what to do with it!`,
      );
    }
  };
}
