import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiDropdownMessage } from "../WebsocketMessages";
import DropdownComponent from "./Dropdown";

function renderDropdown(disabled = false): string {
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
      disabled,
      options: ["Fast", "Accurate"],
    },
  };
  return renderToStaticMarkup(React.createElement(DropdownComponent, message));
}

describe("DropdownComponent", () => {
  it("keeps the stock Combobox trigger composition", () => {
    const markup = renderDropdown();
    expect(markup).toContain('data-slot="combobox-trigger"');
    expect(markup).toContain('role="combobox"');
    expect(markup).toContain('id="mode"');
    expect(markup).toContain("Fast");
    expect(markup).not.toContain('data-slot="select-trigger"');
  });

  it("retains disabled semantics on the Combobox trigger", () => {
    const markup = renderDropdown(true);
    expect(markup).toMatch(
      /<button(?=[^>]*data-slot="combobox-trigger")(?=[^>]*disabled="")[^>]*>/,
    );
  });
});
