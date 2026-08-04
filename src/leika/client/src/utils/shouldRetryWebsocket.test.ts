import { describe, expect, it } from "vitest";

import { shouldRetryWebsocket } from "./shouldRetryWebsocket";

describe("shouldRetryWebsocket", () => {
  it("starts a retry only when there is no live connection", () => {
    expect(shouldRetryWebsocket(null)).toBe(true);
    expect(shouldRetryWebsocket(WebSocket.CLOSING)).toBe(true);
    expect(shouldRetryWebsocket(WebSocket.CLOSED)).toBe(true);
    expect(shouldRetryWebsocket(WebSocket.CONNECTING)).toBe(false);
    expect(shouldRetryWebsocket(WebSocket.OPEN)).toBe(false);
  });
});
