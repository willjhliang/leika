import React from "react";
import { describe, expect, it } from "vitest";

import { GuiButtonGroupMessage } from "../WebsocketMessages";
import ButtonGroupComponent from "./ButtonGroup";
import { renderWithGuiContext } from "./testGuiContext";

function renderButtonGroup(disabled = false): string {
  const options = ["Ocean", "Magma", "Viridis"];
  const message: GuiButtonGroupMessage = {
    type: "GuiButtonGroupMessage",
    uuid: "palette",
    value: "Ocean",
    container_uuid: "root",
    props: {
      order: 0,
      label: "Palette",
      hint: null,
      visible: true,
      disabled,
      color: options.map(() => "inverse"),
      options,
      _merge: [false, false],
    },
  };
  return renderWithGuiContext(
    React.createElement(ButtonGroupComponent, message),
  );
}

describe("ButtonGroupComponent", () => {
  it("is a row of ordinary buttons, with nothing marked as selected", () => {
    const markup = renderButtonGroup();
    expect(markup.match(/<button\b/g)).toHaveLength(3);
    for (const label of ["Ocean", "Magma", "Viridis"]) {
      expect(markup).toContain(label);
    }
    expect(markup).toContain('aria-label="Palette"');
    // Buttons, not toggles: the group's value picks nothing out of the row.
    expect(markup).not.toContain("aria-pressed");
  });

  it("disables every option from the root", () => {
    const markup = renderButtonGroup(true);
    expect(markup.match(/<button\b[^>]*\sdisabled=""[^>]*>/g)).toHaveLength(3);
  });
});
