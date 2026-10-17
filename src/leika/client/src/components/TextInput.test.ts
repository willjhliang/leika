import React from "react";
import { describe, expect, it } from "vitest";

import { GuiTextMessage } from "../WebsocketMessages";
import { MAX_GUI_TEXT_VALUE_CODE_UNITS } from "../guiLimits";
import TextInputComponent from "./TextInput";
import { renderWithGuiContext } from "./testGuiContext";

function renderText({
  value = "note",
  label = "Note" as string | null,
  editable = true,
  markdown = false,
  multiline = false,
  rows = null as number | null,
  disabled = false,
  source,
}: {
  value?: string;
  label?: string | null;
  editable?: boolean;
  markdown?: boolean;
  multiline?: boolean;
  rows?: number | null;
  disabled?: boolean;
  source?: string;
} = {}): string {
  const message: GuiTextMessage = {
    type: "GuiTextMessage",
    uuid: "note",
    value,
    container_uuid: "root",
    props: {
      order: 0,
      label,
      hint: null,
      visible: true,
      disabled,
      editable,
      markdown,
      multiline,
      rows,
      _source: source ?? value,
    },
  };
  return renderWithGuiContext(React.createElement(TextInputComponent, message));
}

describe("TextInputComponent", () => {
  it("bounds editable single- and multi-line values", () => {
    expect(renderText({ editable: true, multiline: false })).toContain(
      `maxLength="${MAX_GUI_TEXT_VALUE_CODE_UNITS}"`,
    );
    expect(renderText({ editable: true, multiline: true })).toContain(
      `maxLength="${MAX_GUI_TEXT_VALUE_CODE_UNITS}"`,
    );
  });
  describe("editable", () => {
    it("is one line by default, and a box of lines when asked", () => {
      expect(renderText()).toContain("<input");
      expect(renderText()).not.toContain("<textarea");
      expect(renderText({ multiline: true })).toContain("<textarea");
    });

    it("is three lines unless a height is asked for", () => {
      expect(renderText({ multiline: true })).toContain('rows="3"');
      expect(renderText({ multiline: true, rows: 8 })).toContain('rows="8"');
    });

    it("carries the height only where it means something", () => {
      expect(renderText({ rows: 8 })).not.toContain('rows="8"');
    });

    it("shows its source rather than rendering it", () => {
      // What is being edited is the markdown, so an editable field shows the
      // characters even when it is marked as markdown.
      const markup = renderText({ value: "**bold**", markdown: true });
      expect(markup).toContain('value="**bold**"');
      expect(markup).not.toContain("<strong>");
    });

    it("disables whichever box it is showing", () => {
      expect(renderText({ disabled: true })).toContain('disabled=""');
      expect(renderText({ disabled: true, multiline: true })).toContain(
        'disabled=""',
      );
    });
  });

  describe("read-only", () => {
    it("renders read-only text without an editable control", () => {
      const markup = renderText({ editable: false });
      expect(markup).not.toContain("<input");
      expect(markup).not.toContain("<textarea");
      expect(markup).toContain("note");
    });
  });
});
