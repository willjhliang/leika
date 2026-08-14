import { describe, expect, it, vi } from "vitest";

import { dispatchGuiLifecycleMessage } from "./guiLifecycleDispatch";
import type { Message } from "./WebsocketMessages";

function actions() {
  return {
    declareTab: vi.fn(),
    updateTab: vi.fn(),
    removeGui: vi.fn(),
    removeModal: vi.fn(),
  };
}

describe("dispatchGuiLifecycleMessage", () => {
  it("routes flat tab declarations and exact-owner metadata updates", () => {
    const guiActions = actions();
    const declaration = {
      type: "GuiTabMessage",
      uuid: "tab",
      group_uuid: "group",
      label: "Initial",
      icon_html: null,
    } satisfies Message;
    const update = {
      ...declaration,
      type: "GuiTabUpdateMessage",
      label: "Updated",
      icon_html: "<svg />",
    } satisfies Message;

    expect(dispatchGuiLifecycleMessage(declaration, guiActions)).toBe(true);
    expect(dispatchGuiLifecycleMessage(update, guiActions)).toBe(true);
    expect(guiActions.declareTab).toHaveBeenCalledWith(declaration);
    expect(guiActions.updateTab).toHaveBeenCalledWith(update);
  });

  it("passes component and tab tombstones through both removal variants", () => {
    const guiActions = actions();
    const remove = {
      type: "GuiRemoveMessage",
      uuid: "tab",
      removed_uuids: ["child"],
      removed_tab_uuids: ["nested-tab"],
    } satisfies Message;
    const close = {
      type: "GuiCloseModalMessage",
      uuid: "modal",
      removed_uuids: ["modal-child"],
      removed_tab_uuids: ["modal-tab"],
    } satisfies Message;

    expect(dispatchGuiLifecycleMessage(remove, guiActions)).toBe(true);
    expect(dispatchGuiLifecycleMessage(close, guiActions)).toBe(true);
    expect(guiActions.removeGui).toHaveBeenCalledWith(
      "tab",
      ["child"],
      ["nested-tab"],
    );
    expect(guiActions.removeModal).toHaveBeenCalledWith(
      "modal",
      ["modal-child"],
      ["modal-tab"],
    );
  });

  it("leaves unrelated messages for the main message handler", () => {
    const guiActions = actions();
    expect(
      dispatchGuiLifecycleMessage(
        { type: "ServerPongMessage", sent_ms: 1 },
        guiActions,
      ),
    ).toBe(false);
    expect(guiActions.declareTab).not.toHaveBeenCalled();
    expect(guiActions.updateTab).not.toHaveBeenCalled();
    expect(guiActions.removeGui).not.toHaveBeenCalled();
    expect(guiActions.removeModal).not.toHaveBeenCalled();
  });
});
