import React from "react";
import { describe, expect, it } from "vitest";

import { GuiDropdownMessage } from "../WebsocketMessages";
import DropdownComponent from "./Dropdown";
import { renderWithGuiContext } from "./testGuiContext";

function renderDropdown(searchable: boolean): string {
  const message: GuiDropdownMessage = {
    type: "GuiDropdownMessage",
    uuid: "mode",
    value: "Fast",
    container_uuid: "root",
    props: {
      order: 0,
      label: "Mode",
      hint: null,
      visible: true,
      disabled: true,
      options: ["Fast", "Accurate"],
      searchable,
    },
  };
  return renderWithGuiContext(React.createElement(DropdownComponent, message));
}

describe("DropdownComponent", () => {
  it("retains disabled semantics on both triggers", () => {
    for (const searchable of [false, true]) {
      expect(renderDropdown(searchable)).toMatch(
        /<button\b[^>]*\sdisabled=""[^>]*>/,
      );
    }
  });
});
