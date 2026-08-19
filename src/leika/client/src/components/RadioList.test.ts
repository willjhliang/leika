import React from "react";
import { describe, expect, it } from "vitest";

import { GuiRadioListMessage } from "../WebsocketMessages";
import { MAX_GUI_COLLECTION_ITEM_CODE_UNITS } from "../guiLimits";
import RadioListComponent from "./RadioList";
import { renderWithGuiContext } from "./testGuiContext";

function renderRadioList({
  value = [
    ["Default", false],
    ["Comfortable", true],
  ] as GuiRadioListMessage["value"],
  label = "Density" as string | null,
  frozen = false,
  disabled = false,
}: {
  value?: GuiRadioListMessage["value"];
  label?: string | null;
  frozen?: boolean;
  disabled?: boolean;
} = {}): string {
  const message: GuiRadioListMessage = {
    type: "GuiRadioListMessage",
    uuid: "density",
    value,
    container_uuid: "root",
    props: { order: 0, label, hint: null, visible: true, disabled, frozen },
  };
  return renderWithGuiContext(React.createElement(RadioListComponent, message));
}

describe("RadioListComponent", () => {
  it("keeps editable fields outside the composite radio group", () => {
    const markup = renderRadioList();
    expect(markup.match(/data-leika-radio-list-radio/g)).toHaveLength(2);
    expect(markup.match(/data-slot="radio-group-item"/g)).toHaveLength(2);
    const entries = [
      ...markup.matchAll(/<input[^>]*data-leika-radio-list-entry[^>]*>/g),
    ].map((match) => match[0]);
    expect(entries[0]).toContain('value="Default"');
    expect(entries[1]).toContain('value="Comfortable"');
    expect(markup).toContain("<fieldset");
    expect(markup).toContain(">Density</legend>");
    expect(markup).not.toContain('data-slot="radio-group"');
    expect(markup).not.toContain('role="radiogroup"');
    expect(markup.match(/name="leika-radio-list-density"/g)).toHaveLength(2);
  });

  it("selects exactly the configured radio", () => {
    const markup = renderRadioList();
    const radioInputs = [...markup.matchAll(/<input[^>]*>/g)]
      .map((match) => match[0])
      .filter((input) => input.includes("data-leika-radio-list-radio"));
    expect(radioInputs).toHaveLength(2);
    expect(radioInputs[0]).toContain('name="leika-radio-list-density"');
    expect(radioInputs[1]).toContain('name="leika-radio-list-density"');
    expect(radioInputs[0]).not.toContain('checked=""');
    expect(radioInputs[1]).toContain('checked=""');
    expect(markup.match(/data-slot="radio-group-indicator"/g)).toHaveLength(1);
  });

  it("uses the checklist-style editable stack", () => {
    const markup = renderRadioList({
      value: [
        ["a", false],
        ["b", true],
        ["c", false],
      ],
    });
    expect(markup.match(/data-leika-list-grip/g)).toHaveLength(3);
    expect(markup.match(/data-leika-list-remove/g)).toHaveLength(3);
    expect(markup.match(/data-leika-list-add/g)).toHaveLength(1);
    expect(markup.match(/-mt-px/g)).toHaveLength(2);
  });

  it("frozen, shows labels and radios without editable list controls", () => {
    const markup = renderRadioList({ frozen: true });
    expect(markup.match(/data-leika-radio-list-radio/g)).toHaveLength(2);
    expect(markup).toContain('data-slot="radio-group"');
    expect(markup).not.toContain('data-slot="input"');
    expect(markup).not.toContain("data-leika-list-grip");
    expect(markup).not.toContain("data-leika-list-remove");
    expect(markup).not.toContain("data-leika-list-add");
    expect(markup).toContain("Default");
    expect(markup).toContain('for="density-0"');
  });

  it("disables every radio through the group", () => {
    const markup = renderRadioList({ disabled: true });
    expect(markup.match(/data-disabled=""/g)?.length).toBeGreaterThanOrEqual(2);
  });

  it("takes the full row when it has no label", () => {
    expect(renderRadioList({ label: null })).not.toContain(
      "data-leika-gui-row",
    );
    expect(renderRadioList({ label: "Density" })).toContain(
      "data-leika-gui-row",
    );
  });

  it("names and bounds every editable choice", () => {
    const markup = renderRadioList();
    expect(markup).toContain('aria-label="Density entry 1"');
    expect(markup).toContain('aria-label="Reorder entry 1"');
    expect(markup).toContain('aria-label="Remove entry 2"');
    expect(markup).toContain(
      `maxLength="${MAX_GUI_COLLECTION_ITEM_CODE_UNITS}"`,
    );
  });
});
