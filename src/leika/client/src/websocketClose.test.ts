import { describe, expect, it, vi } from "vitest";

import {
  CLIENT_REJECTED_CONNECTION_CLOSE_CODE,
  MAX_WEBSOCKET_CLOSE_REASON_BYTES,
  classifySocketClose,
  closeRejectedConnection,
  connectionStateForEvent,
} from "./websocketClose";

describe("connection close lifecycle", () => {
  it("classifies only the protocol rejection as a version mismatch", () => {
    expect(classifySocketClose(1002)).toBe("version_mismatch");
    expect(classifySocketClose(1000)).toBe("socket");
    expect(classifySocketClose(1006)).toBe("socket");
  });

  it("keeps routine socket closes retryable and silent", () => {
    expect(
      connectionStateForEvent(null, {
        type: "closed",
        closeKind: "socket",
        closeReason: "Connection closed",
      }),
    ).toEqual({ retry: true, connectionError: null });
  });

  it("surfaces a worker rejection through retries until reconnecting", () => {
    const rejected = connectionStateForEvent(null, {
      type: "closed",
      closeKind: "worker_rejection",
      closeReason: "Connection receive queue exceeded its browser safety limit",
    });
    expect(rejected).toEqual({
      retry: true,
      connectionError:
        "Connection interrupted locally: Connection receive queue exceeded its browser safety limit",
    });

    const retryClosed = connectionStateForEvent(rejected.connectionError, {
      type: "closed",
      closeKind: "socket",
      closeReason: "Connection closed",
    });
    expect(retryClosed).toEqual(rejected);
    expect(
      connectionStateForEvent(retryClosed.connectionError, {
        type: "connected",
      }),
    ).toEqual({ retry: true, connectionError: null });
  });

  it("keeps a version mismatch terminal and visible", () => {
    expect(
      connectionStateForEvent(null, {
        type: "closed",
        closeKind: "version_mismatch",
        closeReason: "Protocol 8 required",
      }),
    ).toEqual({
      retry: false,
      connectionError: "Connection rejected: Protocol 8 required",
    });
  });
});

describe("closeRejectedConnection", () => {
  it("uses a browser-sendable private code and preserves the reason", () => {
    const close = vi.fn();
    const reason = "Connection receive queue exceeded its browser safety limit";

    closeRejectedConnection({ close }, reason);

    expect(CLIENT_REJECTED_CONNECTION_CLOSE_CODE).toBeGreaterThanOrEqual(4000);
    expect(CLIENT_REJECTED_CONNECTION_CLOSE_CODE).toBeLessThanOrEqual(4999);
    expect(close).toHaveBeenCalledExactlyOnceWith(
      CLIENT_REJECTED_CONNECTION_CLOSE_CODE,
      reason,
    );
  });

  it("bounds multibyte reasons without splitting a code point", () => {
    const close = vi.fn();
    closeRejectedConnection({ close }, "界".repeat(42));

    const reason = close.mock.calls[0]![1];
    expect(reason).toBe("界".repeat(41));
    expect(new TextEncoder().encode(reason)).toHaveLength(
      MAX_WEBSOCKET_CLOSE_REASON_BYTES,
    );
  });

  it("propagates a browser close failure to its lifecycle owner", () => {
    const failure = new Error("close failed");
    expect(() =>
      closeRejectedConnection(
        {
          close: () => {
            throw failure;
          },
        },
        "original rejection",
      ),
    ).toThrow(failure);
  });
});
