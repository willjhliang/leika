import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  createGuiState,
  useGuiState,
  type GuiSession,
} from "../ControlPanel/GuiState";
import {
  createViewportState,
  useViewportState,
  type ViewportSession,
} from "./ViewportState";

describe("viewer state ownership", () => {
  it("keeps GUI and viewport handles stable across owner renders", () => {
    const guiSessions: GuiSession[] = [];
    const viewportSessions: ViewportSession[] = [];
    function Harness() {
      const [rendered, setRendered] = React.useState(false);
      guiSessions.push(useGuiState("ws://example.test"));
      viewportSessions.push(useViewportState(null));
      if (!rendered) setRendered(true);
      return null;
    }
    renderToStaticMarkup(React.createElement(Harness));
    expect(guiSessions.length).toBeGreaterThanOrEqual(2);
    expect(guiSessions.at(-1)).toBe(guiSessions[0]);
    expect(viewportSessions.at(-1)).toBe(viewportSessions[0]);
  });

  it("creates independent sessions without mounting React", () => {
    const firstGui = createGuiState("ws://first.test");
    const secondGui = createGuiState("ws://second.test");
    firstGui.actions.applyMessages([
      { type: "GuiFormSubmitMessage", uuid: "form" },
    ]);
    expect(secondGui.store.get().lastFormSubmit).toBeNull();
    expect(secondGui.store.get().server).toBe("ws://second.test");

    const firstViewport = createViewportState(null);
    const secondViewport = createViewportState(null);
    firstViewport.actions.addPage("main", "Main", true);
    expect(firstViewport.store.get().pageOrder).toEqual(["main"]);
    expect(secondViewport.store.get().pageOrder).toEqual([]);
  });
});
