import { describe, expect, it } from "vitest";

import { websocketServer } from "./SearchParamsUtils";

describe("websocketServer", () => {
  it("maps the page scheme and keeps its host and path", () => {
    expect(websocketServer("http://localhost:8080/")).toBe(
      "ws://localhost:8080",
    );
    expect(
      websocketServer("https://example.com/apps/viewer/?session=1#controls"),
    ).toBe("wss://example.com/apps/viewer");
  });

  it("prefers an explicit websocket override", () => {
    const server = "ws://other.example:9000/live?token=a+b&scope=read";
    expect(
      websocketServer(
        `https://example.com/viewer/?websocket=${encodeURIComponent(server)}`,
      ),
    ).toBe(server);
  });
});
