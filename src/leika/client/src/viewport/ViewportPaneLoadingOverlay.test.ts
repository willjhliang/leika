import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ViewportPaneLoadingOverlay } from "./ViewportPaneLoadingOverlay";

describe("ViewportPaneLoadingOverlay", () => {
  it("announces the default loading status", () => {
    const html = renderToStaticMarkup(
      React.createElement(ViewportPaneLoadingOverlay, { loading: true }),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="Loading"');
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
