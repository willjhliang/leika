import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { GuiHtmlMessage } from "../WebsocketMessages";
import { GUI_HTML_MAX_SOURCE_CODE_UNITS } from "../rendererSourceLimits";
import HtmlComponent from "./Html";

function message(content: string): GuiHtmlMessage {
  return {
    type: "GuiHtmlMessage",
    uuid: "html",
    container_uuid: "root",
    props: { order: 0, content, visible: true },
  };
}

describe("HtmlComponent", () => {
  it("renders ordinary server HTML", () => {
    const html = renderToStaticMarkup(
      createElement(HtmlComponent, message("<strong>Ready</strong>")),
    );

    expect(html).toContain("<strong>Ready</strong>");
  });

  it("shows a status instead of expanding oversized HTML into the DOM", () => {
    const html = renderToStaticMarkup(
      createElement(
        HtmlComponent,
        message("x".repeat(GUI_HTML_MAX_SOURCE_CODE_UNITS + 1)),
      ),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain("1 Mi-character browser render limit");
    expect(html).not.toContain("x".repeat(1024));
  });
});
