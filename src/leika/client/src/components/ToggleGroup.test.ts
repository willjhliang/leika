import React from "react";
import { describe, expect, it } from "vitest";

import { GuiToggleGroupMessage } from "../WebsocketMessages";
import ToggleGroupComponent from "./ToggleGroup";
import { renderWithGuiContext } from "./testGuiContext";

type Color = "inverse" | "default";

const OPTIONS = ["Bold", "Italic", "Under"];

function renderToggleGroup({
  value = ["Bold"],
  multiple = false,
  required = false,
  color = "inverse" as Color | Color[],
  merge = [true, true],
}: {
  value?: string[];
  multiple?: boolean;
  required?: boolean;
  color?: Color | Color[];
  merge?: boolean[];
} = {}): string {
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
      color: typeof color === "string" ? OPTIONS.map(() => color) : color,
      options: OPTIONS,
      multiple,
      required,
      _merge: merge,
    },
  };
  return renderWithGuiContext(
    React.createElement(ToggleGroupComponent, message),
  );
}

/** The class list of each toggle, so a rule meant for the toggles is not
 * confused with one the group itself merely names in a variant. */
function toggleClasses(markup: string): string[] {
  return [...markup.matchAll(/<button[^>]*\sclass="([^"]*)"/g)].map(
    (match) => match[1],
  );
}

describe("ToggleGroupComponent", () => {
  it("marks exactly the options that are on", () => {
    const markup = renderToggleGroup({ value: ["Bold", "Under"] });
    expect(markup.match(/aria-pressed="true"/g)).toHaveLength(2);
    expect(markup.match(/aria-pressed="false"/g)).toHaveLength(1);
  });

  it("wraps its options rather than running them past the row", () => {
    // The same answer the buttons give: a toggle whose words are cut in half
    // at the panel's edge is one nobody can read, and the row scrolled with no
    // scrollbar to say that anything had been hidden there.
    const markup = renderToggleGroup();
    expect(markup).toContain("flex-wrap");
    expect(markup).not.toContain("no-scrollbar");
    expect(markup).not.toContain("overflow-x-auto");
  });

  it("says whether several may be on at once", () => {
    expect(renderToggleGroup({ multiple: true })).toContain("data-multiple");
    expect(renderToggleGroup({ multiple: false })).not.toContain(
      "data-multiple",
    );
  });

  it("rounds the toggles themselves rather than clipping them to the run", () => {
    // Same reason as the buttons: clipping would cut the outline off at the
    // corner, and the outline is what the pointer changes.
    const joined = renderToggleGroup({ merge: [true, true] });
    expect(joined.match(/data-leika-group-run/g)).toHaveLength(1);
    expect(joined).not.toContain("overflow-hidden");
    const [first, , last] = toggleClasses(joined);
    expect(first).toContain("rounded-tl-lg!");
    expect(first).toContain("rounded-tr-none!");
    expect(last).toContain("rounded-br-lg!");
    expect(last).toContain("rounded-bl-none!");
    for (const toggle of toggleClasses(joined))
      expect(toggle).toContain("-mt-px");
    expect(joined.match(/data-leika-joined/g)).toHaveLength(2);

    // Parted: every toggle is its own block, so each is rounded all round and
    // none of them shares an edge.
    const parted = renderToggleGroup({ merge: [false, false] });
    expect(parted.match(/data-leika-group-run/g)).toHaveLength(3);
    for (const toggle of toggleClasses(parted)) {
      expect(toggle).toContain("rounded-tl-lg!");
      expect(toggle).toContain("rounded-br-lg!");
    }
    expect(parted).not.toContain("data-leika-joined");
  });

  it("colors toggles one at a time when the row asks for it", () => {
    const mixed = renderToggleGroup({
      color: ["default", "inverse", "inverse"],
    });
    const roles = [...mixed.matchAll(/data-leika-button-color="(\w+)"/g)].map(
      (match) => match[1],
    );
    expect(roles).toEqual(["default", "inverse", "inverse"]);

    // The hairline between joined toggles is for two filled ones meeting; the
    // outlined half of a pair brings a border of its own. It is drawn in the
    // panel's own surface, which is what shows between two filled buttons.
    const hairline = /border-l-\(--leika-panel-surface\)/g;
    expect(mixed.match(hairline)).toHaveLength(1);
    expect(
      renderToggleGroup({ color: "inverse" }).match(hairline),
    ).toHaveLength(2);
    expect(renderToggleGroup({ color: "default" })).not.toContain(
      "border-l-(--leika-panel-surface)",
    );
  });
});
