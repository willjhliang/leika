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

    it("stops that box sizing itself, which would ignore the height", () => {
      // `rows` is only consulted by a textarea that is not growing with its
      // content, and the stock one grows from a floor of its own -- so without
      // both of these the attribute above measured the same at 1, 2 and 10.
      const markup = renderText({ multiline: true });
      expect(markup).toContain("field-sizing-fixed");
      expect(markup).toContain("min-h-0");
      expect(markup).not.toContain("min-h-16");
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
    it("is not an input at all, and says so with a tint", () => {
      const markup = renderText({ editable: false });
      expect(markup).not.toContain("<input");
      expect(markup).not.toContain("<textarea");
      expect(markup).toContain("data-leika-text-reading");
      // The tone the panel already uses for a part that is not the viewer's to
      // work, at the strength a slider's inactive track wears it: thinned down,
      // it was four values off the panel behind it and read as nothing.
      expect(markup).toContain("bg-muted ");
      expect(markup).not.toContain("bg-muted/");
    });

    it("hands markdown to the renderer, and characters straight through", () => {
      // The renderer evaluates MDX asynchronously, so it contributes nothing to
      // static markup: what is checkable here is which of the two paths the
      // text took. That it comes out as markup is covered in the browser, by
      // `test_text_can_be_read_only_and_rendered_as_markdown`.
      const literal = renderText({ value: "**bold**", editable: false });
      expect(literal).toContain("**bold**");
      expect(literal).not.toContain("data-leika-text-markdown");

      const rendered = renderText({
        value: "**bold**",
        editable: false,
        markdown: true,
      });
      expect(rendered).toContain("data-leika-text-markdown");
      expect(rendered).not.toContain("**bold**");
    });

    it("fits the text it holds unless a height is asked for", () => {
      const fitted = renderText({ editable: false, multiline: true });
      expect(fitted).not.toContain("overflow-y-auto");
      expect(fitted).not.toContain("height:");
      const fixed = renderText({ editable: false, multiline: true, rows: 4 });
      expect(fixed).toContain("overflow-y-auto");
      // In the box's own lines, so the height follows the leading rather than
      // restating it.
      expect(fixed).toContain("calc(4 * 1lh + 1rem)");
    });

    it("keeps its own newlines, but not markdown's", () => {
      expect(renderText({ editable: false, multiline: true })).toContain(
        "whitespace-pre-wrap",
      );
      // Markdown's blocks bring their own spacing; keeping the source's
      // whitespace too would open a blank line between each.
      expect(
        renderText({ editable: false, multiline: true, markdown: true }),
      ).not.toContain("whitespace-pre-wrap");
    });

    it("is one row high on one line, ellipsis and all", () => {
      const markup = renderText({ editable: false });
      expect(markup).toContain("h-6");
      expect(markup).toContain("truncate");
    });

    it("takes the row when it has no label to sit beside", () => {
      expect(
        renderText({ label: null, editable: false, markdown: true }),
      ).not.toContain("data-leika-gui-row");
      expect(renderText({ editable: false })).toContain("data-leika-gui-row");
    });
  });
});
