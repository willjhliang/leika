import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiButtonGroupMessage } from "../WebsocketMessages";
import ButtonGroupComponent from "./ButtonGroup";

type Color = "inverse" | "default";

function renderButtonGroup(
  disabled = false,
  color: Color | Color[] = "inverse",
  merge: boolean[] = [false, false],
): string {
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
      color: typeof color === "string" ? options.map(() => color) : color,
      options,
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

  it("gives every option one role, the row's own unless told otherwise", () => {
    const inverse = renderButtonGroup(false, "inverse");
    const outlined = renderButtonGroup(false, "default");
    // Whatever the colorway resolves to, all three options share it: nothing
    // in the row is styled differently from its neighbours.
    for (const markup of [inverse, outlined]) {
      const classes = [...markup.matchAll(/<button[^>]*class="([^"]*)"/g)].map(
        (match) => match[1],
      );
      expect(classes).toHaveLength(3);
      expect(new Set(classes).size).toBe(1);
    }
    expect(inverse).not.toEqual(outlined);
  });

  it("colors options one at a time when the row asks for it", () => {
    const mixed = renderButtonGroup(false, ["default", "inverse", "inverse"]);
    const roles = [...mixed.matchAll(/data-leika-button-color="(\w+)"/g)].map(
      (match) => match[1],
    );
    expect(roles).toEqual(["default", "inverse", "inverse"]);
    const classes = [...mixed.matchAll(/<button[^>]*class="([^"]*)"/g)].map(
      (match) => match[1],
    );
    // The outlined one is drawn differently from the two filled ones, which
    // still match each other.
    expect(classes[1]).toEqual(classes[2]);
    expect(classes[0]).not.toEqual(classes[1]);
  });

  it("only divides a merged pair when both halves are filled", () => {
    // The hairline exists because two filled buttons have no edge between
    // them; an outlined neighbour brings one of its own.
    const mixed = renderButtonGroup(
      false,
      ["inverse", "default", "inverse"],
      [true, true],
    );
    expect(mixed).not.toContain("button-group-separator");
    const twoFilled = renderButtonGroup(
      false,
      ["inverse", "inverse", "default"],
      [true, true],
    );
    expect(twoFilled.match(/data-slot="button-group-separator"/g)).toHaveLength(
      1,
    );
  });

  it("makes one run per stretch of merged buttons", () => {
    // The row's own group plus one nested group per run.
    const groups = (markup: string) =>
      (markup.match(/data-slot="button-group"/g) ?? []).length - 1;
    expect(groups(renderButtonGroup(false, "default", [true, true]))).toBe(1);
    expect(groups(renderButtonGroup(false, "default", [false, false]))).toBe(3);
    expect(groups(renderButtonGroup(false, "default", [true, false]))).toBe(2);
  });

  it("divides merged filled buttons, and leaves outlined ones to their borders", () => {
    const filled = renderButtonGroup(false, "inverse", [true, true]);
    const outlined = renderButtonGroup(false, "default", [true, true]);
    expect(filled.match(/data-slot="button-group-separator"/g)).toHaveLength(2);
    expect(outlined).not.toContain("button-group-separator");
    // Parted buttons have a gap doing the dividing, so no hairline either.
    expect(renderButtonGroup(false, "inverse", [false, false])).not.toContain(
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
