import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiPlotlyMessage } from "../WebsocketMessages";
import PlotlyComponent from "./PlotlyComponent";

const message = (serialized: string, aspect = 1): GuiPlotlyMessage => ({
  type: "GuiPlotlyMessage",
  uuid: "plot",
  container_uuid: "root",
  props: {
    order: 0,
    _plotly_json_str: serialized,
    aspect,
    visible: true,
  },
});

describe("PlotlyComponent", () => {
  it("reports malformed figure JSON instead of throwing during render", () => {
    const html = renderToStaticMarkup(
      createElement(PlotlyComponent, message("{")),
    );

    expect(html).toContain("Plotly data contains invalid JSON.");
    expect(html).toContain('role="status"');
  });

  it("reports an invalid wire aspect instead of producing infinite geometry", () => {
    const html = renderToStaticMarkup(
      createElement(PlotlyComponent, message('{"data":[]}', 0)),
    );

    expect(html).toContain("Plot aspect must be a positive number.");
    expect(html).not.toContain("Infinity");
  });
});
