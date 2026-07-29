import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiTextMessage } from "../WebsocketMessages";
import TextInputComponent from "./TextInput";

function renderText({
  value = "note",
  multiline = false,
  rows = 3,
  disabled = false,
}: {
  value?: string;
  multiline?: boolean;
  rows?: number;
  disabled?: boolean;
} = {}): string {
  const message: GuiTextMessage = {
    type: "GuiTextMessage",
    uuid: "note",
    value,
    container_uuid: "root",
    props: {
      order: 0,
      label: "Note",
      hint: null,
      visible: true,
      disabled,
      multiline,
      rows,
    },
  };
  return renderToStaticMarkup(React.createElement(TextInputComponent, message));
}

describe("TextInputComponent", () => {
  it("is one line by default, and a box of lines when asked", () => {
    expect(renderText()).toContain("<input");
    expect(renderText()).not.toContain("<textarea");
    expect(renderText({ multiline: true })).toContain("<textarea");
  });

  it("gives a multiline box the height it was asked for", () => {
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
    expect(renderText({ multiline: false, rows: 8 })).not.toContain('rows="8"');
  });

  it("disables whichever box it is showing", () => {
    expect(renderText({ disabled: true })).toContain('disabled=""');
    expect(renderText({ disabled: true, multiline: true })).toContain(
      'disabled=""',
    );
  });
});
