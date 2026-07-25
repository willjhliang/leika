import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiButtonGroupMessage } from "../WebsocketMessages";
import ButtonGroupComponent from "./ButtonGroup";

function renderButtonGroup(disabled = false): string {
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
      options: ["Ocean", "Magma", "Viridis"],
    },
  };
  return renderToStaticMarkup(
    React.createElement(ButtonGroupComponent, message),
  );
}

describe("ButtonGroupComponent", () => {
  it("uses one full-width stock segmented toggle group", () => {
    const markup = renderButtonGroup();
    expect(markup.match(/data-leika-button/g)).toHaveLength(3);
    expect(markup.match(/data-slot="toggle-group-item"/g)).toHaveLength(3);
    expect(markup.match(/data-variant="outline"/g)).toHaveLength(4);
    expect(markup).toContain('data-spacing="0"');
    expect(markup).toContain('aria-label="Palette"');
    expect(markup).toContain("no-scrollbar");
    expect(markup).toContain("overflow-x-auto");
    expect(markup).toContain("min-w-fit flex-1");
    expect(markup).not.toContain("grid-flow-col");
    expect(markup).not.toContain("auto-cols-fr");
    expect(markup).not.toContain("flex-wrap");
  });

  it("disables the group and every option from the root", () => {
    const markup = renderButtonGroup(true);
    expect(markup).toMatch(
      /<div(?=[^>]*data-slot="toggle-group")(?=[^>]*data-disabled="")[^>]*>/,
    );
    expect(
      markup.match(
        /<button(?=[^>]*data-slot="toggle-group-item")(?=[^>]*disabled="")[^>]*>/g,
      ),
    ).toHaveLength(3);
  });
});
