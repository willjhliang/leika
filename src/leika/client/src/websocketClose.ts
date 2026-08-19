/** A socket surface small enough to test without constructing a real link. */
export interface RejectedConnectionSocket {
  close(code: number, reason: string): void;
}

/** Why the worker reports that a connection ended. */
export type WebsocketCloseKind =
  "socket" | "version_mismatch" | "worker_rejection";

export type ConnectionLifecycleEvent =
  | { type: "connected" }
  | {
      type: "closed";
      closeKind: WebsocketCloseKind;
      closeReason: string;
    };

export interface ConnectionLifecycleState {
  retry: boolean;
  connectionError: string | null;
}

/** Private-use code for a connection the browser rejects locally.
 *
 * Browser JavaScript may initiate a close with code 1000 or 3000--4999 only.
 * The 4000--4999 range is explicitly private use, so it cannot collide with a
 * registered library code. Protocol endpoint codes such as 1011 make
 * WebSocket.close() throw before it closes anything.
 */
export const CLIENT_REJECTED_CONNECTION_CLOSE_CODE = 4000;
/** WebSocket.close() permits at most 123 UTF-8 bytes of reason text. */
export const MAX_WEBSOCKET_CLOSE_REASON_BYTES = 123;

const textEncoder = new TextEncoder();

/** Classify a close raised by the socket itself.
 *
 * Worker-owned safety rejections never reach this classifier: the worker
 * reports those before closing its socket, so they cannot be confused with a
 * server or network close that happens to use the same numeric code.
 */
export function classifySocketClose(code: number): WebsocketCloseKind {
  return code === 1002 ? "version_mismatch" : "socket";
}

/** Project transport events onto retry and user-facing diagnostic state.
 *
 * An ordinary socket loss is expected during reconnect and must not create an
 * alert. It also must not erase a preceding worker-safety diagnostic: only a
 * successful connection proves that condition has recovered and clears it.
 */
export function connectionStateForEvent(
  connectionError: string | null,
  event: ConnectionLifecycleEvent,
): ConnectionLifecycleState {
  if (event.type === "connected") {
    return { retry: true, connectionError: null };
  }
  switch (event.closeKind) {
    case "socket":
      return { retry: true, connectionError };
    case "worker_rejection":
      return {
        retry: true,
        connectionError: `Connection interrupted locally: ${event.closeReason}`,
      };
    case "version_mismatch":
      return {
        retry: false,
        connectionError: `Connection rejected: ${event.closeReason}`,
      };
  }
}

function boundedCloseReason(reason: string): string {
  if (textEncoder.encode(reason).byteLength <= MAX_WEBSOCKET_CLOSE_REASON_BYTES)
    return reason;
  let result = "";
  let byteLength = 0;
  for (const codePoint of reason) {
    const codePointBytes = textEncoder.encode(codePoint).byteLength;
    if (byteLength + codePointBytes > MAX_WEBSOCKET_CLOSE_REASON_BYTES) break;
    result += codePoint;
    byteLength += codePointBytes;
  }
  return result;
}

/** Close a connection that the browser worker rejects locally. */
export function closeRejectedConnection(
  socket: RejectedConnectionSocket,
  reason: string,
): void {
  socket.close(
    CLIENT_REJECTED_CONNECTION_CLOSE_CODE,
    boundedCloseReason(reason),
  );
}
