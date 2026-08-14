import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MarkdownPreviewLimit, TextPreviewLimit } from "./FilePreviewDialog";

describe("TextPreviewLimit", () => {
  it("surfaces the nonfatal render limit and keeps download guidance", () => {
    const html = renderToStaticMarkup(
      React.createElement(TextPreviewLimit, { filename: "huge.md" }),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain("huge.md");
    expect(html).toContain("16 MiB");
    expect(html).toContain("Download");
  });
});

describe("MarkdownPreviewLimit", () => {
  it("surfaces the smaller parse-tree safety limit", () => {
    const html = renderToStaticMarkup(
      React.createElement(MarkdownPreviewLimit, { filename: "huge.md" }),
    );

    expect(html).toContain('role="status"');
    expect(html).toContain("huge.md");
    expect(html).toContain("1 MiB");
    expect(html).toContain("Download");
  });
});
