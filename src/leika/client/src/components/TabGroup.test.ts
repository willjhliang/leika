import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { GuiComponentContext } from "../ControlPanel/GuiComponentContext";
import { GuiTabGroupMessage } from "../WebsocketMessages";
import TabGroupComponent from "./TabGroup";

const message: GuiTabGroupMessage = {
  type: "GuiTabGroupMessage",
  uuid: "tabs",
  container_uuid: "root",
  props: {
    _tab_labels: ["First", "Second"],
    _tab_icons_html: [null, null],
    _tab_container_ids: ["first", "second"],
    order: 0,
    visible: true,
  },
};

function renderTabs(): string {
  const context = {
    setValue: () => undefined,
    messageSender: () => undefined,
    GuiContainer: ({ containerUuid }: { containerUuid: string }) =>
      React.createElement(
        "div",
        { "data-test-container": containerUuid },
        containerUuid,
      ),
  };
  return renderToStaticMarkup(
    React.createElement(
      GuiComponentContext.Provider,
      { value: context },
      React.createElement(TabGroupComponent, message),
    ),
  );
}

describe("PlainTabGroup", () => {
  it("keeps the stock fixed-height TabsList on one row", () => {
    const markup = renderTabs();
    expect(markup).toContain("data-leika-tabs-list");
    expect(markup.match(/data-leika-tab(?:=|\s|>)/g)).toHaveLength(2);
    expect(markup).toContain("no-scrollbar");
    expect(markup).toContain("overflow-x-auto");
    expect(markup).toContain("min-w-fit");
    expect(markup).not.toContain("flex-wrap");
  });

  it("keeps inactive panel contents mounted for renderer and draft continuity", () => {
    const markup = renderTabs();
    expect(markup).toContain('data-test-container="first"');
    expect(markup).toContain('data-test-container="second"');
  });
});
