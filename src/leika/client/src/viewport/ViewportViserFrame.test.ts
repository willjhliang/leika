import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ViewportViserFrame } from "./ViewportWorkspace";

describe("ViewportViserFrame", () => {
  it("never discloses the Leika page origin as an iframe referrer", () => {
    const html = renderToStaticMarkup(
      React.createElement(ViewportViserFrame, {
        src: "https://embed.example.test/scene",
        title: "Scene",
      }),
    );
    expect(html).toContain('referrerPolicy="no-referrer"');
    expect(html).not.toContain("strict-origin-when-cross-origin");
  });
});
