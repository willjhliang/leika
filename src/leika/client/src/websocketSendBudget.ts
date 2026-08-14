const MEBIBYTE = 1024 * 1024;

/** Python's websocket `max_size` for every browser-to-server message. */
export const MAX_CLIENT_TO_SERVER_MESSAGE_BYTES = 4 * MEBIBYTE;
/** Bound bytes that the browser may retain after `WebSocket.send()` returns.
 * Four maximum-sized protocol messages leave useful burst headroom while a
 * stalled connection still has a small, deterministic upper bound. */
export const MAX_WEBSOCKET_BUFFERED_SEND_BYTES = 16 * MEBIBYTE;

export const OUTGOING_MESSAGE_LIMIT_REASON =
  "Outgoing message exceeds the server's 4 MiB protocol limit";
export const OUTGOING_BUFFER_LIMIT_REASON =
  "Connection send queue exceeded its browser safety limit";

/** Pure admission against the socket's current queued bytes. */
export function websocketSendRejection(
  bufferedAmount: number,
  encodedByteLength: number,
): string | null {
  if (
    !Number.isSafeInteger(encodedByteLength) ||
    encodedByteLength < 0 ||
    encodedByteLength > MAX_CLIENT_TO_SERVER_MESSAGE_BYTES
  ) {
    return OUTGOING_MESSAGE_LIMIT_REASON;
  }
  if (
    !Number.isSafeInteger(bufferedAmount) ||
    bufferedAmount < 0 ||
    bufferedAmount > MAX_WEBSOCKET_BUFFERED_SEND_BYTES ||
    encodedByteLength > MAX_WEBSOCKET_BUFFERED_SEND_BYTES - bufferedAmount
  ) {
    return OUTGOING_BUFFER_LIMIT_REASON;
  }
  return null;
}

export interface BufferedWebsocketSender {
  readonly bufferedAmount: number;
  send(data: Uint8Array<ArrayBufferLike>): void;
}

/** Admit and send as one synchronous operation against the exact socket. */
export function sendWithWebsocketBudget(
  socket: BufferedWebsocketSender,
  encoded: Uint8Array<ArrayBufferLike>,
): string | null {
  const rejection = websocketSendRejection(
    socket.bufferedAmount,
    encoded.byteLength,
  );
  if (rejection !== null) return rejection;
  socket.send(encoded);
  return null;
}
