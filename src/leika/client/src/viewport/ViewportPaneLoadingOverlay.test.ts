import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ViewportPaneLoadingOverlay } from "./ViewportWorkspace";

describe("ViewportPaneLoadingOverlay", () => {
  it("renders the default loading status as an opaque in-place overlay", () => {
    const html = renderToStaticMarkup(
      React.createElement(ViewportPaneLoadingOverlay, { loading: true }),
    );

    expect(html).toContain("data-viewport-pane-loading");
    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="Loading"');
    expect(html).toContain("position:absolute");
    expect(html).toContain("background:var(--background)");
    expect(html).toContain("z-index:10");
  });

  it("shows a caller-provided loading message as plain text", () => {
    const html = renderToStaticMarkup(
      React.createElement(ViewportPaneLoadingOverlay, {
        loading: "Indexing ABC · 129k episodes",
      }),
    );

    expect(html).toContain('aria-label="Indexing ABC · 129k episodes"');
    expect(html).toContain("<span>Indexing ABC · 129k episodes</span>");
  });
});
