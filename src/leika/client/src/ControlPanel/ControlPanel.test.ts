import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ViewerContext, type ViewerContextContents } from "../ViewerContext";
import { createStore } from "../store";
import { PanelHeader } from "./ControlPanel";

function renderPageHeader(): string {
  const useViewport = createStore({
    pages: {
      overview: {
        pageId: "overview",
        name: "Overview",
        panes: {},
        layout: {
          version: 1,
          root: { type: "pane", pane_id: "__leika_root__" },
        },
      },
      analysis: {
        pageId: "analysis",
        name: "Analysis",
        panes: {},
        layout: {
          version: 1,
          root: { type: "pane", pane_id: "__leika_root__" },
        },
      },
    },
    pageOrder: ["overview", "analysis"],
    activePageId: "analysis",
    interactionEpoch: 0,
  });
  const viewer = {
    useViewport,
    viewportActions: { setActivePage: vi.fn() },
  } as unknown as ViewerContextContents;

  return renderToStaticMarkup(
    React.createElement(
      ViewerContext.Provider,
      { value: viewer },
      React.createElement(PanelHeader, { badge: null }),
    ),
  );
}

describe("PanelHeader page selector", () => {
  it("keeps the page-name styling borderless and leaves a dock drag target", () => {
    const markup = renderPageHeader();

    expect(markup).toContain("data-leika-page-selector");
    expect(markup).toContain('aria-label="Page: Analysis"');
    expect(markup).toContain("Analysis");
    expect(markup).toContain("lucide-chevron-down");
    expect(markup).toContain("border-0");
    expect(markup).toContain("text-muted-foreground");
    expect(markup).toContain("data-leika-panel-drag-space");
    expect(markup.match(/<button/g)).toHaveLength(1);
  });
});
