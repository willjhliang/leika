import React from "react";
import { describe, expect, it } from "vitest";

import { GuiListMessage } from "../WebsocketMessages";
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

  it("gives every entry a grip and a remove, and the list an add", () => {
    const markup = renderList();
    expect(markup.match(/data-leika-list-grip/g)).toHaveLength(2);
    expect(markup.match(/data-leika-list-remove/g)).toHaveLength(2);
    expect(markup.match(/data-leika-list-add/g)).toHaveLength(1);
  });

  it("hugs its entries into one block, ends rounded and insides square", () => {
    const markup = renderList({ value: ["a", "b", "c"] });
    const boxes = [
      ...markup.matchAll(/<input[^>]*data-leika-list-entry[^>]*>/g),
    ].map((match) => match[0]);
    expect(boxes).toHaveLength(3);
    // First keeps its top, last keeps its bottom, the middle keeps neither.
    expect(boxes[0]).toContain("rounded-b-none");
    expect(boxes[0]).not.toContain("rounded-t-none");
    expect(boxes[1]).toContain("rounded-t-none");
    expect(boxes[1]).toContain("rounded-b-none");
    expect(boxes[2]).toContain("rounded-t-none");
    expect(boxes[2]).not.toContain("rounded-b-none");
    // And they share an edge rather than each drawing its own.
    expect(markup.match(/-mt-px/g)).toHaveLength(2);
  });

  it("keeps both of an entry's controls inside its box, as bare icons", () => {
    const markup = renderList({ value: ["a"] });
    // Neither is a button of its own: the panel's Button leaves a `data-slot`,
    // and the only one in a list is the Add underneath.
    expect(markup.match(/data-slot="button"/g)).toHaveLength(1);
    const row = markup.slice(
      markup.indexOf("data-leika-list-item"),
      markup.indexOf("data-leika-list-add"),
    );
    expect(row).toContain("data-leika-list-grip");
    expect(row).toContain("data-leika-list-remove");
    // Both sit over the box, which makes room for them as they arrive -- and
    // an entry too long for what is left of it ends in an ellipsis.
    expect(row).toContain("absolute");
    expect(row).toContain("group-hover/entry:pr-10");
    expect(row).toContain("text-ellipsis");
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

  it("takes the row when it has no label to sit beside", () => {
    expect(renderList({ label: null })).not.toContain("data-leika-gui-row");
    expect(renderList({ label: "Tags" })).toContain("data-leika-gui-row");
  });

  it("names each entry for assistive technology, by its place", () => {
    const markup = renderList({ label: "Tags" });
    expect(markup).toContain('aria-label="Tags entry 1"');
    expect(markup).toContain('aria-label="Tags entry 2"');
    expect(markup).toContain('aria-label="Reorder entry 1"');
    expect(markup).toContain('aria-label="Remove entry 2"');
  });
});
