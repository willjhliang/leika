import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ViewerContext, type ViewerContextContents } from "../ViewerContext";
import { createStore } from "../store";
import { PanelHeader } from "./ControlPanel";

function renderPageHeader({
  pageOrder = ["overview", "analysis"],
  activePageId = "analysis",
}: {
  pageOrder?: string[];
  activePageId?: string;
} = {}): string {
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
    pageOrder,
    activePageId,
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
  it("renders one page as a label with no control that can open a list", () => {
    const markup = renderPageHeader({
      pageOrder: ["overview"],
      activePageId: "overview",
    });

    expect(markup).toContain("Overview");
    expect(markup).not.toContain("data-leika-page-selector");
    expect(markup).not.toContain('role="combobox"');
    expect(markup).not.toContain('role="listbox"');
    expect(markup).not.toContain("lucide-chevron-down");
    // With no button or combobox trigger, clicking the title cannot open a
    // selector. PanelHeader has no other controls because this fixture omits
    // its connection badge.
    expect(markup).not.toContain("<button");
  });

  it("keeps the page-name styling borderless and leaves a dock drag target", () => {
    const markup = renderPageHeader();

    expect(markup).toContain("data-leika-page-selector");
    expect(markup).toContain('aria-label="Page: Analysis"');
    expect(markup).toContain('role="combobox"');
    expect(markup).toContain("Analysis");
    expect(markup).toContain("lucide-chevron-down");
    expect(markup).toContain("border-0");
    expect(markup).toContain("text-muted-foreground");
    expect(markup).toContain("data-leika-panel-drag-space");
    expect(markup.match(/<button/g)).toHaveLength(1);
  });
});
