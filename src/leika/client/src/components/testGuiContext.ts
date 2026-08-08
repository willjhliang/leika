import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";

const TEST_GUI_CONTEXT = {
  setValue: () => undefined,
  messageSender: () => undefined,
  GuiContainer: () => null,
};

/** Render a generated GUI component inside the provider it requires in-app. */
export function renderWithGuiContext(element: React.ReactElement): string {
  return renderToStaticMarkup(
    React.createElement(
      GuiComponentContext.Provider,
      { value: TEST_GUI_CONTEXT },
      element,
    ),
  );
}
