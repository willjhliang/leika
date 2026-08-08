import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { useGuiComponent } from "./ControlPanel/GuiComponentContext";
import { useViewer } from "./ViewerContext";

describe("context assertion hooks", () => {
  it("reports a missing viewer provider at the component boundary", () => {
    function MissingViewer() {
      useViewer();
      return null;
    }

    expect(() =>
      renderToStaticMarkup(React.createElement(MissingViewer)),
    ).toThrowError("useViewer must be used within ViewerContext.Provider");
  });

  it("reports a missing generated-GUI provider at the component boundary", () => {
    function MissingGuiComponent() {
      useGuiComponent();
      return null;
    }

    expect(() =>
      renderToStaticMarkup(React.createElement(MissingGuiComponent)),
    ).toThrowError(
      "useGuiComponent must be used within GuiComponentContext.Provider",
    );
  });
});
