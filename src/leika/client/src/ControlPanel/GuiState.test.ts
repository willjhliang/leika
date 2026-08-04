import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiModalMessage } from "../WebsocketMessages";
import { useGuiState } from "./GuiState";

function createGuiStateHarness(): ReturnType<typeof useGuiState> {
  let gui: ReturnType<typeof useGuiState> | undefined;
  function Harness(): React.ReactNode {
    gui = useGuiState("ws://example.test");
    return null;
  }
  renderToStaticMarkup(React.createElement(Harness));
  if (gui === undefined) throw new Error("GUI state harness did not render");
  return gui;
}

function modal(uuid: string, order: number): GuiModalMessage {
  return { type: "GuiModalMessage", uuid, order, title: uuid };
}

describe("useGuiState", () => {
  it("keeps modals in protocol order", () => {
    const gui = createGuiStateHarness();
    gui.actions.addModal(modal("last", 20));
    gui.actions.addModal(modal("first", 5));
    gui.actions.addModal(modal("middle", 10));

    expect(gui.store.get().modals.map(({ uuid }) => uuid)).toEqual([
      "first",
      "middle",
      "last",
    ]);
  });

  it("treats removal of an unknown component as idempotent", () => {
    const gui = createGuiStateHarness();
    expect(() => gui.actions.removeGui("missing")).not.toThrow();
    expect(gui.store.get().guiUuidSetFromContainerUuid).toEqual({ root: {} });
  });
});
