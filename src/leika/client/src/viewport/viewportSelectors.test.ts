import { describe, expect, it } from "vitest";
import {
  createViewportState,
  initialViewportLayout,
  initialViewportPanes,
  type ViewportPageState,
} from "./ViewportState";
import { displayedViewportPage } from "./viewportSelectors";

const page: ViewportPageState = {
  pageId: "main",
  name: "Main",
  isDefault: true,
  panes: initialViewportPanes(),
  layout: initialViewportLayout(),
};

function readyState() {
  return {
    ...createViewportState(null).store.get(),
    pages: { main: page },
    activePageId: "main",
    displayPageId: "main",
    pageStream: {
      pageId: "main",
      generation: 1,
      accepting: true,
      ready: true,
    },
  };
}

describe("displayedViewportPage", () => {
  it("exposes a complete active generation", () => {
    expect(displayedViewportPage(readyState())).toBe(page);
  });

  it("keeps the transition snapshot visible over an incomplete replacement", () => {
    const state = readyState();
    const transitionPage = { ...page, name: "Previous generation" };
    expect(
      displayedViewportPage({
        ...state,
        transitionPage,
        pageStream: { ...state.pageStream, ready: false },
      }),
    ).toBe(transitionPage);
  });

  it("hides partial, absent, and mismatched live generations", () => {
    const state = readyState();
    expect(
      displayedViewportPage({ ...state, pageStream: null }),
    ).toBeUndefined();
    expect(
      displayedViewportPage({
        ...state,
        pageStream: { ...state.pageStream, ready: false },
      }),
    ).toBeUndefined();
    expect(
      displayedViewportPage({
        ...state,
        pageStream: { ...state.pageStream, pageId: "other" },
      }),
    ).toBeUndefined();
    expect(
      displayedViewportPage({ ...state, activePageId: "other" }),
    ).toBeUndefined();
    expect(
      displayedViewportPage({ ...state, displayPageId: null }),
    ).toBeUndefined();
  });

  it("does not give a stale pane host the new page's contents", () => {
    expect(displayedViewportPage(readyState(), "other")).toBeUndefined();
  });
});
