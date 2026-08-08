import React from "react";
import { describe, expect, it } from "vitest";

import { GuiDropdownMessage } from "../WebsocketMessages";
import DropdownComponent from "./Dropdown";
import { renderWithGuiContext } from "./testGuiContext";

function renderDropdown(disabled = false, searchable = false): string {
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
      searchable,
    },
  };
  return renderWithGuiContext(React.createElement(DropdownComponent, message));
}

describe("DropdownComponent", () => {
  it("keeps the stock Select trigger composition by default", () => {
    const markup = renderDropdown();
    expect(markup).toContain('data-slot="select-trigger"');
    expect(markup).toContain('id="mode"');
    expect(markup).toContain("Fast");
    // A plain dropdown has no filter box, so it must not fall back to the
    // Combobox composition that carries one.
    expect(markup).not.toContain('data-slot="combobox-trigger"');
  });

  it("keeps the stock Combobox trigger composition when searchable", () => {
    const markup = renderDropdown(false, true);
    expect(markup).toContain('data-slot="combobox-trigger"');
    expect(markup).toContain('role="combobox"');
    expect(markup).toContain('id="mode"');
    expect(markup).toContain("Fast");
    expect(markup).not.toContain('data-slot="select-trigger"');
  });

  it("retains disabled semantics on both triggers", () => {
    expect(renderDropdown(true)).toMatch(
      /<button(?=[^>]*data-slot="select-trigger")(?=[^>]*disabled="")[^>]*>/,
    );
    expect(renderDropdown(true, true)).toMatch(
      /<button(?=[^>]*data-slot="combobox-trigger")(?=[^>]*disabled="")[^>]*>/,
    );
  });
});
