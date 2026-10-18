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
    _tabs: [
      { label: "First", icon_html: null, container_id: "first" },
      { label: "Second", icon_html: null, container_id: "second" },
    ],
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

describe("TabGroup", () => {
  it("draws an underlined strip that wraps", () => {
    const markup = renderTabs();
    expect(markup).toContain("data-leika-tabs-list");
    expect(markup.match(/data-leika-tab(?:=|\s|>)/g)).toHaveLength(2);
    expect(markup).toContain('data-variant="line"');
    // It wraps rather than scrolling: a tab cut off at an edge with no
    // scrollbar to admit it is one nobody can read.
    expect(markup).toContain("flex-wrap");
    expect(markup).not.toContain("overflow-x-auto");
    expect(markup).not.toContain("no-scrollbar");
  });

  it("keeps inactive panel contents mounted for renderer and draft continuity", () => {
    const markup = renderTabs();
    expect(markup).toContain('data-test-container="first"');
    expect(markup).toContain('data-test-container="second"');
  });
});
