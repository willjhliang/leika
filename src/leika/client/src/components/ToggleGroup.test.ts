import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiToggleGroupMessage } from "../WebsocketMessages";
import ToggleGroupComponent from "./ToggleGroup";

function renderToggleGroup({
  value = ["Bold"],
  multiple = false,
  color = "primary" as "primary" | "secondary",
  merge = [true, true],
}: {
  value?: string[];
  multiple?: boolean;
  color?: "primary" | "secondary";
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
      color,
      options: ["Bold", "Italic", "Under"],
      multiple,
      _merge: merge,
    },
  };
  return renderToStaticMarkup(
    React.createElement(ToggleGroupComponent, message),
  );
}

describe("ToggleGroupComponent", () => {
  it("marks exactly the options that are on", () => {
    const markup = renderToggleGroup({ value: ["Bold", "Under"] });
    expect(markup.match(/aria-pressed="true"/g)).toHaveLength(2);
    expect(markup.match(/aria-pressed="false"/g)).toHaveLength(1);
  });

  it("says whether several may be on at once", () => {
    expect(renderToggleGroup({ multiple: true })).toContain("data-multiple");
    expect(renderToggleGroup({ multiple: false })).not.toContain(
      "data-multiple",
    );
  });

  it("rounds the ends of each run and parts one run from the next", () => {
    // Joined: one run, so only its two ends are rounded.
    const joined = renderToggleGroup({ merge: [true, true] });
    expect(joined.match(/rounded-l-lg!/g)).toHaveLength(1);
    expect(joined.match(/rounded-r-lg!/g)).toHaveLength(1);
    expect(joined).not.toContain("ml-1!");

    // Parted: every toggle is its own run, and each gap gets the row's step.
    const parted = renderToggleGroup({ merge: [false, false] });
    expect(parted.match(/rounded-l-lg!/g)).toHaveLength(3);
    expect(parted.match(/ml-1!/g)).toHaveLength(2);
  });
});
