import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiButtonGroupMessage } from "../WebsocketMessages";
import ButtonGroupComponent from "./ButtonGroup";

function renderButtonGroup(
  disabled = false,
  color: "primary" | "secondary" = "primary",
  merge: boolean[] = [false, false],
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
      _merge: merge,
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

  it("makes one run per stretch of merged buttons", () => {
    // The row's own group plus one nested group per run.
    const groups = (markup: string) =>
      (markup.match(/data-slot="button-group"/g) ?? []).length - 1;
    expect(groups(renderButtonGroup(false, "secondary", [true, true]))).toBe(1);
    expect(groups(renderButtonGroup(false, "secondary", [false, false]))).toBe(
      3,
    );
    expect(groups(renderButtonGroup(false, "secondary", [true, false]))).toBe(
      2,
    );
  });

  it("divides merged filled buttons, and leaves outlined ones to their borders", () => {
    const filled = renderButtonGroup(false, "primary", [true, true]);
    const outlined = renderButtonGroup(false, "secondary", [true, true]);
    expect(filled.match(/data-slot="button-group-separator"/g)).toHaveLength(2);
    expect(outlined).not.toContain("button-group-separator");
    // Parted buttons have a gap doing the dividing, so no hairline either.
    expect(renderButtonGroup(false, "primary", [false, false])).not.toContain(
      "button-group-separator",
    );
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
