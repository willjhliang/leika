import { describe, expect, it, vi } from "vitest";

import {
  MAX_CLIENT_TO_SERVER_MESSAGE_BYTES,
  MAX_WEBSOCKET_BUFFERED_SEND_BYTES,
  OUTGOING_BUFFER_LIMIT_REASON,
  OUTGOING_MESSAGE_LIMIT_REASON,
  sendWithWebsocketBudget,
  websocketSendRejection,
} from "./websocketSendBudget";

describe("websocket send admission", () => {
  it("admits the exact single-message and aggregate boundaries", () => {
    expect(websocketSendRejection(0, MAX_CLIENT_TO_SERVER_MESSAGE_BYTES)).toBe(
      null,
    );
    expect(
      websocketSendRejection(
        MAX_WEBSOCKET_BUFFERED_SEND_BYTES - MAX_CLIENT_TO_SERVER_MESSAGE_BYTES,
        MAX_CLIENT_TO_SERVER_MESSAGE_BYTES,
      ),
    ).toBe(null);
  });

  it("rejects one byte over either boundary", () => {
    expect(
      websocketSendRejection(0, MAX_CLIENT_TO_SERVER_MESSAGE_BYTES + 1),
    ).toBe(OUTGOING_MESSAGE_LIMIT_REASON);
    expect(
      websocketSendRejection(
        MAX_WEBSOCKET_BUFFERED_SEND_BYTES -
          MAX_CLIENT_TO_SERVER_MESSAGE_BYTES +
          1,
        MAX_CLIENT_TO_SERVER_MESSAGE_BYTES,
      ),
    ).toBe(OUTGOING_BUFFER_LIMIT_REASON);
  });

  it("has no cross-connection state: a fresh socket amount is readmitted", () => {
    const stalledSend = vi.fn();
    const freshSend = vi.fn();
    expect(
      sendWithWebsocketBudget(
        {
          bufferedAmount: MAX_WEBSOCKET_BUFFERED_SEND_BYTES,
          send: stalledSend,
        },
        new Uint8Array(1),
      ),
    ).toBe(OUTGOING_BUFFER_LIMIT_REASON);
    expect(stalledSend).not.toHaveBeenCalled();
    expect(
      sendWithWebsocketBudget(
        { bufferedAmount: 0, send: freshSend },
        new Uint8Array(1),
      ),
    ).toBe(null);
    expect(freshSend).toHaveBeenCalledOnce();
  });

  it("fails closed on invalid browser counters", () => {
    for (const buffered of [-1, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(websocketSendRejection(buffered, 1)).toBe(
        OUTGOING_BUFFER_LIMIT_REASON,
      );
    }
  });
});
