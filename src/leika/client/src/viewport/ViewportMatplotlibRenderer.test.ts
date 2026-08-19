import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MATPLOTLIB_SVG_MAX_SOURCE_CODE_UNITS } from "../rendererSourceLimits";
import type { ViewportMatplotlibPane } from "./ViewportState";
import ViewportMatplotlibRenderer from "./ViewportMatplotlibRenderer";

function pane(svg: string): ViewportMatplotlibPane {
  return {
    kind: "matplotlib",
    paneId: "figure",
    props: { _svg: svg, title: "Figure", visible: true, loading: false },
  };
}

describe("ViewportMatplotlibRenderer", () => {
  it("shows a status before constructing an oversized SVG Blob", () => {
    const html = renderToStaticMarkup(
      createElement(ViewportMatplotlibRenderer, {
        pane: pane("x".repeat(MATPLOTLIB_SVG_MAX_SOURCE_CODE_UNITS + 1)),
      }),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain("16 Mi-character browser render limit");
    expect(html).not.toContain("<img");
  });
});
