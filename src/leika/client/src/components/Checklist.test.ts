import React from "react";
import { describe, expect, it } from "vitest";

import { GuiChecklistMessage } from "../WebsocketMessages";
import ChecklistComponent from "./Checklist";
import { renderWithGuiContext } from "./testGuiContext";

function renderChecklist({
  value = [
    ["Fuel", false],
    ["Doors", true],
  ] as GuiChecklistMessage["value"],
  label = "Preflight" as string | null,
  frozen = false,
  disabled = false,
}: {
  value?: GuiChecklistMessage["value"];
  label?: string | null;
  frozen?: boolean;
  disabled?: boolean;
} = {}): string {
  const message: GuiChecklistMessage = {
    type: "GuiChecklistMessage",
    uuid: "preflight",
    value,
    container_uuid: "root",
    props: { order: 0, label, hint: null, visible: true, disabled, frozen },
  };
  return renderWithGuiContext(React.createElement(ChecklistComponent, message));
}

/** The `disabled` attribute itself, not `data-disabled` and not the utility
 * classes that name it. */
const DISABLED = /(?<!-)disabled=""/g;

describe("ChecklistComponent", () => {
  it("is one box and one entry per item, in order", () => {
    const markup = renderChecklist();
    expect(markup.match(/data-leika-checklist-box/g)).toHaveLength(2);
    const values = [...markup.matchAll(/value="([^"]*)"/g)].map((m) => m[1]);
    expect(values).toEqual(["Fuel", "Doors"]);
  });

  it("ticks the box of an item that is checked, and only that one", () => {
    const markup = renderChecklist();
    const boxes = [
      ...markup.matchAll(/<span[^>]*data-leika-checklist-box[^>]*>/g),
    ].map((match) => match[0]);
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).toContain('aria-checked="false"');
    expect(boxes[1]).toContain('aria-checked="true"');
  });

  it("is a list underneath: the entries hug, and every one can be moved", () => {
    // The words are still the viewer's to write, so the rows are the list's
    // rows -- one block, ends rounded, insides square, with a grip and a
    // remove on each and an add underneath.
    const markup = renderChecklist({
      value: [
        ["a", false],
        ["b", false],
        ["c", false],
      ],
    });
    const boxes = [
      ...markup.matchAll(/<input[^>]*data-leika-checklist-entry[^>]*>/g),
    ].map((match) => match[0]);
    expect(boxes[0]).toContain("rounded-b-none");
    expect(boxes[0]).not.toContain("rounded-t-none");
    expect(boxes[1]).toContain("rounded-t-none");
    expect(boxes[1]).toContain("rounded-b-none");
    expect(boxes[2]).not.toContain("rounded-b-none");
    expect(markup.match(/-mt-px/g)).toHaveLength(2);
    expect(markup.match(/data-leika-list-grip/g)).toHaveLength(3);
    expect(markup.match(/data-leika-list-remove/g)).toHaveLength(3);
    expect(markup.match(/data-leika-list-add/g)).toHaveLength(1);
  });

  it("frozen, is words with boxes rather than fields to type in", () => {
    // What a checklist is asked for is the ticks, so frozen fixes the words
    // too -- and with nothing to write, nothing is drawn as writable.
    const markup = renderChecklist({ frozen: true });
    expect(markup.match(/data-leika-checklist-box/g)).toHaveLength(2);
    // No field: the only inputs left are the hidden ones a checkbox keeps so
    // that a form, and a `<label for>`, can reach it.
    expect(markup).not.toContain('data-slot="input"');
    expect(markup).not.toContain("data-leika-list-grip");
    expect(markup).not.toContain("data-leika-list-remove");
    expect(markup).not.toContain("data-leika-list-add");
    // The words themselves are still shown, and ticking them is one gesture:
    // a 16px box is a small target for a row that is one thing to answer.
    expect(markup).toContain("Fuel");
    expect(markup).toContain('for="preflight-0"');
    // Frozen is not disabled -- the boxes still tick.
    expect(markup.match(DISABLED)).toBeNull();
  });

  it("disables the boxes and everything around them", () => {
    // Two boxes, two entries, two grips, two removes, one add -- a box being
    // counted through the hidden input it keeps, which is what carries the
    // attribute for a control that is a span with a role.
    expect(renderChecklist({ disabled: true }).match(DISABLED)).toHaveLength(9);
    // Frozen, there is nothing left to disable but the boxes.
    expect(
      renderChecklist({ disabled: true, frozen: true }).match(DISABLED),
    ).toHaveLength(2);
  });

  it("takes the row when it has no label to sit beside", () => {
    expect(renderChecklist({ label: null })).not.toContain(
      "data-leika-gui-row",
    );
    expect(renderChecklist({ label: "Preflight" })).toContain(
      "data-leika-gui-row",
    );
  });

  it("names each entry for assistive technology, by its place", () => {
    const markup = renderChecklist();
    expect(markup).toContain('aria-label="Preflight entry 1"');
    expect(markup).toContain('aria-label="Preflight entry 2"');
    expect(markup).toContain('aria-label="Reorder entry 1"');
    expect(markup).toContain('aria-label="Remove entry 2"');
  });
});
