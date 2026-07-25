import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiProgressBarMessage } from "../WebsocketMessages";
import ProgressBarComponent from "./ProgressBar";

function renderProgressBar(animated: boolean): string {
  const message: GuiProgressBarMessage = {
    type: "GuiProgressBarMessage",
    uuid: "progress",
    value: 42,
    container_uuid: "root",
    props: {
      order: 0,
      animated,
      visible: true,
    },
  };
  return renderToStaticMarkup(
    React.createElement(ProgressBarComponent, message),
  );
}

describe("ProgressBarComponent", () => {
  it("uses Tailwind's built-in pulse animation only when requested", () => {
    expect(renderProgressBar(false)).not.toContain("animate-pulse");
    expect(renderProgressBar(true)).toContain("animate-pulse");
  });
});
