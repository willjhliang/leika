import React from "react";
import { describe, expect, it } from "vitest";

import { GuiToggleGroupMessage } from "../WebsocketMessages";
import ToggleGroupComponent from "./ToggleGroup";
import { renderWithGuiContext } from "./testGuiContext";

const OPTIONS = ["Bold", "Italic", "Under"];

function renderToggleGroup(value: string[]): string {
  const message: GuiToggleGroupMessage = {
    type: "GuiToggleGroupMessage",
    uuid: "style",
    value,
    container_uuid: "root",
    props: {
      order: 0,
      label: "Style",
      hint: null,
      visible: true,
      disabled: false,
      color: OPTIONS.map(() => "inverse"),
      options: OPTIONS,
      multiple: true,
      required: false,
      _merge: [true, true],
    },
  };
  return renderWithGuiContext(
    React.createElement(ToggleGroupComponent, message),
  );
}

describe("ToggleGroupComponent", () => {
  it("marks exactly the options that are on", () => {
    const markup = renderToggleGroup(["Bold", "Under"]);
    expect(markup.match(/aria-pressed="true"/g)).toHaveLength(2);
    expect(markup.match(/aria-pressed="false"/g)).toHaveLength(1);
  });
});
