import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiButtonGroupMessage } from "../WebsocketMessages";
import ButtonGroupComponent from "./ButtonGroup";

function renderButtonGroup(
  disabled = false,
  color: "primary" | "secondary" = "primary",
): string {
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
      color,
      options: ["Ocean", "Magma", "Viridis"],
    },
  };
  return renderToStaticMarkup(
    React.createElement(ButtonGroupComponent, message),
  );
}

describe("ButtonGroupComponent", () => {
  it("is a row of ordinary buttons, with nothing marked as selected", () => {
    const markup = renderButtonGroup();
    expect(markup.match(/data-leika-button(?![-\w])/g)).toHaveLength(3);
    expect(markup.match(/data-slot="button"/g)).toHaveLength(3);
    expect(markup).toContain('aria-label="Palette"');
    expect(markup).toContain("no-scrollbar");
    expect(markup).toContain("overflow-x-auto");
    expect(markup).toContain("min-w-fit flex-1");
    // Buttons, not toggles: the group's value picks nothing out of the row.
    expect(markup).not.toContain("aria-pressed");
    expect(markup).not.toContain("data-state=");
    expect(markup).not.toContain("toggle-group");
    expect(markup).not.toContain("flex-wrap");
  });

  it("gives every option the same colorway", () => {
    const primary = renderButtonGroup(false, "primary");
    const secondary = renderButtonGroup(false, "secondary");
    // Whatever the colorway resolves to, all three options share it: nothing
    // in the row is styled differently from its neighbours.
    for (const markup of [primary, secondary]) {
      const classes = [...markup.matchAll(/<button[^>]*class="([^"]*)"/g)].map(
        (match) => match[1],
      );
      expect(classes).toHaveLength(3);
      expect(new Set(classes).size).toBe(1);
    }
    expect(primary).not.toEqual(secondary);
  });

  it("disables every option from the root", () => {
    const markup = renderButtonGroup(true);
    expect(
      markup.match(
        /<button(?=[^>]*data-slot="button")(?=[^>]*disabled="")[^>]*>/g,
      ),
    ).toHaveLength(3);
  });
});
