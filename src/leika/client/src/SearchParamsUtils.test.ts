import { describe, expect, it } from "vitest";

import {
  defaultWebsocketServer,
  isDefaultWebsocketServer,
  searchParamKey,
  urlWithWebsocketServer,
} from "./SearchParamsUtils";

describe("defaultWebsocketServer", () => {
  it("maps the page scheme and keeps its host and path", () => {
    expect(defaultWebsocketServer("http://localhost:8080/")).toBe(
      "ws://localhost:8080",
    );
    expect(
      defaultWebsocketServer(
        "https://example.com/apps/viewer/?session=1#controls",
      ),
    ).toBe("wss://example.com/apps/viewer");
  });
});

describe("isDefaultWebsocketServer", () => {
  const page = "http://example.com:8000/viewer/";

  it("accepts only the exact implied endpoint", () => {
    expect(isDefaultWebsocketServer("ws://example.com:8000/viewer", page)).toBe(
      true,
    );
    expect(isDefaultWebsocketServer("ws://example.com/viewer", page)).toBe(
      false,
    );
    expect(isDefaultWebsocketServer("ws://example.com:8000/other", page)).toBe(
      false,
    );
  });
});

describe("urlWithWebsocketServer", () => {
  it("removes a redundant override without dropping other state", () => {
    const result = urlWithWebsocketServer(
      "https://example.com/viewer/?mode=inspect&websocket=wss://old#pane-2",
      "wss://example.com/viewer",
    );
    expect(result).toBe("/viewer/?mode=inspect#pane-2");
  });

  it("keeps the server readable and safely round-trippable", () => {
    const server = "ws://other.example:9000/live?token=a+b&scope=read";
    const result = urlWithWebsocketServer(
      "https://example.com/viewer/?mode=inspect#pane-2",
      server,
    );
    expect(result).toContain("websocket=ws://other.example:9000/live");
    const parsed = new URL(result, "https://example.com");
    expect(parsed.searchParams.get(searchParamKey)).toBe(server);
    expect(parsed.searchParams.get("mode")).toBe("inspect");
    expect(parsed.hash).toBe("#pane-2");
  });
});
