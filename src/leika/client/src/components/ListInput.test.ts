import React from "react";
import { describe, expect, it } from "vitest";

import { GuiListMessage } from "../WebsocketMessages";
import { MAX_GUI_COLLECTION_ITEM_CODE_UNITS } from "../guiLimits";
import ListInputComponent from "./ListInput";
import { renderWithGuiContext } from "./testGuiContext";

function renderList({
  value = ["alpha", "beta"],
  label = "Tags" as string | null,
  frozen = false,
  disabled = false,
}: {
  value?: string[];
  label?: string | null;
  frozen?: boolean;
  disabled?: boolean;
} = {}): string {
  const message: GuiListMessage = {
    type: "GuiListMessage",
    uuid: "tags",
    value,
    container_uuid: "root",
    props: { order: 0, label, hint: null, visible: true, disabled, frozen },
  };
  return renderWithGuiContext(React.createElement(ListInputComponent, message));
}

/** The `disabled` attribute itself, not `data-disabled` and not the utility
 * classes that name it. */
const DISABLED = /(?<!-)disabled=""/g;

describe("ListInputComponent", () => {
  it("is one text box per entry, in order", () => {
    const markup = renderList({ value: ["alpha", "beta", "gamma"] });
    expect(markup.match(/data-leika-list-entry/g)).toHaveLength(3);
    const values = [...markup.matchAll(/value="([^"]*)"/g)].map((m) => m[1]);
    expect(values).toEqual(["alpha", "beta", "gamma"]);
  });

  it("frozen, is its entries and nothing else", () => {
    // The length and the order are fixed, so the controls that would change
    // them are not drawn -- a dead grip is worse than no grip.
    const markup = renderList({ frozen: true });
    expect(markup.match(/data-leika-list-entry/g)).toHaveLength(2);
    expect(markup).not.toContain("data-leika-list-grip");
    expect(markup).not.toContain("data-leika-list-remove");
    expect(markup).not.toContain("data-leika-list-add");
    // Still editable: frozen is about the list, `disabled` about the boxes.
    // Matched with the hyphen ruled out, since `data-disabled=""` ends in the
    // attribute being looked for and the utility classes mention it too.
    expect(markup.match(DISABLED)).toBeNull();
  });

  it("disables the boxes and every control with them", () => {
    const markup = renderList({ disabled: true });
    // Two entries, two grips, two removes, one add.
    expect(markup.match(DISABLED)).toHaveLength(7);
  });

  it("names each entry for assistive technology, by its place", () => {
    const markup = renderList({ label: "Tags" });
    expect(markup).toContain('aria-label="Tags entry 1"');
    expect(markup).toContain('aria-label="Tags entry 2"');
    expect(markup).toContain('aria-label="Reorder entry 1"');
    expect(markup).toContain('aria-label="Remove entry 2"');
  });

  it("bounds text typed into each retained entry", () => {
    expect(renderList({ value: ["entry"] })).toContain(
      `maxLength="${MAX_GUI_COLLECTION_ITEM_CODE_UNITS}"`,
    );
  });
});
