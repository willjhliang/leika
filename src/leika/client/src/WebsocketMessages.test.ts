import { describe, expect, it } from "vitest";

import { validateMessage } from "./WebsocketMessages";

describe("generated tab lifecycle validation", () => {
  it("accepts the exact flat declaration and update shapes", () => {
    expect(() =>
      validateMessage({
        type: "GuiTabMessage",
        uuid: "tab",
        group_uuid: "group",
        label: "Tab",
        icon_html: null,
      }),
    ).not.toThrow();
    expect(() =>
      validateMessage({
        type: "GuiTabUpdateMessage",
        uuid: "tab",
        group_uuid: "group",
        label: "Renamed",
        icon_html: "<svg />",
      }),
    ).not.toThrow();
  });

  it("rejects nested, incomplete, and extra tab lifecycle shapes", () => {
    for (const message of [
      {
        type: "GuiTabMessage",
        uuid: "tab",
        group_uuid: "group",
        descriptor: { label: "Tab", icon_html: null },
      },
      {
        type: "GuiTabMessage",
        uuid: "tab",
        group_uuid: "group",
        label: "Tab",
      },
      {
        type: "GuiTabUpdateMessage",
        uuid: "tab",
        group_uuid: "group",
        label: "Tab",
        icon_html: null,
        unexpected: true,
      },
    ]) {
      expect(() => validateMessage(message)).toThrow();
    }
  });

  it("requires separately typed tab tombstones on GUI and modal removals", () => {
    for (const type of ["GuiRemoveMessage", "GuiCloseModalMessage"]) {
      expect(() =>
        validateMessage({
          type,
          uuid: "owner",
          removed_uuids: ["child"],
          removed_tab_uuids: ["tab"],
        }),
      ).not.toThrow();
      expect(() =>
        validateMessage({
          type,
          uuid: "owner",
          removed_uuids: ["child"],
        }),
      ).toThrow();
      expect(() =>
        validateMessage({
          type,
          uuid: "owner",
          removed_uuids: ["child"],
          removed_tab_uuids: [1],
        }),
      ).toThrow();
    }
  });
});
